let currentPortfolioName = null;
let portfolioChart = null;
let historicalChart = null;
let isDeleteMode = false;

document.addEventListener('DOMContentLoaded', () => {
    loadPortfolios();
    document.querySelectorAll('.back-button').forEach(button => {
        button.onclick = (e) => {
            e.preventDefault();
            if (currentPortfolioName) {
                const activeLi = document.querySelector(`#portfolio-list li[data-name="${currentPortfolioName}"]`);
                showOptions(currentPortfolioName, activeLi);
            }
        };
    });
    document.getElementById('btn-new-portfolio').addEventListener('click', showNewPortfolioForm);
    document.getElementById('btn-delete-mode').addEventListener('click', toggleDeleteMode);
    document.getElementById('portfolio-form').addEventListener('submit', handleCalculate);
    document.getElementById('save-button').addEventListener('click', saveManualPortfolio);

    // YENİ PDF İŞLEME OLAY DİNLEYİCİLERİ
    document.getElementById('btn-upload-pdf').addEventListener('click', showPdfUploader);
    document.getElementById('pdf-file-input').addEventListener('change', handlePdfFileUpload);
});

function toggleDeleteMode() {
    isDeleteMode = !isDeleteMode;
    const deleteButton = document.getElementById('btn-delete-mode');
    const body = document.body;
    if (isDeleteMode) {
        deleteButton.classList.add('active');
        deleteButton.textContent = 'Silme Modundan Çık';
        body.classList.add('delete-mode-active');
        ['options-container', 'form-container', 'result-area', 'report-container', 'comparison-container', 'pdf-processor-container'].forEach(id => document.getElementById(id).style.display = 'none');
        alert('Silme modu aktif. Silmek istediğiniz portföyü listeden seçin.');
    } else {
        deleteButton.classList.remove('active');
        deleteButton.textContent = 'Portföy Sil';
        body.classList.remove('delete-mode-active');
    }
}

function showNewPortfolioForm() {
    if (isDeleteMode) toggleDeleteMode();
    currentPortfolioName = null;
    document.querySelectorAll('#portfolio-list li').forEach(li => li.classList.remove('active'));
    document.getElementById('portfolio-name').value = '';
    document.getElementById('stocks-container').innerHTML = '';
    document.getElementById('funds-container').innerHTML = '';
    ['options-container', 'result-area', 'report-container', 'comparison-container', 'pdf-processor-container'].forEach(id => document.getElementById(id).style.display = 'none');
    document.getElementById('form-container').style.display = 'block';
    document.querySelector('#form-container .back-button').style.display = 'none';
    document.getElementById('result-area').style.display = 'none';
}

async function deletePortfolio(name) {
    if (confirm(`"${name}" portföyünü silmek istediğinizden emin misiniz? Bu işlem geri alınamaz.`)) {
        try {
            const response = await fetch('/delete_portfolio', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: name })
            });
            const result = await response.json();
            if (response.ok) {
                alert(result.success);
                loadPortfolios();
                showNewPortfolioForm();
            } else { throw new Error(result.error); }
        } catch (error) {
            alert('Portföy silinirken bir hata oluştu: ' + error.message);
        }
    }
}

async function loadPortfolios() {
    const response = await fetch('/get_portfolios');
    const portfolioNames = await response.json();
    const listElement = document.getElementById('portfolio-list');
    listElement.innerHTML = '';
    portfolioNames.forEach(name => {
        const li = document.createElement('li');
        li.textContent = name;
        li.dataset.name = name;
        li.onclick = (event) => {
            if (isDeleteMode) {
                deletePortfolio(name);
            } else {
                showOptions(name, event.currentTarget);
            }
        };
        listElement.appendChild(li);
    });
}

function addAsset(type, ticker = '', weight = '', adet = '') {
    const container = document.getElementById(type === 'stock' ? 'stocks-container' : 'funds-container');
    const newRow = document.createElement('div');
    newRow.className = 'stock-row';
    newRow.innerHTML = `
        <input type="text" placeholder="${type === 'stock' ? 'Hisse Kodu (örn: EREGL)' : 'Fon Kodu (örn: AFT)'}" value="${ticker}" required>
        <input type="number" placeholder="Ağırlık (%)" value="${weight}" min="0.01" step="0.01" required>
        <input type="number" placeholder="Adet (Opsiyonel)" value="${adet}" min="0" step="1">
        <button type="button" class="btn-remove" onclick="this.parentElement.remove()">X</button>
    `;
    container.appendChild(newRow);
}

