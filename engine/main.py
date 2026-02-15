"""
Backtest Engine — Main CLI entry point.

Usage:
    python main.py --strategy dummy
    python main.py --strategy dummy --start 2024-01-01 --end 2024-06-30
    python main.py --strategy dummy --no-plots
    python main.py --list-strategies

Each run creates a timestamped output folder:
    outputs/runs/dummy_20260215_143022/
        ├── backtest_report.html
        ├── trade_0001_long_20240102_154000.html
        ├── trade_0002_short_20240103_182500.html
        └── ...
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

from core.config import load_config
from core.types import Timeframe
from execution.engine import BacktestEngine
from visualization.trade_plotter import TradePlotter


# ==============================================================================
# Strategy Auto-Discovery
# ==============================================================================
# Scans strategy/ folder for any bt.Strategy subclass that has a `cli_name`.
# No need to edit this file when adding a new strategy — just define
# cli_name, cli_description, cli_kwargs, cli_timeframes on your class.

def _discover_strategies() -> dict:
    """Scan strategy/ directory and return registry of all strategies.

    A strategy is auto-registered if it:
      1. Lives in strategy/*.py
      2. Is a subclass of bt.Strategy
      3. Has a `cli_name` class attribute

    Returns:
        Dict mapping cli_name -> {class, kwargs, timeframes, description}
    """
    import importlib
    import inspect
    import backtrader as bt

    strategy_dir = Path(__file__).parent / "strategy"
    registry = {}

    for py_file in sorted(strategy_dir.glob("*.py")):
        if py_file.name.startswith("_"):
            continue

        module_name = f"strategy.{py_file.stem}"
        try:
            module = importlib.import_module(module_name)
        except Exception as e:
            print(f"Warning: could not import {module_name}: {e}")
            continue

        for _name, obj in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(obj, bt.Strategy)
                and obj is not bt.Strategy
                and hasattr(obj, "cli_name")
            ):
                registry[obj.cli_name] = {
                    "class": obj,
                    "kwargs": getattr(obj, "cli_kwargs", {}),
                    "timeframes": getattr(obj, "cli_timeframes", None),
                    "description": getattr(obj, "cli_description", ""),
                }

    return registry


# ==============================================================================
# CLI
# ==============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Backtest Engine — Run trading strategy backtests",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py --strategy dummy
  python main.py --strategy dummy --start 2024-01-01 --end 2024-06-30
  python main.py --strategy dummy --no-plots
  python main.py --list-strategies
        """,
    )
    parser.add_argument(
        "--strategy", "-s",
        type=str,
        default=None,
        help="Strategy to run (use --list-strategies to see available)",
    )
    parser.add_argument(
        "--config", "-c",
        type=str,
        default="config/backtest.yaml",
        help="Path to backtest config YAML (default: config/backtest.yaml)",
    )
    parser.add_argument(
        "--start",
        type=str,
        default=None,
        help="Override start date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end",
        type=str,
        default=None,
        help="Override end date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--no-plots",
        action="store_true",
        help="Skip trade chart generation (report still generated)",
    )
    parser.add_argument(
        "--list-strategies",
        action="store_true",
        help="List available strategies and exit",
    )
    parser.add_argument(
        "--tag",
        type=str,
        default=None,
        help="Optional tag appended to output folder name (e.g. --tag v2)",
    )
    args = parser.parse_args()

    registry = _discover_strategies()

    # --- List strategies mode ---
    if args.list_strategies:
        print("\nAvailable strategies:\n")
        for name, info in registry.items():
            print(f"  {name:15s}  {info['description']}")
        print(f"\nUsage: python main.py --strategy <name>\n")
        return

    # --- Validate strategy ---
    if args.strategy is None:
        parser.print_help()
        print(f"\nError: --strategy is required. Available: {', '.join(registry.keys())}")
        sys.exit(1)

    if args.strategy not in registry:
        print(f"Error: Unknown strategy '{args.strategy}'")
        print(f"Available: {', '.join(registry.keys())}")
        sys.exit(1)

    strategy_info = registry[args.strategy]

    # --- Load config ---
    config = load_config(args.config)

    if args.start:
        config.backtest.start_date = args.start
    if args.end:
        config.backtest.end_date = args.end

    # --- Create timestamped output folder ---
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    folder_name = f"{args.strategy}_{timestamp}"
    if args.tag:
        folder_name = f"{args.strategy}_{args.tag}_{timestamp}"

    run_dir = Path("outputs/runs") / folder_name
    run_dir.mkdir(parents=True, exist_ok=True)

    # Point visualization output to this run's folder
    config.visualization.output_dir = run_dir

    # Strategy's timeframes are the single source of truth —
    # controls both which data gets loaded AND which charts get plotted
    timeframes = strategy_info.get("timeframes")
    if timeframes:
        config.visualization.timeframes = timeframes

    print(f"\n{'='*60}")
    print(f"  Strategy:  {args.strategy}")
    print(f"  Period:    {config.backtest.start_date} → {config.backtest.end_date}")
    print(f"  Output:    {run_dir}")
    print(f"{'='*60}\n")

    # --- Setup and run ---
    engine = BacktestEngine(config)
    engine.setup(
        strategy_info["class"],
        strategy_kwargs=dict(strategy_info["kwargs"]),
        timeframes=timeframes,
    )

    result = engine.run()

    # --- Trade plots ---
    if not args.no_plots and config.visualization.enabled and result.trades:
        print(f"\nGenerating trade charts for {len(result.trades)} trades...")
        plotter = TradePlotter(config, engine.data_manager)
        plotter.plot_all_trades(result.trades)

    # --- Summary ---
    print(f"\n{'='*60}")
    print(f"  📂 All outputs saved to: {run_dir.resolve()}")
    n_files = len(list(run_dir.iterdir()))
    print(f"     ({n_files} files: 1 report + {len(result.trades)} trade charts)")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
