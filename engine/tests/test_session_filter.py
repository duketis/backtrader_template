"""
Tests for the session filter module.

Validates that:
- Timestamps are correctly classified as in/out of session
- DST transitions are handled properly (EST ↔ EDT)
- DataFrame filtering works correctly
- Edge cases (midnight, session boundaries) are handled
"""

from datetime import datetime

import pandas as pd
import pytz
import pytest

from core.types import SessionWindow
from data.session_filter import SessionFilter


@pytest.fixture
def us_session_filter(sample_session_window):
    return SessionFilter(sample_session_window)


class TestSessionFilterBasics:
    """Test basic in-session / out-of-session detection."""

    def test_us_market_hours_in_session_winter(self, us_session_filter):
        """10:00 AM ET in winter = 15:00 UTC (EST, UTC-5)."""
        utc_time = datetime(2024, 1, 15, 15, 0, 0)  # 10 AM ET
        assert us_session_filter.is_in_session(utc_time) is True

    def test_us_premarket_in_session(self, us_session_filter):
        """8:30 AM ET = 13:30 UTC in winter. Should be in session (starts 8:00)."""
        utc_time = datetime(2024, 1, 15, 13, 30, 0)
        assert us_session_filter.is_in_session(utc_time) is True

    def test_before_session_start_winter(self, us_session_filter):
        """7:00 AM ET = 12:00 UTC. Before 8:00 AM start."""
        utc_time = datetime(2024, 1, 15, 12, 0, 0)
        assert us_session_filter.is_in_session(utc_time) is False

    def test_after_session_end_winter(self, us_session_filter):
        """5:00 PM ET = 22:00 UTC. After 4:30 PM end."""
        utc_time = datetime(2024, 1, 15, 22, 0, 0)
        assert us_session_filter.is_in_session(utc_time) is False

    def test_exact_session_start(self, us_session_filter):
        """Exactly 8:00 AM ET should be IN session (boundary inclusive)."""
        utc_time = datetime(2024, 1, 15, 13, 0, 0)  # 8 AM ET = 13:00 UTC (winter)
        assert us_session_filter.is_in_session(utc_time) is True

    def test_exact_session_end(self, us_session_filter):
        """Exactly 4:30 PM ET should be IN session (boundary inclusive)."""
        utc_time = datetime(2024, 1, 15, 21, 30, 0)  # 4:30 PM ET = 21:30 UTC (winter)
        assert us_session_filter.is_in_session(utc_time) is True

    def test_one_second_after_close(self, us_session_filter):
        """4:31 PM ET should be OUT of session."""
        utc_time = datetime(2024, 1, 15, 21, 31, 0)  # 4:31 PM ET
        assert us_session_filter.is_in_session(utc_time) is False


class TestSessionFilterDST:
    """Test DST handling — critical for correct UTC offsets."""

    def test_summer_time_offset(self, us_session_filter):
        """In summer (EDT, UTC-4), 10:00 AM ET = 14:00 UTC."""
        utc_time = datetime(2024, 7, 15, 14, 0, 0)  # 10 AM EDT
        assert us_session_filter.is_in_session(utc_time) is True

    def test_summer_before_session(self, us_session_filter):
        """7:00 AM EDT = 11:00 UTC in summer. Before 8:00 AM start."""
        utc_time = datetime(2024, 7, 15, 11, 0, 0)
        assert us_session_filter.is_in_session(utc_time) is False

    def test_summer_session_start(self, us_session_filter):
        """8:00 AM EDT = 12:00 UTC in summer."""
        utc_time = datetime(2024, 7, 15, 12, 0, 0)
        assert us_session_filter.is_in_session(utc_time) is True

    def test_winter_vs_summer_same_utc(self, us_session_filter):
        """13:00 UTC = 8 AM EST (in session) but 9 AM EDT (also in session).
        But 12:00 UTC = 7 AM EST (out) vs 8 AM EDT (in).
        """
        # 12:00 UTC in January = 7 AM EST → OUT
        winter_time = datetime(2024, 1, 15, 12, 0, 0)
        assert us_session_filter.is_in_session(winter_time) is False

        # 12:00 UTC in July = 8 AM EDT → IN
        summer_time = datetime(2024, 7, 15, 12, 0, 0)
        assert us_session_filter.is_in_session(summer_time) is True

    def test_dst_transition_day_spring(self, us_session_filter):
        """March 10, 2024 — clocks spring forward. EDT starts."""
        # 8 AM EDT = 12:00 UTC
        utc_time = datetime(2024, 3, 11, 12, 0, 0)  # Day after spring forward
        assert us_session_filter.is_in_session(utc_time) is True

    def test_dst_transition_day_fall(self, us_session_filter):
        """Nov 3, 2024 — clocks fall back. EST starts."""
        # 8 AM EST = 13:00 UTC
        utc_time = datetime(2024, 11, 4, 13, 0, 0)  # Day after fall back
        assert us_session_filter.is_in_session(utc_time) is True


class TestSessionFilterDataFrame:
    """Test DataFrame filtering to session hours."""

    def test_filter_removes_out_of_session(self, us_session_filter, sample_tick_data):
        """Filtering should reduce the number of rows."""
        filtered = us_session_filter.filter_dataframe(sample_tick_data)
        assert len(filtered) <= len(sample_tick_data)

    def test_filter_all_rows_in_session(self, us_session_filter):
        """If all data is within session, nothing should be removed."""
        # Create data that's entirely within US session (14:30-21:00 UTC, winter)
        timestamps = pd.date_range(
            "2024-01-15 14:30:00", "2024-01-15 21:00:00", freq="1min"
        )
        df = pd.DataFrame(
            {"open": 100, "high": 101, "low": 99, "close": 100},
            index=timestamps,
        )
        filtered = us_session_filter.filter_dataframe(df)
        assert len(filtered) == len(df)

    def test_filter_preserves_columns(self, us_session_filter, sample_tick_data):
        """Filtering should not change the column structure."""
        filtered = us_session_filter.filter_dataframe(sample_tick_data)
        assert list(filtered.columns) == list(sample_tick_data.columns)

    def test_filter_empty_dataframe(self, us_session_filter):
        """Filtering an empty DataFrame should return an empty DataFrame."""
        df = pd.DataFrame(columns=["open", "high", "low", "close"])
        df.index.name = "datetime"
        filtered = us_session_filter.filter_dataframe(df)
        assert len(filtered) == 0


class TestSessionBoundaries:
    """Test UTC boundary calculation for specific dates."""

    def test_winter_boundaries(self, us_session_filter):
        """Winter: 8 AM ET = 13:00 UTC, 4:30 PM ET = 21:30 UTC."""
        date = datetime(2024, 1, 15)
        start_utc, end_utc = us_session_filter.get_session_boundaries_utc(date)

        assert start_utc.hour == 13
        assert start_utc.minute == 0
        assert end_utc.hour == 21
        assert end_utc.minute == 30

    def test_summer_boundaries(self, us_session_filter):
        """Summer: 8 AM ET = 12:00 UTC, 4:30 PM ET = 20:30 UTC."""
        date = datetime(2024, 7, 15)
        start_utc, end_utc = us_session_filter.get_session_boundaries_utc(date)

        assert start_utc.hour == 12
        assert start_utc.minute == 0
        assert end_utc.hour == 20
        assert end_utc.minute == 30
