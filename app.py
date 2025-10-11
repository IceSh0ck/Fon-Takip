import os
import json
from flask import Flask, render_template, request, jsonify
import yfinance as yf
import requests
from datetime import date, timedelta, datetime
import pandas as pd

app = Flask(__name__)

PORTFOLIOS_FILE = 'portfolios.json'

# --- Portföy Kaydetme/Yükleme Fonksiyonları ---
def load_portfolios():
    if not os.path.exists(PORTFOLIOS_FILE):
        return {}
    try:
        with open(PORTFOLIOS_FILE, 'r', encoding='utf-8') as f:
            # GÜNCELLENDİ: json.load() doğrudan bir dict döndürecek
            portfolios_data = json.load(f)
            return portfolios_data
    except (json.JSONDecodeError, FileNotFoundError):
        return {}

def save_portfolios(portfolios_dict):
    with open(PORTFOLIOS_FILE, 'w', encoding='utf-8') as f:
        # GÜNCELLENDİ: Sözlüğün tamamını kaydet
        json.dump(portfolios_dict, f, indent=4, ensure_ascii=False)

# --- API Endpointleri ---
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
        # Sadece güncel versiyonu döndür
        return jsonify(portfolio_data['current'])
    elif portfolio_data: # Eski formatla uyumluluk için
        return jsonify(portfolio_data)
    return jsonify({'error': 'Portföy bulunamadı'}), 404

# GÜNCELLENDİ: Portföy kaydetme mantığı artık versiyonlama yapıyor
@app.route('/save_portfolio', methods=['POST'])
def save_portfolio():
    data = request.get_json()
    portfolio_name = data.get('name')
    stocks = data.get('stocks', [])
    funds = data.get('funds', [])
    
    if not portfolio_name or (not stocks and not funds):
        return jsonify({'error': 'Portföy adı ve en az bir varlık girilmelidir'}), 400

    portfolios = load_portfolios()
    
    # Mevcut portföy verisini al veya yeni oluştur
    existing_portfolio_data = portfolios.get(portfolio_name, {'current': None, 'history': []})
    
    # Eğer portföy eski yapıdaysa, yeni yapıya dönüştür
    if 'current' not in existing_portfolio_data:
        old_data = existing_portfolio_data.copy()
        existing_portfolio_data = {'current': old_data, 'history': []}

    # Eğer bir "current" versiyon varsa, bunu tarihle birlikte "history"e taşı
    if existing_portfolio_data.get('current'):
        previous_version = existing_portfolio_data['current']
        # 'save_date' anahtarının olmamasını kontrol et, sonsuz döngüyü engelle
        if 'save_date' not in previous_version:
             previous_version['save_date'] = date.today().strftime('%Y-%m-%d')
             existing_portfolio_data['history'].insert(0, previous_version) # En başa ekle

    # Gelen yeni veriyi "current" olarak ayarla
    new_current_version = {'name': portfolio_name, 'stocks': stocks, 'funds': funds}
    existing_portfolio_data['current'] = new_current_version

    portfolios[portfolio_name] = existing_portfolio_data
    save_portfolios(portfolios)
    
    return jsonify({'success': f'"{portfolio_name}" portföyü başarıyla kaydedildi. Değişiklikler geçmişe eklendi.'})

