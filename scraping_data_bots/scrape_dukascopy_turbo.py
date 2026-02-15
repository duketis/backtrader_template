#!/usr/bin/env python3
"""
TURBO Multi-Currency/Indices Dukascopy tick data scraper using multi-threadi# Configuration
START_DATE = date(2010, 1, 1)  # Start from 2010 when data quality becomes excellent for forex
INDICES_START_DATE = date(2020, 1, 2)  # Indices data starts from Jan 2, 2020
END_DATE = date.today() - timedelta(days=1)  # End at yesterday (data has 1-day delay)

# TEST MODE: Testing with just a few days
START_DATE = date(2024, 9, 10)  # Test start
INDICES_START_DATE = date(2024, 9, 10)  # Test start for indices
END_DATE = date(2024, 9, 12)  # Just 3 days for testingoads tick data for multiple currency pairs and indices with 12x performance boost!
"""

import os
import csv
import requests
import time
import json
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
import zipfile
from typing import List, Tuple, Dict, Any
import logging
import argparse
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import lzma
import struct

# Currency pairs configuration
CURRENCY_PAIRS = {
    # Major Pairs
    "AUD-CAD": "audcad",
    "AUD-CHF": "audchf", 
    "AUD-JPY": "audjpy",
    "AUD-NZD": "audnzd",
    "AUD-SGD": "audsgd",
    "AUD-USD": "audusd",
    "CAD-CHF": "cadchf",
    "CAD-HKD": "cadhkd",
    "CAD-JPY": "cadjpy",
    "CHF-JPY": "chfjpy",
    "CHF-PLN": "chfpln",
    "CHF-SGD": "chfsgd",
    "EUR-AUD": "euraud",
    "EUR-CAD": "eurcad",
    "EUR-CHF": "eurchf",
    "EUR-CZK": "eurczk",
    "EUR-DKK": "eurdkk",
    "EUR-GBP": "eurgbp",
    "EUR-HKD": "eurhkd",
    "EUR-HUF": "eurhuf",
    "EUR-JPY": "eurjpy",
    "EUR-MXN": "eurmxn",
    "EUR-NOK": "eurnok",
    "EUR-NZD": "eurnzd",
    "EUR-PLN": "eurpln",
    "EUR-SEK": "eursek",
    "EUR-SGD": "eursgd",
    "EUR-TRY": "eurtry",
    "EUR-USD": "eurusd",
    "EUR-ZAR": "eurzar",
    "GBP-AUD": "gbpaud",
    "GBP-CAD": "gbpcad",
    "GBP-CHF": "gbpchf",
    "GBP-JPY": "gbpjpy",
    "GBP-NZD": "gbpnzd",
    "GBP-USD": "gbpusd",
    "HKD-JPY": "hkdjpy",
    "MXN-JPY": "mxnjpy",
    "NZD-CAD": "nzdcad",
    "NZD-CHF": "nzdchf",
    "NZD-JPY": "nzdjpy",
    "NZD-SGD": "nzdsgd",
    "NZD-USD": "nzdusd",
    "SGD-JPY": "sgdjpy",
    "TRY-JPY": "tryjpy",
    "USD-BRL": "usdbrl",
    "USD-CAD": "usdcad",
    "USD-CHF": "usdchf",
    "USD-CNH": "usdcnh",
    "USD-CZK": "usdczk",
    "USD-DKK": "usddkk",
    "USD-HKD": "usdhkd",
    "USD-HUF": "usdhuf",
    "USD-ILS": "usdils",
    "USD-JPY": "usdjpy",
    "USD-MXN": "usdmxn",
    "USD-NOK": "usdnok",
    "USD-PLN": "usdpln",
    "USD-RON": "usdron",
    "USD-SEK": "usdsek",
    "USD-SGD": "usdsgd",
    "USD-THB": "usdthb",
    "USD-TRY": "usdtry",
    "USD-ZAR": "usdzar",
    "XAG-USD": "xagusd",  # Silver
    "XAU-USD": "xauusd",  # Gold
    "ZAR-JPY": "zarjpy"
}

