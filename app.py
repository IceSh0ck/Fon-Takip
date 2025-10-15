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

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- Veri Yükleme ve Kaydetme (Değişiklik yok) ---
def load_portfolios():
    try:
        response = supabase.table('portfolios').select('name, data').execute()
        portfolios_dict = {row['name']: row['data'] for row in response.data}
        return portfolios_dict
    except Exception as e:
        print(f"Supabase'den veri yüklenirken hata: {e}")
        return {}

def save_portfolios(portfolios_dict):
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

# --- Tekil Varlık Verisi Çekme Fonksiyonları (Değişiklik yok) ---
@lru_cache(maxsize=128)
def get_stock_data(yf_ticker):
    try:
        hist = yf.Ticker(yf_ticker).history(period="2d")
        if len(hist) < 2: return 0.0
        return (hist['Close'].iloc[-1] - hist['Close'].iloc[-2]) / hist['Close'].iloc[-2] * 100
    except Exception:
        return 0.0

@lru_cache(maxsize=128)
def get_fund_data(fund_code):
    try:
        sdt = (date.today() - timedelta(days=10)).strftime('%d-%m-%Y')
        fdt = date.today().strftime('%d-%m-%Y')
        res = requests.get(f"https://www.tefas.gov.tr/api/DB/BindHistoryPrice?sdt={sdt}&fdt={fdt}&kod={fund_code}", timeout=10)
        res.raise_for_status()
        fund_data = [i for i in res.json() if i.get('BirimPayDegeri') is not None]
        if len(fund_data) < 2: return 0.0
        last, prev = fund_data[-1], fund_data[-2]
        return (last['BirimPayDegeri'] - prev['BirimPayDegeri']) / prev['BirimPayDegeri'] * 100
    except Exception:
        return 0.0

# --- YENİ: GÜVENLİ FLOAT ÇEVİRME FONKSİYONU ---
def safe_float(value):
    """Gelen değeri güvenli bir şekilde float'a çevirir, başarısız olursa 0.0 döner."""
    if value is None:
        return 0.0
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0

# --- GÜNCELLENDİ: Hesaplama Yardımcı Fonksiyonu ---
def calculate_portfolio_performance(portfolio_data):
    stocks = portfolio_data.get('stocks', [])
    funds = portfolio_data.get('funds', [])
    if not stocks and not funds:
        return 0.0, []

    total_portfolio_change = 0.0
    asset_details = []

    for stock in stocks:
        ticker = stock.get('ticker', '').strip().upper()
        # GÜNCELLENDİ: Artık güvenli çevirme fonksiyonunu kullanıyoruz
        weight = safe_float(stock.get('weight'))
        
        if not ticker or not weight > 0: continue
        
        daily_change = 0.0
        if ticker not in ['NAKIT', 'CASH', 'TAHVIL', 'BOND', 'DEVLET TAHVILI']:
            yf_ticker = ticker + '.IS' if not ticker.endswith('.IS') else ticker
            daily_change = get_stock_data(yf_ticker)
            
        total_portfolio_change += (weight / 100) * daily_change
        asset_details.append({'type': 'stock', 'ticker': ticker, 'daily_change': daily_change})

    for fund in funds:
        fund_code = fund.get('ticker', '').strip().upper()
        # GÜNCELLENDİ: Artık güvenli çevirme fonksiyonunu kullanıyoruz
        weight = safe_float(fund.get('weight'))

        if not fund_code or not weight > 0: continue

        daily_change = get_fund_data(fund_code)
        total_portfolio_change += (weight / 100) * daily_change
        asset_details.append({'type': 'fund', 'ticker': fund_code, 'daily_change': daily_change})
        
    return total_portfolio_change, asset_details

# --- Dashboard ve Diğer Endpoint'ler (Değişiklik yok) ---
@app.route('/get_dashboard_data', methods=['GET'])
def get_dashboard_data():
    try:
        portfolios = load_portfolios()
        portfolios_with_details = []
        
        for name, data in portfolios.items():
            if 'current' in data and data['current']:
                total_change, asset_details = calculate_portfolio_performance(data['current'])
                stocks_in_portfolio = [
                    asset for asset in asset_details 
                    if asset['type'] == 'stock' and asset['ticker'] not in ['NAKIT', 'CASH', 'TAHVIL', 'BOND', 'DEVLET TAHVILI']
                ]
                stocks_in_portfolio.sort(key=lambda x: x['daily_change'], reverse=True)
                top_stocks = stocks_in_portfolio[:2]
                bottom_stocks = sorted([s for s in stocks_in_portfolio if s['daily_change'] < 0], key=lambda x: x['daily_change'])[:2]
                portfolios_with_details.append({
                    'name': name,
                    'change': total_change,
                    'top_stocks': top_stocks,
                    'bottom_stocks': bottom_stocks
                })

        portfolios_with_details.sort(key=lambda x: x['change'], reverse=True)
        return jsonify({'sorted_portfolios': portfolios_with_details})
    except Exception as e:
        # Hata oluşursa sunucu loglarına yazdır ve istemciye bir hata mesajı gönder.
        print(f"Dashboard verisi oluşturulurken ciddi bir hata oluştu: {e}")
        return jsonify({'error': 'Sunucu tarafında bir hata oluştu.'}), 500

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/calculate', methods=['POST'])
def calculate():
    data = request.get_json()
    total_change, details = calculate_portfolio_performance(data)
    return jsonify({'total_change': total_change, 'details': details})

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
    if not portfolio_name:
        return jsonify({'error': 'Portföy adı belirtilmelidir.'}), 400
    
    # Sunucu tarafında da temel doğrulama yapalım
    stocks = data.get('stocks', [])
    funds = data.get('funds', [])
    if not stocks and not funds:
        return jsonify({'error': 'Portföyde en az bir varlık olmalıdır.'}), 400

    portfolios = load_portfolios()
    # Adı değişirse diye eski portföyü silmek için (opsiyonel ama iyi bir pratik)
    original_name = data.get('original_name')
    if original_name and original_name != portfolio_name and original_name in portfolios:
        del portfolios[original_name]
        
    portfolio_container = portfolios.get(portfolio_name, {'current': None, 'history': []})
    if portfolio_container.get('current'):
        previous_version = portfolio_container['current']
        previous_version['save_timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        portfolio_container['history'].insert(0, previous_version)
        portfolio_container['history'] = portfolio_container['history'][:5]

    new_current_version = {'name': portfolio_name, 'stocks': stocks, 'funds': funds}
    portfolio_container['current'] = new_current_version
    portfolios[portfolio_name] = portfolio_container
    
    save_portfolios(portfolios)
    return jsonify({'success': f'"{portfolio_name}" portföyü başarıyla kaydedildi.'})

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
