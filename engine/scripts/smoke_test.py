"""
Manual smoke test: runs the dummy strategy on real data.

Produces:
  1. Console output with every trade logged
  2. Per-trade summary table (entry/exit prices, P&L, SL/TP, timing)
  3. Plotly HTML charts for visual inspection (saved to outputs/runs/)

Usage:
    cd engine/
    python scripts/smoke_test.py

After running, open the HTML files in a browser and verify:
  - Entry/exit markers appear at correct chart positions
  - SL/TP horizontal lines are at the right levels
  - No trades occur outside NY session (08:00-16:30 ET)
  - P&L numbers are reasonable given SL/TP distances
  - Position rectangles (green=win, red=loss) look right
"""

import sys
from pathlib import Path

# Add engine root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import load_config
from core.types import Timeframe
from execution.engine import BacktestEngine
from strategy.dummy_strategy import DummyStrategy
from visualization.trade_plotter import TradePlotter


def main():
    # ---- 1. Load config and run backtest ----
    config = load_config("config/backtest.yaml")

    # Use a short date range for quick smoke test (1 month of data)
    config.backtest.start_date = "2024-01-01"
    config.backtest.end_date = "2024-02-01"

    engine = BacktestEngine(config)
    engine.setup(
        DummyStrategy,
        strategy_kwargs={
            "buy_every_n_bars": 500,   # ~8 hrs of 1-min bars between trades
            "max_trades": 6,           # Keep it small for inspection
        },
        timeframes=[Timeframe.ONE_MIN],  # Just 1-min for speed
    )

    result = engine.run()

    # ---- 2. Print detailed trade table ----
    print("\n" + "=" * 100)
    print("DETAILED TRADE TABLE FOR MANUAL INSPECTION")
    print("=" * 100)
    print(
        f"{'#':>3} {'Dir':>5} {'Entry Time':>20} {'Exit Time':>20} "
        f"{'Entry':>10} {'Exit':>10} {'SL':>10} {'TP':>10} "
        f"{'Gross':>10} {'Net':>10} {'Costs':>8} {'Size':>8} {'Winner':>7}"
    )
    print("-" * 100)

    for t in result.trades:
        entry_str = t.entry_time.strftime("%Y-%m-%d %H:%M") if t.entry_time else "N/A"
        exit_str = t.exit_time.strftime("%Y-%m-%d %H:%M") if t.exit_time else "OPEN"
        sl_str = f"{t.stop_loss:.2f}" if t.stop_loss else "None"
        tp_str = f"{t.take_profit:.2f}" if t.take_profit else "None"
        winner_str = "✅ WIN" if t.is_winner else "❌ LOSS"
        print(
            f"{t.trade_id:>3} {t.direction.value:>5} {entry_str:>20} {exit_str:>20} "
            f"{t.entry_price:>10.2f} {t.exit_price:>10.2f} {sl_str:>10} {tp_str:>10} "
            f"{t.gross_pnl:>10.2f} {t.net_pnl:>10.2f} {t.total_costs:>8.2f} "
            f"{t.size:>8.4f} {winner_str:>7}"
        )

    # ---- 3. Session filter check ----
    print("\n" + "=" * 60)
    print("SESSION FILTER CHECK")
    print("=" * 60)
    session_violations = []
    for t in result.trades:
        # Entry time should be in NY session (08:00-16:30 ET)
        # The entry_time is UTC — convert to check
        import pytz
        ny = pytz.timezone("America/New_York")
        entry_ny = t.entry_time.replace(tzinfo=pytz.UTC).astimezone(ny)
        hour, minute = entry_ny.hour, entry_ny.minute
        time_decimal = hour + minute / 60.0
        in_session = 8.0 <= time_decimal <= 16.5
        status = "✅ OK" if in_session else "❌ VIOLATION"
        print(f"  Trade #{t.trade_id}: entry {entry_ny.strftime('%H:%M')} ET → {status}")
        if not in_session:
            session_violations.append(t.trade_id)

    if session_violations:
        print(f"\n⚠️  SESSION VIOLATIONS: Trades {session_violations} entered outside NY hours!")
    else:
        print(f"\n✅ All {len(result.trades)} trades entered within NY session hours.")

    # ---- 4. Sanity checks ----
    print("\n" + "=" * 60)
    print("SANITY CHECKS")
    print("=" * 60)

    for t in result.trades:
        issues = []

        # Check exit price is between SL and TP (roughly)
        if t.stop_loss and t.take_profit:
            if t.direction.value == "long":
                if t.exit_price < t.stop_loss - 5:
                    issues.append(f"exit {t.exit_price:.2f} below SL {t.stop_loss:.2f}")
                if t.exit_price > t.take_profit + 5:
                    issues.append(f"exit {t.exit_price:.2f} above TP {t.take_profit:.2f}")
            else:
                if t.exit_price > t.stop_loss + 5:
                    issues.append(f"exit {t.exit_price:.2f} above SL {t.stop_loss:.2f}")
                if t.exit_price < t.take_profit - 5:
                    issues.append(f"exit {t.exit_price:.2f} below TP {t.take_profit:.2f}")

        # Check P&L direction matches price movement
        if t.direction.value == "long":
            expected_positive = t.exit_price > t.entry_price
        else:
            expected_positive = t.exit_price < t.entry_price

        if expected_positive and t.gross_pnl < 0:
            issues.append(f"price moved favorably but gross_pnl={t.gross_pnl:.2f} negative")
        if not expected_positive and t.gross_pnl > 0:
            issues.append(f"price moved adversely but gross_pnl={t.gross_pnl:.2f} positive")

        # Check costs are non-negative
        if t.total_costs < 0:
            issues.append(f"total_costs={t.total_costs:.2f} is negative")

        status = "✅ OK" if not issues else "⚠️  " + "; ".join(issues)
        print(f"  Trade #{t.trade_id}: {status}")

    # ---- 5. Generate visualizations ----
    if result.trades:
        print("\n" + "=" * 60)
        print("GENERATING VISUALIZATIONS")
        print("=" * 60)

        # Need to reload data into DataManager with timeframes for plotting
        plotter = TradePlotter(config, engine.data_manager)

        # Only plot with 1-min since that's what we loaded
        viz_timeframes = [Timeframe.ONE_MIN]

        for trade in result.trades:
            plotter.plot_trade(
                trade,
                timeframes=viz_timeframes,
                save=True,
                show=False,
            )
            print(f"  Trade #{trade.trade_id}: saved")

        output_dir = config.visualization.output_dir
        print(f"\n📂 Charts saved to: {output_dir.resolve()}")
        print(f"   Open in browser to inspect visually.")
    else:
        print("\n⚠️  No trades produced — check the configuration!")


if __name__ == "__main__":
    main()
