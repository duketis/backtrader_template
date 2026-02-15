"""
Tests for core types, enums, and dataclasses.

Validates that our shared data structures behave correctly.
These are the foundation — if types are wrong, everything is wrong.
"""

from datetime import datetime

import pytest

from core.types import (
    BacktestResult,
    CostModel,
    Direction,
    PositionSizingMethod,
    SessionWindow,
    Timeframe,
    TradeRecord,
    TradeStatus,
)


class TestTimeframeEnum:
    """Tests for the Timeframe enum and its utility methods."""

    def test_from_string_valid(self):
        assert Timeframe.from_string("1min") == Timeframe.ONE_MIN
        assert Timeframe.from_string("5min") == Timeframe.FIVE_MIN
        assert Timeframe.from_string("1hour") == Timeframe.ONE_HOUR
        assert Timeframe.from_string("4hour") == Timeframe.FOUR_HOUR
        assert Timeframe.from_string("tick") == Timeframe.TICK

    def test_from_string_invalid_raises(self):
        with pytest.raises(ValueError, match="Unknown timeframe"):
            Timeframe.from_string("2min")

    def test_pandas_freq(self):
        assert Timeframe.ONE_MIN.pandas_freq == "1min"
        assert Timeframe.FIVE_MIN.pandas_freq == "5min"
        assert Timeframe.ONE_HOUR.pandas_freq == "1h"
        assert Timeframe.FOUR_HOUR.pandas_freq == "4h"

    def test_tick_pandas_freq_raises(self):
        with pytest.raises(ValueError, match="Cannot resample to tick"):
            Timeframe.TICK.pandas_freq

    def test_display_name(self):
        assert Timeframe.ONE_MIN.display_name == "1 Minute"
        assert Timeframe.FOUR_HOUR.display_name == "4 Hour"
        assert Timeframe.TICK.display_name == "Tick"


class TestPositionSizingMethod:
    """Tests for the PositionSizingMethod enum."""

    def test_all_methods_exist(self):
        assert PositionSizingMethod.FIXED_LOT.value == "fixed_lot"
        assert PositionSizingMethod.FIXED_RISK.value == "fixed_risk"
        assert PositionSizingMethod.PERCENT_EQUITY.value == "percent_equity"
        assert PositionSizingMethod.FIXED_DOLLAR.value == "fixed_dollar"

    def test_from_yaml_string(self):
        """Config loads these as strings — verify they map correctly."""
        assert PositionSizingMethod("fixed_lot") == PositionSizingMethod.FIXED_LOT
        assert PositionSizingMethod("percent_equity") == PositionSizingMethod.PERCENT_EQUITY


class TestCostModel:
    """Tests for the CostModel dataclass and its calculations."""

    def test_half_spread(self, sample_cost_model):
        assert sample_cost_model.half_spread == pytest.approx(0.57)

    def test_half_spread_zero(self):
        model = CostModel(spread_points=0.0)
        assert model.half_spread == 0.0

    def test_entry_cost_per_unit(self, sample_cost_model):
        # spread_points=1.14, slippage=0 → half_spread = 0.57
        assert sample_cost_model.total_entry_cost_per_unit() == pytest.approx(0.57)

    def test_entry_cost_with_slippage(self):
        model = CostModel(spread_points=2.0, slippage_points=0.5)
        # half_spread=1.0, slippage=0.5 → 1.5
        assert model.total_entry_cost_per_unit() == pytest.approx(1.5)

    def test_commission_for_trade_flat(self):
        model = CostModel(commission_per_trade=5.0, commission_per_lot=0.0)
        assert model.commission_for_trade(lot_size=1.0) == 5.0
        assert model.commission_for_trade(lot_size=3.0) == 5.0  # Flat, not per-lot

    def test_commission_for_trade_per_lot(self):
        model = CostModel(commission_per_trade=0.0, commission_per_lot=2.0)
        assert model.commission_for_trade(lot_size=1.0) == 2.0
        assert model.commission_for_trade(lot_size=3.0) == 6.0

    def test_commission_for_trade_combined(self, sample_cost_model_with_commission):
        # commission_per_trade=2.0, commission_per_lot=1.0
        assert sample_cost_model_with_commission.commission_for_trade(1.0) == 3.0
        assert sample_cost_model_with_commission.commission_for_trade(2.0) == 4.0


class TestTradeRecord:
    """Tests for the TradeRecord dataclass."""

    def test_is_winner_positive_pnl(self, sample_trade_winner):
        assert sample_trade_winner.is_winner is True

    def test_is_winner_negative_pnl(self, sample_trade_loser):
        assert sample_trade_loser.is_winner is False

    def test_is_winner_zero_pnl(self):
        trade = TradeRecord(trade_id=1, direction=Direction.LONG, entry_time=datetime.now())
        trade.net_pnl = 0.0
        assert trade.is_winner is False

    def test_risk_reward_actual(self, sample_trade_winner):
        # entry=16500, exit=16550, SL=16470
        # risk = |16500 - 16470| = 30
        # reward = |16550 - 16500| = 50
        # R:R = 50/30 ≈ 1.667
        assert sample_trade_winner.risk_reward_actual == pytest.approx(50.0 / 30.0)

    def test_risk_reward_no_stop_loss(self):
        trade = TradeRecord(
            trade_id=1, direction=Direction.LONG,
            entry_time=datetime.now(),
            entry_price=100.0, exit_price=110.0, stop_loss=None,
        )
        assert trade.risk_reward_actual is None

    def test_duration_seconds(self, sample_trade_winner):
        # entry=14:30, exit=16:00 → 90 minutes = 5400 seconds
        assert sample_trade_winner.duration_seconds == 5400.0

    def test_duration_open_trade(self):
        trade = TradeRecord(
            trade_id=1, direction=Direction.LONG,
            entry_time=datetime.now(), exit_time=None,
        )
        assert trade.duration_seconds is None

    def test_default_status_is_open(self):
        trade = TradeRecord(trade_id=1, direction=Direction.LONG, entry_time=datetime.now())
        assert trade.status == TradeStatus.OPEN