function showOptions(name, targetElement) {
    currentPortfolioName = name;
    document.querySelectorAll('#portfolio-list li').forEach(li => li.classList.remove('active'));
    if (targetElement) targetElement.classList.add('active');
    document.getElementById('options-title').textContent = `"${name}" Portföyü İçin İşlem Seçin`;
    document.getElementById('btn-show-report').onclick = () => displayPieChartReport(name);
    document.getElementById('btn-show-comparison').onclick = () => displayWeightChangeReport(name);
    document.getElementById('btn-show-historical').onclick = () => displayHistoricalReturns(name);
    document.getElementById('btn-edit-portfolio').onclick = () => showPortfolioEditor(name);
    ['form-container', 'result-area', 'report-container', 'comparison-container', 'pdf-processor-container'].forEach(id => document.getElementById(id).style.display = 'none');
    document.getElementById('options-container').style.display = 'block';
    fetchAndDisplayLiveReturn(name);
}

async function fetchAndDisplayLiveReturn(name) {
    const displayDiv = document.getElementById('live-return-display');
    const noticeDiv = document.getElementById('live-return-notice');
    displayDiv.textContent = 'Anlık getiri hesaplanıyor...';
    displayDiv.className = '';
    noticeDiv.style.display = 'none';
    try {
        const portfolioResponse = await fetch(`/get_portfolio/${name}`);
        const portfolio = await portfolioResponse.json();
        const { stocks, funds } = portfolio;
        const calculateResponse = await fetch('/calculate', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ stocks, funds })
        });
        const result = await calculateResponse.json();
        if (calculateResponse.ok) {
            const value = result.total_change;
            const now = new Date();
            const timeString = now.toLocaleDateString('tr-TR', { day: '2-digit', month: '2-digit', year: 'numeric' }) + ' ' + now.toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' });
            displayDiv.textContent = `${timeString} - ${value >= 0 ? '+' : ''}${value.toFixed(2)}%`;
            displayDiv.className = value >= 0 ? 'positive' : 'negative';
            const hasFunds = result.details.some(d => d.type === 'fund' && d.date_range && d.date_range !== "Yetersiz Veri");
            noticeDiv.textContent = hasFunds ? 'Getiriler, fonlar için bir önceki günün, hisseler için anlık kapanış verilerine göre hesaplanmıştır.' : 'Getiriler anlık hisse senedi kapanış verilerine göre hesaplanmıştır.';
            noticeDiv.style.display = 'block';
        } else { throw new Error(result.error); }
    } catch (error) {
        displayDiv.textContent = `Hata: ${error.message || 'Getiri hesaplanamadı.'}`;
        displayDiv.className = 'negative';
        noticeDiv.style.display = 'none';
    }
}

async function displayPieChartReport(name) {
    document.getElementById('report-title').textContent = `"${name}" Portföy Dağılım Raporu`;
    const response = await fetch(`/get_portfolio/${name}`);
    const portfolio = await response.json();
    const assets = (portfolio.stocks || []).concat(portfolio.funds || []);
    const labels = assets.map(a => a.ticker);
    const data = assets.map(a => parseFloat(a.weight));
    const ctx = document.getElementById('portfolioPieChart').getContext('2d');
    if (portfolioChart) { portfolioChart.destroy(); }
    portfolioChart = new Chart(ctx, { type: 'pie', data: { labels: labels, datasets: [{ label: 'Portföy Ağırlığı (%)', data: data, backgroundColor: generateDeterministicColors(labels), borderColor: '#fff', borderWidth: 1 }] }, options: { responsive: true, plugins: { legend: { position: 'top' }, tooltip: { callbacks: { label: (context) => `${context.label}: ${context.raw.toFixed(2)}%` } } } } });
    document.getElementById('report-container').style.display = 'block';
    ['options-container', 'form-container', 'result-area', 'comparison-container', 'pdf-processor-container'].forEach(id => document.getElementById(id).style.display = 'none');
}

