"""
Data manager: single point of access for all market data.

Loads preprocessed Parquet files and provides clean DataFrames
to the rest of the system. Hides the storage format from consumers —
if we switch from Parquet to a database, only this module changes.
"""

from pathlib import Path
from typing import Dict, Optional

import pandas as pd

from core.config import AppConfig
from core.types import Timeframe


class DataManager:
    """Loads and serves market data from preprocessed Parquet files.

    Usage:
        dm = DataManager(config)
        dm.load()
        df_1min = dm.get_dataframe(Timeframe.ONE_MIN)
        df_ticks = dm.get_dataframe(Timeframe.TICK)
    """

    def __init__(self, config: AppConfig):
        self._config = config
        self._parquet_dir = config.data.parquet_dir
        self._instrument = config.data.instrument
        self._dataframes: Dict[Timeframe, pd.DataFrame] = {}
        self._loaded = False

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def load(
        self,
        timeframes: Optional[list] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> None:
        """Load Parquet data for the specified timeframes.

        Args:
            timeframes: List of Timeframe enums to load. Defaults to all
                        configured timeframes + tick.
            start_date: Optional start date filter (YYYY-MM-DD).
            end_date: Optional end date filter (YYYY-MM-DD).
        """
        if timeframes is None:
            timeframes = [Timeframe.TICK] + self._config.data.timeframes

        # Use backtest period from config if not explicitly provided
        if start_date is None:
            start_date = self._config.backtest.start_date
        if end_date is None:
            end_date = self._config.backtest.end_date

        for tf in timeframes:
            parquet_path = self._get_parquet_path(tf)
            if not parquet_path.exists():
                raise FileNotFoundError(
                    f"Parquet file not found for {tf.value}: {parquet_path}\n"
                    f"Run 'python -m scripts.preprocess' first."
                )

            df = pd.read_parquet(parquet_path, engine="pyarrow")

            # Apply date filters
            if start_date:
                df = df[df.index >= start_date]
            if end_date:
                df = df[df.index <= end_date]

            self._dataframes[tf] = df

        self._loaded = True

    def get_dataframe(self, timeframe: Timeframe) -> pd.DataFrame:
        """Get the DataFrame for a specific timeframe.

        Args:
            timeframe: The timeframe to retrieve.

        Returns:
            DataFrame with datetime index and OHLC columns.

        Raises:
            ValueError: If data hasn't been loaded yet.
            KeyError: If the requested timeframe wasn't loaded.
        """
        if not self._loaded:
            raise ValueError("Data not loaded. Call .load() first.")
        if timeframe not in self._dataframes:
            raise KeyError(
                f"Timeframe {timeframe.value} not loaded. "
                f"Available: {[tf.value for tf in self._dataframes]}"
            )
        return self._dataframes[timeframe]

    def get_slice(
        self,
        timeframe: Timeframe,
        start: str,
        end: str,
    ) -> pd.DataFrame:
        """Get a time-sliced portion of data for a given timeframe.

        Useful for extracting windows around trades for visualization.

        Args:
            timeframe: The timeframe to slice.
            start: Start datetime string.
            end: End datetime string.

        Returns:
            Sliced DataFrame.
        """
        df = self.get_dataframe(timeframe)
        return df[start:end]

    def get_bars_around(
        self,
        timeframe: Timeframe,
        timestamp: pd.Timestamp,
        bars_before: int = 50,
        bars_after: int = 20,
    ) -> pd.DataFrame:
        """Get N bars before and after a specific timestamp.

        Used for trade visualization — centers the chart on the trade.

        Args:
            timeframe: The timeframe to query.
            timestamp: The reference timestamp (e.g., trade entry time).
            bars_before: Number of bars before the timestamp.
            bars_after: Number of bars after the timestamp.

        Returns:
            DataFrame with the requested window of bars.
        """
        df = self.get_dataframe(timeframe)

        # Find the nearest index position to the timestamp
        idx = df.index.get_indexer([timestamp], method="nearest")[0]

        start_idx = max(0, idx - bars_before)
        end_idx = min(len(df), idx + bars_after + 1)

        return df.iloc[start_idx:end_idx]

    def get_available_timeframes(self) -> list:
        """Return list of loaded timeframes."""
        return list(self._dataframes.keys())

    def _get_parquet_path(self, timeframe: Timeframe) -> Path:
        """Build the parquet file path for a given timeframe."""
        return self._parquet_dir / f"{self._instrument}_{timeframe.value}.parquet"

    def __repr__(self) -> str:
        if not self._loaded:
            return "DataManager(not loaded)"
        tf_info = {
            tf.value: f"{len(df):,} bars"
            for tf, df in self._dataframes.items()
        }
        return f"DataManager({tf_info})"