# Add indices configuration - ONLY the ones we actually want to scrape
# UPDATED: Use new binary API symbol format (no dots or dashes)
INDICES = {
    "usatech": "USATECHIDXUSD",  # NASDAQ 100 (Tech 100) - NEW BINARY FORMAT
    "us500": "USA500IDXUSD",     # S&P 500 - NEW BINARY FORMAT
}

# Combine all instruments
ALL_INSTRUMENTS = {**CURRENCY_PAIRS, **INDICES}

# Configuration
START_DATE = date(2020, 1, 1)  # Start from 2010 when data quality becomes excellent for forex
INDICES_START_DATE = date(2020, 1, 2)  # Indices data starts from Jan 2, 2020
END_DATE = date.today() - timedelta(days=1)  # End at yesterday (data has 1-day delay)

# TEST MODE: Uncomment these lines to test with just a few days
# START_DATE = date(2025, 8, 15)  # Test start - use recent date we know works
# INDICES_START_DATE = date(2025, 8, 15)  # Test start for indices
# END_DATE = date(2025, 8, 15)  # Just 1 day for testing
BASE_URL = "https://datafeed.dukascopy.com/datafeed"  # Binary .bi5 endpoint for forex
INDICES_BASE_URL = "https://datafeed.dukascopy.com/datafeed"  # NEW: Same binary endpoint for indices!
# JETTA_BASE_URL = "https://jetta.dukascopy.com/v1/ticks"  # OLD BROKEN JSON API - REMOVED
OUTPUT_DIR = "dukascopy_data"
QC_OUTPUT_DIR = "/Users/jonathan/Documents/personal/quantconnect-strategies/news_scraping_data_bot/quantconnect_data"  # Match your existing data folder structure

# Threading configuration - optimized from testing
MAX_THREADS = 12  # Optimal performance from tests
PROGRESS_REPORT_INTERVAL = 10  # Report progress every N days (reduced for better feedback)

# Setup logging
logging.basicConfig(
    level=logging.INFO,  # Back to INFO level for production
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('dukascopy_turbo_scraper.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Create thread-local storage for sessions
thread_local = threading.local()

def get_session():
    """Get a session for the current thread with connection pooling."""
    if not hasattr(thread_local, 'session'):
        thread_local.session = requests.Session()
        thread_local.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36',
            'Accept': '*/*',
            'Accept-Language': 'en-GB,en-US;q=0.9,en;q=0.8',
            'Referer': 'https://freeserv.dukascopy.com/',
            'Origin': 'https://freeserv.dukascopy.com',
            'Connection': 'keep-alive',
        })
    return thread_local.session


def setup_directories(symbol_file: str):
    """Create necessary directories for data storage for a specific instrument."""
    # Determine clean symbol name to match your existing structure
    if 'IDX' in symbol_file.upper():
        # Extract clean symbol from NEW format like "USATECHIDXUSD" -> "usatech"
        if "USATECH" in symbol_file:
            clean_symbol = "usatech"
        elif "USA500" in symbol_file:
            clean_symbol = "us500"
        elif "USA30" in symbol_file:
            clean_symbol = "us30"
        elif "DEU30" in symbol_file:
            clean_symbol = "de30"
        elif "GBR100" in symbol_file:
            clean_symbol = "uk100"
        else:
            clean_symbol = symbol_file.split('.')[0].lower()
        
        # Create indices structure: quantconnect_data/indices/dukascopy/tick/usatech/
        qc_dir = os.path.join(QC_OUTPUT_DIR, "indices", "dukascopy", "tick", clean_symbol)
    else:
        # Forex structure: quantconnect_data/forex/dukascopy/tick/usdjpy/
        clean_symbol = symbol_file
        qc_dir = os.path.join(QC_OUTPUT_DIR, "forex", "dukascopy", "tick", clean_symbol)
    
    # Create directory structure
    directories = [OUTPUT_DIR, QC_OUTPUT_DIR, qc_dir]
    for directory in directories:
        os.makedirs(directory, exist_ok=True)
    return qc_dir