@app.route('/calculate', methods=['POST'])
def calculate():
    data = request.get_json()
    stocks = data.get('stocks', [])
    funds = data.get('funds', [])

    if not stocks and not funds:
        return jsonify({'error': 'Hesaplanacak veri gönderilmedi.'}), 400

    total_portfolio_change = 0.0
    asset_details = []

    for stock in stocks:
        ticker = stock.get('ticker').strip().upper()
        weight = float(stock.get('weight', 0))
        if ticker in ['NAKIT', 'CASH', 'TAHVIL', 'BOND', 'DEVLET TAHVILI']:
            asset_details.append({ 'type': 'stock', 'ticker': ticker.capitalize(), 'daily_change': 0.0, 'weighted_impact': 0.0 })
            continue
        yf_ticker = ticker + '.IS' if not ticker.endswith('.IS') else ticker
        try:
            hisse = yf.Ticker(yf_ticker)
            hist = hisse.history(period="2d")
            if len(hist) < 2:
                daily_change_percent = 0.0
            else:
                daily_change_percent = (hist['Close'].iloc[-1] - hist['Close'].iloc[-2]) / hist['Close'].iloc[-2] * 100
            weighted_change = (weight / 100) * daily_change_percent
            total_portfolio_change += weighted_change
            asset_details.append({ 'type': 'stock', 'ticker': ticker, 'daily_change': daily_change_percent, 'weighted_impact': weighted_change })
        except Exception:
            asset_details.append({ 'type': 'stock', 'ticker': ticker, 'daily_change': 0.0, 'weighted_impact': 0.0, 'error': 'Veri alınamadı' })

    today = date.today()
    start_date_tefas = today - timedelta(days=10) 
    sdt, fdt = start_date_tefas.strftime('%d-%m-%Y'), today.strftime('%d-%m-%Y')
    for fund in funds:
        fund_code = fund.get('ticker').strip().upper()
        weight = float(fund.get('weight', 0))
        try:
            tefas_url = f"https://www.tefas.gov.tr/api/DB/BindHistoryPrice?sdt={sdt}&fdt={fdt}&kod={fund_code}"
            response = requests.get(tefas_url, timeout=10)
            response.raise_for_status()
            fund_data = [item for item in response.json() if item.get('BirimPayDegeri') is not None]
            if len(fund_data) >= 2:
                last_price_info, prev_price_info = fund_data[-1], fund_data[-2]
                daily_change_percent = (last_price_info['BirimPayDegeri'] - prev_price_info['BirimPayDegeri']) / prev_price_info['BirimPayDegeri'] * 100
                date_range = f"{datetime.strptime(prev_price_info['Tarih'], '%Y-%m-%dT%H:%M:%S').strftime('%d.%m.%Y')} → {datetime.strptime(last_price_info['Tarih'], '%Y-%m-%dT%H:%M:%S').strftime('%d.%m.%Y')}"
            else:
                daily_change_percent, date_range = 0.0, "Yetersiz Veri"
            weighted_change = (weight / 100) * daily_change_percent
            total_portfolio_change += weighted_change
            asset_details.append({ 'type': 'fund', 'ticker': fund_code, 'daily_change': daily_change_percent, 'weighted_impact': weighted_change, 'date_range': date_range })
        except Exception:
            asset_details.append({ 'type': 'fund', 'ticker': fund_code, 'daily_change': 0.0, 'weighted_impact': 0.0, 'error': 'Veri alınamadı' })
    return jsonify({ 'total_change': total_portfolio_change, 'details': asset_details })

@app.route('/calculate_historical/<portfolio_name>', methods=['GET'])
def calculate_historical(portfolio_name):
    portfolios = load_portfolios()
    portfolio_container = portfolios.get(portfolio_name)
    if not portfolio_container:
        return jsonify({'error': 'Portföy bulunamadı'}), 404

    portfolio = portfolio_container.get('current')
    if not portfolio:
         return jsonify({'error': 'Portföyün güncel versiyonu bulunamadı.'}), 404

    end_date = date.today()
    start_date = end_date - timedelta(days=45)
    
    all_assets = portfolio.get('stocks', []) + portfolio.get('funds', [])
    if not all_assets:
        return jsonify({'error': 'Portföyde hesaplanacak varlık yok.'}), 400

    asset_prices_df = pd.DataFrame()
    
    stock_tickers = [s['ticker'].strip().upper() + '.IS' for s in portfolio.get('stocks', [])]
    if stock_tickers:
        try:
            stock_data = yf.download(stock_tickers, start=start_date, end=end_date, progress=False)
            if not stock_data.empty:
                asset_prices_df = pd.concat([asset_prices_df, stock_data['Close']], axis=1)
        except Exception as e:
            print(f"Hisse senedi verisi alınırken hata: {e}")

    sdt_str = start_date.strftime('%d-%m-%Y')
    fdt_str = end_date.strftime('%d-%m-%Y')
    for fund in portfolio.get('funds', []):
        fund_code = fund['ticker'].strip().upper()
        try:
            tefas_url = f"https://www.tefas.gov.tr/api/DB/BindHistoryPrice?sdt={sdt_str}&fdt={fdt_str}&kod={fund_code}"
            response = requests.get(tefas_url, timeout=10)
            fund_data = response.json()
            if fund_data:
                df = pd.DataFrame(fund_data)
                df['Tarih'] = pd.to_datetime(df['Tarih'])
                df = df.set_index('Tarih')[['BirimPayDegeri']].rename(columns={'BirimPayDegeri': fund_code})
                asset_prices_df = pd.concat([asset_prices_df, df], axis=1)
        except Exception as e:
            print(f"Fon verisi alınırken hata ({fund_code}): {e}")
    
    asset_prices_df = asset_prices_df.ffill().dropna()
    if asset_prices_df.empty:
        return jsonify({'error': 'Tarihsel veri bulunamadı.'}), 400
        
    daily_returns = asset_prices_df.pct_change()

    portfolio_daily_returns = []
    
    weights = {asset['ticker'].strip().upper(): float(asset['weight']) / 100 for asset in all_assets}

    for index, row in daily_returns.iterrows():
        daily_portfolio_return = 0
        for ticker, ret in row.items():
            clean_ticker = ticker.replace('.IS', '')
            if clean_ticker in weights:
                daily_portfolio_return += weights[clean_ticker] * ret
        if pd.notna(daily_portfolio_return):
            portfolio_daily_returns.append(daily_portfolio_return * 100)

    dates = daily_returns.index.strftime('%d.%m.%Y').tolist()[-30:]
    returns = portfolio_daily_returns[-30:]

    return jsonify({'dates': dates, 'returns': returns})

