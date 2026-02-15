# Backtest Engine

A configuration-driven backtesting engine built on [backtrader](https://www.backtrader.com/), designed for multi-timeframe strategy development on NASDAQ 100 CFD tick data (Dukascopy).

## Quick Start

```bash
cd engine
source ../backtrader_env/bin/activate
```

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Preprocess Data (one-time)

Converts raw Dukascopy tick zip files into Parquet format and resamples to configured timeframes.

```bash
python scripts/preprocess.py --config config/backtest.yaml
```

### 3. Run a Backtest

```bash
# List available strategies
python main.py --list-strategies

# Run the dummy strategy (infrastructure test)
python main.py --strategy dummy

# Run with a custom date range
python main.py --strategy dummy --start 2024-01-01 --end 2024-06-30

# Skip trade chart generation (report still generated)
python main.py --strategy dummy --no-plots

# Tag a run for easy identification
python main.py --strategy dummy --tag baseline
```

Each run creates a **timestamped output folder** in `outputs/runs/`:

```
outputs/runs/dummy_20260215_143022/
├── backtest_report.html              # Full stats dashboard
├── trade_0001_long_20240102_1540.html   # Per-trade chart
├── trade_0002_short_20240103_1825.html
└── ...
```

### 4. CLI Reference

| Flag | Short | Description |
|------|-------|-------------|
| `--strategy NAME` | `-s` | Strategy to run (required) |
| `--config PATH` | `-c` | Path to YAML config (default: `config/backtest.yaml`) |
| `--start YYYY-MM-DD` | | Override backtest start date |
| `--end YYYY-MM-DD` | | Override backtest end date |
| `--no-plots` | | Skip trade charts (report still generated) |
| `--tag TEXT` | | Tag appended to output folder name |
| `--list-strategies` | | Show available strategies and exit |

### 5. Run Tests

```bash
python -m pytest tests/ -v
```

---

## Project Structure

```
engine/
├── main.py                    # CLI entry point — strategy selection, timestamped runs
├── config/
│   └── backtest.yaml          # All backtest parameters (account, costs, session, etc.)
├── core/
│   ├── types.py               # Enums & dataclasses (TradeRecord, CostModel, BacktestResult, etc.)
│   └── config.py              # YAML config loader → typed AppConfig
├── data/
│   ├── manager.py             # DataManager — loads Parquet, provides DataFrames and slicing
│   ├── session_filter.py      # US session filter with DST-aware timezone handling
│   └── feeds.py               # Custom backtrader PandasData feed + multi-timeframe helper
├── strategy/
│   └── dummy_strategy.py      # Infrastructure test strategy (exercises all engine features)
├── execution/
│   ├── engine.py              # BacktestEngine — wires Cerebro with data, strategy, analyzers
│   ├── risk_manager.py        # Position sizing (4 methods), risk guards, daily loss limits
│   └── order_manager.py       # Bracket order submission with risk guard integration
├── analysis/
│   ├── trade_logger.py        # TradeLogger (bt.Analyzer) — captures TradeRecords from trades
│   ├── metrics.py             # Post-backtest statistics (win rate, Sharpe, drawdown, etc.)
│   └── report.py              # HTML report generator (equity curve, trade table, KPI cards)
├── visualization/
│   └── trade_plotter.py       # Multi-timeframe Plotly charts (TradingView-style position tool)
├── scripts/
│   ├── preprocess.py          # Tick data → Parquet pipeline
│   └── smoke_test.py          # Manual inspection script (session checks, sanity checks)
├── tests/                     # pytest suite (182 tests)
├── outputs/
│   └── runs/                  # Timestamped backtest output folders
├── requirements.txt
└── pytest.ini
```

## Output Report

Every backtest generates an **HTML report** (`backtest_report.html`) containing:

- **KPI Dashboard** — Net Profit, Win Rate, Profit Factor, Max Drawdown, Sharpe, Expectancy
- **Equity Curve** — Interactive Plotly chart showing equity after each trade
- **Trade P&L Chart** — Bar chart of per-trade P&L (green/red)
- **Stats Panels** — P&L breakdown, Risk & Performance, Long vs Short, Trade Duration
- **Trade Log Table** — Every trade with entry/exit, SL/TP, size, P&L, R:R, duration, result

Per-trade charts show **TradingView-style position tool** overlays with:
- Entry/exit markers with price labels
- SL/TP zones (red risk zone, green profit zone)
- Gap-free candlestick charts (integer x-axis, no overnight gaps)
- Hover for OHLC data on each candle

## Configuration

There is a single config file: `config/backtest.yaml`. It covers the **execution environment** — everything that stays the same regardless of which strategy you run:

| Section | Parameters |
|---------|------------|
| **Account** | Starting balance, currency, leverage (50:1 funded, 500:1 personal) |
| **Position Sizing** | `fixed_lot`, `fixed_risk`, `percent_equity`, or `fixed_dollar` |
| **Risk Management** | Max positions, daily loss limits ($, %) |
| **Costs** | Spread (index points), commission (per trade/lot), slippage |
| **Session** | Trading window (8:00–16:30 ET), DST-aware |
| **Data** | Tick data source, Parquet output, instrument, timeframes |
| **Backtest Period** | Start/end dates |
| **Visualization** | Output format (HTML/PNG), timeframes, candle context |

**Strategy-specific parameters** (indicator periods, SL/TP distances, entry rules, etc.) live in the strategy's Python file via backtrader's `params` tuple, with defaults overridable from `main.py`'s strategy registry. This keeps each strategy self-contained — no separate YAML to keep in sync.

## Data Pipeline

```
Dukascopy tick zips (YYYYMMDD_quote.zip)
  → preprocess.py reads CSVs from each zip
  → Concatenates into tick DataFrame (422M+ rows)
  → Saves as USATECHIDXUSD_tick.parquet
  → Resamples to 1min / 5min / 1hr / 4hr OHLC bars
  → Saves each as separate Parquet files
```

Parquet files stored in `../data/usatech_parquet/` (relative to `engine/`).

## Architecture

- **Config-Driven** — All parameters in YAML, loaded into typed dataclasses
- **Pipeline Pattern** — Tick → Parquet → session filter → backtrader feeds
- **Separation of Concerns** — data, strategy, execution, analysis, visualization are independent
- **TDD** — 182 tests covering every module (unit + integration)
- **Strategy is pluggable** — Engine provides risk management, session filtering, cost model; strategy decides when to trade

### Adding a New Strategy

1. Create `strategy/my_strategy.py` extending `bt.Strategy`
2. Add four class attributes for auto-discovery:
   ```python
   cli_name = "my_strategy"
   cli_description = "What it does"
   cli_kwargs = {"param1": 100}           # Default overrides for params
   cli_timeframes = [Timeframe.ONE_MIN]   # Or None for all configured
   ```
3. Define strategy-specific params in the class (backtrader's `params` tuple)
4. Accept `risk_manager` and `session_filter` as params (injected by engine)
5. Use `OrderManager` for bracket order submission
6. Run: `python main.py --strategy my_strategy`

That's it — `main.py` auto-discovers any `bt.Strategy` subclass in `strategy/` that has a `cli_name`. No registration step, no editing other files.

## Tech Stack

| Component | Library |
|-----------|---------|
| Backtesting | backtrader 1.9.78 |
| Data storage | Parquet (pyarrow) |
| Data manipulation | pandas, numpy |
| Configuration | PyYAML |
| Visualization | Plotly |
| Timezone handling | pytz |
| Testing | pytest |
