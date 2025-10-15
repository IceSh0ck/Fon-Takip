# app.py dosyanızdaki mevcut @app.route('/calculate_historical/<portfolio_name>', methods=['GET'])
# fonksiyonunu ve içindeki her şeyi silip yerine bunu yapıştırın.

@app.route('/calculate_historical/<portfolio_name>', methods=['GET'])
def calculate_historical(portfolio_name):
    portfolios = load_portfolios()
    portfolio_container = portfolios.get(portfolio_name)

    if not portfolio_container:
        return jsonify({'error': 'Portföy bulunamadı'}), 404

    # 1. Adım: Tüm portföy versiyonlarını ve geçerlilik tarihlerini topla
    all_versions = []
    current_version = portfolio_container.get('current')
    if current_version:
        # 'current' versiyonun başlangıç tarihi bir önceki versiyonun bittiği gündür.
        # Eğer geçmiş yoksa, 45 gün öncedir.
        history_dates = [
            datetime.strptime(v.get('save_timestamp'), '%Y-%m-%d %H:%M:%S').date()
            for v in portfolio_container.get('history', []) if v.get('save_timestamp')
        ]
        start_of_current = max(history_dates) if history_dates else (date.today() - timedelta(days=45))
        all_versions.append({'portfolio': current_version, 'start_date': start_of_current, 'is_current': True})

    for past_version in portfolio_container.get('history', []):
        try:
            save_date = datetime.strptime(past_version.get('save_timestamp'), '%Y-%m-%d %H:%M:%S').date()
            all_versions.append({'portfolio': past_version, 'start_date': save_date, 'is_current': False})
        except (ValueError, TypeError):
            continue

    # Versiyonları başlangıç tarihine göre en yeniden en eskiye sırala
    all_versions.sort(key=lambda x: x['start_date'], reverse=True)

    if not all_versions:
        return jsonify({'error': 'Hesaplanacak portföy versiyonu bulunamadı.'}), 400

    # 2. Adım: Genel tarih aralığını ve tüm varlıkları belirle
    end_date = date.today()
    start_date = end_date - timedelta(days=45)

    all_stock_tickers = set()
    all_fund_tickers = set()
    for version in all_versions:
        for stock in version['portfolio'].get('stocks', []):
            all_stock_tickers.add(stock['ticker'].strip().upper() + '.IS')
        for fund in version['portfolio'].get('funds', []):
            all_fund_tickers.add(fund['ticker'].strip().upper())
    
    # 3. Adım: Tüm varlıkların fiyat verilerini tek seferde çek
    asset_prices_df = pd.DataFrame()
    if all_stock_tickers:
        try:
            stock_data = yf.download(list(all_stock_tickers), start=start_date, end=end_date, progress=False)['Close']
            if not stock_data.empty:
                if isinstance(stock_data, pd.Series):
                    stock_data = stock_data.to_frame(name=list(all_stock_tickers)[0])
                asset_prices_df = pd.concat([asset_prices_df, stock_data], axis=1)
        except Exception as e:
            print(f"Hisse senedi verisi alınırken hata: {e}")

    sdt_str, fdt_str = start_date.strftime('%d-%m-%Y'), end_date.strftime('%d-%m-%Y')
    for fund_code in all_fund_tickers:
        try:
            res = requests.get(f"https://www.tefas.gov.tr/api/DB/BindHistoryPrice?sdt={sdt_str}&fdt={fdt_str}&kod={fund_code}", timeout=10)
            fund_data = res.json()
            if fund_data:
                df = pd.DataFrame(fund_data)
                df['Tarih'] = pd.to_datetime(df['Tarih'])
                df = df.set_index('Tarih')[['BirimPayDegeri']].rename(columns={'BirimPayDegeri': fund_code})
                asset_prices_df = pd.concat([asset_prices_df, df], axis=1)
        except Exception as e:
            print(f"Fon verisi alınırken hata ({fund_code}): {e}")
            
    if asset_prices_df.empty:
        return jsonify({'error': 'Tarihsel veri bulunamadı.'}), 400

    asset_prices_df.columns = asset_prices_df.columns.str.replace('.IS', '', regex=False)
    asset_prices_df = asset_prices_df.ffill().dropna(how='all')
    daily_returns = asset_prices_df.pct_change()

    # 4. Adım: Her gün için doğru portföy ağırlıklarını kullanarak getiri hesapla
    portfolio_daily_returns = pd.Series(index=daily_returns.index, dtype=float)

    for i, version_data in enumerate(all_versions):
        period_start_date = version_data['start_date']
        period_end_date = all_versions[i-1]['start_date'] - timedelta(days=1) if i > 0 else end_date

        period_start_date = max(period_start_date, start_date)
        if period_start_date > period_end_date: continue

        assets = version_data['portfolio'].get('stocks', []) + version_data['portfolio'].get('funds', [])
        weights_dict = {asset['ticker'].strip().upper(): float(asset['weight']) / 100 for asset in assets}
        aligned_weights = pd.Series(weights_dict).reindex(daily_returns.columns).fillna(0)

        period_mask = (daily_returns.index.date >= period_start_date) & (daily_returns.index.date <= period_end_date)
        period_returns = (daily_returns[period_mask] * aligned_weights).sum(axis=1) * 100
        portfolio_daily_returns.update(period_returns)
        
    # 5. Adım: Frontend için veri setlerini oluştur
    valid_returns = portfolio_daily_returns.dropna()
    datasets = []
    
    # En eski versiyondan başlayarak grafiği oluştur (kronolojik sıra)
    for i in range(len(all_versions) - 1, -1, -1):
        version_data = all_versions[i]
        period_start_date = version_data['start_date']
        period_end_date = all_versions[i-1]['start_date'] - timedelta(days=1) if i > 0 else end_date

        period_start_date = max(period_start_date, start_date)
        if period_start_date > period_end_date: continue

        mask = (valid_returns.index.date >= period_start_date) & (valid_returns.index.date <= period_end_date)
        segment_returns = valid_returns[mask]
        
        if not segment_returns.empty:
            prev_day_index = segment_returns.index[0] - pd.Timedelta(days=1)
            if prev_day_index in valid_returns.index:
                segment_returns = pd.concat([valid_returns.loc[[prev_day_index]], segment_returns])

            # Renk ve etiket ataması
            if version_data['is_current']:
                color = 'rgb(255, 205, 86)' # Belirgin Sarı
                label = f"Güncel Versiyon ({period_start_date.strftime('%d.%m.%Y')} sonrası)"
            else:
                color = 'rgb(54, 162, 235)' # Mavi
                label = f"Önceki Versiyon ({period_end_date.strftime('%d.%m.%Y')} öncesi)"


            datasets.append({
                'label': label,
                'data': [{'x': ts.strftime('%d.%m.%Y'), 'y': val} for ts, val in segment_returns.items()],
                'borderColor': color,
                'backgroundColor': color.replace(')', ', 0.5)').replace('rgb', 'rgba'),
                'tension': 0.1,
                'borderWidth': 2.5 # Çizgi kalınlığını biraz arttıralım
            })

    # Sadece son 30 günü göster
    thirty_days_ago = date.today() - timedelta(days=30)
    final_datasets = []
    for ds in datasets:
        filtered_data = [d for d in ds['data'] if datetime.strptime(d['x'], '%d.%m.%Y').date() >= thirty_days_ago]
        if filtered_data:
            # Kesintisiz çizgi için bir önceki günün verisini ekle
            first_date_in_set = datetime.strptime(filtered_data[0]['x'], '%d.%m.%Y').date()
            original_data_point = next((od for od in ds['data'] if od['x'] == filtered_data[0]['x']), None)
            original_index = ds['data'].index(original_data_point) if original_data_point else -1
            if original_index > 0:
                filtered_data.insert(0, ds['data'][original_index - 1])

            ds['data'] = filtered_data
            final_datasets.append(ds)

    return jsonify({'datasets': final_datasets})
