"""
Session filter: determines if a timestamp is within the active trading session.

Handles US market hours (8:00 AM - 4:30 PM New York time) with automatic
DST adjustment. Data outside the session is available for indicator
calculation but no new trades will be opened.
"""

from datetime import time, datetime
from typing import Optional

import pandas as pd
import pytz

from core.types import SessionWindow


class SessionFilter:
    """Filters timestamps and DataFrames by trading session hours.

    Handles DST transitions automatically — when New York switches
    between EST (UTC-5) and EDT (UTC-4), the UTC cutoff times adjust.

    Usage:
        sf = SessionFilter(session_config)

        # Check a single timestamp
        if sf.is_in_session(some_utc_timestamp):
            ...

        # Filter a full DataFrame
        filtered_df = sf.filter_dataframe(df)
    """

    def __init__(self, session: SessionWindow):
        self._session = session
        self._tz = pytz.timezone(session.timezone)

        # Parse session start/end times
        h, m = map(int, session.start_time.split(":"))
        self._start_time = time(h, m)

        h, m = map(int, session.end_time.split(":"))
        self._end_time = time(h, m)

    @property
    def timezone_name(self) -> str:
        return self._session.timezone

    @property
    def start_time(self) -> time:
        return self._start_time

    @property
    def end_time(self) -> time:
        return self._end_time

    def is_in_session(self, utc_timestamp: datetime) -> bool:
        """Check if a UTC timestamp falls within the trading session.

        Converts the UTC timestamp to the session timezone (e.g., New York)
        and checks if the local time is within the start/end window.

        Args:
            utc_timestamp: A datetime in UTC.

        Returns:
            True if the timestamp is within the session window.
        """
        # Ensure the timestamp is timezone-aware in UTC
        if utc_timestamp.tzinfo is None:
            utc_timestamp = pytz.utc.localize(utc_timestamp)

        # Convert to session timezone (handles DST automatically)
        local_time = utc_timestamp.astimezone(self._tz).time()

        return self._start_time <= local_time <= self._end_time

    def filter_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """Filter a DataFrame to only include rows within the session.

        Uses vectorized operations for performance on large DataFrames.

        Args:
            df: DataFrame with a datetime index (assumed UTC).

        Returns:
            Filtered DataFrame containing only in-session rows.
        """
        if df.empty:
            return df

        index = df.index

        # Localize to UTC if naive, then convert to session timezone
        if index.tz is None:
            index_local = index.tz_localize("UTC").tz_convert(self._tz)
        else:
            index_local = index.tz_convert(self._tz)

        # Vectorized time comparison
        local_times = index_local.time
        mask = pd.array(
            [self._start_time <= t <= self._end_time for t in local_times],
            dtype="boolean",
        )

        return df[mask]

    def get_session_boundaries_utc(self, date: datetime) -> tuple:
        """Get the UTC start and end times for the session on a given date.

        Useful for slicing data for a specific trading day.

        Args:
            date: The date to get session boundaries for.

        Returns:
            Tuple of (session_start_utc, session_end_utc) as datetime objects.
        """
        local_start = self._tz.localize(
            datetime.combine(date, self._start_time)
        )
        local_end = self._tz.localize(
            datetime.combine(date, self._end_time)
        )

        return local_start.astimezone(pytz.utc), local_end.astimezone(pytz.utc)

    def __repr__(self) -> str:
        return (
            f"SessionFilter({self._session.timezone}, "
            f"{self._session.start_time}-{self._session.end_time})"
        )