def download_hour_data_indices_binary(symbol_file: str, year: int, month: int, day: int, hour: int) -> Tuple[int, List[Tuple[datetime, float, float, int, int]]]:
    """
    Download tick data for indices using the NEW working binary API (same format as forex).
    
    Args:
        symbol_file: Instrument identifier (e.g., 'USATECHIDXUSD')
        year: Year (e.g., 2025)
        month: Month (0-11, zero-based for URL!)
        day: Day (1-31)
        hour: Hour (0-23)
    
    Returns:
        Tuple of (hour, ticks_list) or (hour, []) if failed
    """
    # Build URL for the NEW binary API - same format as forex but different symbol format
    url = f"{INDICES_BASE_URL}/{symbol_file}/{year}/{month:02d}/{day:02d}/{hour:02d}h_ticks.bi5"
    
    session = get_session()
    
    try:
        response = session.get(url, timeout=30)
        logger.debug(f"Indices binary API response for {symbol_file} hour {hour}: HTTP {response.status_code}")
        
        if response.status_code != 200:
            logger.debug(f"No data available for {symbol_file} {year}-{month:02d}-{day:02d} hour {hour} (HTTP {response.status_code})")
            return hour, []
        
        # Parse binary .bi5 data (same format as forex)
        try:
            # Decompress LZMA data
            decompressed_data = lzma.decompress(response.content)
            logger.debug(f"Successfully decompressed {len(decompressed_data)} bytes for {symbol_file} hour {hour}")
        except Exception as e:
            logger.debug(f"Failed to decompress {symbol_file} hour {hour}: {e}")
            return hour, []
        
        # Parse tick data
        ticks = []
        try:
            # Each tick is 20 bytes: timestamp(4) + ask(4) + bid(4) + ask_vol(4) + bid_vol(4)
            tick_count = len(decompressed_data) // 20
            logger.debug(f"Processing {tick_count} ticks for {symbol_file} hour {hour}")
            
            for i in range(tick_count):
                try:
                    # Extract 20 bytes for this tick
                    offset = i * 20
                    tick_data = decompressed_data[offset:offset+20]
                    
                    # Unpack binary data (big-endian format)
                    timestamp_ms, ask_int, bid_int, ask_volume, bid_volume = struct.unpack('>IIIII', tick_data)
                    
                    # Convert to actual timestamp (timestamp is milliseconds since hour start)
                    hour_start_timestamp = datetime(year, month + 1, day, hour, 0, 0, tzinfo=timezone.utc).timestamp()
                    actual_timestamp = hour_start_timestamp + (timestamp_ms / 1000.0)
                    tick_time = datetime.fromtimestamp(actual_timestamp, tz=timezone.utc)
                    
                    # Convert prices - indices and forex use different scales!
                    if 'IDX' in symbol_file.upper():
                        # Indices: divide by 1000 (not 100000 like forex)
                        ask_price = ask_int / 1000.0
                        bid_price = bid_int / 1000.0
                    else:
                        # Forex: divide by 100000 (standard forex scale)
                        ask_price = ask_int / 100000.0
                        bid_price = bid_int / 100000.0
                    
                    ticks.append((tick_time, ask_price, bid_price, ask_volume, bid_volume))
                    
                except Exception as e:
                    logger.debug(f"Error processing tick {i} for {symbol_file}: {e}")
                    continue
            
        except Exception as e:
            logger.debug(f"Error parsing binary tick data for {symbol_file}: {e}")
            return hour, []
        
        logger.debug(f"Successfully parsed {len(ticks)} ticks for {symbol_file} hour {hour}")
        return hour, ticks
        
    except Exception as e:
        logger.debug(f"Failed to download {symbol_file} hour {hour} from binary API: {e}")
        return hour, []


