import os
import json
from flask import Flask, render_template, request, jsonify
import yfinance as yf
import requests
from datetime import date, timedelta, datetime
import pandas as pd
import pdfplumber

app = Flask(__name__)

PORTFOLIOS_FILE = 'portfolios.json'

# --- Veri Taşıma ve Yükleme Fonksiyonları ---
def migrate_portfolios_if_needed():
    if not os.path.exists(PORTFOLIOS_FILE): return
    try:
        with open(PORTFOLIOS_FILE, 'r+', encoding='utf-8') as f:
            first_char = f.read(1)
            if not first_char: return
            f.seek(0)
            data = json.load(f)
            if isinstance(data, list):
                print("Eski portföy formatı algılandı, yeni formata geçiriliyor...")
                new_portfolios_dict = {}
                for portfolio in data:
                    portfolio_name = portfolio.get('name')
                    if portfolio_name:
                        new_portfolios_dict[portfolio_name] = {'current': portfolio, 'history': []}
                f.seek(0)
                f.truncate()
                json.dump(new_portfolios_dict, f, indent=4, ensure_ascii=False)
                print("Portföy formatı başarıyla güncellendi.")
    except (json.JSONDecodeError, Exception) as e:
        print(f"Portföy dosyası okunurken veya taşınırken hata oluştu: {e}")

def load_portfolios():
    if not os.path.exists(PORTFOLIOS_FILE): return {}
    try:
        with open(PORTFOLIOS_FILE, 'r', encoding='utf-8') as f:
            content = f.read()
            return json.loads(content) if content else {}
    except (json.JSONDecodeError, FileNotFoundError):
        return {}

def save_portfolios(portfolios_dict):
    with open(PORTFOLIOS_FILE, 'w', encoding='utf-8') as f:
        json.dump(portfolios_dict, f, indent=4, ensure_ascii=False)

migrate_portfolios_if_needed()

# --- API Endpointleri ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/get_portfolios', methods=['GET'])
def get_portfolios():
    portfolios = load_portfolios()
    return jsonify(sorted(list(portfolios.keys())))

# --- DÜZELTME: Bu fonksiyonun doğru çalışması için eksik mantık eklendi ---
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
        previous_version['save_date'] = date.today().strftime('%Y-%m-%d')
        portfolio_container['history'].insert(0, previous_version)
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

@app.route('/compare_versions/<portfolio_name>', methods=['GET'])
def compare_versions(portfolio_name):
    portfolios = load_portfolios()
    portfolio_data = portfolios.get(portfolio_name)
    if not portfolio_data or not portfolio_data.get('current') or not portfolio_data.get('history'):
        return jsonify({'error': 'Karşılaştırma için yeterli geçmiş veri bulunamadı.'}), 400
    current_version, previous_version = portfolio_data['current'], portfolio_data['history'][0]
    current_assets = {a['ticker'].upper(): float(a['weight']) for a in current_version.get('stocks', []) + current_version.get('funds', [])}
    previous_assets = {a['ticker'].upper(): float(a['weight']) for a in previous_version.get('stocks', []) + previous_version.get('funds', [])}
    all_tickers = sorted(list(set(current_assets.keys()) | set(previous_assets.keys())))
    comparison_data = []
    for ticker in all_tickers:
        current, previous = current_assets.get(ticker, 0.0), previous_assets.get(ticker, 0.0)
        comparison_data.append({'ticker': ticker, 'previous_weight': previous, 'current_weight': current, 'change': current - previous})
    comparison_data.sort(key=lambda x: abs(x['change']), reverse=True)
    response_data = {'comparison': comparison_data, 'current_date_str': date.today().strftime('%d.%m.%Y'), 'previous_date_str': datetime.strptime(previous_version.get('save_date', '1970-01-01'), '%Y-%m-%d').strftime('%d.%m.%Y')}
    return jsonify(response_data)

@app.route('/revert_portfolio/<portfolio_name>', methods=['POST'])
def revert_portfolio(portfolio_name):
    portfolios = load_portfolios()
    portfolio_data = portfolios.get(portfolio_name)
    if not portfolio_data or not portfolio_data.get('history'):
        return jsonify({'error': 'Geri alınacak bir önceki versiyon bulunamadı.'}), 400
    last_history_item = portfolio_data['history'].pop(0)
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

# --- GÜVENLİ PDF İŞLEME ENDPOINT'İ ---
@app.route('/upload_pdf', methods=['POST'])
def upload_pdf():
    if 'pdf_file' not in request.files:
        return jsonify({'error': 'Sunucuya dosya gönderilmedi.'}), 400
    
    file = request.files['pdf_file']
    if file.filename == '' or not file.filename.lower().endswith('.pdf'):
        return jsonify({'error': 'Lütfen geçerli bir PDF dosyası seçin.'}), 400

    # --- BU TRY-EXCEPT BLOĞU SUNUCUNUN ÇÖKMESİNİ ENGELLER ---
    try:
        with pdfplumber.open(file) as pdf:
            all_text = ""
            tables = []
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text: all_text += page_text + "\n"
                tables.extend(page.extract_tables())

        portfolio_name = "PDF'ten Okunan Portföy"
        for line in all_text.split('\n'):
            if "Fonun Unvanı" in line:
                potential_name = line.split(':')[-1].strip()
                if len(potential_name) > 5:
                    portfolio_name = potential_name
                    break
        
        assets = []
        found_table = False
        for table in tables:
            for row in table:
                if not row or len(row) < 2: continue
                
                ticker = row[0].split('\n')[0].strip() if row[0] else ''
                weight_str = None
                
                for cell in reversed(row):
                    if cell and isinstance(cell, str) and '%' in cell:
                        weight_str = cell.replace('%', '').replace(',', '.').strip()
                        break
                if not weight_str and row[-1] and isinstance(row[-1], str):
                    weight_str = row[-1].replace(',', '.').strip()

                if ticker and weight_str:
                    try:
                        weight = float(weight_str)
                        clean_ticker = ''.join(filter(str.isalpha, ticker.split(' ')[0]))
                        if 3 <= len(clean_ticker) <= 5 and weight > 0:
                            assets.append({'ticker': clean_ticker.upper(), 'weight': weight})
                            found_table = True
                    except (ValueError, TypeError):
                        continue
        
        if not found_table:
            return jsonify({'error': 'PDF içinden geçerli bir varlık tablosu okunamadı. Lütfen KAP PDR raporu olduğundan emin olun.'}), 400

        stocks = [a for a in assets if len(a['ticker']) > 3]
        funds = [a for a in assets if len(a['ticker']) == 3]

        return jsonify({'name': portfolio_name, 'stocks': stocks, 'funds': funds})

    except Exception as e:
        print(f"PDF işlenirken kritik bir hata oluştu: {e}")
        return jsonify({'error': f'Yüklenen PDF dosyası okunamadı. Lütfen dosyanın bozuk olmadığını veya geçerli bir KAP raporu olduğunu kontrol edin.'}), 500

if __name__ == '__main__':
    app.run(debug=True)
