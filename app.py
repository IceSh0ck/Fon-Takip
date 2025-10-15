import os
import json
from flask import Flask, render_template, request, jsonify
import yfinance as yf
import requests
from datetime import date, timedelta, datetime
import pandas as pd
from supabase import create_client, Client

app = Flask(__name__)

# --- SUPABASE BAĞLANTISI (BİLGİLER DOĞRUDAN KOD İÇİNDE) ---
# DİKKAT: BU YÖNTEM GÜVENLİ DEĞİLDİR VE SADECE TEST İÇİN KULLANILMALIDIR.
# KODUNUZU PAYLAŞIRSANIZ HERKES VERİTABANINIZA ERİŞEBİLİR.

SUPABASE_URL = "https://zaihijqapqxakdohubyr.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InphaWhpanFhcHF4YWtkb2h1YnlyIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc2MDM1NzQzNCwiZXhwIjoyMDc1OTMzNDM0fQ.PrqIn__4qMaTwV_s6111QT_qKy6bKKAuv7v2YnJwQwc"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


# --- DEĞİŞTİ: VERİ YÜKLEME VE KAYDETME FONKSİYONLARI (SUPABASE İÇİN) ---

def load_portfolios():
    """Supabase'den tüm portföyleri yükler ve 'ana'/'deneme' olarak ayırır."""
    portfolios_data = {"main": {}, "sandbox": {}}
    try:
        # 'is_sandbox' sütununu da seçiyoruz
        response = supabase.table('portfolios').select('name, data, is_sandbox').execute()
        
        for row in response.data:
            portfolio_type = "sandbox" if row.get('is_sandbox') else "main"
            # Yapıyı { 'portfolio_name': { 'data': {...}, 'is_sandbox': True/False } } şeklinde saklıyoruz
            portfolios_data[portfolio_type][row['name']] = {
                'data': row['data'],
                'is_sandbox': row.get('is_sandbox', False)
            }
        return portfolios_data
    except Exception as e:
        print(f"Supabase'den veri yüklenirken hata: {e}")
        return {"main": {}, "sandbox": {}}

def save_portfolios(portfolios_data):
    """Tüm portföy verisini Supabase'e kaydeder/günceller."""
    try:
        # Tüm portföyleri tek bir listeye toplayalım
        all_local_portfolios = {**portfolios_data.get('main', {}), **portfolios_data.get('sandbox', {})}
        
        response = supabase.table('portfolios').select('name').execute()
        db_names = {row['name'] for row in response.data}
        local_names = set(all_local_portfolios.keys())
        names_to_delete = list(db_names - local_names)

        if names_to_delete:
            supabase.table('portfolios').delete().in_('name', names_to_delete).execute()

        if all_local_portfolios:
            records_to_save = [
                {'name': name, 'data': details['data'], 'is_sandbox': details.get('is_sandbox', False)}
                for name, details in all_local_portfolios.items()
            ]
            supabase.table('portfolios').upsert(records_to_save).execute()
            
    except Exception as e:
        print(f"Supabase'e veri kaydedilirken hata: {e}")


# --- API ENDPOINT'LERİ ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/get_portfolios', methods=['GET'])
def get_portfolios():
    # --- DEĞİŞTİ: Portföyleri artık gruplanmış olarak gönderiyoruz ---
    portfolios = load_portfolios()
    # Sadece isim listelerini gönderiyoruz
    response_data = {
        "main": sorted(list(portfolios["main"].keys())),
        "sandbox": sorted(list(portfolios["sandbox"].keys()))
    }
    return jsonify(response_data)

@app.route('/get_portfolio/<portfolio_name>', methods=['GET'])
def get_portfolio(portfolio_name):
    portfolios = load_portfolios()
    all_portfolios = {**portfolios.get('main', {}), **portfolios.get('sandbox', {})}
    portfolio_container = all_portfolios.get(portfolio_name)
    
    if portfolio_container and 'data' in portfolio_container and 'current' in portfolio_container['data']:
        # --- DEĞİŞTİ: Portföyün deneme olup olmadığını da gönderiyoruz ---
        response = portfolio_container['data']['current']
        response['is_sandbox'] = portfolio_container.get('is_sandbox', False)
        return jsonify(response)
        
    return jsonify({'error': 'Portföy bulunamadı'}), 404

