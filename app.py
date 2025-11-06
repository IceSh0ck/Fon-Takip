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
# (Bu bölümde değişiklik yok)

def load_portfolios():
    """Supabase veritabanından tüm portföyleri yükler."""
    try:
        response = supabase.table('portfolios').select('name, data').execute()
        
        portfolios_dict = {}
        for row in response.data:
            if row.get('data') and row['data'].get('current'):
                portfolios_dict[row['name']] = row['data']
            elif row.get('data') and 'stocks' in row['data']: 
                print(f"Eski yapı tespit edildi: {row['name']}. 'current' içine taşınıyor...")
                portfolios_dict[row['name']] = {'current': row['data'], 'history': []}
            else:
                print(f"Geçersiz veri yapısı atlanıyor: {row['name']}")

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

# GÜNCELLENDİ: Bu fonksiyon artık 'funds' parametresini alsa da HİÇBİR ŞEKİLDE KULLANMAZ.
# Tüm TEFAS API çağrıları ve fon döngüsü kaldırıldı.
def _calculate_portfolio_return(stocks, funds):
    """
    Verilen hisse listesi için portföy getirisini hesaplar.
    'funds' parametresi artık YALNIZCA HİSSE SENETLERİ üzerinden hesaplama yapar.
    """
    total_portfolio_change, asset_details = 0.0, []
    
    for stock in stocks:
        ticker, weight = stock.get('ticker', '').strip().upper(), float(stock.get('weight', 0))
        
        # YENİ: Borsa tipini al (varsayılan 'bist')
        borsa_tipi = stock.get('borsa_tipi', 'bist') 
        
        if not ticker or weight == 0: continue
        
        if ticker in ['NAKIT', 'CASH', 'TAHVIL', 'BOND', 'DEVLET TAHVILI']:
            asset_details.append({'type': 'stock', 'ticker': ticker.capitalize(), 'daily_change': 0.0, 'weighted_impact': 0.0})
            continue
            
        if borsa_tipi == 'bist':
            yf_ticker = ticker + '.IS'
        else: # 'yabanci' ise
            yf_ticker = ticker
            
        try:
            # --- YENİ HESAPLAMA YÖNTEMİ ---
            t = yf.Ticker(yf_ticker)
            info = t.info

            # 1. Gerçek "Dünkü Kapanış" fiyatını al
            prev_close = info.get('previousClose')
            if prev_close is None:
                hist_2d = t.history(period="2d")
                if len(hist_2d) < 2:
                    raise Exception(f"'{ticker}' için 'previousClose' (dünkü kapanış) verisi alınamadı.")
                prev_close = hist_2d['Close'].iloc[-2]
                
            # 2. En "Son Fiyat"ı al (Anlık veya son kapanış)
            latest_price = info.get('currentPrice', info.get('regularMarketPrice'))
            if latest_price is None:
                hist_1d = t.history(period="1d")
                if hist_1d.empty:
                    raise Exception(f"'{ticker}' için son fiyat (latest price) alınamadı.")
                latest_price = hist_1d['Close'].iloc[-1]

            # 3. Hesaplamayı yap
            daily_change = ((latest_price - prev_close) / prev_close) * 100
            
            total_portfolio_change += (weight / 100) * daily_change
            asset_details.append({'type': 'stock', 'ticker': ticker, 'daily_change': daily_change, 'weighted_impact': (weight / 100) * daily_change})
            # --- YENİ HESAPLAMA SONU ---

        except Exception as e:
            print(f"Hata (_calculate_portfolio_return, {ticker}): {e}") 
            asset_details.append({'type': 'stock', 'ticker': ticker, 'daily_change': 0.0, 'weighted_impact': 0.0, 'error': 'Veri alınamadı'})
    
    # --- TEFAS İLE İLGİLİ TÜM BLOK KALDIRILDI ---
            
    return {'total_change': total_portfolio_change, 'details': asset_details}

# --- API ENDPOINT'LERİ ---
# (Değişiklik yok)
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/get_portfolios', methods=['GET'])
def get_portfolios():
    portfolios = load_portfolios()
    
    portfolio_list = []
    for name, data_container in portfolios.items():
        current_data = data_container.get('current')
        
        if current_data:
            portfolio_list.append({
                'name': current_data.get('name', name), 
                'fonTipi': current_data.get('fonTipi'), 
                'altKategori': current_data.get('altKategori'),
                'yonetim_tipi': current_data.get('yonetim_tipi')
            })
        else:
            portfolio_list.append({
                'name': name, 
                'fonTipi': None, 
                'altKategori': None,
                'yonetim_tipi': None
            })

    sorted_list = sorted(portfolio_list, key=lambda p: p['name'])
    return jsonify(sorted_list)


