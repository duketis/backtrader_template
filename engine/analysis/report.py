"""
HTML backtest report generator.

Produces a single self-contained HTML file with:
  - Summary stats dashboard (KPI cards)
  - Equity curve chart (Plotly)
  - Trade-by-trade breakdown table
  - Long vs Short comparison
  - Streaks, durations, cost breakdown

Designed to be opened in a browser for post-backtest review.
All Plotly JS is loaded from CDN — no local dependencies.
"""

from pathlib import Path
from typing import Optional

import plotly.graph_objects as go

from core.types import BacktestResult, Direction


def generate_report(
    result: BacktestResult,
    output_dir: Path,
    filename: str = "backtest_report.html",
    show: bool = False,
) -> Path:
    """Generate and save an HTML backtest report.

    Args:
        result: Computed BacktestResult with all metrics.
        output_dir: Directory to save the report.
        filename: Output filename.
        show: Whether to open in browser after saving.

    Returns:
        Path to the saved report file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / filename

    html = _build_html(result)
    path.write_text(html, encoding="utf-8")

    if show:
        import webbrowser
        webbrowser.open(f"file://{path.resolve()}")

    return path


def _build_html(result: BacktestResult) -> str:
    """Build the complete HTML report string."""

    equity_chart = _build_equity_chart(result)
    pnl_chart = _build_pnl_bar_chart(result)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Backtest Report</title>
<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
<style>
{_CSS}
</style>
</head>
<body>

<div class="container">

    <!-- Header -->
    <div class="header">
        <h1>📊 Backtest Report</h1>
        <div class="subtitle">
            {result.total_trades} trades &nbsp;|&nbsp;
            {_fmt_currency(result.start_equity)} → {_fmt_currency(result.end_equity)} &nbsp;|&nbsp;
            Return: {result.return_percent:+.2f}%
        </div>
    </div>

    <!-- KPI Cards -->
    <div class="kpi-grid">
        {_kpi_card("Net Profit", _fmt_currency(result.net_profit), _pnl_class(result.net_profit))}
        {_kpi_card("Win Rate", f"{result.win_rate:.1%}", _wr_class(result.win_rate))}
        {_kpi_card("Profit Factor", f"{result.profit_factor:.2f}", _pf_class(result.profit_factor))}
        {_kpi_card("Max Drawdown", f"{_fmt_currency(result.max_drawdown)} ({result.max_drawdown_percent:.1f}%)", "negative")}
        {_kpi_card("Sharpe Ratio", f"{result.sharpe_ratio:.2f}", _pnl_class(result.sharpe_ratio))}
        {_kpi_card("Expectancy", f"{_fmt_currency(result.expectancy)}/trade", _pnl_class(result.expectancy))}
    </div>

    <!-- Equity Curve -->
    <div class="section">
        <h2>Equity Curve</h2>
        <div id="equity-chart"></div>
    </div>

    <!-- P&L Distribution -->
    <div class="section">
        <h2>Trade P&L</h2>
        <div id="pnl-chart"></div>
    </div>

    <!-- Stats Grid -->
    <div class="stats-grid">

        <!-- P&L Breakdown -->
        <div class="stats-card">
            <h3>P&L Breakdown</h3>
            <table class="stats-table">
                {_stat_row("Gross Profit", _fmt_currency(result.gross_profit), "positive")}
                {_stat_row("Gross Loss", _fmt_currency(result.gross_loss), "negative")}
                {_stat_row("Net Profit", _fmt_currency(result.net_profit), _pnl_class(result.net_profit))}
                {_stat_row("Total Costs", _fmt_currency(result.total_costs))}
                {_stat_row("Avg Winner", _fmt_currency(result.avg_winner), "positive")}
                {_stat_row("Avg Loser", _fmt_currency(result.avg_loser), "negative")}
                {_stat_row("Largest Winner", _fmt_currency(result.largest_winner), "positive")}
                {_stat_row("Largest Loser", _fmt_currency(result.largest_loser), "negative")}
            </table>
        </div>

        <!-- Risk & Performance -->
        <div class="stats-card">
            <h3>Risk & Performance</h3>
            <table class="stats-table">
                {_stat_row("Win Rate", f"{result.win_rate:.1%}")}
                {_stat_row("Profit Factor", f"{result.profit_factor:.2f}")}
                {_stat_row("Avg R:R", f"{result.avg_rr:.2f}")}
                {_stat_row("Sharpe Ratio", f"{result.sharpe_ratio:.2f}")}
                {_stat_row("Max Drawdown", f"{_fmt_currency(result.max_drawdown)} ({result.max_drawdown_percent:.1f}%)")}
                {_stat_row("Max Win Streak", str(result.max_consecutive_wins))}
                {_stat_row("Max Loss Streak", str(result.max_consecutive_losses))}
                {_stat_row("Expectancy", f"{_fmt_currency(result.expectancy)}/trade")}
            </table>
        </div>

        <!-- Long vs Short -->
        <div class="stats-card">
            <h3>Long vs Short</h3>
            <table class="stats-table">
                <tr class="header-row"><td></td><td><strong>Long</strong></td><td><strong>Short</strong></td></tr>
                <tr><td>Trades</td><td>{result.long_trades}</td><td>{result.short_trades}</td></tr>
                <tr><td>Win Rate</td><td>{result.long_win_rate:.1%}</td><td>{result.short_win_rate:.1%}</td></tr>
                <tr><td>Net P&L</td>
                    <td class="{_pnl_class(result.long_net_pnl)}">{_fmt_currency(result.long_net_pnl)}</td>
                    <td class="{_pnl_class(result.short_net_pnl)}">{_fmt_currency(result.short_net_pnl)}</td>
                </tr>
            </table>
        </div>

        <!-- Duration -->
        <div class="stats-card">
            <h3>Trade Duration</h3>
            <table class="stats-table">
                {_stat_row("Avg Duration", _fmt_duration(result.avg_trade_duration_min))}
                {_stat_row("Avg Winner Duration", _fmt_duration(result.avg_winner_duration_min))}
                {_stat_row("Avg Loser Duration", _fmt_duration(result.avg_loser_duration_min))}
            </table>
        </div>

    </div>

    <!-- Trade Table -->
    <div class="section">
        <h2>Trade Log</h2>
        <div class="table-wrapper">
            <table class="trade-table">
                <thead>
                    <tr>
                        <th>#</th>
                        <th>Direction</th>
                        <th>Entry Time</th>
                        <th>Exit Time</th>
                        <th>Entry</th>
                        <th>Exit</th>
                        <th>SL</th>
                        <th>TP</th>
                        <th>Size</th>
                        <th>Gross P&L</th>
                        <th>Net P&L</th>
                        <th>Costs</th>
                        <th>R:R</th>
                        <th>Duration</th>
                        <th>Setup</th>
                        <th>Result</th>
                    </tr>
                </thead>
                <tbody>
                    {_build_trade_rows(result)}
                </tbody>
            </table>
        </div>
    </div>

</div>

<script>
{equity_chart}
{pnl_chart}
</script>

</body>
</html>"""


