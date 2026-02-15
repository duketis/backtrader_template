import zipfile
import csv
from datetime import datetime

# Check the new data for price continuity
zip_path = 'quantconnect_data/indices/dukascopy/tick/usatech/20250815_quote.zip'

with zipfile.ZipFile(zip_path, 'r') as zip_file:
    with zip_file.open('20250815_USATECHIDXUSD_tick_quote.csv') as csv_file:
        reader = csv.DictReader(csv_file.read().decode('utf-8').splitlines())
        
        # Store last price of each hour
        hourly_prices = {}
        total_ticks = 0
        
        for row in reader:
            total_ticks += 1
            timestamp = datetime.strptime(row['Time'], '%Y%m%d %H:%M:%S.%f')
            hour = timestamp.hour
            ask_price = float(row['Ask'])
            bid_price = float(row['Bid'])
            
            if hour not in hourly_prices:
                hourly_prices[hour] = {'first_ask': ask_price, 'first_bid': bid_price}
            
            hourly_prices[hour]['last_ask'] = ask_price
            hourly_prices[hour]['last_bid'] = bid_price

print(f'Total ticks processed: {total_ticks}')
print(f'Hours with data: {sorted(hourly_prices.keys())}')

# Check transitions
print('\n=== NEW BINARY API - Price Continuity Check ===')
max_gap = 0
for hour in sorted(hourly_prices.keys())[:-1]:
    if hour + 1 in hourly_prices:
        last_ask = hourly_prices[hour]['last_ask']
        last_bid = hourly_prices[hour]['last_bid']
        next_first_ask = hourly_prices[hour + 1]['first_ask']
        next_first_bid = hourly_prices[hour + 1]['first_bid']
        
        ask_gap = abs(next_first_ask - last_ask)
        bid_gap = abs(next_first_bid - last_bid)
        avg_gap = (ask_gap + bid_gap) / 2
        
        if avg_gap > max_gap:
            max_gap = avg_gap
        
        if avg_gap > 1.0:
            status = '❌ LARGE GAP'
        elif avg_gap > 0.1:
            status = '⚠️ Small gap'
        else:
            status = '✅ Good'
        
        print(f'Hour {hour:2d}→{hour+1:2d}: Ask gap={ask_gap:.3f}, Bid gap={bid_gap:.3f}, Avg={avg_gap:.3f} points {status}')

print(f'\n=== RESULTS ===')
print(f'Maximum gap found: {max_gap:.3f} points')
if max_gap < 0.1:
    print('🎉 EXCELLENT! Price continuity is perfect!')
elif max_gap < 1.0:
    print('✅ GOOD! Small gaps are normal market behavior')
else:
    print('❌ PROBLEM! Large gaps still exist')
