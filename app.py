# app.py (SON HALİ - TAMAMI)

import os
import json
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import yfinance as yf
import requests
from datetime import date, timedelta, datetime
import pandas as pd
from supabase import create_client, Client
from functools import wraps

app = Flask(__name__)
# Session'ları güvence altına almak için bir secret key gereklidir.
# Bu anahtarı Environment Variable olarak ayarlamanız en güvenlisidir.
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "gelistirme-icin-guvensiz-bir-anahtar-kullan")

# --- SUPABASE BAĞLANTISI ---
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


# --- KULLANICI GİRİŞ KONTROLÜ (DECORATOR) ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Gerçek bir uygulamada burada session kontrolü yapılır ve yoksa login sayfasına yönlendirilir.
        # Henüz bir login sisteminiz olmadığı için, test amacıyla varsayılan bir kullanıcı ID'si atıyoruz.
        # Kendi login sisteminizi kurduğunuzda bu bölümü güncellemeniz gerekecek.
        if 'user' not in session:
            # LÜTFEN BU ID'Yİ KENDİ SUPABASE projenizdeki auth.users tablosundan bir kullanıcı ID'si ile değiştirin.
            test_user_id = "dc3d80aa-304d-4a4e-b9b9-bc6a470d6cce"
            if "BURAYA" in test_user_id:
                # Bu hata, ID'yi değiştirmediyseniz uygulamayı çalıştırdığınızda size hatırlatma yapacaktır.
                raise ValueError("LÜTFEN app.py dosyasındaki test_user_id değişkenini kendi Supabase kullanıcı ID'niz ile güncelleyin.")
            session['user'] = {'id': test_user_id}
        return f(*args, **kwargs)
    return decorated_function


# --- ANA UYGULAMA ROUTE'LARI ---

@app.route('/')
@login_required
def index():
    return render_template('index.html')

@app.route('/get_portfolios', methods=['GET'])
@login_required
def get_portfolios():
    user_id = session['user']['id']
    response = supabase.table('portfolios').select('id, name').eq('user_id', user_id).order('name').execute()
    return jsonify(response.data)

@app.route('/get_portfolio/<int:portfolio_id>', methods=['GET'])
@login_required
def get_portfolio(portfolio_id):
    user_id = session['user']['id']
    response = supabase.table('portfolios').select('holdings').eq('id', portfolio_id).eq('user_id', user_id).single().execute()
    if response.data and 'current' in response.data.get('holdings', {}):
        return jsonify(response.data['holdings']['current'])
    return jsonify({'error': 'Portföy bulunamadı'}), 404

@app.route('/save_portfolio', methods=['POST'])
@login_required
def save_portfolio():
    data = request.get_json()
    user_id = session['user']['id']
    portfolio_name = data.get('name')
    existing_id = data.get('id')
    
    holdings_data = {
        "stocks": data.get('stocks', []),
        "funds": data.get('funds', [])
    }
    if not portfolio_name or (not holdings_data["stocks"] and not holdings_data["funds"]):
        return jsonify({'error': 'Portföy adı ve en az bir varlık girilmelidir'}), 400

    if existing_id: # Portföy Güncelleme
        response = supabase.table('portfolios').select('holdings').eq('id', existing_id).eq('user_id', user_id).single().execute()
        portfolio_container = response.data.get('holdings', {'current': None, 'history': []})
        
        if portfolio_container.get('current'):
            previous_version = portfolio_container['current']
            previous_version['save_timestamp'] = datetime.now().isoformat()
            portfolio_container['history'].insert(0, previous_version)
            portfolio_container['history'] = portfolio_container['history'][:5]

        portfolio_container['current'] = holdings_data
        
        supabase.table('portfolios').update({
            'name': portfolio_name, 'holdings': portfolio_container
        }).eq('id', existing_id).execute()
    else: # Yeni Portföy Kaydı
        new_portfolio = {
            'user_id': user_id, 'name': portfolio_name,
            'holdings': {'current': holdings_data, 'history': []}
        }
        supabase.table('portfolios').insert(new_portfolio).execute()
        
    return jsonify({'success': f'"{portfolio_name}" portföyü başarıyla kaydedildi.'})

@app.route('/delete_portfolio', methods=['POST'])
@login_required
def delete_portfolio():
    data = request.get_json()
    portfolio_id = data.get('id')
    user_id = session['user']['id']
    if not portfolio_id:
        return jsonify({'error': 'Silinecek portföy ID\'si belirtilmedi.'}), 400
    
    # Ana portföyü silmeden önce, buna bağlı sandbox portföyünü de silelim
    supabase.table('sandbox_portfolios').delete().eq('main_portfolio_id', portfolio_id).eq('user_id', user_id).execute()
    # Şimdi ana portföyü silelim
    supabase.table('portfolios').delete().eq('id', portfolio_id).eq('user_id', user_id).execute()
    
    return jsonify({'success': 'Portföy başarıyla silindi.'})

