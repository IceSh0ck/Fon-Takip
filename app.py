import os
import json
from flask import Flask, render_template, request, jsonify
import yfinance as yf
import requests
from datetime import date, timedelta, datetime
import pandas as pd
from supabase import create_client, Client
from functools import lru_cache

app = Flask(__name__)

# --- SUPABASE BAĞLANTISI ---
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


# --- GENEL VERİ YÖNETİM FONKSİYONLARI ---

def load_data_from_table(table_name):
    """Belirtilen tablodan tüm veriyi yükler."""
    try:
        response = supabase.table(table_name).select('name, data').execute()
        return {row['name']: row['data'] for row in response.data}
    except Exception as e:
        print(f"{table_name} yüklenirken hata: {e}")
        return {}

def save_data_to_table(table_name, data_dict):
    """Veri sözlüğünü belirtilen tabloya kaydeder/günceller."""
    try:
        response = supabase.table(table_name).select('name').execute()
        db_names = {row['name'] for row in response.data}
        local_names = set(data_dict.keys())
        names_to_delete = list(db_names - local_names)

        if names_to_delete:
            supabase.table(table_name).delete().in_('name', names_to_delete).execute()

        if data_dict:
            records_to_save = [{'name': name, 'data': data} for name, data in data_dict.items()]
            supabase.table(table_name).upsert(records_to_save).execute()
    except Exception as e:
        print(f"{table_name} kaydedilirken hata: {e}")


# --- API ENDPOINT'LERİ ---

@app.route('/')
def index():
    return render_template('index.html')

# --- PORTFÖY ENDPOINT'LERİ ---
@app.route('/get_portfolios', methods=['GET'])
def get_portfolios():
    return jsonify(sorted(list(load_data_from_table('portfolios').keys())))

@app.route('/get_portfolio/<portfolio_name>', methods=['GET'])
def get_portfolio(portfolio_name):
    portfolio_data = load_data_from_table('portfolios').get(portfolio_name)
    if portfolio_data and 'current' in portfolio_data:
        return jsonify(portfolio_data['current'])
    return jsonify({'error': 'Portföy bulunamadı'}), 404

# --- FON İÇERİKLERİ ENDPOINT'LERİ ---
@app.route('/get_compositions', methods=['GET'])
def get_compositions():
    return jsonify(sorted(list(load_data_from_table('fund_compositions').keys())))

@app.route('/get_composition/<composition_name>', methods=['GET'])
def get_composition(composition_name):
    composition_data = load_data_from_table('fund_compositions').get(composition_name)
    if composition_data and 'current' in composition_data:
        return jsonify(composition_data['current'])
    return jsonify({'error': 'Fon içeriği bulunamadı'}), 404