@app.route('/get_portfolio/<portfolio_name>', methods=['GET'])
def get_portfolio(portfolio_name):
    portfolios = load_portfolios()
    portfolio_data = portfolios.get(portfolio_name)
    if portfolio_data and 'current' in portfolio_data:
        return jsonify(portfolio_data['current'])
    return jsonify({'error': 'Portföy bulunamadı'}), 404

@app.route('/save_portfolio', methods=['POST'])
def save_portfolio():
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({'error': 'Geçersiz istek. JSON verisi veya Content-Type başlığı eksik.'}), 400

    portfolio_name = data.get('name')
    fonTipi = data.get('fonTipi')
    altKategori = data.get('altKategori')
    yonetim_tipi = data.get('yonetim_tipi')
    
    # Veri hala 'funds' olarak kaydedilir, ancak hesaplamalarda kullanılmaz.
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

    new_current_version = {
        'name': portfolio_name, 
        'fonTipi': fonTipi,  
        'altKategori': altKategori, 
        'yonetim_tipi': yonetim_tipi,
        'stocks': stocks, 
        'funds': funds
    }
    
    portfolio_container['current'] = new_current_version
    portfolios[portfolio_name] = portfolio_container
    
    save_portfolios(portfolios)
    return jsonify({'success': f'"{portfolio_name}" portföyü başarıyla kaydedildi.'})


@app.route('/calculate', methods=['POST'])
def calculate():
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({'error': 'Geçersiz istek. JSON verisi veya Content-Type başlığı eksik.'}), 400
        
    stocks = data.get('stocks', [])
    funds = data.get('funds', []) # 'funds' alınır ama _calculate_portfolio_return'da kullanılmaz
    
    if not stocks and not funds: 
        return jsonify({'error': 'Hesaplanacak veri gönderilmedi.'}), 400
    
    # Bu fonksiyon artık sadece 'stocks' üzerinden hesap yapacak.
    result = _calculate_portfolio_return(stocks, funds)
    return jsonify(result)

@app.route('/get_all_fund_returns', methods=['GET'])
def get_all_fund_returns():
    """
    Tüm kayıtlı portföylerin günlük getirilerini hesaplar.
    GÜNCELLEME: Hesaplama artık SADECE hisse senetleri üzerinden yapılır.
    """
    portfolios = load_portfolios()
    all_returns = []
    
    for name, data_container in portfolios.items():
        portfolio_data = data_container.get('current')
        if not portfolio_data:
            continue
            
        stocks = portfolio_data.get('stocks', [])
        funds = portfolio_data.get('funds', []) # 'funds' alınır ama hesaplamada kullanılmaz
        
        if not stocks and not funds: # Hissesi olmayan fonlar 0 getiri döner
               all_returns.append({
                   'name': name,
                   'return': 0.0
               })
               continue
            
        # _calculate_portfolio_return artık sadece 'stocks'u dikkate alıyor
        calculation_result = _calculate_portfolio_return(stocks, funds)
        
        all_returns.append({
            'name': name,
            'return': calculation_result.get('total_change', 0)
        })
        
    return jsonify(all_returns)


# --- KONTROL PANELİ TAKİP LİSTESİ API'LERİ ---
# (Bu bölümde değişiklik yapılmadı)

@app.route('/get_tracked_funds', methods=['GET'])
def get_tracked_funds():
    try:
        response = supabase.table('control_panel_data') \
                           .select('value') \
                           .eq('key', 'tracked_funds') \
                           .maybe_single() \
                           .execute()
        
        if response.data and response.data.get('value'):
            return jsonify(response.data['value'])
        else:
            return jsonify([])
    except Exception as e:
        print(f"Takip listesi alınırken hata: {e}")
        return jsonify({'error': f'Sunucu hatası: {e}'}), 500

@app.route('/save_tracked_funds', methods=['POST'])
def save_tracked_funds():
    fund_list = request.get_json(silent=True)
    if not isinstance(fund_list, list):
        return jsonify({'error': 'Geçersiz veri formatı. Bir liste bekleniyordu.'}), 400
        
    try:
        supabase.table('control_panel_data') \
                .upsert({'key': 'tracked_funds', 'value': fund_list}) \
                .execute()

        return jsonify({'success': 'Takip listesi başarıyla güncellendi.'})
    except Exception as e:
        print(f"Takip listesi kaydedilirken hata: {e}")
        return jsonify({'error': f'Sunucu hatası: {e}'}), 500

