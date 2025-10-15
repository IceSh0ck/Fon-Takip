import os
import json
from flask import Flask, render_template, request, jsonify
import yfinance as yf
import requests
from datetime import date, timedelta, datetime
import pandas as pd
from supabase import create_client, Client

app = Flask(__name__)

# --- SUPABASE BAĞLANTISI ---
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


# --- VERİ YÜKLEME VE KAYDETME FONKSİYONLARI ---

def load_portfolios():
    """Supabase veritabanından tüm portföyleri yükler."""
    try:
        response = supabase.table('portfolios').select('name, data').execute()
        portfolios_dict = {row['name']: row['data'] for row in response.data}
        return portfolios_dict
    except Exception as e:
        print(f"Supabase'den veri yüklenirken hata: {e}")
        return {}

def save_portfolios(portfolios_dict):
    """Tüm portföy sözlüğünü Supabase veritabanına kaydeder/günceller."""
    try:
        response = supabase.table('portfolios').select('name').execute()
        db_names = {row['name'] for row in response.data}
        local_names = set(portfolios_dict.keys())
        names_to_delete = list(db_names - local_names)

        if names_to_delete:
            supabase.table('portfolios').delete().in_('name', names_to_delete).execute()

        if portfolios_dict:
            records_to_save = [{'name': name, 'data': data} for name, data in portfolios_dict.items()]
            supabase.table('portfolios').upsert(records_to_save).execute()
            
    except Exception as e:
        print(f"Supabase'e veri kaydedilirken hata: {e}")


# --- API ENDPOINT'LERİ ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/get_portfolios', methods=['GET'])
def get_portfolios():
    portfolios = load_portfolios()
    return jsonify(sorted(list(portfolios.keys())))

@app.route('/get_portfolio/<portfolio_name>', methods=['GET'])
def get_portfolio(portfolio_name):
    portfolios = load_portfolios()
    portfolio_data = portfolios.get(portfolio_name)
    if portfolio_data and 'current' in portfolio_data:
        return jsonify(portfolio_data['current'])
    return jsonify({'error': 'Portföy bulunamadı'}), 404

