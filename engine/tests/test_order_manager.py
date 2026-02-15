"""
Tests for the OrderManager module.

OrderManager is a helper class that strategies delegate to for
bracket order submission (SL/TP). It uses RiskManager for sizing
and risk checks, and wraps backtrader's buy_bracket/sell_bracket.

Unit tests mock the backtrader Strategy to avoid needing Cerebro.
"""

from unittest.mock import MagicMock, patch, call
from datetime import datetime

import pytest

from core.types import Direction, PositionSizingMethod
from core.config import PositionSizingConfig, RiskConfig
from execution.risk_manager import RiskManager
from execution.order_manager import OrderManager


# ==============================================================================
# Fixtures
# ==============================================================================

@pytest.fixture
def risk_manager():
    sizing = PositionSizingConfig(
        method=PositionSizingMethod.FIXED_RISK,
        fixed_lot_size=1.0,
        risk_per_trade_dollars=1000,
        risk_per_trade_percent=1.0,
        fixed_dollar_amount=5000,
    )
    risk = RiskConfig(max_positions=2, max_daily_loss_dollars=5000, max_daily_loss_percent=5.0)
    return RiskManager(sizing_config=sizing, risk_config=risk, initial_balance=100000)


@pytest.fixture
def mock_strategy():
    """Mock backtrader Strategy with the methods we need."""
    strategy = MagicMock()

    # Generate unique refs for each buy_bracket call
    _buy_ref_counter = [0]
    def _buy_bracket(**kwargs):
        base = _buy_ref_counter[0] * 10 + 1
        _buy_ref_counter[0] += 1
        return [MagicMock(ref=base), MagicMock(ref=base + 1), MagicMock(ref=base + 2)]

    _sell_ref_counter = [0]
    def _sell_bracket(**kwargs):
        base = _sell_ref_counter[0] * 10 + 100
        _sell_ref_counter[0] += 1
        return [MagicMock(ref=base), MagicMock(ref=base + 1), MagicMock(ref=base + 2)]

    strategy.buy_bracket = MagicMock(side_effect=_buy_bracket)
    strategy.sell_bracket = MagicMock(side_effect=_sell_bracket)
    strategy.close = MagicMock()
    strategy.broker.getvalue = MagicMock(return_value=100000)
    return strategy


@pytest.fixture
def order_manager(risk_manager, mock_strategy):
    return OrderManager(risk_manager=risk_manager, strategy=mock_strategy)


# ==============================================================================
# Open Long Position
# ==============================================================================

class TestOpenLong:
    """Test opening long positions with bracket orders."""

    def test_submits_buy_bracket(self, order_manager, mock_strategy):
        """Should call strategy.buy_bracket with correct SL/TP."""
        result = order_manager.open_position(
            direction=Direction.LONG,
            entry_price=16500.0,
            sl_distance=50.0,
            tp_distance=100.0,
        )
        assert result is not None
        mock_strategy.buy_bracket.assert_called_once()
        kwargs = mock_strategy.buy_bracket.call_args
        # SL is below entry for long
        assert kwargs.kwargs["stopprice"] == pytest.approx(16450.0)
        # TP is above entry for long
        assert kwargs.kwargs["limitprice"] == pytest.approx(16600.0)

    def test_calculates_correct_size(self, order_manager, mock_strategy):
        """Size = $1000 risk / 50pt SL = 20 units."""
        order_manager.open_position(
            direction=Direction.LONG,
            entry_price=16500.0,
            sl_distance=50.0,
            tp_distance=100.0,
        )
        kwargs = mock_strategy.buy_bracket.call_args
        assert kwargs.kwargs["size"] == pytest.approx(20.0)

    def test_increments_open_positions(self, order_manager, risk_manager):
        order_manager.open_position(
            direction=Direction.LONG,
            entry_price=16500.0,
            sl_distance=50.0,
            tp_distance=100.0,
        )
        assert risk_manager.open_positions == 1

    def test_no_tp_when_distance_zero(self, order_manager, mock_strategy):
        """TP distance = 0 should submit without take profit (no limitprice)."""
        order_manager.open_position(
            direction=Direction.LONG,
            entry_price=16500.0,
            sl_distance=50.0,
            tp_distance=0.0,
        )
        kwargs = mock_strategy.buy_bracket.call_args
        assert kwargs.kwargs.get("limitprice") is None


