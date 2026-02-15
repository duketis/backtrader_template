"""
Tick data preprocessor: converts raw daily zip files to Parquet.

This is a one-time (or periodic) script that:
1. Reads all daily tick zip files from the raw data directory
2. Extracts and parses the CSV tick data
3. Resamples ticks into 1min, 5min, 1hr, 4hr OHLC bars
4. Saves each timeframe as a single Parquet file for fast loading

Usage:
    python -m scripts.preprocess --config config/backtest.yaml

The output Parquet files are the foundation of all backtesting.
This decouples the slow I/O (decompressing 1,776 zips) from the
fast iteration loop (running backtests).
"""

import argparse
import sys
import zipfile
from io import StringIO
from pathlib import Path
from typing import List

import pandas as pd

# Add project root to path so we can import core modules
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import load_config
from core.types import Timeframe


def extract_tick_csv_from_zip(zip_path: Path) -> pd.DataFrame:
    """Extract and parse the CSV file from a single daily tick zip.

    Args:
        zip_path: Path to the zip file (e.g., 20200102_quote.zip).

    Returns:
        DataFrame with columns: datetime (index), open, high, low, close.
        Volume is dropped as it's unreliable in this dataset.
    """
    with zipfile.ZipFile(zip_path, "r") as zf:
        # Each zip contains exactly one CSV file
        csv_filename = zf.namelist()[0]
        with zf.open(csv_filename) as csv_file:
            content = csv_file.read().decode("utf-8")

    df = pd.read_csv(
        StringIO(content),
        parse_dates=["datetime"],
        index_col="datetime",
    )

    # Drop the volume column — it's not real volume (provider artifact)
    if "volume" in df.columns:
        df = df.drop(columns=["volume"])

    return df


def load_all_ticks(tick_data_dir: Path) -> pd.DataFrame:
    """Load and concatenate all daily tick zips into a single DataFrame.

    Args:
        tick_data_dir: Directory containing *_quote.zip files.

    Returns:
        Single DataFrame of all tick data, sorted by datetime index.
    """
    zip_files = sorted(tick_data_dir.glob("*_quote.zip"))
    if not zip_files:
        raise FileNotFoundError(
            f"No *_quote.zip files found in {tick_data_dir}"
        )

    print(f"Found {len(zip_files)} daily tick files to process")

    frames: List[pd.DataFrame] = []
    for i, zip_path in enumerate(zip_files):
        if (i + 1) % 100 == 0 or i == 0:
            print(f"  Processing {i + 1}/{len(zip_files)}: {zip_path.name}")
        try:
            df = extract_tick_csv_from_zip(zip_path)
            frames.append(df)
        except Exception as e:
            print(f"  WARNING: Failed to process {zip_path.name}: {e}")
            continue

    print(f"Concatenating {len(frames)} daily frames...")
    ticks = pd.concat(frames, verify_integrity=False)
    ticks = ticks.sort_index()

    # Since OHLC are identical on each tick, keep only 'close' as 'price'
    # but preserve the OHLC column names for compatibility
    print(f"Total ticks loaded: {len(ticks):,}")
    return ticks


def resample_ticks(ticks: pd.DataFrame, timeframe: Timeframe) -> pd.DataFrame:
    """Resample tick data into OHLC bars at the given timeframe.

    Args:
        ticks: Tick DataFrame with datetime index and OHLC columns.
        timeframe: Target timeframe for resampling.

    Returns:
        OHLC DataFrame at the specified timeframe.
    """
    freq = timeframe.pandas_freq

    ohlc = ticks["close"].resample(freq).ohlc()
    ohlc.columns = ["open", "high", "low", "close"]

    # Drop bars with no ticks (NaN rows)
    ohlc = ohlc.dropna()

    return ohlc


def save_parquet(df: pd.DataFrame, output_path: Path, timeframe_name: str) -> None:
    """Save a DataFrame to Parquet format.

    Args:
        df: DataFrame to save.
        output_path: Full path for the .parquet file.
        timeframe_name: Name for logging purposes.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(output_path, engine="pyarrow")
    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"  Saved {timeframe_name}: {len(df):,} bars ({size_mb:.1f} MB) → {output_path}")


def preprocess(config_path: str) -> None:
    """Run the full preprocessing pipeline.

    1. Load all tick data from zips
    2. Save raw ticks as Parquet (for tick-level backtesting)
    3. Resample to each configured timeframe and save as Parquet

    Args:
        config_path: Path to backtest.yaml config file.
    """
    config = load_config(config_path)

    tick_dir = config.data.tick_data_dir
    parquet_dir = config.data.parquet_dir

    print("=" * 60)
    print("Backtest Engine — Data Preprocessor")
    print("=" * 60)
    print(f"Instrument:   {config.data.instrument}")
    print(f"Tick source:  {tick_dir}")
    print(f"Parquet dest: {parquet_dir}")
    print(f"Timeframes:   {[tf.value for tf in config.data.timeframes]}")
    print("=" * 60)

    # Step 1: Load all tick data
    print("\n[1/3] Loading tick data from zip files...")
    ticks = load_all_ticks(tick_dir)

    # Step 2: Save raw ticks as Parquet
    print("\n[2/3] Saving tick data as Parquet...")
    tick_path = parquet_dir / f"{config.data.instrument}_tick.parquet"
    save_parquet(ticks, tick_path, "tick")

    # Step 3: Resample and save each timeframe
    print("\n[3/3] Resampling to configured timeframes...")
    for tf in config.data.timeframes:
        print(f"\n  Resampling to {tf.display_name}...")
        ohlc = resample_ticks(ticks, tf)
        output_path = parquet_dir / f"{config.data.instrument}_{tf.value}.parquet"
        save_parquet(ohlc, output_path, tf.display_name)

    print("\n" + "=" * 60)
    print("Preprocessing complete!")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Preprocess tick data: zip files → Parquet"
    )
    parser.add_argument(
        "--config",
        type=str,
        default="config/backtest.yaml",
        help="Path to backtest config YAML (default: config/backtest.yaml)",
    )
    args = parser.parse_args()
    preprocess(args.config)


if __name__ == "__main__":
    main()
