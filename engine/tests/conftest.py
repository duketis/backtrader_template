"""
Shared test fixtures for the Backtest Engine test suite.

Provides reusable sample data, configs, and objects so tests
are self-contained and don't depend on real data files.
"""

import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import numpy as np
import pytest

from core.types import (
    CostModel,
    Direction,
    SessionWindow,
    Timeframe,
    TradeRecord,
    TradeStatus,
)


# ==============================================================================
# Sample Data Generators
# ==============================================================================

@pytest.fixture
def sample_tick_data() -> pd.DataFrame:
    """Generate a small sample of tick data mimicking real format.

    Returns ~1000 ticks over a trading day with realistic NAS100 prices.
    """
    np.random.seed(42)  # Reproducible

    # Simulate a trading day: Jan 2, 2024 00:00 - 23:59 UTC
    base_time = datetime(2024, 1, 2, 0, 0, 0)
    n_ticks = 1000
    base_price = 16500.0

    # Random timestamps with millisecond resolution
    offsets = sorted(np.random.randint(0, 86400 * 1000, n_ticks))
    timestamps = [
        base_time + timedelta(milliseconds=int(ms)) for ms in offsets
    ]

    # Random walk price
    returns = np.random.normal(0, 0.5, n_ticks)
    prices = base_price + np.cumsum(returns)

    df = pd.DataFrame(
        {
            "open": prices,
            "high": prices,
            "low": prices,
            "close": prices,
        },
        index=pd.DatetimeIndex(timestamps, name="datetime"),
    )
    return df


@pytest.fixture
def sample_ohlc_1min() -> pd.DataFrame:
    """Generate sample 1-minute OHLC data.

    Returns ~480 bars (8 hours of trading).
    """
    np.random.seed(42)

    # 8 hours * 60 minutes
    base_time = datetime(2024, 1, 2, 13, 30, 0)  # 8:30 AM ET in UTC
    n_bars = 480
    base_price = 16500.0

    timestamps = [base_time + timedelta(minutes=i) for i in range(n_bars)]

    close_returns = np.random.normal(0, 2, n_bars)
    closes = base_price + np.cumsum(close_returns)

    # Generate realistic OHLC from closes
    highs = closes + np.abs(np.random.normal(0, 3, n_bars))
    lows = closes - np.abs(np.random.normal(0, 3, n_bars))
    opens = np.roll(closes, 1)
    opens[0] = base_price

    df = pd.DataFrame(
        {
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
        },
        index=pd.DatetimeIndex(timestamps, name="datetime"),
    )
    return df


@pytest.fixture
def sample_ohlc_5min() -> pd.DataFrame:
    """Generate sample 5-minute OHLC data (~96 bars = 8 hours)."""
    np.random.seed(42)

    base_time = datetime(2024, 1, 2, 13, 30, 0)
    n_bars = 96
    base_price = 16500.0

    timestamps = [base_time + timedelta(minutes=5 * i) for i in range(n_bars)]

    close_returns = np.random.normal(0, 5, n_bars)
    closes = base_price + np.cumsum(close_returns)
    highs = closes + np.abs(np.random.normal(0, 7, n_bars))
    lows = closes - np.abs(np.random.normal(0, 7, n_bars))
    opens = np.roll(closes, 1)
    opens[0] = base_price

    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes},
        index=pd.DatetimeIndex(timestamps, name="datetime"),
    )


@pytest.fixture
def sample_ohlc_1hour() -> pd.DataFrame:
    """Generate sample 1-hour OHLC data (~9 bars)."""
    np.random.seed(42)

    base_time = datetime(2024, 1, 2, 13, 0, 0)
    n_bars = 9
    base_price = 16500.0

    timestamps = [base_time + timedelta(hours=i) for i in range(n_bars)]

    close_returns = np.random.normal(0, 15, n_bars)
    closes = base_price + np.cumsum(close_returns)
    highs = closes + np.abs(np.random.normal(0, 20, n_bars))
    lows = closes - np.abs(np.random.normal(0, 20, n_bars))
    opens = np.roll(closes, 1)
    opens[0] = base_price

    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes},
        index=pd.DatetimeIndex(timestamps, name="datetime"),
    )


