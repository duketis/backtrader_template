"""
Tests for the cost model and trade cost calculations.

Validates that spread, commission, and slippage costs are computed
correctly for various configurations. This is critical — incorrect
cost calculations will make all P&L numbers wrong.
"""

import pytest

from core.types import CostModel


class TestSpreadCosts:
    """Verify spread cost calculations."""

    def test_default_spread(self):
        """Default spread of 1.14 points → half spread of 0.57."""
        model = CostModel(spread_points=1.14)
        assert model.half_spread == pytest.approx(0.57)

    def test_zero_spread(self):
        model = CostModel(spread_points=0.0)
        assert model.half_spread == 0.0
        assert model.total_entry_cost_per_unit() == 0.0

    def test_large_spread(self):
        """Max spread from Dukascopy data: ~18.50 points."""
        model = CostModel(spread_points=18.50)
        assert model.half_spread == pytest.approx(9.25)

    def test_spread_cost_for_position(self):
        """Total spread cost = spread_points * size (both sides)."""
        model = CostModel(spread_points=1.14)
        size = 2.0
        # Entry: half_spread * size = 0.57 * 2 = 1.14
        # Exit:  half_spread * size = 0.57 * 2 = 1.14
        # Total: 2.28
        entry_cost = model.half_spread * size
        exit_cost = model.half_spread * size
        assert entry_cost + exit_cost == pytest.approx(2.28)


class TestCommissionCosts:
    """Verify commission calculations for different configurations."""

    def test_zero_commission(self):
        """Zero-commission broker (spread-only)."""
        model = CostModel(commission_per_trade=0.0, commission_per_lot=0.0)
        assert model.commission_for_trade(1.0) == 0.0
        assert model.commission_for_trade(5.0) == 0.0

    def test_flat_commission_per_trade(self):
        """Fixed $5 per trade regardless of size."""
        model = CostModel(commission_per_trade=5.0, commission_per_lot=0.0)
        assert model.commission_for_trade(0.1) == 5.0
        assert model.commission_for_trade(1.0) == 5.0
        assert model.commission_for_trade(10.0) == 5.0

    def test_per_lot_commission(self):
        """$2 per lot commission scales with size."""
        model = CostModel(commission_per_trade=0.0, commission_per_lot=2.0)
        assert model.commission_for_trade(1.0) == 2.0
        assert model.commission_for_trade(2.5) == 5.0
        assert model.commission_for_trade(0.5) == 1.0

    def test_combined_commission(self):
        """Both flat and per-lot commission."""
        model = CostModel(commission_per_trade=3.0, commission_per_lot=1.5)
        # 3.0 + (1.5 * 2.0) = 6.0
        assert model.commission_for_trade(2.0) == 6.0

    def test_round_trip_commission(self):
        """Total commission for entry + exit (two sides)."""
        model = CostModel(commission_per_trade=5.0)
        size = 1.0
        entry_comm = model.commission_for_trade(size)
        exit_comm = model.commission_for_trade(size)
        assert entry_comm + exit_comm == 10.0


class TestSlippageCosts:
    """Verify slippage calculations."""

    def test_zero_slippage(self):
        model = CostModel(slippage_points=0.0)
        assert model.total_entry_cost_per_unit() == model.half_spread

    def test_slippage_adds_to_half_spread(self):
        model = CostModel(spread_points=1.0, slippage_points=0.5)
        # half_spread = 0.5, slippage = 0.5 → total = 1.0
        assert model.total_entry_cost_per_unit() == pytest.approx(1.0)
        assert model.total_exit_cost_per_unit() == pytest.approx(1.0)


class TestTotalCostScenarios:
    """End-to-end cost scenarios matching real trading conditions."""

    def test_dukascopy_spread_only(self):
        """Typical Dukascopy setup: spread-only, no commission."""
        model = CostModel(
            spread_points=1.14,
            commission_per_trade=0.0,
            commission_per_lot=0.0,
            slippage_points=0.0,
        )
        size = 1.0

        # Entry cost
        entry_spread = model.half_spread * size       # 0.57
        entry_comm = model.commission_for_trade(size)  # 0.0
        entry_slip = model.slippage_points * size      # 0.0

        # Exit cost
        exit_spread = model.half_spread * size         # 0.57
        exit_comm = model.commission_for_trade(size)    # 0.0
        exit_slip = model.slippage_points * size        # 0.0

        total = (entry_spread + entry_comm + entry_slip +
                 exit_spread + exit_comm + exit_slip)

        assert total == pytest.approx(1.14)

    def test_ecn_broker_with_everything(self):
        """ECN broker: tight spread + commission + slippage."""
        model = CostModel(
            spread_points=0.4,
            commission_per_trade=0.0,
            commission_per_lot=3.5,
            slippage_points=0.2,
        )
        size = 2.0

        entry_spread = model.half_spread * size         # 0.2 * 2 = 0.4
        entry_comm = model.commission_for_trade(size)    # 3.5 * 2 = 7.0
        entry_slip = model.slippage_points * size        # 0.2 * 2 = 0.4

        exit_spread = model.half_spread * size           # 0.4
        exit_comm = model.commission_for_trade(size)      # 7.0
        exit_slip = model.slippage_points * size          # 0.4

        total = (entry_spread + entry_comm + entry_slip +
                 exit_spread + exit_comm + exit_slip)

        assert total == pytest.approx(15.6)
