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

# --- YARDIMCI HESAPLAMA FONKSİYONU ---
def _calculate_portfolio_return(stocks, funds):
    """Verilen hisse ve fon listesi için portföy getirisini hesaplar."""
    total_portfolio_change, asset_details = 0.0, []
    
    for stock in stocks:
        ticker, weight = stock.get('ticker', '').strip().upper(), float(stock.get('weight', 0))
        if not ticker or weight == 0: continue
        if ticker in ['NAKIT', 'CASH', 'TAHVIL', 'BOND', 'DEVLET TAHVILI']:
            asset_details.append({'type': 'stock', 'ticker': ticker.capitalize(), 'daily_change': 0.0, 'weighted_impact': 0.0})
            continue
        yf_ticker = ticker + '.IS' if not ticker.endswith('.IS') else ticker
        try:
            hist = yf.Ticker(yf_ticker).history(period="2d")
            daily_change = (hist['Close'].iloc[-1] - hist['Close'].iloc[-2]) / hist['Close'].iloc[-2] * 100 if len(hist) >= 2 else 0.0
            total_portfolio_change += (weight / 100) * daily_change
            asset_details.append({'type': 'stock', 'ticker': ticker, 'daily_change': daily_change, 'weighted_impact': (weight / 100) * daily_change})
        except Exception: 
            asset_details.append({'type': 'stock', 'ticker': ticker, 'daily_change': 0.0, 'weighted_impact': 0.0, 'error': 'Veri alınamadı'})
    
    today, sdt = date.today(), (date.today() - timedelta(days=10)).strftime('%d-%m-%Y')
    fdt = today.strftime('%d-%m-%Y')
    for fund in funds:
        fund_code, weight = fund.get('ticker', '').strip().upper(), float(fund.get('weight', 0))
        if not fund_code or weight == 0: continue
        try:
            res = requests.get(f"https://www.tefas.gov.tr/api/DB/BindHistoryPrice?sdt={sdt}&fdt={fdt}&kod={fund_code}", timeout=10)
            res.raise_for_status()
            fund_data = [i for i in res.json() if i.get('BirimPayDegeri') is not None]
            if len(fund_data) >= 2:
                last, prev = fund_data[-1], fund_data[-2]
                daily_change = (last['BirimPayDegeri'] - prev['BirimPayDegeri']) / prev['BirimPayDegeri'] * 100
                date_range = f"{datetime.strptime(prev['Tarih'],'%Y-%m-%dT%H:%M:%S').strftime('%d.%m.%Y')} → {datetime.strptime(last['Tarih'],'%Y-%m-%dT%H:%M:%S').strftime('%d.%m.%Y')}"
            else: 
                daily_change, date_range = 0.0, "Yetersiz Veri"
            total_portfolio_change += (weight / 100) * daily_change
            asset_details.append({'type': 'fund', 'ticker': fund_code, 'daily_change': daily_change, 'weighted_impact': (weight / 100) * daily_change, 'date_range': date_range})
        except Exception: 
            asset_details.append({'type': 'fund', 'ticker': fund_code, 'daily_change': 0.0, 'weighted_impact': 0.0, 'error': 'Veri alınamadı'})
            
    return {'total_change': total_portfolio_change, 'details': asset_details}

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
    if not stocks and not funds: 
        return jsonify({'error': 'Hesaplanacak veri gönderilmedi.'}), 400
    
    result = _calculate_portfolio_return(stocks, funds)
    return jsonify(result)

@app.route('/get_all_fund_returns', methods=['GET'])
def get_all_fund_returns():
    """Tüm kayıtlı fonların günlük getirilerini hesaplar ve döndürür."""
    portfolios = load_portfolios()
    all_returns = []
    
    for name, data_container in portfolios.items():
        portfolio_data = data_container.get('current')
        if not portfolio_data:
            continue
            
        stocks = portfolio_data.get('stocks', [])
        funds = portfolio_data.get('funds', [])
        
        if not stocks and not funds:
            continue
            
        calculation_result = _calculate_portfolio_return(stocks, funds)
        
        all_returns.append({
            'name': name,
            'return': calculation_result.get('total_change', 0)
        })
        
    return jsonify(all_returns)