def download_hour_data(symbol_file: str, year: int, month: int, day: int, hour: int) -> Tuple[int, List[Tuple[datetime, float, float, int, int]]]:
    """
    Download and parse tick data for a specific hour.
    Uses binary .bi5 format for forex and JSON API for indices.
    
    Args:
        symbol_file: Instrument identifier (e.g., 'usdjpy' or 'USATECH.IDX-USD')
        year: Year (e.g., 2015)
        month: Month (0-11 for binary API, 1-12 for JSON API)
        day: Day (1-31)
        hour: Hour (0-23)
    
    Returns:
        Tuple of (hour, ticks_list) or (hour, []) if failed
    """
    # Check if this is an index (uses NEW binary API) or forex (uses standard binary API)
    if 'IDX' in symbol_file.upper():
        # This is an index, use NEW binary API with 0-based month (same as forex)
        return download_hour_data_indices_binary(symbol_file, year, month, day, hour)
    else:
        # This is forex, use standard binary API with 0-based month
        return download_hour_data_binary(symbol_file, year, month, day, hour)


def download_hour_data_binary(symbol_file: str, year: int, month: int, day: int, hour: int) -> Tuple[int, List[Tuple[datetime, float, float, int, int]]]:
    """
    Download and parse .bi5 tick data for forex pairs using binary format.
    
    Args:
        symbol_file: Instrument identifier (e.g., 'usdjpy')
        year: Year (e.g., 2015)
        month: Month (0-11, zero-based for URL!)
        day: Day (1-31)
        hour: Hour (0-23)
    
    Returns:
        Tuple of (hour, ticks_list) or (hour, []) if failed
    """
    # Convert symbol_file to uppercase for URL
    symbol_upper = symbol_file.upper()
    
    # Build URL for .bi5 file
    bi5_filename = f"{hour:02d}h_ticks.bi5"
    url = f"{BASE_URL}/{symbol_upper}/{year}/{month:02d}/{day:02d}/{bi5_filename}"
    
    logger.debug(f"Attempting to download: {url}")
    
    session = get_session()
    
    try:
        response = session.get(url, timeout=30)
        logger.debug(f"Response status for {symbol_file} hour {hour}: {response.status_code}")
        
        if response.status_code != 200:
            logger.debug(f"No data available for {symbol_file} {year}-{month+1:02d}-{day:02d} hour {hour} (HTTP {response.status_code})")
            return hour, []
        
        # Decompress .bi5 file
        try:
            decompressed = lzma.decompress(response.content)
            logger.debug(f"Successfully decompressed {len(decompressed)} bytes for {symbol_file} hour {hour}")
        except Exception as e:
            logger.debug(f"Error decompressing .bi5 file for {symbol_file} hour {hour}: {e}")
            return hour, []
        
        if not decompressed:
            logger.debug(f"Empty decompressed data for {symbol_file} hour {hour}")
            return hour, []
        
        # Parse binary tick data
        TICK_SIZE = 20
        ticks = []
        
        logger.debug(f"Processing {len(decompressed)} bytes of tick data for {symbol_file} hour {hour}")
        
        for i in range(0, len(decompressed), TICK_SIZE):
            chunk = decompressed[i:i+TICK_SIZE]
            if len(chunk) < TICK_SIZE:
                continue
                
            try:
                # Dukascopy .bi5 format: time_offset(4), ask(4), bid(4), ask_vol(4), bid_vol(4) - all big endian
                time_offset_ms, ask, bid, ask_vol, bid_vol = struct.unpack('>IIIII', chunk[:20])
                
                # Calculate actual timestamp: start of hour + offset
                # month is 0-indexed for URL, but datetime needs 1-indexed month
                hour_start = datetime(year, month + 1, day, hour, 0, 0, tzinfo=timezone.utc)
                tick_time = hour_start + timedelta(milliseconds=time_offset_ms)
                
                # Convert prices based on instrument type
                if symbol_file.endswith('.idx'):
                    # Indices: typically 2 decimal places (divide by 100)
                    bid_price = bid / 100.0
                    ask_price = ask / 100.0
                elif symbol_file.endswith('jpy'):
                    # JPY pairs: divide by 1000 (3 decimal places)
                    bid_price = bid / 1000.0
                    ask_price = ask / 1000.0
                elif symbol_file.startswith('xau') or symbol_file.startswith('xag'):
                    # Precious metals: divide by 1000 (3 decimal places, like JPY)
                    bid_price = bid / 1000.0
                    ask_price = ask / 1000.0
                else:
                    # Non-JPY pairs: divide by 100000 (5 decimal places)
                    bid_price = bid / 100000.0
                    ask_price = ask / 100000.0
                
                ticks.append((tick_time, ask_price, bid_price, ask_vol, bid_vol))
                
            except Exception as e:
                logger.debug(f"Error unpacking tick at byte {i} for {symbol_file}: {e}")
                continue
        
        logger.debug(f"Successfully parsed {len(ticks)} ticks for {symbol_file} hour {hour}")
        return hour, ticks
        
    except Exception as e:
        logger.debug(f"Failed to download {symbol_file} hour {hour}: {e}")
        return hour, []


