"""
Tests for TradeLogger analyzer.

Validates that TradeLogger correctly captures trade lifecycle events
from backtrader and populates TradeRecord objects including SL/TP
prices when bracket orders are used.
"""

from datetime import datetime
from unittest.mock import MagicMock, PropertyMock

import backtrader as bt
import pytest

from core.types import CostModel, Direction, TradeRecord, TradeStatus
from analysis.trade_logger import TradeLogger


# ==============================================================================
# Helpers
# ==============================================================================

# Valid matplotlib ordinal date for 2024-01-15 12:00:00
_VALID_DT_OPEN = bt.date2num(datetime(2024, 1, 15, 12, 0, 0))
_VALID_DT_CLOSE = bt.date2num(datetime(2024, 1, 15, 13, 0, 0))


def _make_mock_trade(
    ref=1,
    size=10.0,
    price=16500.0,
    pnl=0.0,
    pnlcomm=0.0,
    justopened=False,
    isclosed=False,
    dtopen=None,
    dtclose=None,
):
    """Create a mock backtrader Trade object."""
    trade = MagicMock()
    trade.ref = ref
    trade.size = size
    trade.price = price
    trade.pnl = pnl
    trade.pnlcomm = pnlcomm
    trade.justopened = justopened
    trade.isclosed = isclosed
    trade.dtopen = dtopen if dtopen is not None else _VALID_DT_OPEN
    trade.dtclose = dtclose if dtclose is not None else _VALID_DT_CLOSE
    return trade


def _make_logger(cost_model=None):
    """Create a TradeLogger outside of Cerebro for unit testing.

    We manually set the params since we can't add it to Cerebro in unit tests.
    """
    logger = TradeLogger.__new__(TradeLogger)
    logger.p = MagicMock()
    logger.p.cost_model = cost_model or CostModel()
    # Call __init__ logic manually
    logger._trades = []
    logger._open_trades = {}
    logger._trade_counter = 0
    logger._cost_model = logger.p.cost_model
    logger._sl_tp_registry = {}
    logger._order_to_trade = {}
    return logger


# ==============================================================================
# Basic Trade Lifecycle
# ==============================================================================

class TestTradeLifecycle:
    """Test basic trade open/close recording."""

    def test_records_trade_open(self):
        logger = _make_logger()
        trade = _make_mock_trade(ref=1, size=10.0, price=16500.0, justopened=True)
        logger.notify_trade(trade)
        assert len(logger._open_trades) == 1

    def test_records_trade_close(self):
        logger = _make_logger()
        # Open
        trade_open = _make_mock_trade(ref=1, size=10.0, price=16500.0, justopened=True)
        logger.notify_trade(trade_open)
        # Close — pnl=500, pnlcomm=500 (no commission)
        trade_close = _make_mock_trade(ref=1, size=10.0, price=16500.0, pnl=500.0, pnlcomm=500.0, isclosed=True)
        logger.notify_trade(trade_close)
        assert len(logger.get_trades()) == 1
        assert len(logger._open_trades) == 0

    def test_direction_long(self):
        logger = _make_logger()
        trade = _make_mock_trade(ref=1, size=10.0, price=16500.0, justopened=True)
        logger.notify_trade(trade)
        record = logger._open_trades[1]
        assert record.direction == Direction.LONG

    def test_direction_short(self):
        logger = _make_logger()
        trade = _make_mock_trade(ref=1, size=-10.0, price=16500.0, justopened=True)
        logger.notify_trade(trade)
        record = logger._open_trades[1]
        assert record.direction == Direction.SHORT

    def test_trade_counter_increments(self):
        logger = _make_logger()
        t1 = _make_mock_trade(ref=1, size=10.0, price=16500.0, justopened=True)
        t2 = _make_mock_trade(ref=2, size=5.0, price=16600.0, justopened=True)
        logger.notify_trade(t1)
        logger.notify_trade(t2)
        records = list(logger._open_trades.values())
        ids = {r.trade_id for r in records}
        assert ids == {1, 2}