@app.route('/calculate_historical/<portfolio_name>', methods=['GET'])
def calculate_historical(portfolio_name):
    portfolios = load_portfolios()
    portfolio_container = portfolios.get(portfolio_name)
    if not portfolio_container: return jsonify({'error': 'Portföy bulunamadı'}), 404
    portfolio = portfolio_container.get('current')
    if not portfolio: return jsonify({'error': 'Portföyün güncel versiyonu bulunamadı.'}), 404
    end_date, start_date = date.today(), date.today() - timedelta(days=45)
    all_assets = portfolio.get('stocks', []) + portfolio.get('funds', [])
    if not all_assets: return jsonify({'error': 'Portföyde hesaplanacak varlık yok.'}), 400
    asset_prices_df = pd.DataFrame()
    stocks_in_portfolio = portfolio.get('stocks', [])
    if stocks_in_portfolio:
        stock_tickers_is = [s['ticker'].strip().upper() + '.IS' for s in stocks_in_portfolio]
        try:
            stock_data = yf.download(stock_tickers_is, start=start_date, end=end_date, progress=False)
            if not stock_data.empty:
                close_prices = stock_data['Close'] if len(stock_tickers_is) > 1 else stock_data[['Close']]
                asset_prices_df = pd.concat([asset_prices_df, close_prices], axis=1)
        except Exception as e:
            print(f"Hisse senedi verisi alınırken hata: {e}")
    sdt_str, fdt_str = start_date.strftime('%d-%m-%Y'), end_date.strftime('%d-%m-%Y')
    for fund in portfolio.get('funds', []):
        fund_code = fund['ticker'].strip().upper()
        try:
            res = requests.get(f"https://www.tefas.gov.tr/api/DB/BindHistoryPrice?sdt={sdt_str}&fdt={fdt_str}&kod={fund_code}", timeout=10)
            fund_data = res.json()
            if fund_data:
                df = pd.DataFrame(fund_data)
                df['Tarih'] = pd.to_datetime(df['Tarih'])
                df = df.set_index('Tarih')[['BirimPayDegeri']].rename(columns={'BirimPayDegeri': fund_code})
                asset_prices_df = pd.concat([asset_prices_df, df], axis=1)
        except Exception as e: print(f"Fon verisi alınırken hata ({fund_code}): {e}")
    if asset_prices_df.empty: return jsonify({'error': 'Tarihsel veri bulunamadı.'}), 400
    asset_prices_df.columns = asset_prices_df.columns.str.replace('.IS', '', regex=False)
    asset_prices_df = asset_prices_df.ffill().dropna(how='all')
    daily_returns = asset_prices_df.pct_change()
    weights_dict = {asset['ticker'].strip().upper(): float(asset['weight']) / 100 for asset in all_assets}
    aligned_weights = pd.Series(weights_dict).reindex(daily_returns.columns).fillna(0)
    portfolio_daily_returns = (daily_returns * aligned_weights).sum(axis=1) * 100
    valid_returns = portfolio_daily_returns.dropna()
    dates = valid_returns.index.strftime('%d.%m.%Y').tolist()[-30:]
    returns = valid_returns.tolist()[-30:]
    return jsonify({'dates': dates, 'returns': returns})

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

