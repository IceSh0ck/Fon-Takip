import os
import json
from flask import Flask, render_template, request, jsonify
import yfinance as yf
import requests
from datetime import date, timedelta, datetime

app = Flask(__name__)

PORTFOLIOS_FILE = 'portfolios.json'

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

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/get_portfolios', methods=['GET'])
def get_portfolios():
    portfolios = load_portfolios()
    return jsonify(sorted(list(portfolios.keys())))

@app.route('/get_all_portfolios', methods=['GET'])
def get_all_portfolios():
    portfolios = load_portfolios()
    return jsonify(list(portfolios.values()))

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

@app.route('/calculate', methods=['POST'])
def calculate():
    data = request.get_json()
    stocks = data.get('stocks', [])
    funds = data.get('funds', [])
    total_portfolio_change = 0.0
    asset_details = []
    total_weight = sum(float(s.get('weight', 0)) for s in stocks) + sum(float(f.get('weight', 0)) for f in funds)
    if total_weight == 0: total_weight = 100
    for stock in stocks:
        try:
            ticker = stock.get('ticker').strip().upper()
            weight = float(stock.get('weight', 0))
            if ticker in ['NAKIT', 'CASH', 'TAHVIL', 'BOND', 'DEVLET TAHVILI']:
                asset_details.append({ 'type': 'stock', 'ticker': ticker.capitalize(), 'daily_change': 0.0, 'weighted_impact': 0.0 })
                continue
            yf_ticker = ticker + '.IS'
            hist = yf.Ticker(yf_ticker).history(period="2d")
            daily_change_percent = (hist['Close'].iloc[-1] - hist['Close'].iloc[-2]) / hist['Close'].iloc[-2] * 100 if len(hist) >= 2 else 0.0
            weighted_impact = (weight / total_weight) * daily_change_percent
            total_portfolio_change += weighted_impact
            asset_details.append({ 'type': 'stock', 'ticker': ticker, 'daily_change': daily_change_percent, 'weighted_impact': weighted_impact })
        except Exception:
             asset_details.append({ 'type': 'stock', 'ticker': stock.get('ticker'), 'daily_change': 0.0, 'weighted_impact': 0.0, 'error': 'Veri alınamadı' })
    today, start_date = date.today(), date.today() - timedelta(days=15)
    sdt, fdt = start_date.strftime('%d-%m-%Y'), today.strftime('%d-%m-%Y')
    for fund in funds:
        try:
            fund_code = fund.get('ticker').strip().upper()
            weight = float(fund.get('weight', 0))
            tefas_url = f"https://www.tefas.gov.tr/api/DB/BindHistoryPrice?sdt={sdt}&fdt={fdt}&kod={fund_code}"
            response = requests.get(tefas_url, timeout=10)
            fund_data = [item for item in response.json() if item.get('BirimPayDegeri') is not None]
            date_range = "Yetersiz Veri"
            if len(fund_data) >= 2:
                last_price_info, prev_price_info = fund_data[-1], fund_data[-2]
                daily_change_percent = (last_price_info['BirimPayDegeri'] - prev_price_info['BirimPayDegeri']) / prev_price_info['BirimPayDegeri'] * 100
                date_range = f"{datetime.strptime(prev_price_info['Tarih'], '%Y-%m-%dT%H:%M:%S').strftime('%d.%m.%Y')} → {datetime.strptime(last_price_info['Tarih'], '%Y-%m-%dT%H:%M:%S').strftime('%d.%m.%Y')}"
            else:
                daily_change_percent = 0.0
            weighted_impact = (weight / total_weight) * daily_change_percent
            total_portfolio_change += weighted_impact
            asset_details.append({ 'type': 'fund', 'ticker': fund_code, 'daily_change': daily_change_percent, 'weighted_impact': weighted_impact, 'date_range': date_range })
        except Exception:
            asset_details.append({ 'type': 'fund', 'ticker': fund.get('ticker'), 'daily_change': 0.0, 'weighted_impact': 0.0, 'error': 'Veri alınamadı' })
    return jsonify({ 'total_change': total_portfolio_change, 'details': asset_details })

