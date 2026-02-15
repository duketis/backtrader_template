# Backtest Engine

A configuration-driven backtesting framework built on [backtrader](https://www.backtrader.com/), with tick-accurate execution simulation, multi-timeframe analysis, and automated reporting.

## What's Included

```
├── engine/              # Core backtesting engine
│   ├── core/            # Config loader, types, enums
│   ├── data/            # Data manager, session filter, custom feeds
│   ├── execution/       # Engine, risk manager, order manager
│   ├── analysis/        # Trade logger, metrics, HTML report generator
│   ├── visualization/   # TradingView-style trade charts (Plotly)
│   ├── strategy/        # Strategy files (dummy included as example)
│   ├── scripts/         # Preprocessing + smoke test
│   ├── tests/           # 182 pytest tests
│   └── config/          # YAML configuration
├── scraping_data_bots/  # Dukascopy tick data scraper + Forex Factory news
└── data/                # Tick & Parquet data (not committed — too large)
```

## Features

- **Tick-accurate execution** — all timeframes resampled from tick data
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

## Quick Start

```bash
# 1. Set up environment
python -m venv backtrader_env
source backtrader_env/bin/activate
pip install -r engine/requirements.txt

# 2. Get tick data (Dukascopy scraper included)
cd scraping_data_bots
python scrape_dukascopy_turbo.py

# 3. Preprocess ticks → Parquet
cd ../engine
python scripts/preprocess.py --config config/backtest.yaml

# 4. Run a backtest
python main.py --strategy dummy
python main.py --list-strategies

# 5. Run tests
python -m pytest tests/ -v
```

## Adding Your Own Strategy

Create a file in `engine/strategy/` with these class attributes:

```python
import backtrader as bt
from core.types import Timeframe

class MyStrategy(bt.Strategy):
    cli_name = "my_strat"
    cli_description = "My custom strategy"
    cli_kwargs = {}
    cli_timeframes = [Timeframe.ONE_MIN, Timeframe.FIVE_MIN]

    params = (
        ("risk_manager", None),
        ("session_filter", None),
    )

    def next(self):
        # Your logic here
        pass
```

Then run it:

```bash
python main.py --strategy my_strat
```

No registration needed — auto-discovered from the `strategy/` folder.

## CLI Reference

| Flag | Description |
|------|-------------|
| `--strategy NAME` | Strategy to run (required) |
| `--config PATH` | Path to YAML config |
| `--start YYYY-MM-DD` | Override start date |
| `--end YYYY-MM-DD` | Override end date |
| `--no-plots` | Skip trade charts |
| `--tag TEXT` | Tag for output folder |
| `--list-strategies` | Show available strategies |

## Configuration

Edit `engine/config/backtest.yaml` — covers account, position sizing, risk management, costs, session hours, data paths, backtest period, visualization.

See [engine/README.md](engine/README.md) for full documentation.

## License

MIT