# --- GENEL KAYDETME VE SİLME ENDPOINT'LERİ ---
@app.route('/save_item', methods=['POST'])
def save_item():
    data = request.get_json()
    item_type = data.get('type')
    item_name = data.get('name')
    if not all([item_type, item_name]): return jsonify({'error': 'Tip ve isim belirtilmelidir'}), 400

    table_name = 'portfolios' if item_type == 'portfolio' else 'fund_compositions'
    all_items = load_data_from_table(table_name)
    item_container = all_items.get(item_name, {'current': None, 'history': []})

    if item_container.get('current'):
        previous_version = item_container['current']
        previous_version['save_timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        item_container['history'].insert(0, previous_version)
        item_container['history'] = item_container['history'][:5]

    item_container['current'] = {
        'name': item_name,
        'stocks': data.get('stocks', []),
        'funds': data.get('funds', [])
    }
    all_items[item_name] = item_container
    save_data_to_table(table_name, all_items)
    return jsonify({'success': f'"{item_name}" başarıyla kaydedildi.'})

@app.route('/delete_item', methods=['POST'])
def delete_item():
    data = request.get_json()
    item_type = data.get('type')
    item_name = data.get('name')
    if not all([item_type, item_name]): return jsonify({'error': 'Tip ve isim belirtilmelidir'}), 400

    table_name = 'portfolios' if item_type == 'portfolio' else 'fund_compositions'
    all_items = load_data_from_table(table_name)

    if item_name in all_items:
        del all_items[item_name]
        save_data_to_table(table_name, all_items)
        return jsonify({'success': f'"{item_name}" başarıyla silindi.'})
    else:
        return jsonify({'error': 'Silinecek öğe bulunamadı.'}), 404

# --- GEÇMİŞ VE GERİ ALMA ENDPOINT'LERİ (GENELLEŞTİRİLDİ) ---
def _get_item_history(item_type, item_name):
    table_name = 'portfolios' if item_type == 'portfolio' else 'fund_compositions'
    item_data = load_data_from_table(table_name).get(item_name)
    if not item_data: return jsonify({'error': 'Öğe bulunamadı.'}), 404
    
    for entry in item_data.get('history', []):
        if 'save_timestamp' in entry:
            try:
                dt_obj = datetime.strptime(entry['save_timestamp'], '%Y-%m-%d %H:%M:%S')
                entry['display_timestamp'] = dt_obj.strftime('%d.%m.%Y %H:%M')
            except ValueError: entry['display_timestamp'] = entry['save_timestamp']
    return jsonify(item_data)

@app.route('/get_item_history/<item_type>/<item_name>', methods=['GET'])
def get_item_history(item_type, item_name):
    return _get_item_history(item_type, item_name)

def _revert_item(item_type, item_name):
    table_name = 'portfolios' if item_type == 'portfolio' else 'fund_compositions'
    all_items = load_data_from_table(table_name)
    item_data = all_items.get(item_name)

    if not item_data or not item_data.get('history'):
        return jsonify({'error': 'Geri alınacak versiyon bulunamadı.'}), 400
    
    last_history_item = item_data['history'].pop(0)
    for key in ['save_timestamp', 'display_timestamp', 'save_date']:
        if key in last_history_item: del last_history_item[key]

    item_data['current'] = last_history_item
    all_items[item_name] = item_data
    save_data_to_table(table_name, all_items)
    return jsonify({'success': f'"{item_name}" bir önceki versiyona geri alındı.'})

@app.route('/revert_item/<item_type>/<item_name>', methods=['POST'])
def revert_item(item_type, item_name):
    return _revert_item(item_type, item_name)

# --- HESAPLAMA ENDPOINT'LERİ ---
@lru_cache(maxsize=128)
def _get_daily_change_cached(ticker, asset_type, sdt, fdt):
    try:
        if asset_type == 'stock':
            if ticker in ['NAKIT', 'CASH', 'TAHVIL', 'BOND', 'DEVLET TAHVILI']: return 0.0
            yf_ticker = ticker + '.IS' if not ticker.endswith('.IS') else ticker
            hist = yf.Ticker(yf_ticker).history(period="2d")
            if len(hist) >= 2: return (hist['Close'].iloc[-1] - hist['Close'].iloc[-2]) / hist['Close'].iloc[-2] * 100
        elif asset_type == 'fund':
            res = requests.get(f"https://www.tefas.gov.tr/api/DB/BindHistoryPrice?sdt={sdt}&fdt={fdt}&kod={ticker}", timeout=10)
            fund_data = [i for i in res.json() if i.get('BirimPayDegeri') is not None]
            if len(fund_data) >= 2: return (fund_data[-1]['BirimPayDegeri'] - fund_data[-2]['BirimPayDegeri']) / fund_data[-2]['BirimPayDegeri'] * 100
    except Exception: pass
    return 0.0

def get_asset_performance_recursively(ticker, asset_type, sdt, fdt, compositions_dict):
    if asset_type == 'fund' and ticker in compositions_dict:
        total_weighted_change = 0.0
        components = compositions_dict[ticker]['current'].get('stocks', []) + compositions_dict[ticker]['current'].get('funds', [])
        total_internal_weight = sum(float(c.get('weight', 0)) for c in components)
        if total_internal_weight == 0: return 0.0
        for component in components:
            comp_ticker = component['ticker']
            comp_type = 'stock' if any(s['ticker'] == comp_ticker for s in compositions_dict[ticker]['current'].get('stocks', [])) else 'fund'
            comp_weight = float(component.get('weight', 0))
            comp_change = get_asset_performance_recursively(comp_ticker, comp_type, sdt, fdt, compositions_dict)
            total_weighted_change += (comp_weight / total_internal_weight) * comp_change
        return total_weighted_change
    else:
        return _get_daily_change_cached(ticker, asset_type, sdt, fdt)

@app.route('/calculate', methods=['POST'])
def calculate():
    data = request.get_json()
    stocks = data.get('stocks', [])
    funds = data.get('funds', [])
    if not stocks and not funds: return jsonify({'error': 'Hesaplanacak veri gönderilmedi.'}), 400
    _get_daily_change_cached.cache_clear()
    defined_compositions = load_data_from_table('fund_compositions')
    sdt, fdt = (date.today() - timedelta(days=10)).strftime('%d-%m-%Y'), date.today().strftime('%d-%m-%Y')
    total_portfolio_change, asset_details = 0.0, []
    for asset in (stocks + funds):
        ticker, weight = asset.get('ticker').strip().upper(), float(asset.get('weight', 0))
        asset_type = 'stock' if asset in stocks else 'fund'
        daily_change = get_asset_performance_recursively(ticker, asset_type, sdt, fdt, defined_compositions)
        weighted_impact = (weight / 100) * daily_change
        total_portfolio_change += weighted_impact
        asset_details.append({'type': asset_type, 'ticker': ticker, 'daily_change': daily_change, 'weighted_impact': weighted_impact})
    return jsonify({'total_change': total_portfolio_change, 'details': asset_details})

@app.route('/calculate_historical/<item_type>/<item_name>', methods=['GET'])
def calculate_historical(item_type, item_name):
    table_name = 'portfolios' if item_type == 'portfolio' else 'fund_compositions'
    item_container = load_data_from_table(table_name).get(item_name)
    if not item_container: return jsonify({'error': 'Öğe bulunamadı'}), 404
    portfolio = item_container.get('current')
    if not portfolio: return jsonify({'error': 'Güncel versiyon bulunamadı.'}), 404
    
    end_date, start_date = date.today(), date.today() - timedelta(days=45)
    all_assets = portfolio.get('stocks', []) + portfolio.get('funds', [])
    if not all_assets: return jsonify({'error': 'Hesaplanacak varlık yok.'}), 400
    
    asset_prices_df = pd.DataFrame()
    sdt_str, fdt_str = start_date.strftime('%d-%m-%Y'), end_date.strftime('%d-%m-%Y')
    
    stock_tickers = [s['ticker'].strip().upper() for s in portfolio.get('stocks', [])]
    if stock_tickers:
        try:
            stock_data = yf.download([t + '.IS' for t in stock_tickers], start=start_date, end=end_date, progress=False)
            if not stock_data.empty: asset_prices_df = pd.concat([asset_prices_df, stock_data['Close']], axis=1)
        except Exception as e: print(f"Hisse verisi hatası: {e}")
    
    for fund in portfolio.get('funds', []):
        try:
            res = requests.get(f"https://www.tefas.gov.tr/api/DB/BindHistoryPrice?sdt={sdt_str}&fdt={fdt_str}&kod={fund['ticker']}", timeout=10)
            df = pd.DataFrame(res.json())
            if not df.empty:
                df['Tarih'] = pd.to_datetime(df['Tarih'])
                df = df.set_index('Tarih')[['BirimPayDegeri']].rename(columns={'BirimPayDegeri': fund['ticker']})
                asset_prices_df = pd.concat([asset_prices_df, df], axis=1)
        except Exception as e: print(f"Fon verisi hatası ({fund['ticker']}): {e}")

    if asset_prices_df.empty: return jsonify({'error': 'Tarihsel veri bulunamadı.'}), 400
    asset_prices_df.columns = asset_prices_df.columns.str.replace('.IS', '', regex=False)
    asset_prices_df = asset_prices_df.ffill().dropna(how='all')
    daily_returns = asset_prices_df.pct_change()
    weights_dict = {asset['ticker'].strip().upper(): float(asset['weight']) / 100 for asset in all_assets}
    aligned_weights = pd.Series(weights_dict).reindex(daily_returns.columns).fillna(0)
    portfolio_daily_returns = (daily_returns * aligned_weights).sum(axis=1) * 100
    valid_returns = portfolio_daily_returns.dropna()
    return jsonify({'dates': valid_returns.index.strftime('%d.%m.%Y').tolist()[-30:], 'returns': valid_returns.tolist()[-30:]})

@app.route('/calculate_dynamic_weights', methods=['POST'])
def calculate_dynamic_weights():
    data = request.get_json()
    stocks = data.get('stocks', [])
    funds = data.get('funds', [])
    if not (stocks or funds): return jsonify({'error': 'Veri gönderilmedi.'}), 400

    total_portfolio_value, asset_market_values = 0.0, []
    sdt, fdt = (date.today() - timedelta(days=10)).strftime('%d-%m-%Y'), date.today().strftime('%d-%m-%Y')
    
    for stock in stocks:
        ticker, adet = stock.get('ticker').strip().upper(), int(stock.get('adet') or 0)
        if adet == 0: continue
        try:
            price = 1.0 if ticker in ['NAKIT', 'CASH'] else yf.Ticker(ticker + '.IS').history(period="1d")['Close'].iloc[0]
            market_value = price * adet
            asset_market_values.append({'type': 'stock', 'ticker': ticker, 'market_value': market_value, 'daily_change': _get_daily_change_cached(ticker, 'stock', sdt, fdt)})
            total_portfolio_value += market_value
        except Exception: asset_market_values.append({'type': 'stock', 'ticker': ticker, 'market_value': 0, 'daily_change': 0, 'error': True})
    
    for fund in funds:
        fund_code, adet = fund.get('ticker').strip().upper(), int(fund.get('adet') or 0)
        if adet == 0: continue
        try:
            res = requests.get(f"https://www.tefas.gov.tr/api/DB/BindHistoryPrice?sdt={sdt}&fdt={fdt}&kod={fund_code}", timeout=10)
            price = [i['BirimPayDegeri'] for i in res.json() if i.get('BirimPayDegeri') is not None][-1]
            market_value = price * adet
            asset_market_values.append({'type': 'fund', 'ticker': fund_code, 'market_value': market_value, 'daily_change': _get_daily_change_cached(fund_code, 'fund', sdt, fdt)})
            total_portfolio_value += market_value
        except Exception: asset_market_values.append({'type': 'fund', 'ticker': fund_code, 'market_value': 0, 'daily_change': 0, 'error': True})

    if total_portfolio_value == 0: return jsonify({'error': 'Portföy değeri sıfır.'}), 400

    total_change, details = 0.0, []
    for asset in asset_market_values:
        dynamic_weight = (asset['market_value'] / total_portfolio_value) * 100
        weighted_impact = (dynamic_weight / 100) * asset['daily_change']
        total_change += weighted_impact
        details.append({**asset, 'dynamic_weight': dynamic_weight, 'weighted_impact': weighted_impact})
    
    return jsonify({'total_change': total_change, 'details': details})


if __name__ == '__main__':
    app.run(debug=True)