@app.route('/get_portfolio_history/<int:portfolio_id>', methods=['GET'])
@login_required
def get_portfolio_history(portfolio_id):
    user_id = session['user']['id']
    response = supabase.table('portfolios').select('holdings').eq('id', portfolio_id).eq('user_id', user_id).single().execute()
    portfolio_data = response.data.get('holdings', {})
    if not portfolio_data:
        return jsonify({'error': 'Portföy veya geçmişi bulunamadı.'}), 404
        
    for entry in portfolio_data.get('history', []):
        if 'save_timestamp' in entry:
            dt_obj = datetime.fromisoformat(entry['save_timestamp'])
            entry['display_timestamp'] = dt_obj.strftime('%d.%m.%Y %H:%M')
            
    return jsonify(portfolio_data)

# Diğer ana uygulama route'larınız (calculate, calculate_historical, revert vb.)
# eski kodunuzdaki halleriyle büyük ölçüde çalışacaktır. Sadece portfolio_name yerine
# portfolio_id ile veri çekecek şekilde küçük güncellemeler gerekebilir.


# --- SANDBOX MODU ROUTE'LARI ---

@app.route('/sandbox')
@login_required
def sandbox_index():
    user_id = session['user']['id']
    
    main_portfolios_resp = supabase.table('portfolios').select('id, name, holdings').eq('user_id', user_id).execute()
    sandbox_portfolios_resp = supabase.table('sandbox_portfolios').select('id, name, main_portfolio_id').eq('user_id', user_id).execute()
    
    main_portfolios = {p['id']: p for p in main_portfolios_resp.data}
    sandbox_portfolios = {p['main_portfolio_id']: p for p in sandbox_portfolios_resp.data}

    main_ids = set(main_portfolios.keys())
    sandbox_main_ids = set(sandbox_portfolios.keys())

    ids_to_delete = sandbox_main_ids - main_ids
    if ids_to_delete:
        sandbox_ids_to_delete = [sandbox_portfolios[main_id]['id'] for main_id in ids_to_delete]
        supabase.table('sandbox_portfolios').delete().in_('id', sandbox_ids_to_delete).execute()

    ids_to_add = main_ids - sandbox_main_ids
    if ids_to_add:
        new_sandbox_entries = []
        for main_id in ids_to_add:
            main_portfolio = main_portfolios[main_id]
            current_holdings = main_portfolio.get('holdings', {}).get('current', {})
            new_sandbox_entries.append({
                'user_id': user_id,
                'name': main_portfolio['name'],
                'main_portfolio_id': main_id,
                'holdings': current_holdings
            })
        if new_sandbox_entries:
            supabase.table('sandbox_portfolios').insert(new_sandbox_entries).execute()

    final_sandbox_list = supabase.table('sandbox_portfolios').select('id, name').eq('user_id', user_id).order('name').execute()
    
    return render_template('sandbox_index.html', portfolios=final_sandbox_list.data)

@app.route('/sandbox/view/<int:portfolio_id>')
@login_required
def view_sandbox_portfolio(portfolio_id):
    user_id = session['user']['id']
    response = supabase.table('sandbox_portfolios').select('*').eq('id', portfolio_id).eq('user_id', user_id).single().execute()
    if not response.data:
        return "Sandbox portföyü bulunamadı.", 404
    return render_template('sandbox_view.html', portfolio=response.data)

@app.route('/sandbox/edit/<int:portfolio_id>', methods=['GET', 'POST'])
@login_required
def edit_sandbox_portfolio(portfolio_id):
    user_id = session['user']['id']
    
    if request.method == 'POST':
        data = request.get_json()
        new_holdings = {
            "stocks": data.get('stocks', []),
            "funds": data.get('funds', [])
        }
        supabase.table('sandbox_portfolios').update({'holdings': new_holdings}).eq('id', portfolio_id).eq('user_id', user_id).execute()
        return jsonify({'success': True, 'redirect_url': url_for('view_sandbox_portfolio', portfolio_id=portfolio_id)})
        
    response = supabase.table('sandbox_portfolios').select('*').eq('id', portfolio_id).eq('user_id', user_id).single().execute()
    if not response.data: return "Portföy bulunamadı.", 404
    return render_template('sandbox_edit.html', portfolio=response.data)

@app.route('/api/sandbox/recalculate', methods=['POST'])
@login_required
def recalculate_sandbox_portfolio():
    data = request.get_json()
    holdings = data.get('holdings', {})
    stocks = holdings.get('stocks', [])
    
    total_value, updated_stocks = 0.0, []
    
    for holding in stocks:
        if 'adet' not in holding or not holding['adet'] or float(holding.get('adet', 0)) == 0:
            continue
        try:
            ticker = holding['ticker'].strip().upper()
            yf_ticker = ticker + '.IS'
            stock_info = yf.Ticker(yf_ticker)
            # 'regularMarketPrice' anlık veri için daha iyi bir alternatiftir
            current_price = stock_info.info.get('regularMarketPrice', stock_info.history(period='1d')['Close'].iloc[-1])
            quantity = float(holding['adet'])
            value = quantity * current_price
            total_value += value
            updated_stocks.append({'ticker': ticker, 'adet': quantity, 'price': round(current_price, 2), 'value': round(value, 2)})
        except Exception:
            updated_stocks.append({'ticker': holding['ticker'], 'adet': holding.get('adet', 0), 'price': 'N/A', 'value': 0})

    for stock in updated_stocks:
        stock['weight'] = round((stock['value'] / total_value * 100), 2) if total_value > 0 else 0
        
    return jsonify({'stocks': updated_stocks, 'total_value': round(total_value, 2)})

if __name__ == '__main__':
    app.run(debug=True)