@app.route('/save_portfolio', methods=['POST'])
def save_portfolio():
    data = request.get_json()
    portfolio_name = data.get('name')
    stocks = data.get('stocks', [])
    funds = data.get('funds', [])
    is_sandbox = data.get('is_sandbox', False) # --- YENİ: Portföyün türünü alıyoruz ---

    if not portfolio_name or (not stocks and not funds):
        return jsonify({'error': 'Portföy adı ve en az bir varlık girilmelidir'}), 400
    
    portfolios_data = load_portfolios()
    all_portfolios = {**portfolios_data.get('main', {}), **portfolios_data.get('sandbox', {})}

    # Önceki versiyonu bulup geçmişe ekleme
    portfolio_container = all_portfolios.get(portfolio_name, {'data': {'current': None, 'history': []}, 'is_sandbox': is_sandbox})
    
    if portfolio_container.get('data', {}).get('current'):
        previous_version = portfolio_container['data']['current']
        previous_version['save_timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        if 'save_date' in previous_version: del previous_version['save_date']
        
        portfolio_container['data']['history'].insert(0, previous_version)
        portfolio_container['data']['history'] = portfolio_container['data']['history'][:5]

    # Yeni güncel versiyonu oluşturma
    new_current_version = {'name': portfolio_name, 'stocks': stocks, 'funds': funds}
    portfolio_container['data']['current'] = new_current_version
    portfolio_container['is_sandbox'] = is_sandbox

    # Portföyü doğru kategoriye yerleştirme
    portfolio_type = "sandbox" if is_sandbox else "main"
    if portfolio_name in portfolios_data.get("main", {}): del portfolios_data["main"][portfolio_name]
    if portfolio_name in portfolios_data.get("sandbox", {}): del portfolios_data["sandbox"][portfolio_name]
    
    portfolios_data[portfolio_type][portfolio_name] = portfolio_container
    
    save_portfolios(portfolios_data)
    return jsonify({'success': f'"{portfolio_name}" portföyü başarıyla kaydedildi.'})


@app.route('/delete_portfolio', methods=['POST'])
def delete_portfolio():
    data = request.get_json()
    portfolio_name_to_delete = data.get('name')
    if not portfolio_name_to_delete: return jsonify({'error': 'Silinecek portföy adı belirtilmedi.'}), 400
    
    portfolios = load_portfolios()
    # --- DEĞİŞTİ: Her iki listeden de silmeyi deniyoruz ---
    if portfolio_name_to_delete in portfolios['main']:
        del portfolios['main'][portfolio_name_to_delete]
    elif portfolio_name_to_delete in portfolios['sandbox']:
        del portfolios['sandbox'][portfolio_name_to_delete]
    else:
        return jsonify({'error': 'Silinecek portföy bulunamadı.'}), 404
        
    save_portfolios(portfolios)
    return jsonify({'success': f'"{portfolio_name_to_delete}" portföyü başarıyla silindi.'})


# --- YENİ: SİMÜLASYON İÇİN ANLIK FİYAT ENDPOINT'İ ---
@app.route('/get_live_prices', methods=['POST'])
def get_live_prices():
    data = request.get_json()
    tickers = data.get('tickers', [])
    if not tickers:
        return jsonify({'error': 'Fiyatı alınacak kod belirtilmedi.'}), 400

    prices = {}
    sdt, fdt = (date.today() - timedelta(days=5)).strftime('%d-%m-%Y'), date.today().strftime('%d-%m-%Y')

    for ticker in tickers:
        is_stock = ticker.endswith('.IS')
        try:
            if is_stock:
                stock_data = yf.Ticker(ticker).history(period="1d")
                if not stock_data.empty:
                    prices[ticker.replace('.IS', '')] = stock_data['Close'].iloc[-1]
                else:
                    prices[ticker.replace('.IS', '')] = None
            else: # Fon
                res = requests.get(f"https://www.tefas.gov.tr/api/DB/BindHistoryPrice?sdt={sdt}&fdt={fdt}&kod={ticker}", timeout=5)
                fund_data = [i for i in res.json() if i.get('BirimPayDegeri') is not None]
                if fund_data:
                    prices[ticker] = fund_data[-1]['BirimPayDegeri']
                else:
                    prices[ticker] = None
        except Exception as e:
            print(f"Fiyat alınırken hata ({ticker}): {e}")
            prices[ticker.replace('.IS', '')] = None
            
    return jsonify(prices)


# --- Diğer Endpoint'lerde Değişiklik Yok ---

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
    portfolios_data = load_portfolios()
    all_portfolios = {**portfolios_data.get('main', {}), **portfolios_data.get('sandbox', {})}
    portfolio_container = all_portfolios.get(portfolio_name, {}).get('data')

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
    portfolios_data = load_portfolios()
    all_portfolios = {**portfolios_data.get('main', {}), **portfolios_data.get('sandbox', {})}
    portfolio_container = all_portfolios.get(portfolio_name, {}).get('data')

    if not portfolio_container or not portfolio_container.get('current'):
        return jsonify({'error': 'Portföy veya geçmişi bulunamadı.'}), 400
    
    for entry in portfolio_container.get('history', []):
        if 'save_timestamp' in entry:
            try:
                dt_obj = datetime.strptime(entry['save_timestamp'], '%Y-%m-%d %H:%M:%S')
                entry['display_timestamp'] = dt_obj.strftime('%d.%m.%Y %H:%M')
            except ValueError:
                entry['display_timestamp'] = entry['save_timestamp']

    return jsonify(portfolio_container)

@app.route('/revert_portfolio/<portfolio_name>', methods=['POST'])
def revert_portfolio(portfolio_name):
    portfolios_data = load_portfolios()
    all_portfolios = {**portfolios_data.get('main', {}), **portfolios_data.get('sandbox', {})}
    
    if portfolio_name not in all_portfolios:
        return jsonify({'error': 'Portföy bulunamadı.'}), 404

    portfolio_details = all_portfolios[portfolio_name]
    portfolio_data = portfolio_details['data']

    if not portfolio_data or not portfolio_data.get('history'):
        return jsonify({'error': 'Geri alınacak bir önceki versiyon bulunamadı.'}), 400
    
    last_history_item = portfolio_data['history'].pop(0)
    if 'save_timestamp' in last_history_item: del last_history_item['save_timestamp']
    if 'display_timestamp' in last_history_item: del last_history_item['display_timestamp']
    if 'save_date' in last_history_item: del last_history_item['save_date']

    portfolio_data['current'] = last_history_item
    
    # Doğru kategoriye geri koy
    portfolio_type = "sandbox" if portfolio_details.get('is_sandbox') else "main"
    portfolios_data[portfolio_type][portfolio_name]['data'] = portfolio_data

    save_portfolios(portfolios_data)
    return jsonify({'success': f'"{portfolio_name}" portföyü bir önceki versiyona başarıyla geri alındı.'})


if __name__ == '__main__':
    app.run(debug=True)

