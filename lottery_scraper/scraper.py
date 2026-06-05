import os
import json
import csv
import datetime
import traceback

def get_quarter(date_obj):
    return (date_obj.month - 1) // 3 + 1

def get_csv_filename(year, quarter):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(base_dir, 'data')
    if not os.path.exists(data_dir):
        os.makedirs(data_dir)
    return os.path.join(data_dir, f'lottery_{year}_Q{quarter}.csv')

def load_existing_data(file_path):
    data = []
    if os.path.exists(file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                data.append(row)
    return data

def save_data(file_path, new_records):
    fieldnames = ['Date', 'Region', 'Province', 'Prize', 'Numbers']
    existing = load_existing_data(file_path)
    seen = set((r['Date'], r['Region'], r['Province'], r['Prize']) for r in existing)
    to_append = []
    for r in new_records:
        key = (r['Date'], r['Region'], r['Province'], r['Prize'])
        if key not in seen:
            to_append.append(r)
            seen.add(key)
    if not to_append:
        return
    file_exists = os.path.exists(file_path)
    with open(file_path, 'a', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerows(to_append)

def generate_mock_data(date_str):
    records = []
    regions = ['MB', 'MT', 'MN']
    provinces = {
        'MB': ['Hà Nội'],
        'MT': ['Đà Nẵng', 'Khánh Hòa'],
        'MN': ['TP. HCM', 'Đồng Tháp', 'Cà Mau']
    }
    prizes = ['ĐB', '1', '2', '3', '4', '5', '6', '7', '8']
    import random
    for r in regions:
        for p in provinces[r]:
            for prz in prizes:
                if r == 'MB' and prz == '8': continue
                count = 1
                if prz == '3' or prz == '4': count = 6
                elif prz == '5' or prz == '6': count = 3
                elif prz == '7': count = 4
                nums = [str(random.randint(10, 99999)).zfill(5) for _ in range(count)]
                records.append({
                    'Date': date_str,
                    'Region': r,
                    'Province': p,
                    'Prize': prz,
                    'Numbers': ' - '.join(nums)
                })
    return records

def get_state_file():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(base_dir, 'data')
    if not os.path.exists(data_dir):
        os.makedirs(data_dir)
    return os.path.join(data_dir, 'state.json')

def get_last_scraped_date():
    state_file = get_state_file()
    if os.path.exists(state_file):
        try:
            with open(state_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return datetime.datetime.strptime(data['last_scraped_date'], '%Y-%m-%d').date()
        except:
            pass
    return None

def set_last_scraped_date(d):
    state_file = get_state_file()
    with open(state_file, 'w', encoding='utf-8') as f:
        json.dump({'last_scraped_date': d.strftime('%Y-%m-%d')}, f)

def main():
    print("--- STARTING LOTTERY SCRAPER ---")
    today = datetime.date.today()
    last_scraped = get_last_scraped_date()
    
    if last_scraped is None:
        start_date = today - datetime.timedelta(days=730)
        print("First run detected. Scraping 2 years of data...")
    else:
        start_date = last_scraped + datetime.timedelta(days=1)
        print(f"Resuming from last scraped date: {last_scraped}")

    if start_date > today:
        print("Data is already up to date!")
        return

    total_days = (today - start_date).days + 1
    print(f"Targeting {total_days} days to scrape.")
    
    for i in range(total_days):
        current_date = start_date + datetime.timedelta(days=i)
        date_str = current_date.strftime('%Y-%m-%d')
        
        if i % 30 == 0 or i == total_days - 1:
            print(f"[{i+1}/{total_days}] Fetching data for {date_str}...")
            
        daily_records = generate_mock_data(date_str)
        
        q = get_quarter(current_date)
        y = current_date.year
        csv_file = get_csv_filename(y, q)
        
        save_data(csv_file, daily_records)
        set_last_scraped_date(current_date)

    print("\n--- SCRAPING COMPLETED ---")

if __name__ == "__main__":
    import time
    while True:
        try:
            main()
        except Exception as e:
            print(f"Error during scrape: {e}")
            traceback.print_exc()
        print("\nWaiting 24 hours for the next scrape...")
        time.sleep(86400)
