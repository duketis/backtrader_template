"""
Tests for the RiskManager module.

Validates all position sizing methods and risk guards. TDD — these
tests are written BEFORE the implementation to define the contract.

Position sizing methods:
  - fixed_lot:      Always return the configured lot size
  - fixed_risk:     size = risk_dollars / sl_distance_points
  - percent_equity: size = (equity * risk_pct / 100) / sl_distance_points
  - fixed_dollar:   size = dollar_amount / current_price

Risk guards:
  - max_positions:      Block trades if at max concurrent positions
  - max_daily_loss:     Block trades if daily loss limit hit (dollars or %)
"""

from datetime import datetime

import pytest

from core.types import CostModel, Direction, PositionSizingMethod, TradeRecord, TradeStatus
from core.config import PositionSizingConfig, RiskConfig
from execution.risk_manager import RiskManager


# ==============================================================================
# Fixtures
# ==============================================================================

@pytest.fixture
def fixed_lot_config():
    return PositionSizingConfig(
        method=PositionSizingMethod.FIXED_LOT,
        fixed_lot_size=2.0,
        risk_per_trade_dollars=1000,
        risk_per_trade_percent=1.0,
        fixed_dollar_amount=5000,
    )


@pytest.fixture
def fixed_risk_config():
    return PositionSizingConfig(
        method=PositionSizingMethod.FIXED_RISK,
        fixed_lot_size=1.0,
        risk_per_trade_dollars=1000,
        risk_per_trade_percent=1.0,
        fixed_dollar_amount=5000,
    )


@pytest.fixture
def percent_equity_config():
    return PositionSizingConfig(
        method=PositionSizingMethod.PERCENT_EQUITY,
        fixed_lot_size=1.0,
        risk_per_trade_dollars=1000,
        risk_per_trade_percent=2.0,
        fixed_dollar_amount=5000,
    )


@pytest.fixture
def fixed_dollar_config():
    return PositionSizingConfig(
        method=PositionSizingMethod.FIXED_DOLLAR,
        fixed_lot_size=1.0,
        risk_per_trade_dollars=1000,
        risk_per_trade_percent=1.0,
        fixed_dollar_amount=10000,
    )


@pytest.fixture
def risk_config():
    return RiskConfig(
        max_positions=1,
        max_daily_loss_dollars=5000,
        max_daily_loss_percent=5.0,
    )


@pytest.fixture
def relaxed_risk_config():
    """Risk config with generous limits for sizing tests."""
    return RiskConfig(
        max_positions=10,
        max_daily_loss_dollars=0,  # 0 = disabled
        max_daily_loss_percent=0,  # 0 = disabled
    )


@pytest.fixture
def cost_model():
    return CostModel(spread_points=1.14)


def _make_rm(sizing_config, risk_config, initial_balance=100000):
    """Helper to create a RiskManager."""
    return RiskManager(
        sizing_config=sizing_config,
        risk_config=risk_config,
        initial_balance=initial_balance,
    )


# ==============================================================================
# Fixed Lot Sizing
# ==============================================================================

class TestFixedLotSizing:
    """fixed_lot: Always return the configured lot size, ignoring SL."""

    def test_returns_configured_lot_size(self, fixed_lot_config, relaxed_risk_config):
        rm = _make_rm(fixed_lot_config, relaxed_risk_config)
        size = rm.calculate_size(sl_distance=50.0, current_price=16500.0)
        assert size == 2.0

    def test_ignores_sl_distance(self, fixed_lot_config, relaxed_risk_config):
        rm = _make_rm(fixed_lot_config, relaxed_risk_config)
        size_small_sl = rm.calculate_size(sl_distance=10.0, current_price=16500.0)
        size_large_sl = rm.calculate_size(sl_distance=200.0, current_price=16500.0)
        assert size_small_sl == size_large_sl == 2.0

    def test_ignores_current_price(self, fixed_lot_config, relaxed_risk_config):
        rm = _make_rm(fixed_lot_config, relaxed_risk_config)
        size = rm.calculate_size(sl_distance=50.0, current_price=20000.0)
        assert size == 2.0


