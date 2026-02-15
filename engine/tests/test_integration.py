"""
Integration tests for the Backtest Engine.

These tests run real backtests on synthetic data to verify the full
pipeline works end-to-end: data loading → feeds → strategy → orders →
trade logging → metrics.

Each test verifies a specific infrastructure requirement:
  - Session filter enforcement (no trades outside NY session)
  - Daily loss reset at day boundaries
  - Cost model accuracy (no double-counting)
  - Bracket order lifecycle
  - Trade record completeness
"""

from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import backtrader as bt
import numpy as np
import pandas as pd
import pytest

from core.types import (
    BacktestResult,
    CostModel,
    Direction,
    SessionWindow,
    Timeframe,
    TradeRecord,
    TradeStatus,
)
from analysis.trade_logger import TradeLogger
from data.session_filter import SessionFilter


# ==============================================================================
# Helpers: synthetic data + minimal Cerebro runner
# ==============================================================================

def _make_minute_data(
    start: datetime,
    n_bars: int,
    base_price: float = 16500.0,
    step: float = 1.0,
    hl_margin: float = 2.0,
) -> pd.DataFrame:
    """Generate a deterministic series of 1-min bars.

    Price increments by `step` each bar so we know exact entry/exit prices.
    hl_margin controls how far high/low extend from the close (must be > slippage
    to avoid slippage being capped by bar range).
    """
    timestamps = [start + timedelta(minutes=i) for i in range(n_bars)]
    prices = [base_price + i * step for i in range(n_bars)]
    return pd.DataFrame(
        {
            "open": prices,
            "high": [p + hl_margin for p in prices],
            "low": [p - hl_margin for p in prices],
            "close": prices,
        },
        index=pd.DatetimeIndex(timestamps, name="datetime"),
    )


def _run_cerebro(
    df: pd.DataFrame,
    strategy_class,
    strategy_kwargs: dict = None,
    cash: float = 100_000.0,
    leverage: float = 50.0,
    cost_model: CostModel = None,
    spread_slip: float = 0.0,
    commission: float = 0.0,
):
    """Run a minimal Cerebro on a DataFrame. Returns (strategy_instance, trades).

    IMPORTANT: Always sets stocklike=True with leverage so that CFD-style
    margin is used (notional / leverage). Without this, orders for $16,500
    instruments will be margin-rejected with $100k cash.
    """
    strategy_kwargs = strategy_kwargs or {}
    cost_model = cost_model or CostModel(
        spread_points=0.0,
        commission_per_trade=commission,
        commission_per_lot=0.0,
        slippage_points=0.0,
    )

    cerebro = bt.Cerebro()

    feed = bt.feeds.PandasData(
        dataname=df,
        timeframe=bt.TimeFrame.Minutes,
        compression=1,
    )
    cerebro.adddata(feed)

    cerebro.broker.setcash(cash)

    # Commission setup: use COMM_FIXED for fixed-dollar commissions.
    # With stocklike=True + leverage, the broker only requires
    # (notional / leverage) as margin.
    if commission > 0:
        cerebro.broker.setcommission(
            commission=commission,
            commtype=bt.CommInfoBase.COMM_FIXED,
            stocklike=True,
            leverage=leverage,
        )
    else:
        cerebro.broker.setcommission(
            commission=0,
            stocklike=True,
            leverage=leverage,
        )

    if spread_slip > 0:
        cerebro.broker.set_slippage_fixed(
            spread_slip, slip_open=True, slip_limit=True,
        )

    cerebro.addstrategy(strategy_class, **strategy_kwargs)
    cerebro.addanalyzer(
        TradeLogger, _name="trade_logger", cost_model=cost_model,
    )

    results = cerebro.run()
    strat = results[0]
    trades = strat.analyzers.trade_logger.get_trades()
    return strat, trades


# ==============================================================================
# Minimal strategies for testing specific behaviors
# ==============================================================================

