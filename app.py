import os
import json
from flask import Flask, render_template, request, jsonify
import yfinance as yf
import requests
from datetime import date, timedelta

app = Flask(__name__)

# --- DOSYA YOLU AYARI (SUNUCU İÇİN ÖNEMLİ) ---
path = os.path.dirname(os.path.abspath(__file__))
PORTFOLIOS_FILE = os.path.join(path, 'portfolios.json')

# --- Portföy Kaydetme/Yükleme Fonksiyonları ---
def load_portfolios():
    if not os.path.exists(PORTFOLIOS_FILE):
        with open(PORTFOLIOS_FILE, 'w', encoding='utf-8') as f:
            json.dump([], f)
        return {}
    try:
        with open(PORTFOLIOS_FILE, 'r', encoding='utf-8') as f:
            # Dosya boşsa hata vermemesi için kontrol
            content = f.read()
            if not content:
                return {}
            portfolios_list = json.loads(content)
            return {p['name']: p for p in portfolios_list}
    except (json.JSONDecodeError, FileNotFoundError):
        return {}

def save_portfolios(portfolios_dict):
    with open(PORTFOLIOS_FILE, 'w', encoding='utf-8') as f:
        json.dump(list(portfolios_dict.values()), f, indent=4, ensure_ascii=False)

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
    portfolio = portfolios.get(portfolio_name)
    if portfolio:
        return jsonify(portfolio)
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
    portfolios[portfolio_name] = {'name': portfolio_name, 'stocks': stocks, 'funds': funds}
    save_portfolios(portfolios)
    return jsonify({'success': f'"{portfolio_name}" portföyü başarıyla kaydedildi.'})

# --- YENİ SİLME FONKSİYONU ---
@app.route('/delete_portfolio/<portfolio_name>', methods=['DELETE'])
def delete_portfolio(portfolio_name):
    portfolios = load_portfolios()
    if portfolio_name in portfolios:
        del portfolios[portfolio_name]
        save_portfolios(portfolios)
        return jsonify({'success': f'"{portfolio_name}" portföyü başarıyla silindi.'})
    else:
        return jsonify({'error': 'Silinecek portföy bulunamadı'}), 404


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
            total_portfolio_change += 0.0
            asset_details.append({ 'type': 'stock', 'ticker': ticker.capitalize(), 'daily_change': 0.0, 'weighted_impact': 0.0 })
            continue
        yf_ticker = ticker + '.IS' if not ticker.endswith('.IS') else ticker
        try:
            hisse = yf.Ticker(yf_ticker)
            hist = hisse.history(period="2d")
            if len(hist) < 2: daily_change_percent = 0.0
            else: daily_change_percent = (hist['Close'].iloc[-1] - hist['Close'].iloc[-2]) / hist['Close'].iloc[-2] * 100
            weighted_change = (weight / 100) * daily_change_percent
            total_portfolio_change += weighted_change
            asset_details.append({ 'type': 'stock', 'ticker': ticker, 'daily_change': round(daily_change_percent, 2), 'weighted_impact': round(weighted_change, 2) })
        except Exception: return jsonify({'error': f'"{ticker}" hisse kodu için Yahoo Finance verisi alınamadı.'}), 400
    
    today = date.today()
    start_date = today - timedelta(days=15)
    sdt = start_date.strftime('%d-%m-%Y')
    fdt = today.strftime('%d-%m-%Y')
    for fund in funds:
        fund_code = fund.get('ticker').strip().upper()
        weight = float(fund.get('weight', 0))
        try:
            tefas_url = f"https://www.tefas.gov.tr/api/DB/BindHistoryPrice?sdt={sdt}&fdt={fdt}&kod={fund_code}"
            response = requests.get(tefas_url, timeout=10)
            response.raise_for_status()
            fund_data = [item for item in response.json() if item.get('BirimPayDegeri') is not None]
            if len(fund_data) >= 2:
                last_price_info = fund_data[-1]
                prev_price_info = fund_data[-2]
                daily_change_percent = (last_price_info['BirimPayDegeri'] - prev_price_info['BirimPayDegeri']) / prev_price_info['BirimPayDegeri'] * 100
                prev_date_str = prev_price_info['Tarih'].split('T')[0].split('-')
                last_date_str = last_price_info['Tarih'].split('T')[0].split('-')
                date_range = f"{prev_date_str[2]}.{prev_date_str[1]}.{prev_date_str[0]} → {last_date_str[2]}.{last_date_str[1]}.{last_date_str[0]}"
            else:
                daily_change_percent = 0.0
                date_range = "Yetersiz Veri"
            weighted_change = (weight / 100) * daily_change_percent
            total_portfolio_change += weighted_change
            asset_details.append({ 'type': 'fund', 'ticker': fund_code, 'daily_change': round(daily_change_percent, 2), 'weighted_impact': round(weighted_change, 2), 'date_range': date_range })
        except Exception: return jsonify({'error': f'"{fund_code}" fonu için TEFAS verisi alınamadı.'}), 400
    return jsonify({ 'total_change': round(total_portfolio_change, 2), 'details': asset_details })

if __name__ == '__main__':
    app.run(debug=True)