# ==============================================================================
# Fixed Risk Sizing
# ==============================================================================

class TestFixedRiskSizing:
    """fixed_risk: size = risk_dollars / sl_distance_points."""

    def test_basic_calculation(self, fixed_risk_config, relaxed_risk_config):
        """$1000 risk / 50pt SL = 20 units."""
        rm = _make_rm(fixed_risk_config, relaxed_risk_config)
        size = rm.calculate_size(sl_distance=50.0, current_price=16500.0)
        assert size == pytest.approx(20.0)

    def test_small_sl_gives_larger_size(self, fixed_risk_config, relaxed_risk_config):
        """$1000 risk / 10pt SL = 100 units."""
        rm = _make_rm(fixed_risk_config, relaxed_risk_config)
        size = rm.calculate_size(sl_distance=10.0, current_price=16500.0)
        assert size == pytest.approx(100.0)

    def test_large_sl_gives_smaller_size(self, fixed_risk_config, relaxed_risk_config):
        """$1000 risk / 200pt SL = 5 units."""
        rm = _make_rm(fixed_risk_config, relaxed_risk_config)
        size = rm.calculate_size(sl_distance=200.0, current_price=16500.0)
        assert size == pytest.approx(5.0)

    def test_fractional_size(self, fixed_risk_config, relaxed_risk_config):
        """$1000 risk / 300pt SL = 3.333... units."""
        rm = _make_rm(fixed_risk_config, relaxed_risk_config)
        size = rm.calculate_size(sl_distance=300.0, current_price=16500.0)
        assert size == pytest.approx(1000.0 / 300.0)

    def test_zero_sl_raises(self, fixed_risk_config, relaxed_risk_config):
        """SL distance of 0 should raise — can't divide by zero."""
        rm = _make_rm(fixed_risk_config, relaxed_risk_config)
        with pytest.raises(ValueError, match="stop loss distance"):
            rm.calculate_size(sl_distance=0.0, current_price=16500.0)

    def test_negative_sl_raises(self, fixed_risk_config, relaxed_risk_config):
        """Negative SL distance should raise."""
        rm = _make_rm(fixed_risk_config, relaxed_risk_config)
        with pytest.raises(ValueError, match="stop loss distance"):
            rm.calculate_size(sl_distance=-10.0, current_price=16500.0)

    def test_risk_per_trade_respected(self, relaxed_risk_config):
        """Different risk amounts should scale proportionally."""
        config_500 = PositionSizingConfig(
            method=PositionSizingMethod.FIXED_RISK,
            fixed_lot_size=1.0,
            risk_per_trade_dollars=500,
            risk_per_trade_percent=1.0,
            fixed_dollar_amount=5000,
        )
        config_2000 = PositionSizingConfig(
            method=PositionSizingMethod.FIXED_RISK,
            fixed_lot_size=1.0,
            risk_per_trade_dollars=2000,
            risk_per_trade_percent=1.0,
            fixed_dollar_amount=5000,
        )
        rm_500 = _make_rm(config_500, relaxed_risk_config)
        rm_2000 = _make_rm(config_2000, relaxed_risk_config)

        size_500 = rm_500.calculate_size(sl_distance=50.0, current_price=16500.0)
        size_2000 = rm_2000.calculate_size(sl_distance=50.0, current_price=16500.0)

        assert size_500 == pytest.approx(10.0)   # 500 / 50
        assert size_2000 == pytest.approx(40.0)  # 2000 / 50


# ==============================================================================
# Percent Equity Sizing
# ==============================================================================