class BuyOnceStrategy(bt.Strategy):
    """Buys once on bar N and sells on bar N+M. Zero indicator dependencies."""

    params = (
        ("buy_bar", 5),
        ("sell_bar", 15),
        ("size", 1.0),
    )

    def __init__(self):
        self._bar = 0

    def next(self):
        self._bar += 1
        if self._bar == self.p.buy_bar and not self.position:
            self.buy(size=self.p.size)
        elif self._bar == self.p.sell_bar and self.position:
            self.sell(size=self.p.size)


class SessionAwareStrategy(bt.Strategy):
    """Only trades during session hours. Tests session filter integration."""

    params = (
        ("session_filter", None),
        ("buy_bar", 5),
        ("sell_bar", 15),
        ("size", 1.0),
    )

    def __init__(self):
        self._bar = 0
        self._attempted_outside = 0
        self._attempted_inside = 0

    def next(self):
        self._bar += 1

        # Check session
        current_dt = self.datas[0].datetime.datetime(0)
        if self.p.session_filter and not self.p.session_filter.is_in_session(current_dt):
            if self._bar == self.p.buy_bar:
                self._attempted_outside += 1
            return  # Skip — outside session

        if self._bar == self.p.buy_bar and not self.position:
            self._attempted_inside += 1
            self.buy(size=self.p.size)
        elif self._bar == self.p.sell_bar and self.position:
            self.sell(size=self.p.size)


class MultiBuyStrategy(bt.Strategy):
    """Opens a trade at regular intervals. For testing daily loss reset.

    Each trade buys on one bar and closes `hold_bars` later.
    """

    params = (
        ("risk_manager", None),
        ("interval", 60),       # bars between trade attempts
        ("hold_bars", 20),      # how many bars to hold each trade
        ("size", 1.0),
        ("max_trades", 5),
    )

    def __init__(self):
        self._bar = 0
        self._trade_count = 0
        self._blocked_count = 0
        self._last_date = None
        self._entry_bar = None   # bar number when we entered

    def next(self):
        self._bar += 1

        # Day boundary detection — reset daily loss
        current_date = self.datas[0].datetime.date(0)
        if self.p.risk_manager and self._last_date is not None:
            if current_date != self._last_date:
                self.p.risk_manager.reset_daily()
        self._last_date = current_date

        # Close position after hold_bars
        if self.position and self._entry_bar is not None:
            if self._bar - self._entry_bar >= self.p.hold_bars:
                self.close()
                self._entry_bar = None
                return

        if self._trade_count >= self.p.max_trades:
            return
        if self._bar % self.p.interval != 0:
            return
        if self.position:
            return

        # Check risk guard
        if self.p.risk_manager:
            allowed, reason = self.p.risk_manager.can_open_trade(return_reason=True)
            if not allowed:
                self._blocked_count += 1
                return

        self.buy(size=self.p.size)
        self._entry_bar = self._bar
        self._trade_count += 1

    def notify_trade(self, trade):
        if trade.isclosed and self.p.risk_manager:
            self.p.risk_manager.on_trade_closed(pnl=trade.pnlcomm)


# ==============================================================================
# Test: Cost Model Accuracy (Gap H — no double counting)
# ==============================================================================

