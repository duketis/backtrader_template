"""
Tests for post-backtest metrics calculation.

Validates that win rate, P&L, drawdown, Sharpe ratio, and other
statistics are computed correctly from trade records.
"""

from datetime import datetime

import pytest

from core.types import Direction, TradeRecord, TradeStatus
from analysis.metrics import calculate_metrics, format_results


class TestMetricsBasics:
    """Test basic metrics calculations."""

    def test_empty_trades(self):
        result = calculate_metrics([], initial_balance=100000)
        assert result.total_trades == 0
        assert result.win_rate == 0.0
        assert result.net_profit == 0.0
        assert result.end_equity == 100000

    def test_single_winning_trade(self, sample_trade_winner):
        result = calculate_metrics([sample_trade_winner], initial_balance=100000)
        assert result.total_trades == 1
        assert result.winning_trades == 1
        assert result.losing_trades == 0
        assert result.win_rate == 1.0
        assert result.net_profit == sample_trade_winner.net_pnl

    def test_single_losing_trade(self, sample_trade_loser):
        result = calculate_metrics([sample_trade_loser], initial_balance=100000)
        assert result.total_trades == 1
        assert result.winning_trades == 0
        assert result.losing_trades == 1
        assert result.win_rate == 0.0

    def test_mixed_trades(self, sample_trades):
        result = calculate_metrics(sample_trades, initial_balance=100000)
        assert result.total_trades == 2
        assert result.winning_trades == 1
        assert result.losing_trades == 1
        assert result.win_rate == pytest.approx(0.5)


class TestPnLCalculations:
    """Test P&L-related metrics."""

    def test_gross_profit(self, sample_trades):
        result = calculate_metrics(sample_trades, initial_balance=100000)
        # Winner net_pnl = 48.86
        assert result.gross_profit == pytest.approx(48.86)

    def test_gross_loss(self, sample_trades):
        result = calculate_metrics(sample_trades, initial_balance=100000)
        # Loser net_pnl = -31.14
        assert result.gross_loss == pytest.approx(-31.14)

    def test_net_profit(self, sample_trades):
        result = calculate_metrics(sample_trades, initial_balance=100000)
        # 48.86 + (-31.14) = 17.72
        assert result.net_profit == pytest.approx(17.72)

    def test_total_costs(self, sample_trades):
        result = calculate_metrics(sample_trades, initial_balance=100000)
        # Each trade has 1.14 total costs → 2.28
        assert result.total_costs == pytest.approx(2.28)

    def test_end_equity(self, sample_trades):
        result = calculate_metrics(sample_trades, initial_balance=100000)
        expected = 100000 + 48.86 + (-31.14)
        assert result.end_equity == pytest.approx(expected)

    def test_return_percent(self, sample_trades):
        result = calculate_metrics(sample_trades, initial_balance=100000)
        expected_return = (17.72 / 100000) * 100
        assert result.return_percent == pytest.approx(expected_return)


class TestTradeStats:
    """Test trade-level statistics."""

    def test_avg_winner(self, sample_trades):
        result = calculate_metrics(sample_trades, initial_balance=100000)
        assert result.avg_winner == pytest.approx(48.86)

    def test_avg_loser(self, sample_trades):
        result = calculate_metrics(sample_trades, initial_balance=100000)
        assert result.avg_loser == pytest.approx(-31.14)

    def test_largest_winner(self, sample_trades):
        result = calculate_metrics(sample_trades, initial_balance=100000)
        assert result.largest_winner == pytest.approx(48.86)

    def test_largest_loser(self, sample_trades):
        result = calculate_metrics(sample_trades, initial_balance=100000)
        assert result.largest_loser == pytest.approx(-31.14)

    def test_profit_factor(self, sample_trades):
        result = calculate_metrics(sample_trades, initial_balance=100000)
        # gross_profit / abs(gross_loss) = 48.86 / 31.14 ≈ 1.569
        assert result.profit_factor == pytest.approx(48.86 / 31.14)

    def test_profit_factor_no_losers(self, sample_trade_winner):
        result = calculate_metrics([sample_trade_winner], initial_balance=100000)
        assert result.profit_factor == float("inf")

    def test_profit_factor_no_winners(self, sample_trade_loser):
        result = calculate_metrics([sample_trade_loser], initial_balance=100000)
        assert result.profit_factor == 0.0


class TestDrawdown:
    """Test max drawdown calculations."""

    def test_no_drawdown_single_winner(self, sample_trade_winner):
        result = calculate_metrics([sample_trade_winner], initial_balance=100000)
        assert result.max_drawdown == 0.0
        assert result.max_drawdown_percent == 0.0

    def test_drawdown_single_loser(self, sample_trade_loser):
        result = calculate_metrics([sample_trade_loser], initial_balance=100000)
        assert result.max_drawdown == pytest.approx(31.14)

    def test_drawdown_sequence(self):
        """Three consecutive losers then a winner."""
        trades = [
            TradeRecord(
                trade_id=i,
                direction=Direction.LONG,
                entry_time=datetime(2024, 1, i + 1),
                exit_time=datetime(2024, 1, i + 1),
                net_pnl=pnl,
                total_costs=0,
                status=TradeStatus.CLOSED,
            )
            for i, pnl in enumerate([-100, -200, -150, 500])
        ]
        result = calculate_metrics(trades, initial_balance=10000)
        # Peak starts at 10000
        # After trade 1: 9900 (dd=100)
        # After trade 2: 9700 (dd=300)
        # After trade 3: 9550 (dd=450) ← max drawdown
        # After trade 4: 10050 (new peak)
        assert result.max_drawdown == pytest.approx(450.0)


class TestFormatResults:
    """Test human-readable output formatting."""

    def test_format_returns_string(self, sample_trades):
        result = calculate_metrics(sample_trades, initial_balance=100000)
        output = format_results(result)
        assert isinstance(output, str)
        assert "BACKTEST RESULTS" in output
        assert "Net Profit" in output

    def test_format_empty_trades(self):
        result = calculate_metrics([], initial_balance=100000)
        output = format_results(result)
        assert "Total Trades:        0" in output