@app.route('/calculate_dynamic_weights', methods=['POST'])
def calculate_dynamic_weights():
    data = request.get_json()
    stocks = data.get('stocks', [])
    funds = data.get('funds', [])
    if not stocks and not funds:
        return jsonify({'error': 'Hesaplanacak veri gönderilmedi.'}), 400

    total_portfolio_value = 0.0
    asset_market_values = []
    
    for stock in stocks:
        ticker, adet = stock.get('ticker').strip().upper(), int(stock.get('adet') or 0)
        if adet == 0: continue
        if ticker in ['NAKIT', 'CASH', 'TAHVIL', 'BOND', 'DEVLET TAHVILI']:
            market_value = float(adet)
            asset_market_values.append({'type': 'stock', 'ticker': ticker, 'adet': adet, 'market_value': market_value, 'data': None})
            total_portfolio_value += market_value
            continue
            
        yf_ticker = ticker + '.IS' if not ticker.endswith('.IS') else ticker
        try:
            hist = yf.Ticker(yf_ticker).history(period="2d")
            if hist.empty: raise Exception("Veri yok")
            latest_price = hist['Close'].iloc[-1]
            market_value = latest_price * adet
            asset_market_values.append({'type': 'stock', 'ticker': ticker, 'adet': adet, 'market_value': market_value, 'data': hist})
            total_portfolio_value += market_value
        except Exception as e:
            print(f"Fiyat alınamadı ({ticker}): {e}")
            asset_market_values.append({'type': 'stock', 'ticker': ticker, 'adet': adet, 'market_value': 0, 'data': None, 'error': 'Fiyat alınamadı'})

    sdt, fdt = (date.today() - timedelta(days=10)).strftime('%d-%m-%Y'), date.today().strftime('%d-%m-%Y')
    for fund in funds:
        fund_code, adet = fund.get('ticker').strip().upper(), int(fund.get('adet') or 0)
        if adet == 0: continue
        try:
            res = requests.get(f"https://www.tefas.gov.tr/api/DB/BindHistoryPrice?sdt={sdt}&fdt={fdt}&kod={fund_code}", timeout=10)
            fund_data = [i for i in res.json() if i.get('BirimPayDegeri') is not None]
            if not fund_data: raise Exception("Veri yok")
            latest_price = fund_data[-1]['BirimPayDegeri']
            market_value = latest_price * adet
            asset_market_values.append({'type': 'fund', 'ticker': fund_code, 'adet': adet, 'market_value': market_value, 'data': fund_data})
            total_portfolio_value += market_value
        except Exception as e:
            print(f"Fiyat alınamadı ({fund_code}): {e}")
            asset_market_values.append({'type': 'fund', 'ticker': fund_code, 'adet': adet, 'market_value': 0, 'data': None, 'error': 'Fiyat alınamadı'})

    if total_portfolio_value == 0:
        return jsonify({'error': 'Portföy toplam değeri sıfır. Adetleri veya varlık kodlarını kontrol edin.'}), 400

    total_portfolio_change = 0.0
    asset_details = []
    for asset in asset_market_values:
        dynamic_weight = (asset['market_value'] / total_portfolio_value) * 100
        
        if asset.get('error'):
            asset_details.append({**asset, 'dynamic_weight': 0.0, 'daily_change': 0.0, 'weighted_impact': 0.0})
            continue

        daily_change = 0.0
        date_range = None
        
        if asset['type'] == 'stock':
            hist = asset['data']
            if hist is not None and len(hist) >= 2:
                daily_change = (hist['Close'].iloc[-1] - hist['Close'].iloc[-2]) / hist['Close'].iloc[-2] * 100
            elif asset['ticker'] in ['NAKIT', 'CASH', 'TAHVIL', 'BOND', 'DEVLET TAHVILI']:
                daily_change = 0.0

        elif asset['type'] == 'fund':
            fund_data = asset['data']
            if len(fund_data) >= 2:
                last, prev = fund_data[-1], fund_data[-2]
                daily_change = (last['BirimPayDegeri'] - prev['BirimPayDegeri']) / prev['BirimPayDegeri'] * 100
                date_range = f"{datetime.strptime(prev['Tarih'],'%Y-%m-%dT%H:%M:%S').strftime('%d.%m.%Y')} → {datetime.strptime(last['Tarih'],'%Y-%m-%dT%H:%M:%S').strftime('%d.%m.%Y')}"
            else:
                date_range = "Yetersiz Veri"

        weighted_impact = (dynamic_weight / 100) * daily_change
        total_portfolio_change += weighted_impact
        
        detail = {
            'type': asset['type'],
            'ticker': asset['ticker'],
            'dynamic_weight': dynamic_weight,
            'daily_change': daily_change,
            'weighted_impact': weighted_impact
        }
        if date_range: detail['date_range'] = date_range
        asset_details.append(detail)
        
    return jsonify({'total_change': total_portfolio_change, 'details': asset_details})


if __name__ == '__main__':
    app.run(debug=True)