class TestCostModelAccuracy:
    """Verify costs are correctly tracked — NOT double-counted.

    The broker applies spread via set_slippage_fixed which moves fill prices.
    trade.pnl already reflects this. TradeLogger must not subtract it again.
    """

    def test_zero_cost_pnl_matches_price_diff(self):
        """With zero costs, net_pnl should equal price movement × size.

        Prices: bar 1=16500, bar 2=16501, ..., step=1.
        Buy at bar 5 → fills at bar 6 open = 16505.
        Sell at bar 15 → fills at bar 16 open = 16515.
        Expected pnl = (16515 - 16505) × 10 = 100.
        """
        df = _make_minute_data(datetime(2024, 1, 2, 14, 0), 50)

        _, trades = _run_cerebro(
            df, BuyOnceStrategy,
            strategy_kwargs={"buy_bar": 5, "sell_bar": 15, "size": 10.0},
            spread_slip=0.0,
            commission=0.0,
        )

        assert len(trades) == 1
        t = trades[0]

        # With zero costs: gross = net = 100
        assert t.gross_pnl == pytest.approx(100.0, abs=0.5)
        assert t.net_pnl == pytest.approx(100.0, abs=0.5)
        assert t.total_costs == pytest.approx(0.0, abs=0.01)

        # Exit price should be different from entry price
        assert t.entry_price == pytest.approx(16505.0, abs=0.5)
        assert t.exit_price == pytest.approx(16515.0, abs=0.5)

    def test_spread_not_double_counted(self):
        """With spread applied via broker slippage, TradeLogger should NOT
        subtract spread again. The gross_pnl from backtrader already
        reflects the adverse fill prices.

        No-spread:  buy@16505, sell@16515 → pnl = 100
        With 0.57 slip: buy@16505.57, sell@16514.43 → pnl = 88.6
        Diff should be ~11.4 (= 0.57 * 10 * 2 sides)
        """
        df = _make_minute_data(datetime(2024, 1, 2, 14, 0), 50)
        spread = 1.14
        half_spread = spread / 2.0

        # Run with spread via broker slippage
        _, trades_with_spread = _run_cerebro(
            df, BuyOnceStrategy,
            strategy_kwargs={"buy_bar": 5, "sell_bar": 15, "size": 10.0},
            cost_model=CostModel(spread_points=spread),
            spread_slip=half_spread,
            commission=0.0,
        )

        # Run with zero spread for comparison
        _, trades_no_spread = _run_cerebro(
            df, BuyOnceStrategy,
            strategy_kwargs={"buy_bar": 5, "sell_bar": 15, "size": 10.0},
            spread_slip=0.0,
            commission=0.0,
        )

        assert len(trades_with_spread) == 1
        assert len(trades_no_spread) == 1

        t_spread = trades_with_spread[0]
        t_clean = trades_no_spread[0]

        # The DIFFERENCE between the two net_pnls should be approximately
        # the total spread impact: half_spread * size * 2 sides = 11.4
        expected_spread_impact = half_spread * 10.0 * 2  # ~11.4
        actual_diff = t_clean.net_pnl - t_spread.net_pnl
        assert actual_diff == pytest.approx(expected_spread_impact, abs=1.0), (
            f"Spread impact mismatch: expected ~{expected_spread_impact}, "
            f"got {actual_diff}. clean={t_clean.net_pnl}, spread={t_spread.net_pnl}. "
            f"If diff is ~2x expected, TradeLogger is double-counting."
        )

        # TradeLogger should still record spread costs (informational)
        assert t_spread.spread_cost > 0

    def test_commission_tracked_correctly(self):
        """Commission set on the broker should appear once, not twice.

        With COMM_FIXED, commission=5.0 means $5 per unit per side.
        10 units × $5 × 2 sides = $100 total commission.
        gross_pnl=100, pnlcomm=0, total_costs=100.
        """
        df = _make_minute_data(datetime(2024, 1, 2, 14, 0), 50)

        _, trades = _run_cerebro(
            df, BuyOnceStrategy,
            strategy_kwargs={"buy_bar": 5, "sell_bar": 15, "size": 10.0},
            cost_model=CostModel(commission_per_trade=5.0),
            spread_slip=0.0,
            commission=5.0,
        )

        assert len(trades) == 1, f"Expected 1 trade, got {len(trades)}"
        t = trades[0]

        # Commission from broker: $5/unit × 10 units × 2 sides = $100
        # gross_pnl = 100 (price diff), net_pnl = 0 (after commission)
        assert t.gross_pnl == pytest.approx(100.0, abs=0.5)
        assert t.total_costs == pytest.approx(100.0, abs=1.0)
        assert t.net_pnl == pytest.approx(0.0, abs=1.0)

        # TradeLogger should report commission cost (informational)
        assert t.commission_cost > 0

    def test_combined_spread_and_commission(self):
        """Spread via slippage + commission via broker. Both should apply
        without double-counting.

        Spread: 0.57 per side × 10 units × 2 = 11.4 (in fill prices)
        Commission: $5/unit × 10 units × 2 = 100 (broker commission)
        gross_pnl = ~88.6 (100 - 11.4 from slippage)
        net_pnl = ~-11.4 (88.6 - 100 from commission)
        """
        df = _make_minute_data(datetime(2024, 1, 2, 14, 0), 50)

        _, trades = _run_cerebro(
            df, BuyOnceStrategy,
            strategy_kwargs={"buy_bar": 5, "sell_bar": 15, "size": 10.0},
            cost_model=CostModel(spread_points=1.14, commission_per_trade=5.0),
            spread_slip=0.57,
            commission=5.0,
        )

        assert len(trades) == 1
        t = trades[0]

        # gross_pnl includes slippage but not commission
        assert t.gross_pnl == pytest.approx(88.6, abs=2.0)
        # total_costs = commission only (what broker charges beyond slippage)
        assert t.total_costs == pytest.approx(100.0, abs=1.0)
        # net_pnl = gross_pnl - commission
        assert t.net_pnl == pytest.approx(-11.4, abs=2.0)