# YENİ: PORTFÖY AĞIRLIK DEĞİŞİMİ İÇİN YENİ ENDPOINT
@app.route('/compare_versions/<portfolio_name>', methods=['GET'])
def compare_versions(portfolio_name):
    portfolios = load_portfolios()
    portfolio_data = portfolios.get(portfolio_name)

    if not portfolio_data or not portfolio_data.get('current') or not portfolio_data.get('history'):
        return jsonify({'error': 'Karşılaştırma için yeterli geçmiş veri bulunamadı. Lütfen portföyü güncelleyip tekrar kaydedin.'}), 400

    current_version = portfolio_data['current']
    previous_version = portfolio_data['history'][0] # En son kaydedilen geçmiş

    current_assets = {a['ticker'].upper(): float(a['weight']) for a in current_version.get('stocks', []) + current_version.get('funds', [])}
    previous_assets = {a['ticker'].upper(): float(a['weight']) for a in previous_version.get('stocks', []) + previous_version.get('funds', [])}

    all_tickers = sorted(list(set(current_assets.keys()) | set(previous_assets.keys())))

    comparison_data = []
    for ticker in all_tickers:
        current_weight = current_assets.get(ticker, 0.0)
        previous_weight = previous_assets.get(ticker, 0.0)
        change = current_weight - previous_weight
        comparison_data.append({
            'ticker': ticker,
            'previous_weight': previous_weight,
            'current_weight': current_weight,
            'change': change
        })
    
    comparison_data.sort(key=lambda x: abs(x['change']), reverse=True)
    
    response_data = {
        'comparison': comparison_data,
        'current_date_str': date.today().strftime('%d.%m.%Y'),
        'previous_date_str': datetime.strptime(previous_version.get('save_date', '1970-01-01'), '%Y-%m-%d').strftime('%d.%m.%Y')
    }
    return jsonify(response_data)

# YENİ: PORTFÖY DEĞİŞİKLİĞİNİ GERİ ALMAK İÇİN ENDPOINT
@app.route('/revert_portfolio/<portfolio_name>', methods=['POST'])
def revert_portfolio(portfolio_name):
    portfolios = load_portfolios()
    portfolio_data = portfolios.get(portfolio_name)
    if not portfolio_data or not portfolio_data.get('history'):
        return jsonify({'error': 'Geri alınacak bir önceki versiyon bulunamadı.'}), 400

    # En son geçmiş versiyonu al ve onu current yap
    last_history_item = portfolio_data['history'].pop(0) 
    
    # save_date anahtarını silerek tekrar geçmişe eklenmesini sağla
    if 'save_date' in last_history_item:
        del last_history_item['save_date']
        
    portfolio_data['current'] = last_history_item
    
    portfolios[portfolio_name] = portfolio_data
    save_portfolios(portfolios)
    
    return jsonify({'success': f'"{portfolio_name}" portföyü bir önceki versiyona başarıyla geri alındı.'})


@app.route('/delete_portfolio', methods=['POST'])
def delete_portfolio():
    data = request.get_json()
    portfolio_name_to_delete = data.get('name')
    if not portfolio_name_to_delete:
        return jsonify({'error': 'Silinecek portföy adı belirtilmedi.'}), 400
    portfolios = load_portfolios()
    if portfolio_name_to_delete in portfolios:
        del portfolios[portfolio_name_to_delete]
        save_portfolios(portfolios)
        return jsonify({'success': f'"{portfolio_name_to_delete}" portföyü başarıyla silindi.'})
    else:
        return jsonify({'error': 'Silinecek portföy bulunamadı.'}), 404

if __name__ == '__main__':
    app.run(debug=True)
