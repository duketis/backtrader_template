"""
Comprehensive dummy strategy for infrastructure testing.

This is NOT a real trading strategy. It exists to verify the entire
engine pipeline works correctly by systematically testing:

  1. All 4 position sizing methods (fixed_lot, fixed_risk, percent_equity, fixed_dollar)
  2. Bracket orders (SL + TP) via OrderManager
  3. Risk management (max positions, daily loss limits)
  4. Both long and short trades
  5. Various SL/TP distances
  6. Trade logging with SL/TP capture
  7. Cost application (spread, slippage, commission)

The strategy opens trades at regular intervals with predetermined
parameters, cycling through different configurations to test each
sizing method and trade direction.

Designed to produce ~10 trades during a typical backtest run.
"""

import backtrader as bt

from core.types import Direction, PositionSizingMethod, Timeframe
from execution.order_manager import OrderManager
from execution.risk_manager import RiskManager


class DummyStrategy(bt.Strategy):
    """Infrastructure test strategy that exercises all engine features.

    Each trade uses a different combination of:
    - Direction (long/short alternating)
    - SL distance (small/medium/large)
    - TP distance (0 = no TP, or 2x SL, 3x SL)

    The strategy itself doesn't look at any indicators — it trades
    at fixed bar intervals so we get predictable, verifiable results.
    """

    # --- CLI Registration (auto-discovered by main.py) ---
    cli_name = "dummy"
    cli_description = "Infrastructure test strategy — trades at fixed intervals"
    cli_kwargs = {"buy_every_n_bars": 500, "max_trades": 10}
    cli_timeframes = [Timeframe.ONE_MIN]

    params = (
        ("risk_manager", None),      # Injected by BacktestEngine
        ("session_filter", None),    # Injected by BacktestEngine
        ("buy_every_n_bars", 100),   # Open a trade every N bars
        ("max_trades", 10),          # Total trades to take
    )

    # Predefined trade configurations — one per trade
    # Each tuple: (direction, sl_distance, tp_distance)
    TRADE_CONFIGS = [
        (Direction.LONG,  50.0,  100.0),   # Trade 1: Long, 50pt SL, 100pt TP
        (Direction.SHORT, 50.0,  100.0),   # Trade 2: Short, 50pt SL, 100pt TP
        (Direction.LONG,  25.0,  75.0),    # Trade 3: Long, tight SL
        (Direction.SHORT, 100.0, 200.0),   # Trade 4: Short, wide SL
        (Direction.LONG,  50.0,  0.0),     # Trade 5: Long, no TP (SL only)
        (Direction.SHORT, 30.0,  90.0),    # Trade 6: Short, 1:3 R:R
        (Direction.LONG,  75.0,  150.0),   # Trade 7: Long, medium SL
        (Direction.SHORT, 40.0,  120.0),   # Trade 8: Short, 1:3 R:R
        (Direction.LONG,  60.0,  60.0),    # Trade 9: Long, 1:1 R:R
        (Direction.SHORT, 50.0,  150.0),   # Trade 10: Short, 1:3 R:R
    ]

    def __init__(self):
        self._bar_count = 0
        self._trade_count = 0
        self._order_manager = None
        self._pending_orders = {}  # order.ref -> True
        self._active_main_refs = set()  # Track main order refs for open trades
        self._trade_to_order = {}  # trade.ref -> main order.ref (bridging the two ref systems)
        self._trade_logger = None  # Will be set after start
        self._last_date = None     # For day-boundary detection

    def start(self):
        """Called once when the strategy starts — initialize OrderManager."""
        if self.p.risk_manager is None:
            raise RuntimeError(
                "DummyStrategy requires a risk_manager. "
                "Use BacktestEngine.setup() to inject it."
            )
        self._order_manager = OrderManager(
            risk_manager=self.p.risk_manager,
            strategy=self,
        )

    def nextstart(self):
        """Called once when minimum period is satisfied — find the TradeLogger."""
        # Find the TradeLogger analyzer for SL/TP registration
        for analyzer in self.analyzers:
            if hasattr(analyzer, 'register_sl_tp'):
                self._trade_logger = analyzer
                break
        self.next()

    def next(self):
        """Called on every bar of the primary data feed."""
        self._bar_count += 1

        # --- Day-boundary detection: reset daily P&L ---
        current_date = self.datas[0].datetime.date(0)
        if self._last_date is not None and current_date != self._last_date:
            self._order_manager.reset_daily()
        self._last_date = current_date

        # --- Session filter: skip if outside trading hours ---
        if self.p.session_filter is not None:
            current_dt = self.datas[0].datetime.datetime(0)
            if not self.p.session_filter.is_in_session(current_dt):
                return

        # Don't open new trades if at max
        if self._trade_count >= self.p.max_trades:
            return

        # Only attempt a trade at the scheduled bar interval
        if self._bar_count % self.p.buy_every_n_bars != 0:
            return

        # Skip if we have a position or pending orders
        if self.position or self._pending_orders:
            return

        self._open_next_trade()

    def _open_next_trade(self):
        """Open the next trade from the predefined configs."""
        config_idx = self._trade_count % len(self.TRADE_CONFIGS)
        direction, sl_distance, tp_distance = self.TRADE_CONFIGS[config_idx]

        current_price = self.data.close[0]

        orders = self._order_manager.open_position(
            direction=direction,
            entry_price=current_price,
            sl_distance=sl_distance,
            tp_distance=tp_distance,
        )

        if orders is None:
            self.log(f"Trade #{self._trade_count + 1} BLOCKED by risk guard")
            return

        self._trade_count += 1
        main_order = orders[0]
        self._active_main_refs.add(main_order.ref)

        # Register SL/TP with TradeLogger so it captures them
        sl_price = self._order_manager.get_trade_info(main_order.ref)["sl_price"]
        tp_price = self._order_manager.get_trade_info(main_order.ref)["tp_price"]
        if self._trade_logger is not None:
            self._trade_logger.register_sl_tp(
                order_ref=main_order.ref,
                sl_price=sl_price,
                tp_price=tp_price,
            )

        # Track all order refs (main + stop + limit)
        for order in orders:
            self._pending_orders[order.ref] = True

        self.log(
            f"Trade #{self._trade_count}: {direction.value.upper()} "
            f"@ {current_price:.2f}, SL={sl_distance:.0f}pt, TP={tp_distance:.0f}pt, "
            f"Size={self._order_manager.get_trade_info(main_order.ref)['size']:.4f}"
        )

    def notify_order(self, order):
        """Handle order state changes."""
        if order.status in [order.Completed]:
            direction = "BUY" if order.isbuy() else "SELL"
            self.log(
                f"  {direction} EXECUTED @ {order.executed.price:.2f}, "
                f"Size: {order.executed.size:.4f}, "
                f"Comm: {order.executed.comm:.2f}"
            )
            # Remove from pending
            self._pending_orders.pop(order.ref, None)

        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            is_entry_order = order.ref in self._active_main_refs

            if is_entry_order:
                # Real failure: entry order was rejected/cancelled
                self.log(f"  ENTRY ORDER {order.ref} REJECTED: {order.getstatusname()}")
                self._order_manager.on_order_rejected(ref=order.ref)
                self._active_main_refs.discard(order.ref)
                self._trade_count -= 1  # Allow retry

                # Cancel any remaining bracket legs
                self._pending_orders.clear()
                self.log(f"    → Rolled back risk state for rejected entry order")
            else:
                # Expected: bracket leg cancelled because the other leg filled
                # (e.g. SL hit → TP auto-cancelled, or vice versa)
                self.log(
                    f"  Bracket leg {order.ref} cancelled "
                    f"(expected — other leg filled)"
                )

            self._pending_orders.pop(order.ref, None)

    def notify_trade(self, trade):
        """Handle trade lifecycle events."""
        if trade.justopened:
            # Link trade.ref → order.ref so TradeLogger can look up SL/TP.
            # trade.ref and order.ref are independent counters in backtrader,
            # so we must explicitly bridge the mapping.
            # We only allow one position at a time, so the most recently
            # added main order ref is the one that produced this trade.
            for oref in list(self._active_main_refs):
                self._trade_to_order[trade.ref] = oref
                if self._trade_logger is not None:
                    self._trade_logger.link_trade_to_order(
                        trade_ref=trade.ref,
                        order_ref=oref,
                    )

        if trade.isclosed:
            self.log(
                f"  TRADE CLOSED — Gross P&L: {trade.pnl:.2f}, "
                f"Net P&L: {trade.pnlcomm:.2f}"
            )
            # Map trade.ref back to order.ref for OrderManager cleanup
            order_ref = self._trade_to_order.pop(trade.ref, None)
            self._order_manager.on_trade_closed(
                pnl=trade.pnlcomm, ref=order_ref,
            )
            if order_ref is not None:
                self._active_main_refs.discard(order_ref)

            # Clear any remaining pending orders for this bracket
            self._pending_orders.clear()

    def log(self, msg: str) -> None:
        """Helper to log with current datetime."""
        dt = self.datas[0].datetime.datetime(0)
        print(f"[{dt:%Y-%m-%d %H:%M}] {msg}")