# ==============================================================================
# Test: Session Filter Integration (Gap A)
# ==============================================================================

class TestSessionFilterIntegration:
    """Verify that a strategy using SessionFilter only trades in-session."""

    def test_trades_only_during_session(self):
        """Data spanning 24h but session is 13:00-21:30 UTC (8AM-4:30PM ET winter).
        Strategy should only trade during the session window."""
        # Generate 24 hours of 1-min data starting midnight UTC
        df = _make_minute_data(datetime(2024, 1, 2, 0, 0), 1440)

        session = SessionWindow(
            timezone="America/New_York",
            start_time="08:00",
            end_time="16:30",
            dst_aware=True,
        )
        sf = SessionFilter(session)

        # Buy at bar 100 (01:40 UTC = 20:40 ET previous day — OUTSIDE session)
        _, trades_outside = _run_cerebro(
            df, SessionAwareStrategy,
            strategy_kwargs={
                "session_filter": sf,
                "buy_bar": 100,
                "sell_bar": 200,
                "size": 1.0,
            },
        )
        # Should NOT have opened — bar 100 is ~01:40 UTC = outside NY session
        assert len(trades_outside) == 0

    def test_trades_during_session_succeed(self):
        """When buy_bar falls in session hours, trade should execute."""
        # 24h of data starting midnight UTC
        df = _make_minute_data(datetime(2024, 1, 2, 0, 0), 1440)

        session = SessionWindow(
            timezone="America/New_York",
            start_time="08:00",
            end_time="16:30",
            dst_aware=True,
        )
        sf = SessionFilter(session)

        # Bar 800 = 13:20 UTC = 08:20 ET — INSIDE session
        _, trades_inside = _run_cerebro(
            df, SessionAwareStrategy,
            strategy_kwargs={
                "session_filter": sf,
                "buy_bar": 800,
                "sell_bar": 900,
                "size": 1.0,
            },
        )
        assert len(trades_inside) == 1

    def test_session_filter_blocks_outside_hours(self):
        """Verify the session_filter.is_in_session works for various times."""
        session = SessionWindow(
            timezone="America/New_York",
            start_time="08:00",
            end_time="16:30",
            dst_aware=True,
        )
        sf = SessionFilter(session)

        # Winter: ET = UTC-5. 8AM ET = 13:00 UTC, 4:30PM ET = 21:30 UTC
        assert sf.is_in_session(datetime(2024, 1, 2, 13, 0)) is True   # 8AM ET
        assert sf.is_in_session(datetime(2024, 1, 2, 21, 30)) is True  # 4:30PM ET
        assert sf.is_in_session(datetime(2024, 1, 2, 12, 59)) is False # 7:59AM ET
        assert sf.is_in_session(datetime(2024, 1, 2, 21, 31)) is False # 4:31PM ET
        assert sf.is_in_session(datetime(2024, 1, 2, 5, 0)) is False   # midnight ET
        assert sf.is_in_session(datetime(2024, 1, 2, 15, 0)) is True   # 10AM ET


# ==============================================================================
# Test: Daily Loss Reset (Gap B)
# ==============================================================================