# ==============================================================================
# Open Short Position
# ==============================================================================

class TestOpenShort:
    """Test opening short positions with bracket orders."""

    def test_submits_sell_bracket(self, order_manager, mock_strategy):
        result = order_manager.open_position(
            direction=Direction.SHORT,
            entry_price=16500.0,
            sl_distance=50.0,
            tp_distance=100.0,
        )
        assert result is not None
        mock_strategy.sell_bracket.assert_called_once()
        kwargs = mock_strategy.sell_bracket.call_args
        # SL is above entry for short
        assert kwargs.kwargs["stopprice"] == pytest.approx(16550.0)
        # TP is below entry for short
        assert kwargs.kwargs["limitprice"] == pytest.approx(16400.0)

    def test_calculates_correct_size(self, order_manager, mock_strategy):
        order_manager.open_position(
            direction=Direction.SHORT,
            entry_price=16500.0,
            sl_distance=50.0,
            tp_distance=100.0,
        )
        kwargs = mock_strategy.sell_bracket.call_args
        assert kwargs.kwargs["size"] == pytest.approx(20.0)


# ==============================================================================
# Risk Guard Integration
# ==============================================================================

class TestRiskGuardIntegration:
    """Test that OrderManager respects risk guards."""

    def test_blocks_when_max_positions_reached(self, order_manager, risk_manager, mock_strategy):
        """max_positions=2, so 3rd trade should be blocked."""
        order_manager.open_position(
            direction=Direction.LONG, entry_price=16500.0,
            sl_distance=50.0, tp_distance=100.0,
        )
        order_manager.open_position(
            direction=Direction.LONG, entry_price=16500.0,
            sl_distance=50.0, tp_distance=100.0,
        )
        result = order_manager.open_position(
            direction=Direction.LONG, entry_price=16500.0,
            sl_distance=50.0, tp_distance=100.0,
        )
        # Third should be blocked
        assert result is None
        # buy_bracket should have been called only twice
        assert mock_strategy.buy_bracket.call_count == 2

    def test_blocks_when_daily_loss_hit(self, order_manager, risk_manager, mock_strategy):
        """After daily loss >= $5000, new trades should be blocked."""
        risk_manager.on_trade_closed(pnl=-5000)
        result = order_manager.open_position(
            direction=Direction.LONG, entry_price=16500.0,
            sl_distance=50.0, tp_distance=100.0,
        )
        assert result is None
        mock_strategy.buy_bracket.assert_not_called()

    def test_allows_after_position_closed(self, order_manager, risk_manager, mock_strategy):
        """Opening 2 (at max), closing 1, should allow a new trade."""
        order_manager.open_position(
            direction=Direction.LONG, entry_price=16500.0,
            sl_distance=50.0, tp_distance=100.0,
        )
        order_manager.open_position(
            direction=Direction.LONG, entry_price=16500.0,
            sl_distance=50.0, tp_distance=100.0,
        )
        # Close one
        order_manager.on_trade_closed(pnl=200.0)
        # Now should be allowed
        result = order_manager.open_position(
            direction=Direction.LONG, entry_price=16500.0,
            sl_distance=50.0, tp_distance=100.0,
        )
        assert result is not None


# ==============================================================================
# Trade State Tracking
# ==============================================================================

class TestTradeStateTracking:
    """OrderManager should track SL/TP prices for open positions."""

    def test_stores_sl_tp_for_bracket(self, order_manager):
        orders = order_manager.open_position(
            direction=Direction.LONG,
            entry_price=16500.0,
            sl_distance=50.0,
            tp_distance=100.0,
        )
        main_ref = orders[0].ref
        info = order_manager.get_trade_info(main_ref)
        assert info is not None
        assert info["sl_price"] == pytest.approx(16450.0)
        assert info["tp_price"] == pytest.approx(16600.0)
        assert info["direction"] == Direction.LONG
        assert info["size"] == pytest.approx(20.0)

    def test_cleans_up_on_close(self, order_manager, risk_manager):
        orders = order_manager.open_position(
            direction=Direction.LONG,
            entry_price=16500.0,
            sl_distance=50.0,
            tp_distance=100.0,
        )
        main_ref = orders[0].ref
        order_manager.on_trade_closed(pnl=100.0, ref=main_ref)
        assert order_manager.get_trade_info(main_ref) is None

    def test_no_tp_stored_when_zero(self, order_manager):
        orders = order_manager.open_position(
            direction=Direction.LONG,
            entry_price=16500.0,
            sl_distance=50.0,
            tp_distance=0.0,
        )
        main_ref = orders[0].ref
        info = order_manager.get_trade_info(main_ref)
        assert info["tp_price"] is None