# --- YENİ API'LERİN SONU ---


# GÜNCELLENDİ: Bu fonksiyon artık SADECE hisse senetleri için geçmiş hesabı yapar.
# (Değişiklik yok)
@app.route('/calculate_historical/<portfolio_name>', methods=['GET'])
def calculate_historical(portfolio_name):
    portfolios = load_portfolios()
    portfolio_container = portfolios.get(portfolio_name)
    if not portfolio_container: return jsonify({'error': 'Portföy bulunamadı'}), 404
    portfolio = portfolio_container.get('current')
    if not portfolio: return jsonify({'error': 'Portföyün güncel versiyonu bulunamadı.'}), 404
    
    end_date, start_date = date.today(), date.today() - timedelta(days=45)
    
    # 'all_assets' ağırlık hesabı için hala 'funds' içerebilir, bu sorun değil.
    all_assets = portfolio.get('stocks', []) + portfolio.get('funds', [])
    if not all_assets: return jsonify({'error': 'Portföyde hesaplanacak varlık yok.'}), 400
    
    asset_prices_df = pd.DataFrame()
    stocks_in_portfolio = portfolio.get('stocks', [])
    
    if stocks_in_portfolio:
        stock_tickers_is = []
        for s in stocks_in_portfolio:
            ticker = s['ticker'].strip().upper()
            borsa_tipi = s.get('borsa_tipi', 'bist') 
            
            if borsa_tipi == 'bist':
                stock_tickers_is.append(ticker + '.IS')
            else: # 'yabanci' ise
                stock_tickers_is.append(ticker)
                
        try:
            stock_data = yf.download(stock_tickers_is, start=start_date, end=end_date, progress=False)
            if not stock_data.empty:
                close_prices = stock_data['Close'] if len(stock_tickers_is) > 1 else stock_data[['Close']]
                asset_prices_df = pd.concat([asset_prices_df, close_prices], axis=1)
        except Exception as e:
            print(f"Hisse senedi verisi alınırken hata: {e}")
            
    # --- TEFAS İLE İLGİLİ TÜM BLOK KALDIRILDI ---
    # (for fund in portfolio.get('funds', []): ... bloğu silindi)

    if asset_prices_df.empty: return jsonify({'error': 'Tarihsel veri bulunamadı (Sadece hisseler dikkate alındı).'}), 400
    
    asset_prices_df.columns = asset_prices_df.columns.str.replace('.IS', '', regex=False)
    
    asset_prices_df = asset_prices_df.ffill().dropna(how='all')
    daily_returns = asset_prices_df.pct_change()
    
    # Ağırlık sözlüğü hem hisseleri hem fonları içerebilir
    weights_dict = {asset['ticker'].strip().upper(): float(asset['weight']) / 100 for asset in all_assets}
    
    # 'reindex' sayesinde SADECE 'daily_returns.columns' (yani hisseler) için olan ağırlıklar kalır.
    # Fonların ağırlıkları otomatik olarak 0'lanır. Bu tam istediğimiz şey.
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
    data = request.get_json(silent=True)
    if data is None:
            return jsonify({'error': 'Geçersiz istek. JSON verisi veya Content-Type başlığı eksik.'}), 400
            
    portfolio_name_to_delete = data.get('name')
    if not portfolio_name_to_delete: return jsonify({'error': 'Silinecek portföy adı belirtilmedi.'}), 400
    
    portfolios = load_portfolios()
    if portfolio_name_to_delete in portfolios:
        del portfolios[portfolio_name_to_delete]
        save_portfolios(portfolios) # Bu fonksiyonun içinde zaten try/except var
        return jsonify({'success': f'"{portfolio_name_to_delete}" portföyü başarıyla silindi.'})
    else:
        return jsonify({'error': 'Silinecek portföy bulunamadı.'}), 404

