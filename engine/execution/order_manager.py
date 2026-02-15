"""
Order Manager — bracket order submission with risk guard integration.

Strategies delegate order submission to OrderManager, which:
  1. Checks risk guards (max positions, daily loss)
  2. Calculates position size via RiskManager
  3. Calculates SL/TP prices
  4. Submits bracket orders via backtrader's buy_bracket/sell_bracket
  5. Tracks order refs → trade metadata for TradeLogger
"""

from typing import Dict, List, Optional, Any

from core.types import Direction, PositionSizingMethod
from execution.risk_manager import RiskManager


class OrderManager:
    """Manages bracket order submission with integrated risk checking.

    Acts as a bridge between the Strategy and RiskManager:
    - Strategy calls open_position() with intent (direction, SL, TP)
    - OrderManager consults RiskManager for sizing and permission
    - If allowed, submits bracket orders via the strategy's backtrader API

    Args:
        risk_manager: RiskManager instance for sizing + guards.
        strategy: Backtrader Strategy instance (must have buy_bracket,
                  sell_bracket, close, broker.getvalue methods).
    """

    def __init__(self, risk_manager: RiskManager, strategy: Any):
        self._rm = risk_manager
        self._strategy = strategy
        # Track active bracket orders: main_order_ref -> trade metadata
        self._active_trades: Dict[int, Dict] = {}

    def open_position(
        self,
        direction: Direction,
        entry_price: float,
        sl_distance: float,
        tp_distance: float = 0.0,
    ) -> Optional[List]:
        """Open a bracket order (entry + SL + optional TP).

        Args:
            direction: LONG or SHORT.
            entry_price: Expected entry price (current close).
            sl_distance: Stop loss distance in points (must be > 0).
            tp_distance: Take profit distance in points (0 = no TP).

        Returns:
            List of [main_order, stop_order, limit_order] if submitted,
            or None if blocked by risk guards.
        """
        # 1. Risk guard check
        if not self._rm.can_open_trade():
            return None

        # 2. Calculate position size
        current_equity = self._strategy.broker.getvalue()
        size = self._rm.calculate_size(
            sl_distance=sl_distance,
            current_price=entry_price,
            current_equity=current_equity,
        )

        # 3. Calculate SL/TP prices
        sl_price = self._rm.calculate_sl_price(entry_price, sl_distance, direction)
        tp_price = self._rm.calculate_tp_price(entry_price, tp_distance, direction)

        # 4. Submit bracket order
        if direction == Direction.LONG:
            orders = self._submit_long_bracket(size, sl_price, tp_price)
        else:
            orders = self._submit_short_bracket(size, sl_price, tp_price)

        # 5. Track state and notify RiskManager
        main_ref = orders[0].ref
        self._active_trades[main_ref] = {
            "direction": direction,
            "sl_price": sl_price,
            "tp_price": tp_price,
            "size": size,
            "entry_price": entry_price,
        }
        self._rm.on_trade_opened()

        return orders

    def on_trade_closed(self, pnl: float, ref: Optional[int] = None) -> None:
        """Notify that a trade has been closed.

        Args:
            pnl: Realised P&L of the closed trade.
            ref: Main order ref (to clean up tracking). If None, just
                 updates RiskManager without cleaning up specific trade.
        """
        self._rm.on_trade_closed(pnl=pnl)
        if ref is not None:
            self._active_trades.pop(ref, None)

    def on_order_rejected(self, ref: int) -> None:
        """Rollback RiskManager state when broker rejects an order.

        When a bracket order is submitted, on_trade_opened() is called
        optimistically. If the broker rejects the entry order (e.g. due
        to margin), we must undo that so the position count doesn't
        get permanently stuck.

        Args:
            ref: Main order reference of the rejected bracket.
        """
        if ref not in self._active_trades:
            return  # Unknown ref — nothing to roll back
        self._active_trades.pop(ref)
        self._rm.on_order_rejected()

    def get_trade_info(self, ref: int) -> Optional[Dict]:
        """Get stored metadata for an active trade by order ref.

        Args:
            ref: Main order reference from buy_bracket/sell_bracket.

        Returns:
            Dict with sl_price, tp_price, direction, size, entry_price,
            or None if not found.
        """
        return self._active_trades.get(ref)

    def reset_daily(self) -> None:
        """Reset daily loss tracking. Called at the start of each trading day."""
        self._rm.reset_daily()

    # ------------------------------------------------------------------
    # Internal Order Submission
    # ------------------------------------------------------------------

    def _submit_long_bracket(
        self, size: float, sl_price: float, tp_price: Optional[float]
    ) -> List:
        """Submit a buy bracket order (entry + SL below + optional TP above)."""
        kwargs = {
            "size": size,
            "stopprice": sl_price,
        }
        if tp_price is not None:
            kwargs["limitprice"] = tp_price

        return self._strategy.buy_bracket(**kwargs)

    def _submit_short_bracket(
        self, size: float, sl_price: float, tp_price: Optional[float]
    ) -> List:
        """Submit a sell bracket order (entry + SL above + optional TP below)."""
        kwargs = {
            "size": size,
            "stopprice": sl_price,
        }
        if tp_price is not None:
            kwargs["limitprice"] = tp_price

        return self._strategy.sell_bracket(**kwargs)