async function displayWeightChangeReport(name) {
    ['options-container', 'report-container', 'form-container', 'result-area', 'pdf-processor-container'].forEach(id => document.getElementById(id).style.display = 'none');
    const container = document.getElementById('comparison-container');
    const tableContainer = document.getElementById('comparison-table-container');
    const title = document.getElementById('comparison-title');
    container.style.display = 'block';
    title.textContent = `"${name}" Portföyü Ağırlık Değişimi Hesaplanıyor...`;
    tableContainer.innerHTML = '<div class="loader"></div>';
    try {
        const response = await fetch(`/compare_versions/${name}`);
        const data = await response.json();
        if (!response.ok) { throw new Error(data.error || 'Bilinmeyen bir hata oluştu.'); }
        title.textContent = `"${name}" Portföy Ağırlık Değişim Raporu`;
        let tableHTML = `<table class="detail-table"><thead><tr><th>Varlık Kodu</th><th>Önceki Ağırlık (% - ${data.previous_date_str})</th><th>Güncel Ağırlık (% - ${data.current_date_str})</th><th>Değişim (%)</th></tr></thead><tbody>`;
        data.comparison.forEach(asset => {
            let changeClass = '';
            if (asset.change > 0.001) changeClass = 'positive';
            if (asset.change < -0.001) changeClass = 'negative';
            const changeSign = asset.change > 0 ? '+' : '';
            tableHTML += `<tr><td>${asset.ticker}</td><td>${asset.previous_weight.toFixed(2)}%</td><td>${asset.current_weight.toFixed(2)}%</td><td class="${changeClass}">${changeSign}${asset.change.toFixed(2)}%</td></tr>`;
        });
        tableHTML += '</tbody></table>';
        tableHTML += `<button type="button" class="btn-revert" id="revert-button">Son Değişikliği Geri Al</button>`;
        tableContainer.innerHTML = tableHTML;
        document.getElementById('revert-button').onclick = () => revertPortfolio(name);
    } catch (error) {
        title.textContent = 'Hata';
        tableContainer.innerHTML = `<div id="total-result" class="negative">Hata: ${error.message}</div>`;
    }
}

async function revertPortfolio(name) {
    if (confirm(`"${name}" portföyündeki son değişikliği geri almak istediğinizden emin misiniz? Güncel dağılımınız silinecek ve bir önceki dağılım geri yüklenecektir.`)) {
        try {
            const response = await fetch(`/revert_portfolio/${name}`, { method: 'POST' });
            const result = await response.json();
            if (response.ok) {
                alert(result.success);
                const activeLi = document.querySelector(`#portfolio-list li[data-name="${name}"]`);
                showOptions(name, activeLi);
            } else { throw new Error(result.error); }
        } catch (error) {
            alert('Geri alma işlemi sırasında bir hata oluştu: ' + error.message);
        }
    }
}

async function displayHistoricalReturns(name) {
    showResultArea(true, true);
    document.getElementById('result-title').textContent = `"${name}" Portföyü - Son 30 Günlük Getiri Hesaplanıyor...`;
    try {
        const response = await fetch(`/calculate_historical/${name}`);
        const data = await response.json();
        if (!response.ok) { throw new Error(data.error || 'Bilinmeyen bir hata oluştu.'); }
        showResultArea(false, true);
        document.getElementById('result-title').textContent = `"${name}" Portföyü - Son 30 Günlük Getiri Grafiği`;
        const ctx = document.getElementById('historicalLineChart').getContext('2d');
        if (historicalChart) { historicalChart.destroy(); }
        historicalChart = new Chart(ctx, { type: 'line', data: { labels: data.dates, datasets: [{ label: 'Günlük Portföy Getirisi (%)', data: data.returns, borderColor: 'rgb(54, 162, 235)', backgroundColor: 'rgba(54, 162, 235, 0.5)', borderWidth: 2, tension: 0.1, pointBackgroundColor: data.returns.map(v => v >= 0 ? '#27ae60' : '#c0392b') }] }, options: { responsive: true, plugins: { legend: { display: false }, tooltip: { callbacks: { label: (context) => `Getiri: ${context.raw.toFixed(2)}%` } } }, scales: { y: { title: { display: true, text: 'Günlük Getiri (%)' } }, x: { title: { display: true, text: 'Tarih' } } } } });
    } catch (error) {
        showResultArea(false, false);
        document.getElementById('total-result').innerHTML = `<span class="negative">Hata: ${error.message}</span>`;
    }
}