# ==============================================================================
# SL/TP Capture from Registry
# ==============================================================================

class TestSLTPCapture:
    """TradeLogger should populate SL/TP fields from the registry."""

    def test_sl_tp_recorded_on_open(self):
        logger = _make_logger()
        # Register SL/TP BEFORE the trade opens (strategy calls this)
        logger.register_sl_tp(
            order_ref=1, sl_price=16450.0, tp_price=16600.0
        )
        trade = _make_mock_trade(ref=1, size=20.0, price=16500.0, justopened=True)
        logger.notify_trade(trade)
        record = logger._open_trades[1]
        assert record.stop_loss == pytest.approx(16450.0)
        assert record.take_profit == pytest.approx(16600.0)

    def test_sl_only_no_tp(self):
        logger = _make_logger()
        logger.register_sl_tp(order_ref=1, sl_price=16450.0, tp_price=None)
        trade = _make_mock_trade(ref=1, size=20.0, price=16500.0, justopened=True)
        logger.notify_trade(trade)
        record = logger._open_trades[1]
        assert record.stop_loss == pytest.approx(16450.0)
        assert record.take_profit is None

    def test_no_registration_means_no_sl_tp(self):
        logger = _make_logger()
        trade = _make_mock_trade(ref=1, size=20.0, price=16500.0, justopened=True)
        logger.notify_trade(trade)
        record = logger._open_trades[1]
        assert record.stop_loss is None
        assert record.take_profit is None

    def test_sl_tp_persists_through_close(self):
        """SL/TP should be on the final TradeRecord after close."""
        logger = _make_logger()
        logger.register_sl_tp(order_ref=1, sl_price=16450.0, tp_price=16600.0)
        trade_open = _make_mock_trade(ref=1, size=20.0, price=16500.0, justopened=True)
        logger.notify_trade(trade_open)
        trade_close = _make_mock_trade(ref=1, size=20.0, price=16500.0, pnl=2000.0, pnlcomm=2000.0, isclosed=True)
        logger.notify_trade(trade_close)
        completed = logger.get_trades()
        assert len(completed) == 1
        assert completed[0].stop_loss == pytest.approx(16450.0)
        assert completed[0].take_profit == pytest.approx(16600.0)


# ==============================================================================
# Cost Calculation
# ==============================================================================

class TestCostCalculation:
    """Verify costs are correctly applied on open and close."""

    def test_spread_cost_both_sides(self):
        cost_model = CostModel(spread_points=1.14)
        logger = _make_logger(cost_model=cost_model)
        # Open
        trade_open = _make_mock_trade(ref=1, size=10.0, price=16500.0, justopened=True)
        logger.notify_trade(trade_open)
        # Close — pnl=500 (after slippage), pnlcomm=500 (no commission)
        trade_close = _make_mock_trade(ref=1, size=10.0, price=16500.0, pnl=500.0, pnlcomm=500.0, isclosed=True)
        logger.notify_trade(trade_close)
        record = logger.get_trades()[0]
        # Spread cost is informational: half_spread * size * 2 sides
        # half_spread = 0.57, 0.57 * 10 * 2 = 11.4
        assert record.spread_cost == pytest.approx(0.57 * 10 * 2)
        # net_pnl = pnlcomm = 500 (spread is already in fill prices)
        assert record.net_pnl == pytest.approx(500.0)
        # total_costs = pnl - pnlcomm = 0 (no commission)
        assert record.total_costs == pytest.approx(0.0)

    def test_total_costs_from_pnlcomm(self):
        """total_costs = trade.pnl - trade.pnlcomm (commission only)."""
        cost_model = CostModel(spread_points=1.14, slippage_points=0.5, commission_per_trade=10.0)
        logger = _make_logger(cost_model=cost_model)
        trade_open = _make_mock_trade(ref=1, size=10.0, price=16500.0, justopened=True)
        logger.notify_trade(trade_open)
        # pnl=500 (after slippage), pnlcomm=480 (pnl - 20 commission)
        trade_close = _make_mock_trade(ref=1, size=10.0, price=16500.0, pnl=500.0, pnlcomm=480.0, isclosed=True)
        logger.notify_trade(trade_close)
        record = logger.get_trades()[0]
        # total_costs = pnl - pnlcomm = 20
        assert record.total_costs == pytest.approx(20.0)
        assert record.net_pnl == pytest.approx(480.0)
        assert record.gross_pnl == pytest.approx(500.0)
        # Informational cost breakdown should still be populated
        assert record.spread_cost > 0
        assert record.slippage_cost > 0
        assert record.commission_cost > 0