# ==============================================================================
# Equity Passthrough for Percent Equity Sizing
# ==============================================================================

class TestEquityPassthrough:
    """When using percent_equity sizing, equity should be read from broker."""

    def test_uses_broker_equity(self, mock_strategy):
        sizing = PositionSizingConfig(
            method=PositionSizingMethod.PERCENT_EQUITY,
            fixed_lot_size=1.0,
            risk_per_trade_dollars=1000,
            risk_per_trade_percent=2.0,
            fixed_dollar_amount=5000,
        )
        risk = RiskConfig(max_positions=10, max_daily_loss_dollars=0, max_daily_loss_percent=0)
        rm = RiskManager(sizing_config=sizing, risk_config=risk, initial_balance=100000)
        om = OrderManager(risk_manager=rm, strategy=mock_strategy)

        mock_strategy.broker.getvalue.return_value = 120000

        om.open_position(
            direction=Direction.LONG,
            entry_price=16500.0,
            sl_distance=50.0,
            tp_distance=100.0,
        )
        kwargs = mock_strategy.buy_bracket.call_args
        # 2% of 120k = 2400, 2400 / 50 = 48
        assert kwargs.kwargs["size"] == pytest.approx(48.0)


# ==============================================================================
# Order Rejection Rollback
# ==============================================================================

class TestOrderRejectionRollback:
    """When a broker rejects an order (Margin, etc.), the RiskManager state
    must be rolled back so the position count doesn't get stuck."""

    def test_rollback_decrements_open_positions(self, order_manager, risk_manager):
        """on_order_rejected should undo on_trade_opened so positions = 0."""
        orders = order_manager.open_position(
            direction=Direction.LONG,
            entry_price=16500.0,
            sl_distance=50.0,
            tp_distance=100.0,
        )
        assert risk_manager.open_positions == 1
        main_ref = orders[0].ref
        order_manager.on_order_rejected(ref=main_ref)
        assert risk_manager.open_positions == 0

    def test_rollback_removes_trade_info(self, order_manager):
        """Rejected order metadata should be cleaned up."""
        orders = order_manager.open_position(
            direction=Direction.LONG,
            entry_price=16500.0,
            sl_distance=50.0,
            tp_distance=100.0,
        )
        main_ref = orders[0].ref
        order_manager.on_order_rejected(ref=main_ref)
        assert order_manager.get_trade_info(main_ref) is None

    def test_rollback_allows_new_trades(self, order_manager, risk_manager, mock_strategy):
        """After rejection rollback, a new trade should be allowed."""
        # Fill up to max (2 positions)
        orders1 = order_manager.open_position(
            direction=Direction.LONG, entry_price=16500.0,
            sl_distance=50.0, tp_distance=100.0,
        )
        orders2 = order_manager.open_position(
            direction=Direction.LONG, entry_price=16500.0,
            sl_distance=50.0, tp_distance=100.0,
        )
        assert risk_manager.open_positions == 2

        # Reject the second order using its actual main ref
        order_manager.on_order_rejected(ref=orders2[0].ref)
        assert risk_manager.open_positions == 1

        # Now a new trade should be allowed
        result = order_manager.open_position(
            direction=Direction.LONG, entry_price=16500.0,
            sl_distance=50.0, tp_distance=100.0,
        )
        assert result is not None

    def test_rollback_unknown_ref_is_noop(self, order_manager, risk_manager):
        """Rejecting an unknown ref should not crash or change state."""
        order_manager.on_order_rejected(ref=9999)
        assert risk_manager.open_positions == 0
