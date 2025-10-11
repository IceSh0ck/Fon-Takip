import os
import json
from flask import Flask, render_template, request, jsonify
import yfinance as yf
import requests
from datetime import date, timedelta, datetime
import pandas as pd

app = Flask(__name__)

PORTFOLIOS_FILE = 'portfolios.json'

# --- Veri Taşıma ve Yükleme Fonksiyonları (YENİ VE GÜVENLİ) ---

def migrate_portfolios_if_needed():
    """
    Uygulama başlangıcında çalışır. Eğer portfolios.json eski 'liste' formatındaysa,
    onu yeni 'versiyonlu sözlük' formatına tüm verileri koruyarak dönüştürür.
    """
    if not os.path.exists(PORTFOLIOS_FILE):
        return # Dosya yoksa yapılacak bir şey yok

    try:
        with open(PORTFOLIOS_FILE, 'r+', encoding='utf-8') as f:
            # Dosyanın boş olup olmadığını kontrol et
            first_char = f.read(1)
            if not first_char:
                return # Dosya boş

            f.seek(0) # Okuma imlecini başa al
            data = json.load(f)

            # Eğer veri eski formatta (liste) ise dönüşümü yap
            if isinstance(data, list):
                print("Eski portföy formatı algılandı, yeni formata geçiriliyor...")
                new_portfolios_dict = {}
                for portfolio in data:
                    portfolio_name = portfolio.get('name')
                    if portfolio_name:
                        # Her portföyü yeni versiyonlu yapıya sok
                        new_portfolios_dict[portfolio_name] = {
                            'current': portfolio,
                            'history': []
                        }
                
                # Dosyanın imlecini başa al ve üzerine yeni veriyi yaz
                f.seek(0)
                f.truncate()
                json.dump(new_portfolios_dict, f, indent=4, ensure_ascii=False)
                print("Portföy formatı başarıyla güncellendi.")
    except (json.JSONDecodeError, Exception) as e:
        print(f"Portföy dosyası okunurken veya taşınırken hata oluştu: {e}")


def load_portfolios():
    if not os.path.exists(PORTFOLIOS_FILE):
        return {}
    try:
        with open(PORTFOLIOS_FILE, 'r', encoding='utf-8') as f:
            # Dosya boşsa boş sözlük döndür
            content = f.read()
            if not content:
                return {}
            return json.loads(content)
    except (json.JSONDecodeError, FileNotFoundError):
        return {}

def save_portfolios(portfolios_dict):
    with open(PORTFOLIOS_FILE, 'w', encoding='utf-8') as f:
        json.dump(portfolios_dict, f, indent=4, ensure_ascii=False)

# DÜZELTİLDİ: Uygulama ilk başladığında veri taşıma fonksiyonunu çağır
migrate_portfolios_if_needed()


# --- API Endpointleri (ARTIK DAHA TEMİZ VE GÜVENLİ) ---
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
    # Artık tüm verinin yeni formatta olduğunu varsayabiliriz
    if portfolio_data and 'current' in portfolio_data:
        return jsonify(portfolio_data['current'])
    return jsonify({'error': 'Portföy bulunamadı'}), 404

# DÜZELTİLDİ: Karmaşık ve hatalı "anlık taşıma" mantığı kaldırıldı
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
    portfolio_container = portfolios.get(portfolio_name, {'current': None, 'history': []})
    
    # Mevcut bir 'current' varsa, bunu tarihle birlikte geçmişe taşı
    if portfolio_container.get('current'):
        previous_version = portfolio_container['current']
        previous_version['save_date'] = date.today().strftime('%Y-%m-%d')
        portfolio_container['history'].insert(0, previous_version) # En yeni geçmiş en başa

    # Gelen yeni veriyi 'current' olarak ayarla
    new_current_version = {'name': portfolio_name, 'stocks': stocks, 'funds': funds}
    portfolio_container['current'] = new_current_version

    portfolios[portfolio_name] = portfolio_container
    save_portfolios(portfolios)
    
    return jsonify({'success': f'"{portfolio_name}" portföyü başarıyla kaydedildi.'})