class TestPercentEquitySizing:
    """percent_equity: size = (equity * pct / 100) / sl_distance."""

    def test_basic_calculation(self, percent_equity_config, relaxed_risk_config):
        """2% of $100k = $2000 risk. $2000 / 50pt SL = 40 units."""
        rm = _make_rm(percent_equity_config, relaxed_risk_config, initial_balance=100000)
        size = rm.calculate_size(sl_distance=50.0, current_price=16500.0, current_equity=100000)
        assert size == pytest.approx(40.0)

    def test_equity_growth_increases_size(self, percent_equity_config, relaxed_risk_config):
        """As equity grows, risk amount grows → bigger position."""
        rm = _make_rm(percent_equity_config, relaxed_risk_config, initial_balance=100000)
        size = rm.calculate_size(sl_distance=50.0, current_price=16500.0, current_equity=150000)
        # 2% of 150k = 3000. 3000 / 50 = 60
        assert size == pytest.approx(60.0)

    def test_equity_drawdown_decreases_size(self, percent_equity_config, relaxed_risk_config):
        """After a drawdown, equity is lower → smaller position."""
        rm = _make_rm(percent_equity_config, relaxed_risk_config, initial_balance=100000)
        size = rm.calculate_size(sl_distance=50.0, current_price=16500.0, current_equity=80000)
        # 2% of 80k = 1600. 1600 / 50 = 32
        assert size == pytest.approx(32.0)

    def test_uses_initial_balance_if_no_equity_provided(self, percent_equity_config, relaxed_risk_config):
        """If current_equity not passed, falls back to initial_balance."""
        rm = _make_rm(percent_equity_config, relaxed_risk_config, initial_balance=100000)
        size = rm.calculate_size(sl_distance=50.0, current_price=16500.0)
        # 2% of 100k = 2000. 2000 / 50 = 40
        assert size == pytest.approx(40.0)

    def test_zero_sl_raises(self, percent_equity_config, relaxed_risk_config):
        rm = _make_rm(percent_equity_config, relaxed_risk_config)
        with pytest.raises(ValueError, match="stop loss distance"):
            rm.calculate_size(sl_distance=0.0, current_price=16500.0)


# ==============================================================================
# Fixed Dollar Sizing
# ==============================================================================

class TestFixedDollarSizing:
    """fixed_dollar: size = dollar_amount / current_price."""

    def test_basic_calculation(self, fixed_dollar_config, relaxed_risk_config):
        """$10,000 / $16,500 price ≈ 0.606 units."""
        rm = _make_rm(fixed_dollar_config, relaxed_risk_config)
        size = rm.calculate_size(sl_distance=50.0, current_price=16500.0)
        assert size == pytest.approx(10000.0 / 16500.0)

    def test_higher_price_gives_smaller_size(self, fixed_dollar_config, relaxed_risk_config):
        rm = _make_rm(fixed_dollar_config, relaxed_risk_config)
        size = rm.calculate_size(sl_distance=50.0, current_price=20000.0)
        assert size == pytest.approx(10000.0 / 20000.0)

    def test_lower_price_gives_larger_size(self, fixed_dollar_config, relaxed_risk_config):
        rm = _make_rm(fixed_dollar_config, relaxed_risk_config)
        size = rm.calculate_size(sl_distance=50.0, current_price=10000.0)
        assert size == pytest.approx(10000.0 / 10000.0)

    def test_zero_price_raises(self, fixed_dollar_config, relaxed_risk_config):
        rm = _make_rm(fixed_dollar_config, relaxed_risk_config)
        with pytest.raises(ValueError, match="current price"):
            rm.calculate_size(sl_distance=50.0, current_price=0.0)


# ==============================================================================
# Max Positions Guard
# ==============================================================================

