# Backtrader Template

A production-ready backtesting framework built on [backtrader](https://www.backtrader.com/), with tick-accurate execution simulation, multi-timeframe analysis, automated reporting, and data scrapers for Dukascopy tick data and Forex Factory economic news.

---

## What's Included

```
├── engine/                  # Core backtesting engine
│   ├── core/                # Config loader, types, enums
│   ├── data/                # Data manager, session filter, custom feeds
│   ├── execution/           # Engine, risk manager, order manager
│   ├── analysis/            # Trade logger, metrics, HTML report generator
│   ├── visualization/       # TradingView-style trade charts (Plotly)
│   ├── strategy/            # Strategy files (dummy included as example)
│   ├── scripts/             # Preprocessing + smoke test
│   ├── tests/               # 182 pytest tests
│   └── config/              # YAML configuration
├── scraping_data_bots/      # Data scrapers
│   ├── scrape_dukascopy_turbo.py      # Dukascopy tick data (binary API)
│   ├── scrape_forex_factory.py        # Forex Factory economic calendar
│   ├── check_price_continuity.py      # Data quality verification
│   ├── test_binary_price_continuity.py
│   ├── test_new_binary_api.py
│   └── test_price_gaps.py
└── data/                    # Tick & Parquet data (not committed — too large)
```

---

## Engine Features

- **Tick-accurate execution** — all timeframes resampled from raw tick data
- **Multi-timeframe** — 1M, 5M, 1HR, 4HR OHLC from raw ticks
- **Config-driven** — single YAML controls account, costs, session, sizing
- **4 position sizing methods** — fixed lot, fixed risk, percent equity, fixed dollar
- **Risk management** — max positions, daily loss limits ($ and %)
- **Bracket orders** — SL + TP with automatic lifecycle management
- **DST-aware session filter** — America/New_York timezone handling
- **Cost model** — spread, commission, slippage (proven via 182 tests)
- **HTML reports** — KPI dashboard, equity curve, P&L chart, trade table
- **TradingView-style charts** — gap-free candles, position tool overlays
- **Strategy auto-discovery** — drop a file in `strategy/`, it appears in CLI
- **Timestamped runs** — each backtest gets its own output folder

---

## Quick Start

```bash
# 1. Create and activate virtual environment
python -m venv backtrader_env
source backtrader_env/bin/activate

# 2. Install dependencies
pip install -r engine/requirements.txt

# 3. Scrape tick data from Dukascopy
cd scraping_data_bots
pip install requests
python scrape_dukascopy_turbo.py --pairs usatech

# 4. Move tick data into data/ folder
#    The scraper outputs to quantconnect_data/indices/dukascopy/tick/usatech/
#    Copy those zip files into data/usatech/ (or update data.tick_data_dir in config)

# 5. Preprocess ticks → Parquet
cd ../engine
python scripts/preprocess.py --config config/backtest.yaml

# 6. Run a backtest
python main.py --strategy dummy

# 7. Run tests
python -m pytest tests/ -v
```

---

## Backtesting Engine

### CLI Reference

```bash
# List all available strategies
python main.py --list-strategies

# Run a strategy
python main.py --strategy dummy

# Override date range
python main.py --strategy dummy --start 2024-01-01 --end 2024-06-30

# Skip trade chart generation (report still generated)
python main.py --strategy dummy --no-plots

# Tag a run for easy identification
python main.py --strategy dummy --tag baseline
```

| Flag | Short | Description |
|------|-------|-------------|
| `--strategy NAME` | `-s` | Strategy to run (required) |
| `--config PATH` | `-c` | Path to YAML config (default: `config/backtest.yaml`) |
| `--start YYYY-MM-DD` | | Override backtest start date |
| `--end YYYY-MM-DD` | | Override backtest end date |
| `--no-plots` | | Skip trade charts (report still generated) |
| `--tag TEXT` | | Tag appended to output folder name |
| `--list-strategies` | | Show available strategies and exit |

### Output Structure

Each run creates a timestamped output folder:

```
outputs/runs/dummy_20260215_143022/
├── backtest_report.html                    # Full stats dashboard
├── trade_0001_long_20240102_1540.html      # Per-trade chart
├── trade_0002_short_20240103_1825.html
└── ...
```

### Configuration

All parameters live in `engine/config/backtest.yaml`:

```yaml
account:
  initial_balance: 100000
  currency: USD
  leverage: 50

position_sizing:
  method: fixed_risk             # fixed_lot | fixed_risk | percent_equity | fixed_dollar
  risk_per_trade_dollars: 1000

risk_management:
  max_positions: 1
  max_daily_loss_dollars: 5000
  max_daily_loss_percent: 5.0

costs:
  spread_points: 1.14            # Half-spread applied on each side of fill
  commission_per_trade: 0.0
  slippage_points: 0.0

session:
  timezone: America/New_York
  start_time: "08:00"
  end_time: "16:30"
  dst_aware: true

data:
  instrument: USATECHIDXUSD
  tick_data_dir: ../data/usatech
  parquet_dir: ../data/usatech_parquet
  timeframes: [1min, 5min, 1hour, 4hour]

backtest:
  start_date: "2020-01-01"
  end_date: "2025-09-15"

visualization:
  enabled: true
  output_dir: outputs/runs
  plot_format: html
  timeframes: [1min, 5min, 1hour, 4hour]
  candles_before_trade: 50
  candles_after_trade: 20
```

### Adding Your Own Strategy

Create a file in `engine/strategy/` with these class attributes:

```python
import backtrader as bt
from core.types import Timeframe

class MyStrategy(bt.Strategy):
    cli_name = "my_strat"
    cli_description = "My custom strategy"
    cli_kwargs = {}                                      # Extra CLI args (optional)
    cli_timeframes = [Timeframe.ONE_MIN, Timeframe.FIVE_MIN]

    params = (
        ("risk_manager", None),
        ("session_filter", None),
    )

    def next(self):
        # Your logic here
        pass
```

Then run it — no registration needed, auto-discovered from the `strategy/` folder:

```bash
python main.py --strategy my_strat
```

The strategy's `cli_timeframes` controls both which data feeds are loaded and which timeframes appear in trade charts.

### Engine Architecture

```
engine/
├── main.py                    # CLI entry point — auto-discovers strategies
├── config/
│   └── backtest.yaml          # All parameters (account, costs, session, etc.)
├── core/
│   ├── types.py               # Enums & dataclasses (TradeRecord, CostModel, etc.)
│   └── config.py              # YAML config loader → typed AppConfig
├── data/
│   ├── manager.py             # DataManager — loads Parquet, provides DataFrames
│   ├── session_filter.py      # US session filter with DST-aware timezone handling
│   └── feeds.py               # Custom backtrader PandasData feed + multi-TF helper
├── strategy/
│   └── dummy_strategy.py      # Infrastructure test strategy
├── execution/
│   ├── engine.py              # BacktestEngine — wires Cerebro with data + strategy
│   ├── risk_manager.py        # Position sizing (4 methods), daily loss limits
│   └── order_manager.py       # Bracket order submission with risk guard integration
├── analysis/
│   ├── trade_logger.py        # TradeLogger (bt.Analyzer) — captures TradeRecords
│   ├── metrics.py             # Post-backtest stats (win rate, Sharpe, drawdown, etc.)
│   └── report.py              # HTML report generator (equity curve, trade table)
├── visualization/
│   └── trade_plotter.py       # Multi-TF Plotly charts (TradingView-style overlays)
├── scripts/
│   ├── preprocess.py          # Tick → Parquet conversion
│   └── smoke_test.py          # Quick end-to-end validation
└── tests/                     # 182 pytest tests covering all modules
```

---

## Data Scrapers

### Dukascopy Tick Data Scraper

High-performance multi-threaded tick data scraper using Dukascopy's binary `.bi5` API. Downloads gap-free, correctly-scaled tick data for indices and 70+ forex pairs.

#### Features

- **Gap-free data** — perfect tick-by-tick price continuity between hours
- **Correct price scaling** — NASDAQ-100 at ~23,800 (not 238)
- **12x performance** — multi-threaded with 12 concurrent connections
- **Binary API** — uses Dukascopy's fast `.bi5` endpoint (not the broken JSON API)
- **Resume capability** — automatically continues from last downloaded date
- **Backtrader-ready** — OHLC format with headers for `GenericCSVData`

#### Supported Instruments

| Symbol | Name | Start Date |
|--------|------|------------|
| `usatech` | NASDAQ-100 (Tech 100) | 2020-01-02 |
| `us500` | S&P 500 | 2020-01-02 |
| 70+ forex pairs | EUR/USD, GBP/USD, USD/JPY, etc. | 2010-01-01 |

#### Usage

```bash
cd scraping_data_bots
source ../backtrader_env/bin/activate

# Download NASDAQ-100 tick data
python scrape_dukascopy_turbo.py --pairs usatech

# Download S&P 500
python scrape_dukascopy_turbo.py --pairs us500

# Download specific forex pairs
python scrape_dukascopy_turbo.py --pairs EUR-USD GBP-USD USD-JPY

# Download all indices only
python scrape_dukascopy_turbo.py --indices-only

# Download all forex pairs only
python scrape_dukascopy_turbo.py --forex-only

# Download everything (all forex + all indices)
python scrape_dukascopy_turbo.py --all

# List all available instruments
python scrape_dukascopy_turbo.py --list

# Test mode — download a single day first
python scrape_dukascopy_turbo.py --pairs usatech --test

# Custom thread count
python scrape_dukascopy_turbo.py --pairs usatech --threads 8
```

| Flag | Description |
|------|-------------|
| `--pairs NAME [NAME ...]` | Specific instruments to scrape (e.g. `usatech`, `EUR-USD`) |
| `--all` | Scrape all available instruments |
| `--forex-only` | Scrape only forex pairs |
| `--indices-only` | Scrape only indices |
| `--list` | List all available instruments |
| `--test` | Test download for a single day before full scrape |
| `--threads N` | Number of concurrent threads (default: 12) |

#### Configuration

Edit the top of `scrape_dukascopy_turbo.py` to change date ranges:

```python
# Full date range
START_DATE = date(2020, 1, 1)
INDICES_START_DATE = date(2020, 1, 2)
END_DATE = date.today() - timedelta(days=1)  # 1-day delay

# Performance
MAX_THREADS = 12
```

#### Output Format

Output: `quantconnect_data/indices/dukascopy/tick/usatech/YYYYMMDD_quote.zip`

Each zip contains a CSV:

```csv
datetime,open,high,low,close,volume
2025-08-15 00:00:00.181,23798.14,23798.14,23798.14,23798.14,1907910372
2025-08-15 00:00:00.286,23799.18,23799.18,23799.18,23799.18,1907910372
```

- Mid-price (`(bid + ask) / 2`) used for OHLC values (since each row is a single tick)
- Millisecond-precision timestamps
- Combined bid/ask volume
- Headers included — ready for backtrader `GenericCSVData`

#### Using with Backtrader

```python
import backtrader as bt
import backtrader.feeds as btfeeds

data = btfeeds.GenericCSVData(
    dataname='quantconnect_data/indices/dukascopy/tick/usatech/20250815_quote.zip',
    datetime=0, open=1, high=2, low=3, close=4, volume=5,
    dtformat='%Y-%m-%d %H:%M:%S.%f',
    headers=True,
    fromdate=datetime.datetime(2025, 8, 15),
    todate=datetime.datetime(2025, 8, 15),
)

cerebro = bt.Cerebro()
cerebro.adddata(data)
```

> **Note:** The engine's preprocessing script (`scripts/preprocess.py`) handles this automatically — it reads all tick zips and resamples them into 1M/5M/1HR/4HR Parquet files.

#### Data Quality Verification

Run the included continuity checker to verify your downloaded data:

```bash
python check_price_continuity.py
```

This checks for price gaps between hourly transitions and reports:
- `✅ Good` — gaps < 0.1 points (normal)
- `⚠️ Small gap` — gaps 0.1-1.0 points (market behavior)
- `❌ LARGE GAP` — gaps > 1.0 points (data problem)

#### Performance

- ~8 seconds for 212,826 ticks (1 full trading day)
- ~26,000 ticks/second processing throughput
- Robust error handling and retry logic

#### Dependencies

Only `requests` needs installing — everything else is Python standard library:

```bash
pip install requests
```

Built-in modules used: `lzma` (decompression), `struct` (binary parsing), `concurrent.futures` (threading), `zipfile` (archive creation).

---

### Forex Factory News Scraper

Scrapes economic calendar events from [forexfactory.com](https://www.forexfactory.com/) using Selenium (headless Chrome). Captures event impact levels, actual/forecast/previous values, and timestamps.

#### Features

- **Economic calendar** — all scheduled news events and data releases
- **Impact classification** — High, Medium, Low impact
- **Multi-currency** — USD, EUR, GBP, JPY, and more
- **Resume capability** — automatically continues from last scraped date
- **CSV output** — clean structured data, appended incrementally
- **Cloudflare bypass** — automated warm-up with wait periods

#### Usage

```bash
cd scraping_data_bots
source ../backtrader_env/bin/activate

python scrape_forex_factory.py
```

The scraper will:
1. Launch a headless Chrome browser
2. Wait 15 seconds for Cloudflare bypass
3. Pause another 15 seconds for manual timezone adjustment (if needed)
4. Scrape each day sequentially with 5-second delays between pages
5. Resume from the last scraped date if `forex_factory_news.csv` already exists

#### Configuration

Edit the top of `scrape_forex_factory.py`:

```python
START_DATE = date(2007, 1, 2)    # Earliest available data
END_DATE   = date(2025, 6, 6)    # Scrape up to this date
CSV_FILE   = "forex_factory_news.csv"
LOCAL_TZ   = ZoneInfo("Australia/Sydney")  # Your local timezone
```

#### Output Format

File: `forex_factory_news.csv`

```csv
local_datetime,impact,currency,event,actual,forecast,previous
2025-01-02T15:00:00,High Impact Expected,USD,ISM Manufacturing PMI,51.4,51.0,49.5
2025-01-02T15:00:00,Medium Impact Expected,USD,ISM Manufacturing Prices,64.0,56.5,50.3
2025-01-02T10:00:00,Low Impact Expected,USD,JOLTS Job Openings,8.10M,7.74M,7.84M
```

| Column | Description |
|--------|-------------|
| `local_datetime` | Event timestamp (`YYYY-MM-DDTHH:MM:SS`) |
| `impact` | `High Impact Expected`, `Medium Impact Expected`, `Low Impact Expected` |
| `currency` | Currency affected (USD, EUR, GBP, etc.) |
| `event` | Event name (e.g. "Non-Farm Employment Change") |
| `actual` | Actual released value |
| `forecast` | Market consensus forecast |
| `previous` | Previous period's value |

#### Dependencies

```bash
pip install selenium webdriver-manager beautifulsoup4
```

Requires Google Chrome installed on the system.

---

## Data Pipeline (End-to-End)

```
1. Scrape ticks          scrape_dukascopy_turbo.py --pairs usatech
                               ↓
2. Raw tick zips          data/usatech/YYYYMMDD_quote.zip
                               ↓
3. Preprocess             python scripts/preprocess.py --config config/backtest.yaml
                               ↓
4. Parquet files          data/usatech_parquet/USATECHIDXUSD_{1min,5min,1hour,4hour}.parquet
                               ↓
5. Run backtest           python main.py --strategy dummy
                               ↓
6. Output                 outputs/runs/dummy_YYYYMMDD_HHMMSS/backtest_report.html
```

---

## License

MIT