# ==============================================================================
# Chart builders (return JS strings for Plotly)
# ==============================================================================

def _build_equity_chart(result: BacktestResult) -> str:
    """Build Plotly JS for the equity curve chart."""
    if not result.equity_curve:
        return ""

    x_vals = [pt[0] for pt in result.equity_curve]
    y_vals = [pt[1] for pt in result.equity_curve]

    # Color the fill based on whether equity is above or below starting
    return f"""
    Plotly.newPlot('equity-chart', [{{
        x: {x_vals},
        y: {y_vals},
        type: 'scatter',
        mode: 'lines+markers',
        line: {{ color: '#2962ff', width: 2 }},
        marker: {{ size: 6, color: '#2962ff' }},
        fill: 'tozeroy',
        fillcolor: 'rgba(41, 98, 255, 0.08)',
        hovertemplate: 'Trade #%{{x}}<br>Equity: $%{{y:,.2f}}<extra></extra>'
    }}], {{
        plot_bgcolor: '#131722',
        paper_bgcolor: '#131722',
        font: {{ color: '#d1d4dc' }},
        margin: {{ l: 60, r: 30, t: 20, b: 40 }},
        height: 300,
        xaxis: {{
            title: 'Trade #',
            gridcolor: '#1e222d',
            zeroline: false
        }},
        yaxis: {{
            title: 'Equity ($)',
            gridcolor: '#1e222d',
            zeroline: false,
            tickformat: '$,.0f'
        }},
        shapes: [{{
            type: 'line',
            x0: 0, x1: {x_vals[-1]},
            y0: {result.start_equity}, y1: {result.start_equity},
            line: {{ color: '#555', width: 1, dash: 'dash' }}
        }}]
    }});
    """