class TestMaxPositionsGuard:
    """Enforce max concurrent open positions."""

    def test_can_trade_when_no_positions(self, fixed_risk_config, risk_config):
        rm = _make_rm(fixed_risk_config, risk_config)
        assert rm.can_open_trade() is True

    def test_cannot_trade_at_max_positions(self, fixed_risk_config, risk_config):
        """max_positions=1, one position open → can't trade."""
        rm = _make_rm(fixed_risk_config, risk_config)
        rm.on_trade_opened()
        assert rm.can_open_trade() is False

    def test_can_trade_after_position_closes(self, fixed_risk_config, risk_config):
        rm = _make_rm(fixed_risk_config, risk_config)
        rm.on_trade_opened()
        assert rm.can_open_trade() is False
        rm.on_trade_closed(pnl=50.0)
        assert rm.can_open_trade() is True

    def test_multiple_positions_allowed(self, fixed_risk_config):
        """max_positions=3, should allow 3 concurrent."""
        config = RiskConfig(max_positions=3, max_daily_loss_dollars=0, max_daily_loss_percent=0)
        rm = _make_rm(fixed_risk_config, config)
        rm.on_trade_opened()
        rm.on_trade_opened()
        assert rm.can_open_trade() is True  # 2 open, limit is 3
        rm.on_trade_opened()
        assert rm.can_open_trade() is False  # 3 open, at limit

    def test_open_positions_count(self, fixed_risk_config, risk_config):
        rm = _make_rm(fixed_risk_config, risk_config)
        assert rm.open_positions == 0
        rm.on_trade_opened()
        assert rm.open_positions == 1
        rm.on_trade_closed(pnl=0)
        assert rm.open_positions == 0


# ==============================================================================
# Daily Loss Limit Guard
# ==============================================================================

class TestDailyLossLimit:
    """Enforce daily loss limits (dollars and percent)."""

    def test_can_trade_within_loss_limit(self, fixed_risk_config, risk_config):
        """Daily loss < $5000 → can still trade."""
        rm = _make_rm(fixed_risk_config, risk_config, initial_balance=100000)
        rm.on_trade_closed(pnl=-1000)
        assert rm.can_open_trade() is True

    def test_cannot_trade_at_dollar_limit(self, fixed_risk_config):
        """Daily loss >= $5000 → blocked."""
        config = RiskConfig(max_positions=10, max_daily_loss_dollars=5000, max_daily_loss_percent=0)
        rm = _make_rm(fixed_risk_config, config, initial_balance=100000)
        rm.on_trade_closed(pnl=-3000)
        rm.on_trade_closed(pnl=-2000)
        # Total daily loss = -5000, at limit
        assert rm.can_open_trade() is False

    def test_cannot_trade_at_percent_limit(self, fixed_risk_config):
        """Daily loss >= 5% of initial balance → blocked."""
        config = RiskConfig(max_positions=10, max_daily_loss_dollars=0, max_daily_loss_percent=5.0)
        rm = _make_rm(fixed_risk_config, config, initial_balance=100000)
        rm.on_trade_closed(pnl=-5000)  # 5% of 100k
        assert rm.can_open_trade() is False

    def test_winning_trades_offset_losses(self, fixed_risk_config):
        """A win after a loss should reduce daily loss count."""
        config = RiskConfig(max_positions=10, max_daily_loss_dollars=5000, max_daily_loss_percent=0)
        rm = _make_rm(fixed_risk_config, config, initial_balance=100000)
        rm.on_trade_closed(pnl=-4000)
        rm.on_trade_closed(pnl=2000)
        # Net daily = -2000, still under limit
        assert rm.can_open_trade() is True

    def test_daily_loss_resets_on_new_day(self, fixed_risk_config):
        """Loss tracking should reset for a new trading day."""
        config = RiskConfig(max_positions=10, max_daily_loss_dollars=5000, max_daily_loss_percent=0)
        rm = _make_rm(fixed_risk_config, config, initial_balance=100000)
        rm.on_trade_closed(pnl=-5000)
        assert rm.can_open_trade() is False
        rm.reset_daily()
        assert rm.can_open_trade() is True

    def test_disabled_when_zero(self, fixed_risk_config, relaxed_risk_config):
        """0 means disabled — should never block."""
        rm = _make_rm(fixed_risk_config, relaxed_risk_config, initial_balance=100000)
        rm.on_trade_closed(pnl=-50000)  # Massive loss
        assert rm.can_open_trade() is True  # Still allowed (limits disabled)

    def test_daily_pnl_tracking(self, fixed_risk_config, risk_config):
        rm = _make_rm(fixed_risk_config, risk_config, initial_balance=100000)
        assert rm.daily_pnl == 0.0
        rm.on_trade_closed(pnl=-1000)
        assert rm.daily_pnl == -1000.0
        rm.on_trade_closed(pnl=500)
        assert rm.daily_pnl == -500.0


