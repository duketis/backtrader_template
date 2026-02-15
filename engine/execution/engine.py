"""
Execution engine: wires everything together and runs backtests.

This is the orchestrator — it takes configuration, loads data,
configures Cerebro (backtrader's main engine), attaches the strategy
and analyzers, runs the backtest, and collects results.

Separation of concerns: this module knows HOW to run a backtest
but not WHAT the trading strategy does.
"""

import backtrader as bt

from core.config import AppConfig
from core.types import CostModel, PositionSizingMethod, Timeframe
from data.manager import DataManager
from data.session_filter import SessionFilter
from data.feeds import MultiTimeframeFeeds
from analysis.trade_logger import TradeLogger
from analysis.metrics import calculate_metrics, format_results, BacktestResult
from analysis.report import generate_report
from execution.risk_manager import RiskManager


class BacktestEngine:
    """Configures and runs a backtrader backtest.

    Usage:
        engine = BacktestEngine(config)
        engine.setup(StrategyClass, strategy_kwargs={})
        result = engine.run()
        print(format_results(result))
    """

    def __init__(self, config: AppConfig):
        self._config = config
        self._cerebro = bt.Cerebro()
        self._data_manager = DataManager(config)
        self._session_filter = SessionFilter(config.session)
        self._risk_manager = RiskManager(
            sizing_config=config.position_sizing,
            risk_config=config.risk,
            initial_balance=config.initial_balance,
        )
        self._strategy_class = None
        self._is_setup = False

    @property
    def data_manager(self) -> DataManager:
        """Access the data manager (for visualization after run)."""
        return self._data_manager

    @property
    def session_filter(self) -> SessionFilter:
        """Access the session filter."""
        return self._session_filter

    @property
    def risk_manager(self) -> RiskManager:
        """Access the risk manager."""
        return self._risk_manager

    def setup(
        self,
        strategy_class,
        strategy_kwargs: dict = None,
        timeframes: list = None,
    ) -> None:
        """Configure the backtest engine with a strategy.

        Args:
            strategy_class: The backtrader Strategy class to use.
            strategy_kwargs: Parameters to pass to the strategy.
            timeframes: Timeframes to load. Defaults to config.
        """
        strategy_kwargs = strategy_kwargs or {}

        # 1. Load data
        if timeframes is None:
            # Load all timeframes the strategy needs + tick for execution
            timeframes = [Timeframe.TICK] + self._config.data.timeframes

        print("Loading data...")
        self._data_manager.load(timeframes=timeframes)
        print(f"  {self._data_manager}")

        # 2. Create data feeds and add to Cerebro
        # The first feed added is the primary (datas[0]). Use smallest timeframe.
        mtf = MultiTimeframeFeeds(self._data_manager, self._session_filter)
        available = self._data_manager.get_available_timeframes()

        # Order timeframes: smallest first (primary), rest as supplementary
        tf_order = [
            Timeframe.TICK, Timeframe.ONE_MIN, Timeframe.FIVE_MIN,
            Timeframe.ONE_HOUR, Timeframe.FOUR_HOUR,
        ]
        added_primary = False
        for tf in tf_order:
            if tf in available:
                feed = mtf.create_feed(tf, apply_session_filter=False)
                self._cerebro.adddata(feed)
                if not added_primary:
                    added_primary = True

        # 3. Configure broker
        self._configure_broker()

        # 4. Add strategy — inject risk_manager and session_filter
        self._strategy_class = strategy_class
        strategy_kwargs["risk_manager"] = self._risk_manager
        strategy_kwargs["session_filter"] = self._session_filter
        self._cerebro.addstrategy(strategy_class, **strategy_kwargs)

        # 5. Add trade logger analyzer
        cost_model = self._config.costs
        self._cerebro.addanalyzer(
            TradeLogger,
            _name="trade_logger",
            cost_model=cost_model,
        )

        # 6. Add standard backtrader analyzers
        self._cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="bt_trades")
        self._cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")

        self._is_setup = True
        print("Engine setup complete.")

    def run(self) -> BacktestResult:
        """Execute the backtest and return results.

        Returns:
            BacktestResult with all trades and metrics.

        Raises:
            RuntimeError: If setup() hasn't been called.
        """
        if not self._is_setup:
            raise RuntimeError("Call setup() before run()")

        print("\nRunning backtest...")
        results = self._cerebro.run()
        strategy_instance = results[0]

        # Extract trades from our custom analyzer
        trade_logger = strategy_instance.analyzers.trade_logger
        trades = trade_logger.get_trades()
        open_trades = trade_logger.get_open_trades()

        print(f"\n  Completed trades: {len(trades)}")
        if open_trades:
            print(f"  Still open at end: {len(open_trades)}")

        # Calculate metrics
        result = calculate_metrics(trades, self._config.initial_balance)

        # Print formatted results
        print(format_results(result))

        # Generate HTML report
        if self._config.visualization.enabled:
            report_path = generate_report(
                result,
                output_dir=self._config.visualization.output_dir,
            )
            print(f"\n📄 Report saved to: {report_path.resolve()}")

        return result

    def _configure_broker(self) -> None:
        """Set up the backtrader broker with account and cost settings."""
        broker = self._cerebro.broker

        # Starting cash
        broker.setcash(self._config.initial_balance)

        # CFD-style leverage — treat as stock-like with leverage so the broker
        # only requires (notional / leverage) as margin, not the full notional.
        # e.g. 50:1 leverage: 20 units × $17k = $340k / 50 = $6.8k margin.
        #
        # Commission: use COMM_FIXED so that commission_per_trade is a fixed
        # dollar amount per unit traded (not a percentage of trade value).
        commission = self._config.costs.commission_per_trade
        if commission > 0:
            broker.setcommission(
                commission=commission,
                commtype=bt.CommInfoBase.COMM_FIXED,
                stocklike=True,
                leverage=self._config.leverage,
            )
        else:
            broker.setcommission(
                commission=0,
                stocklike=True,
                leverage=self._config.leverage,
            )

        # Spread modeled as fixed slippage (half-spread per side)
        slip = self._config.costs.half_spread + self._config.costs.slippage_points
        if slip > 0:
            broker.set_slippage_fixed(slip, slip_open=True, slip_limit=True)