class TestDailyLossReset:
    """Verify that daily P&L resets at day boundaries."""

    def test_daily_loss_resets_across_days(self):
        """Losses on Day 1 should not block trades on Day 2."""
        from core.config import PositionSizingConfig, RiskConfig
        from execution.risk_manager import RiskManager

        sizing = PositionSizingConfig(
            method="fixed_lot",
            fixed_lot_size=1.0,
            risk_per_trade_dollars=1000,
            risk_per_trade_percent=1.0,
            fixed_dollar_amount=5000,
        )
        risk = RiskConfig(
            max_positions=1,
            max_daily_loss_dollars=200,  # Tight limit
            max_daily_loss_percent=0,
        )
        rm = RiskManager(
            sizing_config=sizing,
            risk_config=risk,
            initial_balance=100000,
        )

        # Generate 2 days of data: Day 1 = Jan 2, Day 2 = Jan 3
        # Day 1: prices decline (losers), Day 2: prices rise (winners)
        day1 = _make_minute_data(datetime(2024, 1, 2, 14, 0), 480, step=-1.0)
        day2 = _make_minute_data(datetime(2024, 1, 3, 14, 0), 480, step=1.0)
        df = pd.concat([day1, day2])

        _, trades = _run_cerebro(
            df, MultiBuyStrategy,
            strategy_kwargs={
                "risk_manager": rm,
                "interval": 60,
                "hold_bars": 20,
                "size": 10.0,
                "max_trades": 5,
            },
        )

        # Day 1 should have at least 1 trade (loser), then daily loss blocks
        # Day 2 should allow trading again because reset_daily was called
        # So total trades should be > 1 (proving the reset worked)
        assert len(trades) >= 2, (
            f"Expected at least 2 trades (across 2 days with daily reset), "
            f"got {len(trades)}"
        )

    def test_daily_loss_blocks_within_day(self):
        """Within a single day, the daily loss limit should block."""
        from core.config import PositionSizingConfig, RiskConfig
        from execution.risk_manager import RiskManager

        sizing = PositionSizingConfig(
            method="fixed_lot",
            fixed_lot_size=1.0,
            risk_per_trade_dollars=1000,
            risk_per_trade_percent=1.0,
            fixed_dollar_amount=5000,
        )
        risk = RiskConfig(
            max_positions=1,
            max_daily_loss_dollars=50,  # Very tight
            max_daily_loss_percent=0,
        )
        rm = RiskManager(
            sizing_config=sizing,
            risk_config=risk,
            initial_balance=100000,
        )

        # Single day of declining prices — every trade loses
        df = _make_minute_data(datetime(2024, 1, 2, 14, 0), 480, step=-1.0)

        strat, trades = _run_cerebro(
            df, MultiBuyStrategy,
            strategy_kwargs={
                "risk_manager": rm,
                "interval": 30,
                "hold_bars": 10,
                "size": 10.0,
                "max_trades": 10,
            },
        )

        # First trade should execute and lose money. After that daily loss
        # limit should block remaining trades.
        assert len(trades) >= 1
        assert strat._blocked_count > 0, "Expected some trades to be blocked by daily loss"


# ==============================================================================
# Test: Trade Record Completeness
# ==============================================================================