# ==============================================================================
# Edge Cases
# ==============================================================================

class TestEdgeCases:
    """Edge case tests."""

    def test_close_without_open_is_safe(self):
        """If we get a close for an unknown ref, nothing crashes."""
        logger = _make_logger()
        trade_close = _make_mock_trade(ref=99, size=10.0, price=16500.0, pnlcomm=0.0, isclosed=True)
        logger.notify_trade(trade_close)
        assert len(logger.get_trades()) == 0

    def test_multiple_trades(self):
        logger = _make_logger()
        for i in range(1, 4):
            trade_open = _make_mock_trade(ref=i, size=float(i * 5), price=16500.0, justopened=True)
            logger.notify_trade(trade_open)
            trade_close = _make_mock_trade(ref=i, size=float(i * 5), price=16500.0, pnl=100.0 * i, pnlcomm=100.0 * i, isclosed=True)
            logger.notify_trade(trade_close)
        assert len(logger.get_trades()) == 3

    def test_get_analysis_returns_dict(self):
        logger = _make_logger()
        analysis = logger.get_analysis()
        assert "total_trades" in analysis
        assert "open_trades" in analysis


# ==============================================================================
# Exit Price Derivation
# ==============================================================================

class TestExitPrice:
    """Exit price is derived from trade.pnl since trade.price is always entry."""

    def test_exit_price_long(self):
        """For a LONG trade, exit = entry + pnl/size."""
        logger = _make_logger()
        trade_open = _make_mock_trade(ref=1, size=10.0, price=16500.0, justopened=True)
        logger.notify_trade(trade_open)
        # pnl=100 means exit = 16500 + 100/10 = 16510
        trade_close = _make_mock_trade(ref=1, size=10.0, price=16500.0, pnl=100.0, pnlcomm=100.0, isclosed=True)
        logger.notify_trade(trade_close)
        record = logger.get_trades()[0]
        assert record.exit_price == pytest.approx(16510.0)

    def test_exit_price_short(self):
        """For a SHORT trade, exit = entry - pnl/size."""
        logger = _make_logger()
        trade_open = _make_mock_trade(ref=1, size=-10.0, price=16500.0, justopened=True)
        logger.notify_trade(trade_open)
        # SHORT: pnl=100 means price went down by 10pts: exit = 16500 - 100/10 = 16490
        trade_close = _make_mock_trade(ref=1, size=-10.0, price=16500.0, pnl=100.0, pnlcomm=100.0, isclosed=True)
        logger.notify_trade(trade_close)
        record = logger.get_trades()[0]
        assert record.exit_price == pytest.approx(16490.0)

    def test_exit_price_losing_long(self):
        """Losing LONG trade: exit < entry."""
        logger = _make_logger()
        trade_open = _make_mock_trade(ref=1, size=5.0, price=16500.0, justopened=True)
        logger.notify_trade(trade_open)
        # pnl=-50 means exit = 16500 + (-50)/5 = 16490
        trade_close = _make_mock_trade(ref=1, size=5.0, price=16500.0, pnl=-50.0, pnlcomm=-50.0, isclosed=True)
        logger.notify_trade(trade_close)
        record = logger.get_trades()[0]
        assert record.exit_price == pytest.approx(16490.0)