@app.route('/save_portfolio', methods=['POST'])
def save_portfolio():
    data = request.get_json()
    portfolio_name = data.get('name')
    stocks = data.get('stocks', [])
    funds = data.get('funds', [])
    if not portfolio_name or (not stocks and not funds):
        return jsonify({'error': 'Portföy adı ve en az bir varlık girilmelidir'}), 400
    
    portfolios = load_portfolios()
    portfolio_container = portfolios.get(portfolio_name, {'current': None, 'history': []})
    
    if portfolio_container.get('current'):
        previous_version = portfolio_container['current']
        previous_version['save_timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        if 'save_date' in previous_version:
            del previous_version['save_date']
        
        portfolio_container['history'].insert(0, previous_version)
        portfolio_container['history'] = portfolio_container['history'][:5]

    new_current_version = {'name': portfolio_name, 'stocks': stocks, 'funds': funds}
    portfolio_container['current'] = new_current_version
    portfolios[portfolio_name] = portfolio_container
    
    save_portfolios(portfolios)
    return jsonify({'success': f'"{portfolio_name}" portföyü başarıyla kaydedildi.'})

@app.route('/calculate', methods=['POST'])
def calculate():
    data = request.get_json()
    stocks = data.get('stocks', [])
    funds = data.get('funds', [])
    if not stocks and not funds: return jsonify({'error': 'Hesaplanacak veri gönderilmedi.'}), 400
    total_portfolio_change, asset_details = 0.0, []
    for stock in stocks:
        ticker, weight = stock.get('ticker').strip().upper(), float(stock.get('weight', 0))
        if ticker in ['NAKIT', 'CASH', 'TAHVIL', 'BOND', 'DEVLET TAHVILI']:
            asset_details.append({'type': 'stock', 'ticker': ticker.capitalize(), 'daily_change': 0.0, 'weighted_impact': 0.0})
            continue
        yf_ticker = ticker + '.IS' if not ticker.endswith('.IS') else ticker
        try:
            hist = yf.Ticker(yf_ticker).history(period="2d")
            daily_change = (hist['Close'].iloc[-1] - hist['Close'].iloc[-2]) / hist['Close'].iloc[-2] * 100 if len(hist) >= 2 else 0.0
            total_portfolio_change += (weight / 100) * daily_change
            asset_details.append({'type': 'stock', 'ticker': ticker, 'daily_change': daily_change, 'weighted_impact': (weight / 100) * daily_change})
        except Exception: asset_details.append({'type': 'stock', 'ticker': ticker, 'daily_change': 0.0, 'weighted_impact': 0.0, 'error': 'Veri alınamadı'})
    
    today, sdt = date.today(), (date.today() - timedelta(days=10)).strftime('%d-%m-%Y')
    fdt = today.strftime('%d-%m-%Y')
    for fund in funds:
        fund_code, weight = fund.get('ticker').strip().upper(), float(fund.get('weight', 0))
        try:
            res = requests.get(f"https://www.tefas.gov.tr/api/DB/BindHistoryPrice?sdt={sdt}&fdt={fdt}&kod={fund_code}", timeout=10)
            res.raise_for_status()
            fund_data = [i for i in res.json() if i.get('BirimPayDegeri') is not None]
            if len(fund_data) >= 2:
                last, prev = fund_data[-1], fund_data[-2]
                daily_change = (last['BirimPayDegeri'] - prev['BirimPayDegeri']) / prev['BirimPayDegeri'] * 100
                date_range = f"{datetime.strptime(prev['Tarih'],'%Y-%m-%dT%H:%M:%S').strftime('%d.%m.%Y')} → {datetime.strptime(last['Tarih'],'%Y-%m-%dT%H:%M:%S').strftime('%d.%m.%Y')}"
            else: daily_change, date_range = 0.0, "Yetersiz Veri"
            total_portfolio_change += (weight / 100) * daily_change
            asset_details.append({'type': 'fund', 'ticker': fund_code, 'daily_change': daily_change, 'weighted_impact': (weight / 100) * daily_change, 'date_range': date_range})
        except Exception: asset_details.append({'type': 'fund', 'ticker': fund_code, 'daily_change': 0.0, 'weighted_impact': 0.0, 'error': 'Veri alınamadı'})
    
    return jsonify({'total_change': total_portfolio_change, 'details': asset_details})

@app.route('/calculate_historical/<portfolio_name>', methods=['GET'])
def calculate_historical(portfolio_name):
    portfolios = load_portfolios()
    portfolio_container = portfolios.get(portfolio_name)

    if not portfolio_container:
        return jsonify({'error': 'Portföy bulunamadı'}), 404

    # 1. Adım: Tüm portföy versiyonlarını ve geçerlilik tarihlerini topla
    all_versions = []
    current_version = portfolio_container.get('current')
    if current_version:
        history_dates = [
            datetime.strptime(v.get('save_timestamp'), '%Y-%m-%d %H:%M:%S').date()
            for v in portfolio_container.get('history', []) if v.get('save_timestamp')
        ]
        start_of_current = max(history_dates) if history_dates else (date.today() - timedelta(days=45))
        all_versions.append({'portfolio': current_version, 'start_date': start_of_current, 'is_current': True})

    for past_version in portfolio_container.get('history', []):
        try:
            save_date = datetime.strptime(past_version.get('save_timestamp'), '%Y-%m-%d %H:%M:%S').date()
            all_versions.append({'portfolio': past_version, 'start_date': save_date, 'is_current': False})
        except (ValueError, TypeError):
            continue

    all_versions.sort(key=lambda x: x['start_date'], reverse=True)

    if not all_versions:
        return jsonify({'error': 'Hesaplanacak portföy versiyonu bulunamadı.'}), 400

    # 2. Adım: Genel tarih aralığını ve tüm varlıkları belirle
    end_date = date.today()
    start_date = end_date - timedelta(days=45)

    all_stock_tickers = set()
    all_fund_tickers = set()
    for version in all_versions:
        for stock in version['portfolio'].get('stocks', []):
            all_stock_tickers.add(stock['ticker'].strip().upper() + '.IS')
        for fund in version['portfolio'].get('funds', []):
            all_fund_tickers.add(fund['ticker'].strip().upper())
    
    # 3. Adım: Tüm varlıkların fiyat verilerini tek seferde çek
    asset_prices_df = pd.DataFrame()
    if all_stock_tickers:
        try:
            stock_data = yf.download(list(all_stock_tickers), start=start_date, end=end_date, progress=False)['Close']
            if not stock_data.empty:
                if isinstance(stock_data, pd.Series):
                    stock_data = stock_data.to_frame(name=list(all_stock_tickers)[0])
                asset_prices_df = pd.concat([asset_prices_df, stock_data], axis=1)
        except Exception as e:
            print(f"Hisse senedi verisi alınırken hata: {e}")

    sdt_str, fdt_str = start_date.strftime('%d-%m-%Y'), end_date.strftime('%d-%m-%Y')
    for fund_code in all_fund_tickers:
        try:
            res = requests.get(f"https://www.tefas.gov.tr/api/DB/BindHistoryPrice?sdt={sdt_str}&fdt={fdt_str}&kod={fund_code}", timeout=10)
            fund_data = res.json()
            if fund_data:
                df = pd.DataFrame(fund_data)
                df['Tarih'] = pd.to_datetime(df['Tarih'])
                df = df.set_index('Tarih')[['BirimPayDegeri']].rename(columns={'BirimPayDegeri': fund_code})
                asset_prices_df = pd.concat([asset_prices_df, df], axis=1)
        except Exception as e:
            print(f"Fon verisi alınırken hata ({fund_code}): {e}")
            
    if asset_prices_df.empty:
        return jsonify({'error': 'Tarihsel veri bulunamadı.'}), 400

    asset_prices_df.columns = asset_prices_df.columns.str.replace('.IS', '', regex=False)
    asset_prices_df = asset_prices_df.ffill().dropna(how='all')
    daily_returns = asset_prices_df.pct_change()

    # 4. Adım: Her gün için doğru portföy ağırlıklarını kullanarak getiri hesapla
    portfolio_daily_returns = pd.Series(index=daily_returns.index, dtype=float)

    for i, version_data in enumerate(all_versions):
        period_start_date = version_data['start_date']
        period_end_date = all_versions[i-1]['start_date'] - timedelta(days=1) if i > 0 else end_date

        period_start_date = max(period_start_date, start_date)
        if period_start_date > period_end_date: continue

        assets = version_data['portfolio'].get('stocks', []) + version_data['portfolio'].get('funds', [])
        weights_dict = {asset['ticker'].strip().upper(): float(asset['weight']) / 100 for asset in assets}
        aligned_weights = pd.Series(weights_dict).reindex(daily_returns.columns).fillna(0)

        period_mask = (daily_returns.index.date >= period_start_date) & (daily_returns.index.date <= period_end_date)
        period_returns = (daily_returns[period_mask] * aligned_weights).sum(axis=1) * 100
        portfolio_daily_returns.update(period_returns)
        
    # 5. Adım: Frontend için veri setlerini oluştur
    valid_returns = portfolio_daily_returns.dropna()
    datasets = []
    
    for i in range(len(all_versions) - 1, -1, -1):
        version_data = all_versions[i]
        period_start_date = version_data['start_date']
        period_end_date = all_versions[i-1]['start_date'] - timedelta(days=1) if i > 0 else end_date

        period_start_date = max(period_start_date, start_date)
        if period_start_date > period_end_date: continue

        mask = (valid_returns.index.date >= period_start_date) & (valid_returns.index.date <= period_end_date)
        segment_returns = valid_returns[mask]
        
        if not segment_returns.empty:
            prev_day_index = segment_returns.index[0] - pd.Timedelta(days=1)
            if prev_day_index in valid_returns.index:
                segment_returns = pd.concat([valid_returns.loc[[prev_day_index]], segment_returns])

            if version_data['is_current']:
                color = 'rgb(255, 205, 86)' # Sarı
                label = f"Güncel Versiyon ({period_start_date.strftime('%d.%m.%Y')} sonrası)"
            else:
                color = 'rgb(54, 162, 235)' # Mavi
                label = f"Önceki Versiyon ({period_end_date.strftime('%d.%m.%Y')} öncesi)"

            datasets.append({
                'label': label,
                'data': [{'x': ts.strftime('%d.%m.%Y'), 'y': val} for ts, val in segment_returns.items()],
                'borderColor': color,
                'backgroundColor': color.replace(')', ', 0.5)').replace('rgb', 'rgba'),
                'tension': 0.1,
                'borderWidth': 2.5
            })

    # Son 30 günü göster
    thirty_days_ago = date.today() - timedelta(days=30)
    final_datasets = []
    for ds in datasets:
        filtered_data = [d for d in ds['data'] if datetime.strptime(d['x'], '%d.%m.%Y').date() >= thirty_days_ago]
        if filtered_data:
            first_date_in_set = datetime.strptime(filtered_data[0]['x'], '%d.%m.%Y').date()
            original_data_point = next((od for od in ds['data'] if od['x'] == filtered_data[0]['x']), None)
            original_index = ds['data'].index(original_data_point) if original_data_point else -1
            if original_index > 0:
                filtered_data.insert(0, ds['data'][original_index - 1])
            ds['data'] = filtered_data
            final_datasets.append(ds)

    return jsonify({'datasets': final_datasets})


@app.route('/get_portfolio_history/<portfolio_name>', methods=['GET'])
def get_portfolio_history(portfolio_name):
    portfolios = load_portfolios()
    portfolio_data = portfolios.get(portfolio_name)
    if not portfolio_data or not portfolio_data.get('current'):
        return jsonify({'error': 'Portföy veya geçmişi bulunamadı.'}), 400
    
    for entry in portfolio_data.get('history', []):
        if 'save_timestamp' in entry:
            try:
                dt_obj = datetime.strptime(entry['save_timestamp'], '%Y-%m-%d %H:%M:%S')
                entry['display_timestamp'] = dt_obj.strftime('%d.%m.%Y %H:%M')
            except ValueError:
                entry['display_timestamp'] = entry['save_timestamp'] 

    return jsonify(portfolio_data)


@app.route('/revert_portfolio/<portfolio_name>', methods=['POST'])
def revert_portfolio(portfolio_name):
    portfolios = load_portfolios()
    portfolio_data = portfolios.get(portfolio_name)
    if not portfolio_data or not portfolio_data.get('history'):
        return jsonify({'error': 'Geri alınacak bir önceki versiyon bulunamadı.'}), 400
    
    last_history_item = portfolio_data['history'].pop(0)
    if 'save_timestamp' in last_history_item: del last_history_item['save_timestamp']
    if 'display_timestamp' in last_history_item: del last_history_item['display_timestamp']
    if 'save_date' in last_history_item: del last_history_item['save_date']

    portfolio_data['current'] = last_history_item
    portfolios[portfolio_name] = portfolio_data
    save_portfolios(portfolios)
    return jsonify({'success': f'"{portfolio_name}" portföyü bir önceki versiyona başarıyla geri alındı.'})

@app.route('/delete_portfolio', methods=['POST'])
def delete_portfolio():
    data = request.get_json()
    portfolio_name_to_delete = data.get('name')
    if not portfolio_name_to_delete: return jsonify({'error': 'Silinecek portföy adı belirtilmedi.'}), 400
    
    portfolios = load_portfolios()
    if portfolio_name_to_delete in portfolios:
        del portfolios[portfolio_name_to_delete]
        save_portfolios(portfolios)
        return jsonify({'success': f'"{portfolio_name_to_delete}" portföyü başarıyla silindi.'})
    else:
        return jsonify({'error': 'Silinecek portföy bulunamadı.'}), 404

if __name__ == '__main__':
    app.run(debug=True)
