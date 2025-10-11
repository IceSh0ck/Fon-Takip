import os
import json
from flask import Flask, render_template, request, jsonify
import yfinance as yf
import requests
from datetime import date, timedelta, datetime
import pandas as pd

app = Flask(__name__)

PORTFOLIOS_FILE = 'portfolios.json'

# --- Portföy Kaydetme/Yükleme Fonksiyonları (Değişiklik yok) ---
def load_portfolios():
    if not os.path.exists(PORTFOLIOS_FILE):
        return {}
    try:
        with open(PORTFOLIOS_FILE, 'r', encoding='utf-8') as f:
            portfolios_list = json.load(f)
            return {p['name']: p for p in portfolios_list}
    except (json.JSONDecodeError, FileNotFoundError):
        return {}

def save_portfolios(portfolios_dict):
    with open(PORTFOLIOS_FILE, 'w', encoding='utf-8') as f:
        json.dump(list(portfolios_dict.values()), f, indent=4, ensure_ascii=False)

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


# YENİ: DÜZENLENMİŞ VE İÇİ DOLDURULMUŞ FONKSİYON
@app.route('/calculate_historical/<portfolio_name>', methods=['GET'])
def calculate_historical(portfolio_name):
    portfolios = load_portfolios()
    portfolio = portfolios.get(portfolio_name)
    if not portfolio:
        return jsonify({'error': 'Portföy bulunamadı'}), 404

    end_date = date.today()
    start_date = end_date - timedelta(days=45) # Hafta sonları ve tatilleri telafi etmek için daha geniş aralık
    
    all_assets = portfolio.get('stocks', []) + portfolio.get('funds', [])
    if not all_assets:
        return jsonify({'error': 'Portföyde hesaplanacak varlık yok.'}), 400

    asset_prices_df = pd.DataFrame()
    
    # Hisse verilerini çek
    stock_tickers = [s['ticker'].strip().upper() + '.IS' for s in portfolio.get('stocks', [])]
    if stock_tickers:
        try:
            stock_data = yf.download(stock_tickers, start=start_date, end=end_date, progress=False)
            if not stock_data.empty:
                asset_prices_df = pd.concat([asset_prices_df, stock_data['Close']], axis=1)
        except Exception as e:
            print(f"Hisse senedi verisi alınırken hata: {e}")

    # Fon verilerini çek
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
    
    # Ağırlıkları bir sözlükte topla
    weights = {asset['ticker'].strip().upper(): float(asset['weight']) / 100 for asset in all_assets}

    for index, row in daily_returns.iterrows():
        daily_portfolio_return = 0
        for ticker, ret in row.items():
            # Ticker'ları .IS olmadan eşleştir
            clean_ticker = ticker.replace('.IS', '')
            if clean_ticker in weights:
                daily_portfolio_return += weights[clean_ticker] * ret
        if pd.notna(daily_portfolio_return):
            portfolio_daily_returns.append(daily_portfolio_return * 100) # Yüzde olarak

    # Son 30 işlem gününü al
    dates = daily_returns.index.strftime('%d.%m.%Y').tolist()[-30:]
    returns = portfolio_daily_returns[-30:]

    return jsonify({'dates': dates, 'returns': returns})


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
