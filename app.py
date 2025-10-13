import os
import json
from flask import Flask, render_template, request, jsonify
import yfinance as yf
import requests
from datetime import date, timedelta, datetime
import pandas as pd
from collections import defaultdict
from pymongo import MongoClient

app = Flask(__name__)

# --- MONGODB BAĞLANTISI ---
# Bağlantı bilgisini Render'daki ortam değişkeninden güvenli bir şekilde al
MONGO_URI = os.environ.get('DATABASE_URI')
client = MongoClient(MONGO_URI)
db = client['portfolio_db'] # Veritabanınızın adı
portfolios_collection = db['portfolios'] # Verilerinizin saklanacağı tablo (collection)

# --- VERİTABANI İŞLEMLERİ ---

def load_portfolios():
    """Veritabanından tüm portföyleri okur."""
    portfolios_from_db = portfolios_collection.find()
    portfolios_dict = {}
    for portfolio in portfolios_from_db:
        portfolio_name = portfolio.get('name')
        if portfolio_name:
            portfolio.pop('_id', None) # MongoDB'nin kendi ID'sini kaldır
            portfolios_dict[portfolio_name] = portfolio
    return portfolios_dict

def save_portfolios(portfolios_dict):
    """Veritabanına portföyleri yazar/günceller."""
    for name, data in portfolios_dict.items():
        query = {'name': name}
        data['name'] = name 
        portfolios_collection.update_one(query, {'$set': data}, upsert=True)

# --- API ENDPOINTLERİ ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/get_portfolios', methods=['GET'])
def get_portfolios():
    portfolios = load_portfolios()
    categorized_portfolios = defaultdict(list)
    for name, data in portfolios.items():
        category = data.get('current', {}).get('category', 'owned')
        categorized_portfolios[category].append(name)
    
    categorized_portfolios['owned'].sort()
    categorized_portfolios['tracked'].sort()
    return jsonify(categorized_portfolios)

@app.route('/get_portfolio/<portfolio_name>', methods=['GET'])
def get_portfolio(portfolio_name):
    # Veritabanından tek bir fonu bul
    portfolio_data = portfolios_collection.find_one({'name': portfolio_name})
    if portfolio_data and 'current' in portfolio_data:
        return jsonify(portfolio_data['current'])
    return jsonify({'error': 'Fon bulunamadı'}), 404

@app.route('/save_portfolio', methods=['POST'])
def save_portfolio():
    data = request.get_json()
    portfolio_name = data.get('name')
    stocks = data.get('stocks', [])
    funds = data.get('funds', [])
    category = data.get('category', 'owned')

    if not portfolio_name:
        return jsonify({'error': 'Fon adı girilmelidir'}), 400
        
    # Veritabanından mevcut kaydı al (varsa)
    portfolio_container = portfolios_collection.find_one({'name': portfolio_name})
    if not portfolio_container:
        portfolio_container = {'name': portfolio_name, 'current': None, 'history': []}

    if portfolio_container.get('current'):
        previous_version = portfolio_container['current']
        previous_version['save_timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        portfolio_container['history'].insert(0, previous_version)
        portfolio_container['history'] = portfolio_container['history'][:5]

    portfolio_container['current'] = {
        'name': portfolio_name, 
        'stocks': stocks, 
        'funds': funds,
        'category': category
    }
    
    # Veritabanına kaydet/güncelle
    portfolios_collection.update_one({'name': portfolio_name}, {'$set': portfolio_container}, upsert=True)
    return jsonify({'success': f'"{portfolio_name}" fonu başarıyla kaydedildi.'})

@app.route('/get_all_returns', methods=['GET'])
def get_all_returns():
    portfolios = load_portfolios()
    all_returns = []
    # ... (Bu fonksiyonun geri kalanı aynı, değişiklik yok)
    if not portfolios:
        return jsonify([])

    for name, data in portfolios.items():
        if 'current' not in data:
            continue
        
        current_portfolio = data['current']
        stocks = current_portfolio.get('stocks', [])
        funds = current_portfolio.get('funds', [])
        category = current_portfolio.get('category', 'owned')
        total_change = 0.0

        for stock in stocks:
            ticker, weight = stock.get('ticker').strip().upper(), float(stock.get('weight', 0))
            if ticker in ['NAKIT', 'CASH']: continue
            yf_ticker = ticker + '.IS'
            try:
                hist = yf.Ticker(yf_ticker).history(period="2d")
                if len(hist) >= 2:
                    daily_change = (hist['Close'].iloc[-1] - hist['Close'].iloc[-2]) / hist['Close'].iloc[-2] * 100
                    total_change += (weight / 100) * daily_change
            except Exception: pass
        
        sdt = (date.today() - timedelta(days=10)).strftime('%d-%m-%Y')
        fdt = date.today().strftime('%d-%m-%Y')
        for fund in funds:
            fund_code, weight = fund.get('ticker').strip().upper(), float(fund.get('weight', 0))
            try:
                res = requests.get(f"https://www.tefas.gov.tr/api/DB/BindHistoryPrice?sdt={sdt}&fdt={fdt}&kod={fund_code}", timeout=10)
                res.raise_for_status()
                fund_data = [i for i in res.json() if i.get('BirimPayDegeri') is not None]
                if len(fund_data) >= 2:
                    last, prev = fund_data[-1], fund_data[-2]
                    daily_change = (last['BirimPayDegeri'] - prev['BirimPayDegeri']) / prev['BirimPayDegeri'] * 100
                    total_change += (weight / 100) * daily_change
            except Exception: pass
        
        all_returns.append({'name': name, 'category': category, 'change': total_change})
    
    sorted_returns = sorted(all_returns, key=lambda x: x['change'], reverse=True)
    return jsonify(sorted_returns)


# Geri kalan tüm diğer fonksiyonlarınızda (get_portfolio_history, calculate, vb.)
# herhangi bir değişiklik yapmanıza gerek yoktur.

if __name__ == '__main__':
    app.run(debug=True)
