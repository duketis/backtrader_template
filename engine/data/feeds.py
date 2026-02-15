"""
Custom backtrader data feed for Parquet-based OHLC data.

Bridges our preprocessed Parquet data with backtrader's data feed system.
Supports loading any timeframe (tick, 1min, 5min, 1hr, 4hr) and
provides the data in the format backtrader expects.
"""

import backtrader as bt
import pandas as pd

from core.types import Timeframe


class ParquetDataFeed(bt.feeds.PandasData):
    """Backtrader data feed that loads from a pandas DataFrame.

    This extends backtrader's built-in PandasData feed. The DataFrame
    should have a datetime index and OHLC columns (from our Parquet files).

    Since our tick data has no real volume and no open interest,
    those fields are set to -1 (disabled).

    Usage:
        df = data_manager.get_dataframe(Timeframe.ONE_MIN)
        feed = ParquetDataFeed(dataname=df, name="NAS100_1min")
        cerebro.adddata(feed)
    """

    # Map DataFrame columns to backtrader's expected line names
    params = (
        ("open", "open"),
        ("high", "high"),
        ("low", "low"),
        ("close", "close"),
        ("volume", -1),         # No reliable volume data
        ("openinterest", -1),   # Not applicable for CFD index
    )


class MultiTimeframeFeeds:
    """Helper to create and manage backtrader data feeds for multiple timeframes.

    Creates a set of data feeds from our DataManager, one per timeframe,
    and provides them in a format ready for cerebro.adddata().

    Usage:
        mtf = MultiTimeframeFeeds(data_manager, session_filter)
        feeds = mtf.create_feeds()
        for name, feed in feeds.items():
            cerebro.adddata(feed)
    """

    # Map our timeframes to backtrader compression/timeframe pairs
    BT_TIMEFRAME_MAP = {
        Timeframe.TICK: (bt.TimeFrame.Ticks, 1),
        Timeframe.ONE_MIN: (bt.TimeFrame.Minutes, 1),
        Timeframe.FIVE_MIN: (bt.TimeFrame.Minutes, 5),
        Timeframe.ONE_HOUR: (bt.TimeFrame.Minutes, 60),
        Timeframe.FOUR_HOUR: (bt.TimeFrame.Minutes, 240),
    }

    def __init__(self, data_manager, session_filter=None):
        """
        Args:
            data_manager: Loaded DataManager instance.
            session_filter: Optional SessionFilter to apply to data.
        """
        self._data_manager = data_manager
        self._session_filter = session_filter

    def create_feed(
        self,
        timeframe: Timeframe,
        apply_session_filter: bool = False,
    ) -> ParquetDataFeed:
        """Create a single backtrader data feed for a timeframe.

        Args:
            timeframe: The timeframe to create a feed for.
            apply_session_filter: Whether to filter data to session hours.

        Returns:
            A ParquetDataFeed ready for cerebro.adddata().
        """
        df = self._data_manager.get_dataframe(timeframe)

        if apply_session_filter and self._session_filter is not None:
            df = self._session_filter.filter_dataframe(df)

        bt_tf, bt_comp = self.BT_TIMEFRAME_MAP[timeframe]

        feed = ParquetDataFeed(
            dataname=df,
            name=f"{self._data_manager._instrument}_{timeframe.value}",
            timeframe=bt_tf,
            compression=bt_comp,
        )

        return feed

    def create_all_feeds(
        self,
        timeframes: list = None,
        apply_session_filter: bool = False,
    ) -> dict:
        """Create data feeds for all specified timeframes.

        Args:
            timeframes: List of Timeframe enums. Defaults to all loaded.
            apply_session_filter: Whether to filter to session hours.

        Returns:
            Dict mapping Timeframe → ParquetDataFeed.
        """
        if timeframes is None:
            timeframes = self._data_manager.get_available_timeframes()

        feeds = {}
        for tf in timeframes:
            feeds[tf] = self.create_feed(tf, apply_session_filter)

        return feeds