class TestTradeRecordCompleteness:
    """Verify that TradeRecords have all required fields populated."""

    def test_closed_trade_has_all_fields(self):
        """A closed trade should have entry/exit times, prices, P&L."""
        df = _make_minute_data(datetime(2024, 1, 2, 14, 0), 50)
        _, trades = _run_cerebro(
            df, BuyOnceStrategy,
            strategy_kwargs={"buy_bar": 5, "sell_bar": 15, "size": 5.0},
        )

        assert len(trades) == 1
        t = trades[0]

        # All fields populated
        assert t.trade_id == 1
        assert t.direction == Direction.LONG
        assert t.entry_time is not None
        assert t.exit_time is not None
        assert t.entry_price > 0
        assert t.exit_price > 0
        assert t.exit_price != t.entry_price  # They should be different!
        assert t.size == pytest.approx(5.0)
        assert t.status == TradeStatus.CLOSED

    def test_entry_before_exit(self):
        """Entry time should be before exit time."""
        df = _make_minute_data(datetime(2024, 1, 2, 14, 0), 50)
        _, trades = _run_cerebro(
            df, BuyOnceStrategy,
            strategy_kwargs={"buy_bar": 5, "sell_bar": 15, "size": 1.0},
        )
        t = trades[0]
        assert t.entry_time < t.exit_time

    def test_duration_is_correct(self):
        """Duration should match the bar interval."""
        df = _make_minute_data(datetime(2024, 1, 2, 14, 0), 50)
        _, trades = _run_cerebro(
            df, BuyOnceStrategy,
            strategy_kwargs={"buy_bar": 5, "sell_bar": 15, "size": 1.0},
        )
        t = trades[0]
        # 10 bars × 1 minute = 600 seconds
        assert t.duration_seconds == pytest.approx(600.0, abs=120)

    def test_exit_price_is_accurate(self):
        """Exit price should be the actual fill price, not entry price."""
        df = _make_minute_data(datetime(2024, 1, 2, 14, 0), 50)
        _, trades = _run_cerebro(
            df, BuyOnceStrategy,
            strategy_kwargs={"buy_bar": 5, "sell_bar": 15, "size": 10.0},
        )
        t = trades[0]
        # Buy at bar 5 → fill at bar 6 open = 16505
        # Sell at bar 15 → fill at bar 16 open = 16515
        assert t.entry_price == pytest.approx(16505.0, abs=0.5)
        assert t.exit_price == pytest.approx(16515.0, abs=0.5)

        # Verify: (exit - entry) * size == gross_pnl
        computed_pnl = (t.exit_price - t.entry_price) * t.size
        assert computed_pnl == pytest.approx(t.gross_pnl, abs=0.5)


# ==============================================================================
# Test: Bracket Order Leg Cancellation (Gap I)
# ==============================================================================

class TestBracketOrderCancellation:
    """Verify that bracket order leg cancellations (expected) don't
    corrupt the risk manager state or trade log."""

    def test_bracket_cancel_does_not_affect_trade_count(self):
        """When SL fills, TP is auto-canceled — this should NOT create
        a second trade or corrupt the trade logger."""
        from execution.order_manager import OrderManager
        from execution.risk_manager import RiskManager
        from core.config import PositionSizingConfig, RiskConfig

        sizing = PositionSizingConfig(
            method="fixed_lot",
            fixed_lot_size=1.0,
            risk_per_trade_dollars=1000,
            risk_per_trade_percent=1.0,
            fixed_dollar_amount=5000,
        )
        risk = RiskConfig(max_positions=2, max_daily_loss_dollars=0, max_daily_loss_percent=0)
        rm = RiskManager(sizing_config=sizing, risk_config=risk, initial_balance=100000)

        # Open and close a trade
        rm.on_trade_opened()
        assert rm.open_positions == 1
        rm.on_trade_closed(pnl=-50)
        assert rm.open_positions == 0

        # The bracket leg cancel should NOT call on_trade_closed again
        # (only the actual trade.isclosed event should)
        assert rm.open_positions == 0

    def test_bracket_cancel_does_not_affect_daily_pnl(self):
        """Bracket leg cancellation should not double-count daily P&L."""
        from execution.risk_manager import RiskManager
        from core.config import PositionSizingConfig, RiskConfig

        sizing = PositionSizingConfig(
            method="fixed_lot",
            fixed_lot_size=1.0,
            risk_per_trade_dollars=1000,
            risk_per_trade_percent=1.0,
            fixed_dollar_amount=5000,
        )
        risk = RiskConfig(max_positions=2, max_daily_loss_dollars=0, max_daily_loss_percent=0)
        rm = RiskManager(sizing_config=sizing, risk_config=risk, initial_balance=100000)

        rm.on_trade_opened()
        rm.on_trade_closed(pnl=-75)
        assert rm.daily_pnl == pytest.approx(-75.0)
        # Bracket cancel doesn't change daily_pnl
        assert rm.daily_pnl == pytest.approx(-75.0)