def _build_pnl_bar_chart(result: BacktestResult) -> str:
    """Build Plotly JS for per-trade P&L bar chart."""
    if not result.trades:
        return ""

    trade_ids = [t.trade_id for t in result.trades]
    pnls = [t.net_pnl for t in result.trades]
    colors = ['#26a69a' if p > 0 else '#ef5350' for p in pnls]
    dirs = [t.direction.value.upper() for t in result.trades]

    return f"""
    Plotly.newPlot('pnl-chart', [{{
        x: {trade_ids},
        y: {pnls},
        type: 'bar',
        marker: {{ color: {colors} }},
        customdata: {dirs},
        hovertemplate: 'Trade #%{{x}} (%{{customdata}})<br>P&L: $%{{y:+,.2f}}<extra></extra>'
    }}], {{
        plot_bgcolor: '#131722',
        paper_bgcolor: '#131722',
        font: {{ color: '#d1d4dc' }},
        margin: {{ l: 60, r: 30, t: 20, b: 40 }},
        height: 250,
        xaxis: {{
            title: 'Trade #',
            gridcolor: '#1e222d',
            zeroline: false
        }},
        yaxis: {{
            title: 'Net P&L ($)',
            gridcolor: '#1e222d',
            zeroline: true,
            zerolinecolor: '#555',
            tickformat: '$,.0f'
        }}
    }});
    """


# ==============================================================================
# Trade table
# ==============================================================================

def _build_trade_rows(result: BacktestResult) -> str:
    """Build HTML table rows for each trade."""
    rows = []
    for t in result.trades:
        entry_str = t.entry_time.strftime("%Y-%m-%d %H:%M") if t.entry_time else ""
        exit_str = t.exit_time.strftime("%Y-%m-%d %H:%M") if t.exit_time else "OPEN"
        sl_str = f"{t.stop_loss:,.2f}" if t.stop_loss else "—"
        tp_str = f"{t.take_profit:,.2f}" if t.take_profit else "—"
        rr_str = f"{t.risk_reward_actual:.2f}" if t.risk_reward_actual is not None else "—"
        dur = t.duration_seconds
        dur_str = _fmt_duration(dur / 60.0) if dur is not None else "—"
        dir_class = "long" if t.direction == Direction.LONG else "short"
        pnl_class = "positive" if t.net_pnl > 0 else "negative"
        result_str = "✅ WIN" if t.is_winner else "❌ LOSS"
        result_class = "win-badge" if t.is_winner else "loss-badge"

        setup_str = t.metadata.get("confluence", "—")

        rows.append(f"""<tr>
            <td>{t.trade_id}</td>
            <td class="{dir_class}">{t.direction.value.upper()}</td>
            <td>{entry_str}</td>
            <td>{exit_str}</td>
            <td>{t.entry_price:,.2f}</td>
            <td>{t.exit_price:,.2f}</td>
            <td>{sl_str}</td>
            <td>{tp_str}</td>
            <td>{t.size:.2f}</td>
            <td class="{_pnl_class(t.gross_pnl)}">{_fmt_currency(t.gross_pnl)}</td>
            <td class="{pnl_class}">{_fmt_currency(t.net_pnl)}</td>
            <td>{_fmt_currency(t.total_costs)}</td>
            <td>{rr_str}</td>
            <td>{dur_str}</td>
            <td>{setup_str}</td>
            <td><span class="{result_class}">{result_str}</span></td>
        </tr>""")

    return "\n".join(rows)


# ==============================================================================
# Helpers
# ==============================================================================

def _kpi_card(label: str, value: str, css_class: str = "") -> str:
    return f"""<div class="kpi-card">
        <div class="kpi-value {css_class}">{value}</div>
        <div class="kpi-label">{label}</div>
    </div>"""


def _stat_row(label: str, value: str, css_class: str = "") -> str:
    return f'<tr><td>{label}</td><td class="{css_class}">{value}</td></tr>'


def _fmt_currency(val: float) -> str:
    return f"${val:+,.2f}" if val != 0 else "$0.00"


