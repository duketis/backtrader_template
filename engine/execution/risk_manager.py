"""
Risk Manager — position sizing and risk guards.

Centralises all risk-related logic:
  - Position size calculation (4 methods)
  - Max concurrent positions enforcement
  - Daily loss limit enforcement
  - SL/TP price calculation
"""

from typing import Optional, Tuple, Union

from core.config import PositionSizingConfig, RiskConfig
from core.types import Direction, PositionSizingMethod


class RiskManager:
    """Calculates position sizes and enforces risk limits.

    This class is stateful — it tracks open positions and daily P&L
    so that risk guards can block new trades when limits are reached.

    Args:
        sizing_config: Position sizing parameters from YAML config.
        risk_config: Risk limit parameters from YAML config.
        initial_balance: Starting account balance in dollars.
    """

    def __init__(
        self,
        sizing_config: PositionSizingConfig,
        risk_config: RiskConfig,
        initial_balance: float,
    ):
        self._sizing = sizing_config
        self._risk = risk_config
        self._initial_balance = initial_balance

        # Mutable state
        self._open_positions: int = 0
        self._daily_pnl: float = 0.0

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def open_positions(self) -> int:
        return self._open_positions

    @property
    def daily_pnl(self) -> float:
        return self._daily_pnl

    # ------------------------------------------------------------------
    # Position Sizing
    # ------------------------------------------------------------------

    def calculate_size(
        self,
        sl_distance: float,
        current_price: float,
        current_equity: Optional[float] = None,
    ) -> float:
        """Calculate position size based on the configured sizing method.

        Args:
            sl_distance: Distance to stop loss in index points (always positive).
            current_price: Current market price (needed for fixed_dollar).
            current_equity: Current account equity. Used by percent_equity;
                            falls back to initial_balance if not provided.

        Returns:
            Position size (number of units/contracts).

        Raises:
            ValueError: If sl_distance <= 0 (for methods that require it)
                        or current_price <= 0 (for fixed_dollar).
        """
        method = self._sizing.method

        if method == PositionSizingMethod.FIXED_LOT:
            return self._sizing.fixed_lot_size

        if method == PositionSizingMethod.FIXED_RISK:
            self._validate_sl_distance(sl_distance)
            return self._sizing.risk_per_trade_dollars / sl_distance

        if method == PositionSizingMethod.PERCENT_EQUITY:
            self._validate_sl_distance(sl_distance)
            equity = current_equity if current_equity is not None else self._initial_balance
            risk_dollars = equity * self._sizing.risk_per_trade_percent / 100.0
            return risk_dollars / sl_distance

        if method == PositionSizingMethod.FIXED_DOLLAR:
            if current_price <= 0:
                raise ValueError("current price must be > 0 for fixed_dollar sizing")
            return self._sizing.fixed_dollar_amount / current_price

        raise ValueError(f"Unknown sizing method: {method}")

    # ------------------------------------------------------------------
    # Risk Guards
    # ------------------------------------------------------------------

    def can_open_trade(self, return_reason: bool = False) -> Union[bool, Tuple[bool, str]]:
        """Check whether a new trade is allowed.

        Evaluates all risk guards:
          1. Max concurrent positions
          2. Daily loss limit (dollars)
          3. Daily loss limit (percent of initial balance)

        Args:
            return_reason: If True, return a (bool, str) tuple with the
                           blocking reason. Otherwise return just bool.

        Returns:
            True if allowed, False if blocked.
            Or (True/False, reason_string) if return_reason=True.
        """
        # --- Max positions ---
        if self._open_positions >= self._risk.max_positions:
            reason = (
                f"Max positions reached ({self._open_positions}/{self._risk.max_positions})"
            )
            return (False, reason) if return_reason else False

        # --- Daily dollar loss ---
        if self._risk.max_daily_loss_dollars > 0:
            if abs(self._daily_pnl) >= self._risk.max_daily_loss_dollars and self._daily_pnl < 0:
                reason = (
                    f"Daily loss limit hit: "
                    f"${abs(self._daily_pnl):.2f} >= ${self._risk.max_daily_loss_dollars:.2f}"
                )
                return (False, reason) if return_reason else False

        # --- Daily percent loss ---
        if self._risk.max_daily_loss_percent > 0:
            loss_pct = abs(self._daily_pnl) / self._initial_balance * 100.0
            if loss_pct >= self._risk.max_daily_loss_percent and self._daily_pnl < 0:
                reason = (
                    f"Daily loss % limit hit: "
                    f"{loss_pct:.2f}% >= {self._risk.max_daily_loss_percent:.2f}%"
                )
                return (False, reason) if return_reason else False

        return (True, "") if return_reason else True

    # ------------------------------------------------------------------
    # State Updates
    # ------------------------------------------------------------------

    def on_trade_opened(self) -> None:
        """Notify the manager that a new position has been opened."""
        self._open_positions += 1

    def on_trade_closed(self, pnl: float) -> None:
        """Notify the manager that a position has been closed.

        Args:
            pnl: Realised P&L of the trade (positive = profit).
        """
        self._open_positions = max(0, self._open_positions - 1)
        self._daily_pnl += pnl

    def on_order_rejected(self) -> None:
        """Rollback on_trade_opened when broker rejects the order.

        This undoes the optimistic position count increment that happened
        when the bracket order was submitted but before it was filled.
        """
        self._open_positions = max(0, self._open_positions - 1)

    def reset_daily(self) -> None:
        """Reset daily P&L tracking. Call at the start of each trading day."""
        self._daily_pnl = 0.0

    # ------------------------------------------------------------------
    # SL / TP Price Helpers
    # ------------------------------------------------------------------

    def calculate_sl_price(
        self, entry_price: float, sl_distance: float, direction: Direction
    ) -> float:
        """Calculate stop-loss price from entry and distance.

        Args:
            entry_price: Fill price of the trade.
            sl_distance: Distance in index points (positive).
            direction: LONG or SHORT.

        Returns:
            Stop-loss price.
        """
        if direction == Direction.LONG:
            return entry_price - sl_distance
        return entry_price + sl_distance

    def calculate_tp_price(
        self,
        entry_price: float,
        tp_distance: float,
        direction: Direction,
    ) -> Optional[float]:
        """Calculate take-profit price from entry and distance.

        Args:
            entry_price: Fill price of the trade.
            tp_distance: Distance in index points (positive). 0 = no TP.
            direction: LONG or SHORT.

        Returns:
            Take-profit price, or None if tp_distance is 0.
        """
        if tp_distance == 0.0:
            return None
        if direction == Direction.LONG:
            return entry_price + tp_distance
        return entry_price - tp_distance

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_sl_distance(sl_distance: float) -> None:
        if sl_distance <= 0:
            raise ValueError(
                f"stop loss distance must be > 0, got {sl_distance}"
            )