# GÜNCELLENDİ: Bu fonksiyon artık SADECE hisse senetleri için dinamik ağırlık hesabı yapar.
@app.route('/calculate_dynamic_weights', methods=['POST'])
def calculate_dynamic_weights():
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({'error': 'Geçersiz istek. JSON verisi veya Content-Type başlığı eksik.'}), 400
        
    stocks = data.get('stocks', [])
    # 'funds' alınır ama hesaplamada kullanılmaz
    funds = data.get('funds', []) 
    
    if not stocks and not funds:
        return jsonify({'error': 'Hesaplanacak veri gönderilmedi.'}), 400

    total_portfolio_value = 0.0
    asset_market_values = [] # Hem market değeri hem de hesaplanan değişim burada tutulacak
    
    # --- BİRİNCİ DÖNGÜ: Fiyatları al, değeri ve DEĞİŞİMİ hesapla ---
    for stock in stocks:
        ticker, adet = stock.get('ticker').strip().upper(), int(stock.get('adet') or 0)
        borsa_tipi = stock.get('borsa_tipi', 'bist')
        
        if adet == 0: continue
        
        if ticker in ['NAKIT', 'CASH', 'TAHVIL', 'BOND', 'DEVLET TAHVILI']:
            market_value = float(adet)
            asset_market_values.append({
                'type': 'stock', 
                'ticker': ticker, 
                'adet': adet, 
                'market_value': market_value, 
                'daily_change_calc': 0.0 # Nakit değişimi 0
            })
            total_portfolio_value += market_value
            continue
            
        if borsa_tipi == 'bist':
            yf_ticker = ticker + '.IS'
        else: # 'yabanci' ise
            yf_ticker = ticker
            
        try:
            # --- YENİ HESAPLAMA YÖNTEMİ ---
            t = yf.Ticker(yf_ticker)
            info = t.info

            # 1. Gerçek "Dünkü Kapanış" fiyatını al
            prev_close = info.get('previousClose')
            if prev_close is None:
                hist_2d = t.history(period="2d")
                if len(hist_2d) < 2:
                    raise Exception(f"'{ticker}' için 'previousClose' (dünkü kapanış) verisi alınamadı.")
                prev_close = hist_2d['Close'].iloc[-2]
                
            # 2. En "Son Fiyat"ı al (Anlık veya son kapanış)
            latest_price = info.get('currentPrice', info.get('regularMarketPrice'))
            if latest_price is None:
                hist_1d = t.history(period="1d")
                if hist_1d.empty:
                    raise Exception(f"'{ticker}' için son fiyat (latest price) alınamadı.")
                latest_price = hist_1d['Close'].iloc[-1]

            # 3. Hesaplamaları yap
            market_value = latest_price * adet
            daily_change = ((latest_price - prev_close) / prev_close) * 100
            
            asset_market_values.append({
                'type': 'stock', 
                'ticker': ticker, 
                'adet': adet, 
                'market_value': market_value,
                'daily_change_calc': daily_change # Değişimi burada sakla
            })
            total_portfolio_value += market_value
            # --- YENİ HESAPLAMA SONU ---

        except Exception as e:
            print(f"Fiyat/Info alınamadı ({ticker}): {e}")
            # Hata durumunda, market değeri 0, değişim 0 olsun
            asset_market_values.append({'type': 'stock', 'ticker': ticker, 'adet': adet, 'market_value': 0, 'daily_change_calc': 0, 'error': str(e)})

    # --- TEFAS İLE İLGİLİ TÜM BLOK KALDIRILDI ---
    # (for fund in funds: ... bloğu silindi)

    if total_portfolio_value == 0:
        if not stocks:
            return jsonify({'error': 'Portföyde hiç hisse senedi yok.'}), 400
        return jsonify({'error': 'Portföy toplam değeri sıfır (Sadece hisseler dikkate alındı). Adetleri veya varlık kodlarını kontrol edin.'}), 400

    total_portfolio_change = 0.0
    asset_details = []
    
    # --- İKİNCİ DÖNGÜ: Ağırlıkları ve etkiyi hesapla ---
    # Bu döngü artık SADECE 'asset_market_values' içindeki hisseler için çalışacak.
    for asset in asset_market_values:
        dynamic_weight = (asset['market_value'] / total_portfolio_value) * 100
        
        if asset.get('error'):
            asset_details.append({**asset, 'dynamic_weight': 0.0, 'daily_change': 0.0, 'weighted_impact': 0.0})
            continue

        # Değişimi ilk döngüden al
        daily_change = asset.get('daily_change_calc', 0.0)
        
        weighted_impact = (dynamic_weight / 100) * daily_change
        total_portfolio_change += weighted_impact
        
        detail = {
            'type': asset['type'],
            'ticker': asset['ticker'],
            'dynamic_weight': dynamic_weight,
            'daily_change': daily_change,
            'weighted_impact': weighted_impact
        }
        asset_details.append(detail)
        
    return jsonify({'total_change': total_portfolio_change, 'details': asset_details})


if __name__ == '__main__':
    app.run(debug=True)