# ==============================================================================
# Combined Guards
# ==============================================================================

class TestCombinedGuards:
    """Test that both guards work together."""

    def test_blocked_by_positions_even_if_pnl_ok(self, fixed_risk_config):
        config = RiskConfig(max_positions=1, max_daily_loss_dollars=5000, max_daily_loss_percent=0)
        rm = _make_rm(fixed_risk_config, config)
        rm.on_trade_opened()
        # P&L is fine but max positions reached
        assert rm.can_open_trade() is False

    def test_blocked_by_daily_loss_even_if_positions_ok(self, fixed_risk_config):
        config = RiskConfig(max_positions=10, max_daily_loss_dollars=1000, max_daily_loss_percent=0)
        rm = _make_rm(fixed_risk_config, config, initial_balance=100000)
        rm.on_trade_closed(pnl=-1000)
        # Positions are fine but daily loss limit hit
        assert rm.can_open_trade() is False

    def test_reason_returned_when_blocked(self, fixed_risk_config):
        """can_open_trade should explain WHY it blocked."""
        config = RiskConfig(max_positions=1, max_daily_loss_dollars=5000, max_daily_loss_percent=0)
        rm = _make_rm(fixed_risk_config, config)
        rm.on_trade_opened()
        allowed, reason = rm.can_open_trade(return_reason=True)
        assert allowed is False
        assert "max positions" in reason.lower()


# ==============================================================================
# SL/TP Price Calculation
# ==============================================================================

class TestSLTPCalculation:
    """Test stop loss and take profit price calculation."""

    def test_long_sl_below_entry(self, fixed_risk_config, relaxed_risk_config):
        rm = _make_rm(fixed_risk_config, relaxed_risk_config)
        sl = rm.calculate_sl_price(entry_price=16500.0, sl_distance=50.0, direction=Direction.LONG)
        assert sl == pytest.approx(16450.0)

    def test_short_sl_above_entry(self, fixed_risk_config, relaxed_risk_config):
        rm = _make_rm(fixed_risk_config, relaxed_risk_config)
        sl = rm.calculate_sl_price(entry_price=16500.0, sl_distance=50.0, direction=Direction.SHORT)
        assert sl == pytest.approx(16550.0)

    def test_long_tp_above_entry(self, fixed_risk_config, relaxed_risk_config):
        rm = _make_rm(fixed_risk_config, relaxed_risk_config)
        tp = rm.calculate_tp_price(entry_price=16500.0, tp_distance=100.0, direction=Direction.LONG)
        assert tp == pytest.approx(16600.0)

    def test_short_tp_below_entry(self, fixed_risk_config, relaxed_risk_config):
        rm = _make_rm(fixed_risk_config, relaxed_risk_config)
        tp = rm.calculate_tp_price(entry_price=16500.0, tp_distance=100.0, direction=Direction.SHORT)
        assert tp == pytest.approx(16400.0)

    def test_zero_tp_distance_returns_none(self, fixed_risk_config, relaxed_risk_config):
        """TP of 0 means no take profit — return None."""
        rm = _make_rm(fixed_risk_config, relaxed_risk_config)
        tp = rm.calculate_tp_price(entry_price=16500.0, tp_distance=0.0, direction=Direction.LONG)
        assert tp is None
