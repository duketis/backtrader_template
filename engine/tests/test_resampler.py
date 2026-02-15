"""
Tests for data resampling logic.

Validates that tick data is correctly resampled into OHLC bars
at various timeframes. This is critical — bad resampling means
bad candles, which means bad strategy signals.
"""

from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

# Import the resample function from our preprocessing script
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.types import Timeframe
from scripts.preprocess import resample_ticks


class TestResamplingBasics:
    """Test basic resampling from ticks to OHLC."""

    @pytest.fixture
    def minute_ticks(self) -> pd.DataFrame:
        """Create ticks that span exactly 5 minutes with known OHLC."""
        # 5 minutes of ticks, 10 ticks per minute
        timestamps = []
        prices = []

        for minute in range(5):
            for sec in range(10):
                ts = datetime(2024, 1, 2, 14, minute, sec * 6)
                timestamps.append(ts)

                # Minute 0: prices go 100, 102, 98, 101 → O=100, H=102, L=98, C=101
                if minute == 0:
                    prices.append(100 + np.sin(sec) * 2)
                else:
                    prices.append(100 + minute * 5 + np.sin(sec) * 2)

        df = pd.DataFrame(
            {"open": prices, "high": prices, "low": prices, "close": prices},
            index=pd.DatetimeIndex(timestamps, name="datetime"),
        )
        return df

    def test_resample_to_1min(self, minute_ticks):
        """Resampling to 1min should produce 5 bars."""
        result = resample_ticks(minute_ticks, Timeframe.ONE_MIN)
        assert len(result) == 5

    def test_resample_to_5min(self, minute_ticks):
        """Resampling to 5min should produce 1 bar."""
        result = resample_ticks(minute_ticks, Timeframe.FIVE_MIN)
        assert len(result) == 1

    def test_resample_columns(self, minute_ticks):
        """Resampled data should have standard OHLC columns."""
        result = resample_ticks(minute_ticks, Timeframe.ONE_MIN)
        assert list(result.columns) == ["open", "high", "low", "close"]

    def test_resample_ohlc_values(self):
        """Verify OHLC values are correct for a known input."""
        # 3 ticks in the same minute: 100, 105, 102
        timestamps = [
            datetime(2024, 1, 2, 14, 0, 0),
            datetime(2024, 1, 2, 14, 0, 30),
            datetime(2024, 1, 2, 14, 0, 45),
        ]
        prices = [100.0, 105.0, 102.0]

        df = pd.DataFrame(
            {"open": prices, "high": prices, "low": prices, "close": prices},
            index=pd.DatetimeIndex(timestamps, name="datetime"),
        )

        result = resample_ticks(df, Timeframe.ONE_MIN)

        assert len(result) == 1
        bar = result.iloc[0]
        assert bar["open"] == 100.0    # First tick price
        assert bar["high"] == 105.0    # Highest tick price
        assert bar["low"] == 100.0     # Lowest tick price
        assert bar["close"] == 102.0   # Last tick price

    def test_resample_drops_nan_bars(self):
        """Bars with no ticks should be dropped (gaps in data)."""
        # Ticks at 14:00 and 14:05 — nothing at 14:01-14:04
        timestamps = [
            datetime(2024, 1, 2, 14, 0, 0),
            datetime(2024, 1, 2, 14, 5, 0),
        ]
        prices = [100.0, 105.0]

        df = pd.DataFrame(
            {"open": prices, "high": prices, "low": prices, "close": prices},
            index=pd.DatetimeIndex(timestamps, name="datetime"),
        )

        result = resample_ticks(df, Timeframe.ONE_MIN)
        assert len(result) == 2  # Only 2 bars, not 6

    def test_resample_tick_raises_error(self, sample_tick_data):
        """Cannot resample TO tick — tick is the base."""
        with pytest.raises(ValueError, match="Cannot resample to tick"):
            resample_ticks(sample_tick_data, Timeframe.TICK)


class TestResamplingEdgeCases:
    """Test edge cases in resampling."""

    def test_single_tick(self):
        """A single tick should produce one bar."""
        df = pd.DataFrame(
            {"open": [100.0], "high": [100.0], "low": [100.0], "close": [100.0]},
            index=pd.DatetimeIndex(
                [datetime(2024, 1, 2, 14, 0, 0)], name="datetime"
            ),
        )
        result = resample_ticks(df, Timeframe.ONE_MIN)
        assert len(result) == 1

    def test_empty_dataframe(self):
        """Empty input should produce empty output."""
        df = pd.DataFrame(
            columns=["open", "high", "low", "close"],
            index=pd.DatetimeIndex([], name="datetime"),
        )
        # close column won't exist meaningfully — handle gracefully
        result = resample_ticks(df, Timeframe.ONE_MIN)
        assert len(result) == 0

    def test_cross_hour_boundary(self):
        """Ticks spanning an hour boundary should split correctly."""
        timestamps = [
            datetime(2024, 1, 2, 14, 58, 0),
            datetime(2024, 1, 2, 14, 59, 30),
            datetime(2024, 1, 2, 15, 0, 0),
            datetime(2024, 1, 2, 15, 0, 30),
        ]
        prices = [100.0, 101.0, 102.0, 103.0]

        df = pd.DataFrame(
            {"open": prices, "high": prices, "low": prices, "close": prices},
            index=pd.DatetimeIndex(timestamps, name="datetime"),
        )

        result = resample_ticks(df, Timeframe.ONE_HOUR)
        assert len(result) == 2  # One bar for 14:xx, one for 15:xx