def _fmt_duration(minutes: float) -> str:
    if minutes <= 0:
        return "—"
    if minutes < 60:
        return f"{minutes:.0f}m"
    hours = minutes / 60
    if hours < 24:
        h = int(hours)
        m = int((hours - h) * 60)
        return f"{h}h {m}m" if m > 0 else f"{h}h"
    days = hours / 24
    return f"{days:.1f}d"


def _pnl_class(val: float) -> str:
    return "positive" if val > 0 else "negative" if val < 0 else ""


def _wr_class(val: float) -> str:
    return "positive" if val >= 0.5 else "negative"


def _pf_class(val: float) -> str:
    return "positive" if val >= 1.0 else "negative"


# ==============================================================================
# CSS
# ==============================================================================

_CSS = """
* { margin: 0; padding: 0; box-sizing: border-box; }

body {
    background: #0d1117;
    color: #d1d4dc;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    font-size: 14px;
    line-height: 1.5;
}

.container {
    max-width: 1200px;
    margin: 0 auto;
    padding: 24px;
}

.header {
    margin-bottom: 24px;
    border-bottom: 1px solid #1e222d;
    padding-bottom: 16px;
}

.header h1 {
    font-size: 24px;
    color: white;
    margin-bottom: 4px;
}

.subtitle {
    color: #8b8f99;
    font-size: 14px;
}

/* KPI Cards */
.kpi-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
    gap: 12px;
    margin-bottom: 24px;
}

.kpi-card {
    background: #131722;
    border: 1px solid #1e222d;
    border-radius: 8px;
    padding: 16px;
    text-align: center;
}

.kpi-value {
    font-size: 22px;
    font-weight: 700;
    color: white;
    margin-bottom: 4px;
}

.kpi-label {
    font-size: 12px;
    color: #8b8f99;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}

/* Stats Grid */
.stats-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
    gap: 16px;
    margin-bottom: 24px;
}

.stats-card {
    background: #131722;
    border: 1px solid #1e222d;
    border-radius: 8px;
    padding: 16px;
}

.stats-card h3 {
    font-size: 14px;
    color: #8b8f99;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-bottom: 12px;
    border-bottom: 1px solid #1e222d;
    padding-bottom: 8px;
}

.stats-table {
    width: 100%;
    border-collapse: collapse;
}

.stats-table td {
    padding: 5px 0;
    border-bottom: 1px solid #1a1e2d;
}

.stats-table td:last-child {
    text-align: right;
    font-weight: 600;
}

.stats-table .header-row td {
    border-bottom: 2px solid #1e222d;
    padding-bottom: 8px;
    text-align: right;
}

.stats-table .header-row td:first-child {
    text-align: left;
}

/* Sections */
.section {
    margin-bottom: 24px;
}

.section h2 {
    font-size: 16px;
    color: white;
    margin-bottom: 12px;
}

/* Trade Table */
.table-wrapper {
    overflow-x: auto;
    background: #131722;
    border: 1px solid #1e222d;
    border-radius: 8px;
}

.trade-table {
    width: 100%;
    border-collapse: collapse;
    white-space: nowrap;
    font-size: 13px;
}

.trade-table th {
    background: #1a1e2d;
    padding: 10px 12px;
    text-align: right;
    color: #8b8f99;
    font-weight: 600;
    text-transform: uppercase;
    font-size: 11px;
    letter-spacing: 0.5px;
    position: sticky;
    top: 0;
}

.trade-table th:first-child,
.trade-table th:nth-child(2),
.trade-table th:nth-child(3),
.trade-table th:nth-child(4) {
    text-align: left;
}

.trade-table td {
    padding: 8px 12px;
    text-align: right;
    border-bottom: 1px solid #1a1e2d;
}

.trade-table td:first-child,
.trade-table td:nth-child(2),
.trade-table td:nth-child(3),
.trade-table td:nth-child(4) {
    text-align: left;
}

.trade-table tbody tr:hover {
    background: #1a1e2d;
}

/* Colors */
.positive { color: #26a69a; }
.negative { color: #ef5350; }
.long { color: #26a69a; font-weight: 600; }
.short { color: #ef5350; font-weight: 600; }

.win-badge {
    color: #26a69a;
    font-weight: 600;
}

.loss-badge {
    color: #ef5350;
    font-weight: 600;
}
"""