@app.route('/calculate', methods=['POST'])
def calculate():
    # Bu fonksiyonda değişiklik yok
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
            daily_change_percent = (hist['Close'].iloc[-1] - hist['Close'].iloc[-2]) / hist['Close'].iloc[-2] * 100 if len(hist) >= 2 else 0.0
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
    # Bu fonksiyonda değişiklik yok
    portfolios = load_portfolios()
    portfolio_container = portfolios.get(portfolio_name)
    if not portfolio_container: return jsonify({'error': 'Portföy bulunamadı'}), 404
    portfolio = portfolio_container.get('current')
    if not portfolio: return jsonify({'error': 'Portföyün güncel versiyonu bulunamadı.'}), 404
    end_date = date.today()
    start_date = end_date - timedelta(days=45)
    all_assets = portfolio.get('stocks', []) + portfolio.get('funds', [])
    if not all_assets: return jsonify({'error': 'Portföyde hesaplanacak varlık yok.'}), 400
    asset_prices_df = pd.DataFrame()
    stock_tickers = [s['ticker'].strip().upper() + '.IS' for s in portfolio.get('stocks', [])]
    if stock_tickers:
        try:
            stock_data = yf.download(stock_tickers, start=start_date, end=end_date, progress=False)['Close']
            if not stock_data.empty: asset_prices_df = pd.concat([asset_prices_df, stock_data], axis=1)
        except Exception as e: print(f"Hisse senedi verisi alınırken hata: {e}")
    sdt_str, fdt_str = start_date.strftime('%d-%m-%Y'), end_date.strftime('%d-%m-%Y')
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
        except Exception as e: print(f"Fon verisi alınırken hata ({fund_code}): {e}")
    asset_prices_df = asset_prices_df.ffill().dropna()
    if asset_prices_df.empty: return jsonify({'error': 'Tarihsel veri bulunamadı.'}), 400
    daily_returns = asset_prices_df.pct_change()
    weights = {asset['ticker'].strip().upper(): float(asset['weight']) / 100 for asset in all_assets}
    portfolio_daily_returns = (daily_returns * pd.Series(weights)).sum(axis=1) * 100
    valid_returns = portfolio_daily_returns.dropna()
    dates = valid_returns.index.strftime('%d.%m.%Y').tolist()[-30:]
    returns = valid_returns.tolist()[-30:]
    return jsonify({'dates': dates, 'returns': returns})


@app.route('/compare_versions/<portfolio_name>', methods=['GET'])
def compare_versions(portfolio_name):
    # Bu fonksiyonda değişiklik yok
    portfolios = load_portfolios()
    portfolio_data = portfolios.get(portfolio_name)
    if not portfolio_data or not portfolio_data.get('current') or not portfolio_data.get('history'):
        return jsonify({'error': 'Karşılaştırma için yeterli geçmiş veri bulunamadı.'}), 400
    current_version = portfolio_data['current']
    previous_version = portfolio_data['history'][0]
    current_assets = {a['ticker'].upper(): float(a['weight']) for a in current_version.get('stocks', []) + current_version.get('funds', [])}
    previous_assets = {a['ticker'].upper(): float(a['weight']) for a in previous_version.get('stocks', []) + previous_version.get('funds', [])}
    all_tickers = sorted(list(set(current_assets.keys()) | set(previous_assets.keys())))
    comparison_data = []
    for ticker in all_tickers:
        current_weight = current_assets.get(ticker, 0.0)
        previous_weight = previous_assets.get(ticker, 0.0)
        change = current_weight - previous_weight
        comparison_data.append({'ticker': ticker, 'previous_weight': previous_weight, 'current_weight': current_weight, 'change': change})
    comparison_data.sort(key=lambda x: abs(x['change']), reverse=True)
    response_data = {
        'comparison': comparison_data,
        'current_date_str': date.today().strftime('%d.%m.%Y'),
        'previous_date_str': datetime.strptime(previous_version.get('save_date', '1970-01-01'), '%Y-%m-%d').strftime('%d.%m.%Y')
    }
    return jsonify(response_data)


@app.route('/revert_portfolio/<portfolio_name>', methods=['POST'])
def revert_portfolio(portfolio_name):
    # Bu fonksiyonda değişiklik yok
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
def delete_portfolio(portfolio_name): # Düzeltme: URL'den isim almak daha standart
    # Bu fonksiyonda değişiklik yok
    portfolios = load_portfolios()
    if portfolio_name in portfolios:
        del portfolios[portfolio_name]
        save_portfolios(portfolios)
        return jsonify({'success': f'"{portfolio_name}" portföyü başarıyla silindi.'})
    else:
        return jsonify({'error': 'Silinecek portföy bulunamadı.'}), 404

if __name__ == '__main__':
    app.run(debug=True)