async function showPortfolioEditor(name) {
    const response = await fetch(`/get_portfolio/${name}`);
    const portfolio = await response.json();
    document.getElementById('portfolio-name').value = portfolio.name;
    const stocksContainer = document.getElementById('stocks-container');
    stocksContainer.innerHTML = '';
    (portfolio.stocks || []).forEach(s => addAsset('stock', s.ticker, s.weight, s.adet));
    const fundsContainer = document.getElementById('funds-container');
    fundsContainer.innerHTML = '';
    (portfolio.funds || []).forEach(f => addAsset('fund', f.ticker, f.weight, f.adet));
    document.getElementById('form-container').style.display = 'block';
    ['options-container', 'result-area', 'report-container', 'comparison-container', 'pdf-processor-container'].forEach(id => document.getElementById(id).style.display = 'none');
    document.querySelector('#form-container .back-button').style.display = 'block';
}

async function saveManualPortfolio() {
    const portfolioName = document.getElementById('portfolio-name').value.trim();
    if (!portfolioName) { alert('Lütfen bir portföy adı girin.'); return; }
    const stocks = Array.from(document.querySelectorAll('#stocks-container .stock-row')).map(r => ({ ticker: r.children[0].value.trim().toUpperCase(), weight: r.children[1].value, adet: r.children[2].value }));
    const funds = Array.from(document.querySelectorAll('#funds-container .stock-row')).map(r => ({ ticker: r.children[0].value.trim().toUpperCase(), weight: r.children[1].value, adet: r.children[2].value }));
    
    savePortfolioData(portfolioName, stocks, funds);
}

// --- YENİ PDF İŞLEME FONKSİYONLARI ---

function showPdfUploader() {
    if (isDeleteMode) toggleDeleteMode();
    currentPortfolioName = null;
    document.querySelectorAll('#portfolio-list li').forEach(li => li.classList.remove('active'));
    ['options-container', 'form-container', 'result-area', 'report-container', 'comparison-container'].forEach(id => document.getElementById(id).style.display = 'none');
    const pdfContainer = document.getElementById('pdf-processor-container');
    pdfContainer.style.display = 'block';
    document.getElementById('pdf-file-input').value = '';
    document.getElementById('pdf-edit-form-area').style.display = 'none';
    document.getElementById('pdf-edit-form-area').innerHTML = '';
}

async function handlePdfFileUpload(event) {
    const file = event.target.files[0];
    if (!file) return;
    const loader = document.getElementById('pdf-loader');
    const editFormArea = document.getElementById('pdf-edit-form-area');
    loader.style.display = 'block';
    editFormArea.style.display = 'none';
    editFormArea.innerHTML = '';
    const formData = new FormData();
    formData.append('pdf_file', file);
    try {
        const response = await fetch('/upload_pdf', { method: 'POST', body: formData });
        const result = await response.json();
        if (!response.ok) { throw new Error(result.error || 'Bilinmeyen bir sunucu hatası.'); }
        populatePdfEditForm(result);
    } catch (error) {
        alert('Hata: ' + error.message);
    } finally {
        loader.style.display = 'none';
    }
}

function populatePdfEditForm(data) {
    const editFormArea = document.getElementById('pdf-edit-form-area');
    editFormArea.innerHTML = `
        <div class="form-group">
            <label for="pdf-portfolio-name">Portföy Adı (Değiştirebilirsiniz)</label>
            <input type="text" id="pdf-portfolio-name" value="${data.name || ''}" required>
        </div>
        <h3>Hisse Senetleri</h3><div id="pdf-stocks-container"></div>
        <button type="button" class="btn-add" onclick="addPdfAsset('stock')">Yeni Hisse Ekle</button>
        <h3>Yatırım Fonları</h3><div id="pdf-funds-container"></div>
        <button type="button" class="btn-add" onclick="addPdfAsset('fund')">Yeni Fon Ekle</button>
        <hr style="margin: 20px 0;">
        <button type="button" class="btn-save" id="save-pdf-portfolio-button">Bu Portföyü Kaydet</button>
    `;
    (data.stocks || []).forEach(s => addPdfAsset('stock', s.ticker, s.weight));
    (data.funds || []).forEach(f => addPdfAsset('fund', f.ticker, f.weight));
    document.getElementById('save-pdf-portfolio-button').addEventListener('click', savePdfPortfolio);
    editFormArea.style.display = 'block';
}