@pytest.fixture
def sample_ohlc_4hour() -> pd.DataFrame:
    """Generate sample 4-hour OHLC data (~6 bars = 24 hours)."""
    np.random.seed(42)

    base_time = datetime(2024, 1, 2, 0, 0, 0)
    n_bars = 6
    base_price = 16500.0

    timestamps = [base_time + timedelta(hours=4 * i) for i in range(n_bars)]

    close_returns = np.random.normal(0, 30, n_bars)
    closes = base_price + np.cumsum(close_returns)
    highs = closes + np.abs(np.random.normal(0, 40, n_bars))
    lows = closes - np.abs(np.random.normal(0, 40, n_bars))
    opens = np.roll(closes, 1)
    opens[0] = base_price

    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes},
        index=pd.DatetimeIndex(timestamps, name="datetime"),
    )


# ==============================================================================
# Config Fixtures
# ==============================================================================

@pytest.fixture
def sample_cost_model() -> CostModel:
    """Standard cost model for testing."""
    return CostModel(
        spread_points=1.14,
        commission_per_trade=0.0,
        commission_per_lot=0.0,
        slippage_points=0.0,
    )


@pytest.fixture
def sample_cost_model_with_commission() -> CostModel:
    """Cost model with all cost types for testing."""
    return CostModel(
        spread_points=1.5,
        commission_per_trade=2.0,
        commission_per_lot=1.0,
        slippage_points=0.5,
    )


@pytest.fixture
def sample_session_window() -> SessionWindow:
    """US session window config."""
    return SessionWindow(
        timezone="America/New_York",
        start_time="08:00",
        end_time="16:30",
        dst_aware=True,
    )


@pytest.fixture
def sample_trade_winner() -> TradeRecord:
    """A completed winning long trade for testing."""
    return TradeRecord(
        trade_id=1,
        direction=Direction.LONG,
        entry_time=datetime(2024, 1, 2, 14, 30, 0),
        exit_time=datetime(2024, 1, 2, 16, 0, 0),
        entry_price=16500.0,
        exit_price=16550.0,
        stop_loss=16470.0,
        take_profit=16560.0,
        size=1.0,
        spread_cost=1.14,
        commission_cost=0.0,
        slippage_cost=0.0,
        gross_pnl=50.0,
        net_pnl=48.86,
        total_costs=1.14,
        status=TradeStatus.CLOSED,
        entry_reason="test",
        exit_reason="tp_hit",
    )


@pytest.fixture
def sample_trade_loser() -> TradeRecord:
    """A completed losing short trade for testing."""
    return TradeRecord(
        trade_id=2,
        direction=Direction.SHORT,
        entry_time=datetime(2024, 1, 3, 15, 0, 0),
        exit_time=datetime(2024, 1, 3, 15, 45, 0),
        entry_price=16550.0,
        exit_price=16580.0,
        stop_loss=16580.0,
        take_profit=16510.0,
        size=1.0,
        spread_cost=1.14,
        commission_cost=0.0,
        slippage_cost=0.0,
        gross_pnl=-30.0,
        net_pnl=-31.14,
        total_costs=1.14,
        status=TradeStatus.CLOSED,
        entry_reason="test",
        exit_reason="sl_hit",
    )


@pytest.fixture
def sample_trades(sample_trade_winner, sample_trade_loser) -> list:
    """A list of mixed trades for metrics testing."""
    return [sample_trade_winner, sample_trade_loser]


@pytest.fixture
def temp_parquet_dir(sample_tick_data, sample_ohlc_1min, sample_ohlc_5min,
                     sample_ohlc_1hour, sample_ohlc_4hour):
    """Create a temporary directory with sample parquet files for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        instrument = "USATECHIDXUSD"

        sample_tick_data.to_parquet(tmpdir / f"{instrument}_tick.parquet")
        sample_ohlc_1min.to_parquet(tmpdir / f"{instrument}_1min.parquet")
        sample_ohlc_5min.to_parquet(tmpdir / f"{instrument}_5min.parquet")
        sample_ohlc_1hour.to_parquet(tmpdir / f"{instrument}_1hour.parquet")
        sample_ohlc_4hour.to_parquet(tmpdir / f"{instrument}_4hour.parquet")

        yield tmpdir
