"""
Multi-timeframe trade visualizer using Plotly.

For each trade, generates interactive candlestick charts at configured
timeframes with entry/exit markers, SL/TP zones, and position overlays
styled to match TradingView's position tool.

Key design decisions:
  - Uses integer x-axis (bar index) instead of datetime to eliminate
    overnight/weekend gaps that make charts unreadable.
  - Shows datetime labels via customdata hover + tick labels.
  - Renders SL/TP/entry as filled zones (not just lines) like TV's
    position tool — green for profit zone, red for risk zone.
"""

from pathlib import Path
from typing import List, Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from core.config import AppConfig
from core.types import Direction, Timeframe, TradeRecord
from data.manager import DataManager


class TradePlotter:
    """Generates interactive multi-timeframe trade visualizations.

    Usage:
        plotter = TradePlotter(config, data_manager)
        plotter.plot_trade(trade_record)           # Single trade, 4 charts
        plotter.plot_all_trades(trade_records)      # All trades
    """

    # Colors matching TradingView
    LONG_COLOR = "#26a69a"       # Green (bullish candles)
    SHORT_COLOR = "#ef5350"      # Red (bearish candles)
    WIN_COLOR = "#26a69a"        # Green (profit zone)
    LOSS_COLOR = "#ef5350"       # Red (loss zone)
    ENTRY_COLOR = "#2962ff"      # Blue (entry line)
    SL_COLOR = "#ef5350"         # Red (stop loss)
    TP_COLOR = "#26a69a"         # Green (take profit)
    BG_COLOR = "#131722"         # Dark background
    GRID_COLOR = "#1e222d"       # Subtle grid
    TEXT_COLOR = "#d1d4dc"       # Light text

    def __init__(self, config: AppConfig, data_manager: DataManager):
        self._config = config
        self._dm = data_manager
        self._viz_config = config.visualization
        self._output_dir = config.visualization.output_dir

    def plot_trade(
        self,
        trade: TradeRecord,
        timeframes: Optional[List[Timeframe]] = None,
        save: bool = True,
        show: bool = False,
    ) -> Optional[go.Figure]:
        """Generate a multi-timeframe chart for a single trade.

        Args:
            trade: The TradeRecord to visualize.
            timeframes: Timeframes to plot. Defaults to config.
            save: Whether to save to file.
            show: Whether to display in browser.

        Returns:
            The Plotly figure object.
        """
        if timeframes is None:
            timeframes = self._viz_config.timeframes

        # Only plot timeframes that are actually loaded in the DataManager
        available = set(self._dm.get_available_timeframes())
        timeframes = [tf for tf in timeframes if tf in available]
        if not timeframes:
            print(f"  ⚠ Skipping trade #{trade.trade_id}: no matching timeframes loaded")
            return None

        n_charts = len(timeframes)

        fig = make_subplots(
            rows=n_charts,
            cols=1,
            shared_xaxes=False,
            vertical_spacing=0.06,
            subplot_titles=[tf.display_name for tf in timeframes],
            row_heights=[1.0 / n_charts] * n_charts,
        )

        for i, tf in enumerate(timeframes, 1):
            self._add_chart(fig, trade, tf, row=i, n_rows=n_charts)

        # Title
        direction_str = trade.direction.value.upper()
        pnl_str = f"${trade.net_pnl:+,.2f}"
        result_emoji = "✅" if trade.is_winner else "❌"
        size_str = f"{trade.size:.2f}" if trade.size >= 1 else f"{trade.size:.4f}"

        fig.update_layout(
            title=dict(
                text=(
                    f"Trade #{trade.trade_id} — {direction_str} — "
                    f"{pnl_str} {result_emoji}  |  "
                    f"Size: {size_str}  |  "
                    f"Entry: {trade.entry_price:,.2f}  →  "
                    f"Exit: {trade.exit_price:,.2f}"
                ),
                font=dict(size=15, color="white"),
                x=0.01, xanchor="left",
            ),
            height=500 * n_charts,
            plot_bgcolor=self.BG_COLOR,
            paper_bgcolor=self.BG_COLOR,
            font=dict(color=self.TEXT_COLOR, size=11),
            showlegend=False,
            margin=dict(l=10, r=80, t=60, b=30),
        )

        if save:
            self._save_figure(fig, trade)
        if show:
            fig.show()

        return fig

    def plot_all_trades(
        self,
        trades: List[TradeRecord],
        show: bool = False,
    ) -> None:
        """Generate charts for all trades."""
        for trade in trades:
            self.plot_trade(trade, save=True, show=show)

    # ------------------------------------------------------------------
    # Core chart builder
    # ------------------------------------------------------------------

    def _add_chart(
        self,
        fig: go.Figure,
        trade: TradeRecord,
        timeframe: Timeframe,
        row: int,
        n_rows: int,
    ) -> None:
        """Add a gap-free candlestick chart with TradingView-style position tool."""

        # --- 1. Get bars covering entry → exit plus context ---
        df = self._get_trade_window(trade, timeframe)
        if df.empty:
            return

        n_bars = len(df)
        x = list(range(n_bars))  # Integer x-axis — no datetime gaps!

        # Build datetime labels for tick marks
        dt_labels = [dt.strftime("%H:%M") for dt in df.index]
        date_labels = [dt.strftime("%b %d") for dt in df.index]

        # --- 2. Candlesticks ---
        fig.add_trace(
            go.Candlestick(
                x=x,
                open=df["open"],
                high=df["high"],
                low=df["low"],
                close=df["close"],
                increasing=dict(
                    line=dict(color=self.LONG_COLOR, width=1),
                    fillcolor=self.LONG_COLOR,
                ),
                decreasing=dict(
                    line=dict(color=self.SHORT_COLOR, width=1),
                    fillcolor=self.SHORT_COLOR,
                ),
                name=timeframe.value,
                customdata=[f"{date_labels[i]} {dt_labels[i]}" for i in range(n_bars)],
                hovertemplate=(
                    "%{customdata}<br>"
                    "O: %{open:.2f}<br>"
                    "H: %{high:.2f}<br>"
                    "L: %{low:.2f}<br>"
                    "C: %{close:.2f}<extra></extra>"
                ),
            ),
            row=row, col=1,
        )

        # --- 3. Find entry/exit bar indices ---
        entry_idx = self._find_nearest_bar(df, trade.entry_time)
        exit_idx = self._find_nearest_bar(df, trade.exit_time) if trade.exit_time else None

        # --- 4. TradingView-style position tool (filled zones) ---
        if exit_idx is not None:
            self._add_position_tool(fig, trade, entry_idx, exit_idx, row)

        # --- 5. Entry marker ---
        entry_symbol = "triangle-up" if trade.direction == Direction.LONG else "triangle-down"
        entry_color = self.LONG_COLOR if trade.direction == Direction.LONG else self.SHORT_COLOR

        fig.add_trace(
            go.Scatter(
                x=[entry_idx],
                y=[trade.entry_price],
                mode="markers+text",
                marker=dict(
                    symbol=entry_symbol,
                    size=16,
                    color=entry_color,
                    line=dict(color="white", width=1.5),
                ),
                text=[f"  Entry {trade.entry_price:,.2f}"],
                textposition="middle right",
                textfont=dict(color="white", size=11),
                hovertemplate=f"Entry: {trade.entry_price:,.2f}<extra></extra>",
            ),
            row=row, col=1,
        )

        # --- 6. Exit marker ---
        if exit_idx is not None:
            exit_color = self.WIN_COLOR if trade.is_winner else self.LOSS_COLOR
            pnl_text = f"${trade.net_pnl:+,.2f}"
            fig.add_trace(
                go.Scatter(
                    x=[exit_idx],
                    y=[trade.exit_price],
                    mode="markers+text",
                    marker=dict(
                        symbol="x",
                        size=14,
                        color=exit_color,
                        line=dict(color="white", width=2),
                    ),
                    text=[f"  Exit {trade.exit_price:,.2f}  ({pnl_text})"],
                    textposition="middle right",
                    textfont=dict(color=exit_color, size=11),
                    hovertemplate=(
                        f"Exit: {trade.exit_price:,.2f}<br>"
                        f"P&L: {pnl_text}<extra></extra>"
                    ),
                ),
                row=row, col=1,
            )

        # --- 7. Configure axes ---
        # Show ~10-12 evenly spaced time labels
        n_ticks = min(12, n_bars)
        tick_step = max(1, n_bars // n_ticks)
        tick_vals = list(range(0, n_bars, tick_step))
        tick_text = []
        last_date = ""
        for i in tick_vals:
            cur_date = date_labels[i]
            if cur_date != last_date:
                tick_text.append(f"{cur_date}\n{dt_labels[i]}")
                last_date = cur_date
            else:
                tick_text.append(dt_labels[i])

        xaxis_name = f"xaxis{row}" if row > 1 else "xaxis"
        yaxis_name = f"yaxis{row}" if row > 1 else "yaxis"

        fig.update_layout(**{
            xaxis_name: dict(
                tickvals=tick_vals,
                ticktext=tick_text,
                gridcolor=self.GRID_COLOR,
                showgrid=True,
                rangeslider=dict(visible=False),
                zeroline=False,
            ),
            yaxis_name: dict(
                gridcolor=self.GRID_COLOR,
                showgrid=True,
                side="right",
                zeroline=False,
                tickformat=",.2f",
            ),
        })

    # ------------------------------------------------------------------
    # TradingView Position Tool
    # ------------------------------------------------------------------

    def _add_position_tool(
        self,
        fig: go.Figure,
        trade: TradeRecord,
        entry_idx: int,
        exit_idx: int,
        row: int,
    ) -> None:
        """Draw TradingView-style position zones.

        Creates filled zones from entry bar to exit bar:
          - TP zone (entry → TP):  green fill
          - SL zone (entry → SL):  red fill
          - Entry line:            blue horizontal
          - Result zone (entry → exit): highlighted with border
        """
        x0 = entry_idx - 0.5
        x1 = exit_idx + 0.5

        # --- Profit zone (entry → TP) ---
        if trade.take_profit is not None:
            fig.add_shape(
                type="rect",
                x0=x0, x1=x1,
                y0=trade.entry_price,
                y1=trade.take_profit,
                fillcolor="rgba(38, 166, 154, 0.12)",
                line=dict(width=0),
                row=row, col=1,
            )
            # TP line
            fig.add_shape(
                type="line",
                x0=x0, x1=x1,
                y0=trade.take_profit, y1=trade.take_profit,
                line=dict(color=self.TP_COLOR, width=1.5, dash="dash"),
                row=row, col=1,
            )
            # TP label with distance
            tp_dist = abs(trade.take_profit - trade.entry_price)
            fig.add_trace(
                go.Scatter(
                    x=[x0 + 1],
                    y=[trade.take_profit],
                    mode="text",
                    text=[f"TP {trade.take_profit:,.2f}  (+{tp_dist:.0f}pt)"],
                    textposition="top right",
                    textfont=dict(color=self.TP_COLOR, size=11),
                    hoverinfo="skip",
                ),
                row=row, col=1,
            )

        # --- Risk zone (entry → SL) ---
        if trade.stop_loss is not None:
            fig.add_shape(
                type="rect",
                x0=x0, x1=x1,
                y0=trade.entry_price,
                y1=trade.stop_loss,
                fillcolor="rgba(239, 83, 80, 0.12)",
                line=dict(width=0),
                row=row, col=1,
            )
            # SL line
            fig.add_shape(
                type="line",
                x0=x0, x1=x1,
                y0=trade.stop_loss, y1=trade.stop_loss,
                line=dict(color=self.SL_COLOR, width=1.5, dash="dash"),
                row=row, col=1,
            )
            # SL label with distance
            sl_dist = abs(trade.stop_loss - trade.entry_price)
            fig.add_trace(
                go.Scatter(
                    x=[x0 + 1],
                    y=[trade.stop_loss],
                    mode="text",
                    text=[f"SL {trade.stop_loss:,.2f}  (-{sl_dist:.0f}pt)"],
                    textposition="bottom right",
                    textfont=dict(color=self.SL_COLOR, size=11),
                    hoverinfo="skip",
                ),
                row=row, col=1,
            )

        # --- Entry line (blue horizontal) ---
        fig.add_shape(
            type="line",
            x0=x0, x1=x1,
            y0=trade.entry_price, y1=trade.entry_price,
            line=dict(color=self.ENTRY_COLOR, width=1.5),
            row=row, col=1,
        )

        # --- Actual result overlay (entry → exit price) ---
        result_color = (
            "rgba(38, 166, 154, 0.20)" if trade.is_winner
            else "rgba(239, 83, 80, 0.20)"
        )
        border = self.WIN_COLOR if trade.is_winner else self.LOSS_COLOR

        fig.add_shape(
            type="rect",
            x0=x0, x1=x1,
            y0=trade.entry_price,
            y1=trade.exit_price,
            fillcolor=result_color,
            line=dict(color=border, width=1.5),
            row=row, col=1,
        )

    # ------------------------------------------------------------------
    # Data helpers
    # ------------------------------------------------------------------

    def _get_trade_window(
        self,
        trade: TradeRecord,
        timeframe: Timeframe,
    ) -> pd.DataFrame:
        """Get candle data covering the full trade duration plus context.

        Unlike get_bars_around (which only centers on entry), this
        ensures we have bars covering entry → exit plus padding on
        both sides.
        """
        df_full = self._dm.get_dataframe(timeframe)

        entry_ts = pd.Timestamp(trade.entry_time)
        exit_ts = pd.Timestamp(trade.exit_time) if trade.exit_time else entry_ts

        # Find indices of entry and exit in the full dataframe
        entry_loc = df_full.index.get_indexer([entry_ts], method="nearest")[0]
        exit_loc = df_full.index.get_indexer([exit_ts], method="nearest")[0]

        # Add context bars before entry and after exit
        before = self._viz_config.candles_before_trade
        after = self._viz_config.candles_after_trade

        start = max(0, entry_loc - before)
        end = min(len(df_full), exit_loc + after + 1)

        return df_full.iloc[start:end]

    @staticmethod
    def _find_nearest_bar(df: pd.DataFrame, dt) -> int:
        """Find the integer index (position) of the bar nearest to dt."""
        ts = pd.Timestamp(dt)
        idx = df.index.get_indexer([ts], method="nearest")[0]
        return idx

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def _save_figure(self, fig: go.Figure, trade: TradeRecord) -> None:
        """Save the figure to disk."""
        self._output_dir.mkdir(parents=True, exist_ok=True)

        direction = trade.direction.value
        entry_date = trade.entry_time.strftime("%Y%m%d_%H%M%S")
        filename = f"trade_{trade.trade_id:04d}_{direction}_{entry_date}"

        if self._viz_config.plot_format == "html":
            path = self._output_dir / f"{filename}.html"
            fig.write_html(str(path), include_plotlyjs="cdn")
        else:
            path = self._output_dir / f"{filename}.png"
            fig.write_image(str(path), scale=2)