function addPdfAsset(type, ticker = '', weight = '', adet = '') {
    const container = document.getElementById(type === 'stock' ? 'pdf-stocks-container' : 'pdf-funds-container');
    const newRow = document.createElement('div');
    newRow.className = 'stock-row';
    newRow.innerHTML = `
        <input type="text" value="${ticker}" required>
        <input type="number" value="${weight}" step="0.01" required>
        <input type="number" placeholder="Adet (Opsiyonel)" min="0" step="1" value="${adet}">
        <button type="button" class="btn-remove" onclick="this.parentElement.remove()">X</button>
    `;
    container.appendChild(newRow);
}

async function savePdfPortfolio() {
    const portfolioName = document.getElementById('pdf-portfolio-name').value.trim();
    if (!portfolioName) { alert('Lütfen bir portföy adı girin.'); return; }
    const stocks = Array.from(document.querySelectorAll('#pdf-stocks-container .stock-row')).map(r => ({ ticker: r.children[0].value.trim().toUpperCase(), weight: r.children[1].value, adet: r.children[2].value }));
    const funds = Array.from(document.querySelectorAll('#pdf-funds-container .stock-row')).map(r => ({ ticker: r.children[0].value.trim().toUpperCase(), weight: r.children[1].value, adet: r.children[2].value }));

    savePortfolioData(portfolioName, stocks, funds);
}

async function savePortfolioData(name, stocks, funds) {
    if (stocks.length === 0 && funds.length === 0) { alert('Lütfen en az bir varlık girin.'); return; }
    const totalWeight = [...stocks, ...funds].reduce((sum, asset) => sum + parseFloat(asset.weight || 0), 0);
    if (Math.abs(totalWeight - 100) > 0.1) {
        if (!confirm(`Toplam ağırlık ${totalWeight.toFixed(2)}%. 100%'e yakın değil. Yine de kaydetmek istiyor musunuz?`)) return;
    }
    const response = await fetch('/save_portfolio', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name, stocks, funds }) });
    const result = await response.json();
    alert(response.ok ? result.success : 'Hata: ' + result.error);
    if (response.ok) {
        loadPortfolios();
        showNewPortfolioForm();
    }
}

// --- Yardımcı Fonksiyonlar ---

function generateDeterministicColors(labels) {
    const colors = [];
    for (const label of labels) {
        let hash = 0;
        for (let i = 0; i < label.length; i++) {
            hash = label.charCodeAt(i) + ((hash << 5) - hash);
        }
        colors.push(`hsl(${hash % 360}, 75%, 60%)`);
    }
    return colors;
}

function showResultArea(isLoading, isHistorical = false) {
    ['options-container', 'report-container', 'form-container', 'comparison-container', 'pdf-processor-container'].forEach(id => document.getElementById(id).style.display = 'none');
    document.getElementById('result-area').style.display = 'block';
    
    document.getElementById('total-result').innerHTML = '';
    document.getElementById('stock-results-container').style.display = 'none';
    document.getElementById('fund-results-container').style.display = 'none';
    document.getElementById('historical-results-container').style.display = 'none';

    if (isHistorical) {
        document.getElementById('historical-results-container').style.display = 'block';
    }

    if (isLoading) {
        document.getElementById('loader').style.display = 'block';
        document.getElementById('result-content').style.display = 'none';
    } else {
        document.getElementById('loader').style.display = 'none';
        document.getElementById('result-content').style.display = 'block';
    }
}

async function handleCalculate(event) {
    event.preventDefault();
    showResultArea(true);
    const stocks = Array.from(document.querySelectorAll('#stocks-container .stock-row')).map(r => ({ ticker: r.children[0].value, weight: r.children[1].value }));
    const funds = Array.from(document.querySelectorAll('#funds-container .stock-row')).map(r => ({ ticker: r.children[0].value, weight: r.children[1].value }));
    try {
        const response = await fetch('/calculate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ stocks, funds }) });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error);
        showResultArea(false);
        document.getElementById('result-title').textContent = "Anlık Portföy Getiri Analizi";
        const totalResultDiv = document.getElementById('total-result');
        totalResultDiv.textContent = `${result.total_change >= 0 ? '+' : ''}${result.total_change.toFixed(2)}%`;
        totalResultDiv.className = result.total_change >= 0 ? 'positive' : 'negative';
    } catch (error) {
        showResultArea(false);
        document.getElementById('total-result').innerHTML = `<span class="negative">Hata: ${error.message}</span>`;
    }
}