def milliseconds_since_midnight(dt: datetime) -> int:
    """Convert datetime to milliseconds since midnight."""
    midnight = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    return int((dt - midnight).total_seconds() * 1000)


def save_ticks_to_quantconnect_format(ticks: List[Tuple[datetime, float, float, float, float]], 
                                    target_date: date, symbol_file: str, qc_dir: str):
    """
    Save ticks in QuantConnect format.
    
    Format: Time,Bid Price,Ask Price
    Where Time is milliseconds since midnight
    """
    if not ticks:
        return
    
    # Filter ticks for the target date
    date_ticks = [tick for tick in ticks if tick[0].date() == target_date]
    
    if not date_ticks:
        return
    
    # Sort by timestamp
    date_ticks.sort(key=lambda x: x[0])
    
    # Create filename in QuantConnect format
    date_str = target_date.strftime("%Y%m%d")
    filename = f"{date_str}_quote.zip"
    
    # Clean symbol for CSV filename to match your existing format
    if '-' in symbol_file and 'IDX' in symbol_file.upper():
        if "USATECH" in symbol_file:
            clean_symbol = "nas100"
        elif "USA500" in symbol_file:
            clean_symbol = "us500"
        else:
            clean_symbol = symbol_file.split('.')[0].lower()
    else:
        clean_symbol = symbol_file.replace('.idx', '').replace('.i', '')
    csv_filename = f"{date_str}_{clean_symbol}_tick_quote.csv"
    
    filepath = os.path.join(qc_dir, filename)
    
    # Create CSV content with Backtrader-compatible format
    csv_rows = []
    
    # Add header row for Backtrader compatibility (OHLC format using mid-price for ticks)
    csv_rows.append(['datetime', 'open', 'high', 'low', 'close', 'volume'])
    
    # Determine decimal places based on instrument type
    if 'IDX' in symbol_file.upper():
        decimal_places = 2  # Indices
    else:
        decimal_places = 5  # Forex
    
    for tick_timestamp, ask_price, bid_price, ask_volume, bid_volume in date_ticks:
        # Format datetime as ISO string for Backtrader compatibility
        datetime_str = tick_timestamp.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]  # Remove last 3 digits for milliseconds
        
        # Calculate mid-price for tick data (since ticks don't have OHLC, we use mid-price for all)
        mid_price = (ask_price + bid_price) / 2.0
        
        # Use total volume (bid + ask volumes)
        total_volume = ask_volume + bid_volume
        
        csv_rows.append([
            datetime_str,
            f"{mid_price:.{decimal_places}f}",  # open = mid_price
            f"{mid_price:.{decimal_places}f}",  # high = mid_price
            f"{mid_price:.{decimal_places}f}",  # low = mid_price  
            f"{mid_price:.{decimal_places}f}",  # close = mid_price
            total_volume
        ])
    
    # Write to temporary CSV file
    temp_csv_path = os.path.join(qc_dir, csv_filename)
    with open(temp_csv_path, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerows(csv_rows)
    
    # Create ZIP file
    with zipfile.ZipFile(filepath, 'w', zipfile.ZIP_DEFLATED) as zipf:
        zipf.write(temp_csv_path, csv_filename)
    
    # Remove temporary CSV file
    os.remove(temp_csv_path)


def get_last_processed_date(qc_dir: str) -> date:
    """Get the last date that was successfully processed for an instrument."""
    try:
        if not os.path.exists(qc_dir):
            return START_DATE
        
        # Look for the latest ZIP file
        zip_files = [f for f in os.listdir(qc_dir) if f.endswith("_quote.zip")]
        if not zip_files:
            return START_DATE
        
        # Extract dates from filenames and find the latest
        dates = []
        for zip_file in zip_files:
            try:
                date_str = zip_file[:8]  # YYYYMMDD
                file_date = datetime.strptime(date_str, "%Y%m%d").date()
                dates.append(file_date)
            except ValueError:
                continue
        
        if dates:
            last_date = max(dates)
            return last_date + timedelta(days=1)  # Start from next day
        else:
            return START_DATE
            
    except Exception as e:
        logger.error(f"Error getting last processed date: {e}")
        return START_DATE


def scrape_day_data_turbo(symbol: str, symbol_file: str, target_date: date, qc_dir: str) -> bool:
    """
    Scrape all tick data for a specific day using TURBO THREADING!
    
    Args:
        symbol: Instrument symbol with dash (e.g., 'USD-JPY' or 'NAS100') - for display only
        symbol_file: Instrument identifier for file naming (e.g., 'usdjpy' or 'USATECH.IDX-USD')
        target_date: The date to scrape data for
        qc_dir: QuantConnect directory for this instrument
    
    Returns:
        True if successful, False otherwise
    """
    logger.info(f"📅 {symbol}: Processing {target_date}")  # Show immediate progress
    
    year = target_date.year
    month = target_date.month - 1  # Convert to 0-based for URL (will be converted back for JSON API)
    day = target_date.day
    
    all_ticks = []
    
    # Use ThreadPoolExecutor for concurrent hour downloads
    with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
        # Submit all 24 hours for download
        future_to_hour = {
            executor.submit(download_hour_data, symbol_file, year, month, day, hour): hour 
            for hour in range(24)
        }
        
        # Collect results in CHRONOLOGICAL ORDER (not random completion order)
        hour_results = {}
        successful_hours = 0
        
        for future in as_completed(future_to_hour):
            hour = future_to_hour[future]
            try:
                hour_num, hour_ticks = future.result()
                hour_results[hour] = hour_ticks  # Store by hour number
                
                if hour_ticks:
                    successful_hours += 1
                        
            except Exception as e:
                logger.error(f"Error processing {symbol} hour {hour} for {target_date}: {e}")
                hour_results[hour] = []  # Empty list for failed hours
                continue
        
        # NOW add ticks in chronological order (0, 1, 2, ..., 23)
        for hour in range(24):
            if hour in hour_results and hour_results[hour]:
                all_ticks.extend(hour_results[hour])
    
    if all_ticks:
        # Sort ticks by timestamp
        all_ticks.sort(key=lambda x: x[0])
        
        # Save in QuantConnect format
        save_ticks_to_quantconnect_format(all_ticks, target_date, symbol_file, qc_dir)
        
        logger.info(f"✅ {symbol}: Saved {len(all_ticks):,} ticks for {target_date}")
        return True
    else:
        logger.info(f"⚠️ {symbol}: No tick data found for {target_date}")
        return False


def scrape_instrument(symbol: str, symbol_file: str):
    """Scrape all data for a specific instrument using TURBO mode."""
    logger.info(f"🚀 Starting TURBO {symbol} ({symbol_file.upper()}) scraper")
    
    # Setup directories for this instrument
    qc_dir = setup_directories(symbol_file)
    
    # Determine start date based on instrument type
    is_index = '-' in symbol_file and 'IDX' in symbol_file.upper()
    instrument_start_date = INDICES_START_DATE if is_index else START_DATE
    
    # Get starting date for this instrument (either last processed or instrument start date)
    current_date = get_last_processed_date(qc_dir)
    if current_date < instrument_start_date:
        current_date = instrument_start_date
        logger.info(f"▶️ {symbol}: Starting from {instrument_start_date} (instrument data start)")
    else:
        logger.info(f"▶️ {symbol}: Resuming from {current_date}")
    
    # For indices, check if data exists for the start date
    if is_index:
        logger.info(f"🔍 {symbol}: Checking data availability from {current_date}...")
        
        # Test a few dates to see when data starts (only if starting from the beginning)
        if current_date == instrument_start_date:
            test_dates = [current_date, date(2020, 6, 1), date(2021, 1, 1)]
            data_found = False
            
            for test_date in test_dates:
                if test_date > END_DATE:
                    continue
                logger.info(f"🔍 {symbol}: Testing data availability for {test_date}")
                if scrape_day_data_turbo(symbol, symbol_file, test_date, qc_dir):
                    current_date = test_date
                    data_found = True
                    logger.info(f"✅ {symbol}: Found data starting from {test_date}")
                    break
            
            if not data_found:
                logger.warning(f"⚠️ {symbol}: No data found for any test dates. Continuing anyway...")
    
    total_days = 0
    successful_days = 0
    failed_days = 0
    start_time = time.time()
    
    # Process each day
    while current_date <= END_DATE:
        try:
            success = scrape_day_data_turbo(symbol, symbol_file, current_date, qc_dir)
            total_days += 1
            
            if success:
                successful_days += 1
            else:
                failed_days += 1
            
            # Progress report every N days
            if total_days % PROGRESS_REPORT_INTERVAL == 0:
                elapsed = time.time() - start_time
                days_remaining = (END_DATE - current_date).days
                avg_time_per_day = elapsed / total_days
                eta_seconds = days_remaining * avg_time_per_day
                eta_hours = eta_seconds / 3600
                
                logger.info(f"📊 {symbol}: {total_days} days processed ({successful_days} successful, {failed_days} failed)")
                logger.info(f"⏱️ {symbol}: ETA {eta_hours:.1f}h remaining at {avg_time_per_day:.2f}s/day")
            
        except Exception as e:
            logger.error(f"❌ {symbol}: Failed to process {current_date}: {e}")
            failed_days += 1
        
        current_date += timedelta(days=1)
    
    # Final summary for this instrument
    elapsed = time.time() - start_time
    logger.info(f"🎉 {symbol} completed! {successful_days}/{total_days} days successful in {elapsed/3600:.2f}h")


def test_single_day(symbol: str, symbol_file: str, test_date: date = date(2024, 1, 15)) -> bool:
    """Test downloading a single day to check if URLs and format are correct."""
    logger.info(f"🔍 Testing {symbol} ({symbol_file}) for {test_date}")
    
    year = test_date.year
    month = test_date.month - 1  # Convert to 0-based for binary API (will be converted back for JSON API)
    day = test_date.day
    
    # Try to download just one hour to test the format
    hour_num, hour_ticks = download_hour_data(symbol_file, year, month, day, 12)  # Test noon
    
    if hour_ticks:
        logger.info(f"✅ Test successful! Found {len(hour_ticks)} ticks for {symbol} at hour 12")
        return True
    else:
        logger.warning(f"⚠️ Test failed! No ticks found for {symbol}")
        
        # For indices, try different identifier variations using NEW binary API
        if 'IDX' in symbol_file.upper():
            # Test alternative index identifiers with NEW binary format
            test_identifiers = []
            if "USATECH" in symbol_file:
                test_identifiers = ["USATECHIDXUSD", "NASDAQIDXUSD", "NAS100IDXUSD"]
            elif "USA500" in symbol_file:
                test_identifiers = ["USA500IDXUSD", "SPX500IDXUSD", "SP500IDXUSD"]
            
            session = get_session()
            for test_id in test_identifiers:
                test_url = f"{INDICES_BASE_URL}/{test_id}/{year}/{month:02d}/{day:02d}/12h_ticks.bi5"
                try:
                    response = session.get(test_url, timeout=10)
                    logger.debug(f"Testing binary URL: {test_url} -> HTTP {response.status_code}")
                    if response.status_code == 200:
                        logger.info(f"✅ Found working identifier: {test_id}")
                        break
                except Exception as e:
                    logger.debug(f"Error testing URL {test_url}: {e}")
        
        return False


def main():
    """Main scraping function with TURBO POWER!"""
    parser = argparse.ArgumentParser(description='TURBO Multi-Currency/Indices Dukascopy Tick Data Scraper')
    parser.add_argument('--pairs', nargs='+', help='Specific instruments to scrape (e.g., USD-JPY NAS100 US500)')
    parser.add_argument('--all', action='store_true', help='Scrape all available instruments')
    parser.add_argument('--forex-only', action='store_true', help='Scrape only forex pairs')
    parser.add_argument('--indices-only', action='store_true', help='Scrape only indices')
    parser.add_argument('--list', action='store_true', help='List all available instruments')
    parser.add_argument('--test', action='store_true', help='Test download for a single day before full scrape')
    parser.add_argument('--threads', type=int, default=12, help='Number of threads (default: 12)')
    
    args = parser.parse_args()
    
    # Update thread count if specified
    global MAX_THREADS
    MAX_THREADS = args.threads
    
    if args.list:
        print("\nAvailable forex pairs:")
        for symbol, file_name in CURRENCY_PAIRS.items():
            print(f"  {symbol} -> {file_name}")
        print("\nAvailable indices:")
        for symbol, file_name in INDICES.items():
            print(f"  {symbol} -> {file_name}")
        return
    
    if args.test:
        print("\n🔍 Testing mode - checking if URLs work...")
        # Test both forex (known working) and indices
        test_pairs = [
            ("usdjpy", "usdjpy"),              # Known working forex pair
            ("usatech", "USATECH.IDX-USD"),    # NASDAQ 100 using new Jetta API
            ("us500", "USA500.IDX-USD")        # S&P 500 using new Jetta API
        ]
        for symbol, symbol_file in test_pairs:
            test_single_day(symbol, symbol_file)
        return
    
    # Determine which instruments to scrape
    if args.all:
        pairs_to_scrape = list(ALL_INSTRUMENTS.items())
        logger.info(f"🌍 TURBO scraping ALL {len(pairs_to_scrape)} instruments!")
    elif args.forex_only:
        pairs_to_scrape = list(CURRENCY_PAIRS.items())
        logger.info(f"💱 TURBO scraping {len(pairs_to_scrape)} forex pairs only")
    elif args.indices_only:
        pairs_to_scrape = list(INDICES.items())
        logger.info(f"📈 TURBO scraping {len(pairs_to_scrape)} indices only")
    elif args.pairs:
        pairs_to_scrape = []
        for pair in args.pairs:
            if pair in ALL_INSTRUMENTS:
                pairs_to_scrape.append((pair, ALL_INSTRUMENTS[pair]))
            else:
                logger.error(f"❌ Unknown instrument: {pair}")
                logger.info(f"💡 Try: {', '.join(list(ALL_INSTRUMENTS.keys())[:5])}...")
                return
        logger.info(f"🎯 TURBO scraping {len(pairs_to_scrape)} selected instruments")
    else:
        # Default to usatech and us500 if no arguments
        pairs_to_scrape = [("usatech", "USATECH.IDX-USD"), ("us500", "USA500.IDX-USD")]
        logger.info("🎯 No instruments specified, defaulting to usatech and us500")
    
    logger.info(f"📅 Date range: {START_DATE} to {END_DATE}")
    logger.info(f"🧵 Using {MAX_THREADS} threads for MAXIMUM SPEED!")
    logger.info(f"⚡ Expected speedup: ~12x faster than sequential!")
    
    # Scrape each instrument
    for symbol, symbol_file in pairs_to_scrape:
        try:
            scrape_instrument(symbol, symbol_file)
        except KeyboardInterrupt:
            logger.info(f"⚠️ TURBO scraping interrupted by user during {symbol}")
            break
        except Exception as e:
            logger.error(f"❌ Failed to TURBO scrape {symbol}: {e}")
            continue
    
    logger.info("🎉 TURBO multi-instrument scraping completed!")


if __name__ == "__main__":
    main()