# DÜZELTİLDİ: Bu fonksiyonun içi doğru mantıkla dolduruldu.
@app.route('/calculate_historical/<portfolio_name>', methods=['GET'])
def calculate_historical(portfolio_name):
    portfolios = load_portfolios()
    portfolio = portfolios.get(portfolio_name)
    if not portfolio:
        return jsonify({'error': 'Portföy bulunamadı'}), 404
    stocks = portfolio.get('stocks', [])
    funds = portfolio.get('funds', [])
    daily_returns = []
    end_date = date.today()
    start_date = end_date - timedelta(days=45)
    stock_history_data = {}
    for stock in stocks:
        ticker = stock.get('ticker').strip().upper()
        if ticker not in ['NAKIT', 'CASH', 'TAHVIL', 'BOND', 'DEVLET TAHVILI'] and ticker:
            try:
                hist = yf.Ticker(ticker + '.IS').history(start=start_date, end=end_date)
                stock_history_data[ticker] = {k.date(): v for k, v in hist['Close'].to_dict().items()}
            except Exception:
                stock_history_data[ticker] = {}
    fund_history_data = {}
    sdt_str, fdt_str = start_date.strftime('%d-%m-%Y'), end_date.strftime('%d-%m-%Y')
    for fund in funds:
        fund_code = fund.get('ticker').strip().upper()
        if fund_code:
            try:
                tefas_url = f"https://www.tefas.gov.tr/api/DB/BindHistoryPrice?sdt={sdt_str}&fdt={fdt_str}&kod={fund_code}"
                response = requests.get(tefas_url, timeout=10)
                fund_history_data[fund_code] = { datetime.strptime(item['Tarih'], '%Y-%m-%dT%H:%M:%S').date(): item['BirimPayDegeri'] for item in response.json() if item.get('BirimPayDegeri') is not None }
            except Exception:
                fund_history_data[fund_code] = {}
    total_weight = sum(float(s.get('weight', 0)) for s in stocks) + sum(float(f.get('weight', 0)) for f in funds)
    if total_weight == 0: total_weight = 100
    
    checked_dates = set()
    for i in range(1, 35):
        day_to_check = end_date - timedelta(days=i)
        if day_to_check.weekday() >= 5: continue # Hafta sonunu atla
        
        day_return = 0.0
        is_valid_day = False

        # Bir önceki işlem gününü bul
        prev_day_to_check = day_to_check - timedelta(days=1)
        while prev_day_to_check.weekday() >= 5:
            prev_day_to_check -= timedelta(days=1)

        for stock in stocks:
            weight = float(stock.get('weight', 0))
            ticker = stock.get('ticker').strip().upper()
            if ticker in stock_history_data:
                current_price = stock_history_data[ticker].get(day_to_check)
                prev_price = stock_history_data[ticker].get(prev_day_to_check)
                if current_price and prev_price and prev_price > 0:
                    day_return += (weight / total_weight) * ((current_price - prev_price) / prev_price * 100)
                    is_valid_day = True
        for fund in funds:
            weight = float(fund.get('weight', 0))
            fund_code = fund.get('ticker').strip().upper()
            if fund_code in fund_history_data:
                current_price = fund_history_data[fund_code].get(day_to_check)
                prev_price = fund_history_data[fund_code].get(prev_day_to_check)
                if current_price and prev_price and prev_price > 0:
                    day_return += (weight / total_weight) * ((current_price - prev_price) / prev_price * 100)
                    is_valid_day = True
        
        if is_valid_day and day_to_check not in checked_dates:
            daily_returns.append({"date": day_to_check.strftime('%d.%m.%Y'), "return": f"{day_return:.2f}"})
            checked_dates.add(day_to_check)
            if len(daily_returns) >= 30:
                break

    return jsonify(sorted(daily_returns, key=lambda x: datetime.strptime(x['date'], '%d.%m.%Y'), reverse=True))

if __name__ == '__main__':
    app.run(debug=True)
