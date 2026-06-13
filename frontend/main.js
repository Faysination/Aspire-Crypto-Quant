import { createChart, CandlestickSeries, ColorType } from 'https://esm.sh/lightweight-charts';

const API = window.location.port === '5173' ? 'http://127.0.0.1:5001/api' : '/api';

// Elements
const el = {
  statusInd: document.querySelector('.indicator'),
  statusText: document.querySelector('#bot-status span'),
  spotGrid: document.getElementById('spot-grid'),
  futGrid: document.getElementById('fut-grid'),
  posList: document.getElementById('positions-list'),
  console: document.getElementById('console-window'),
  chartSymbolSelect: document.getElementById('chart-symbol-select'),
  
  autoToggle: document.getElementById('auto-portfolio-toggle'),
  symbolSelect: document.getElementById('symbol-select'),
  futuresToggle: document.getElementById('futures-toggle'),
  liveToggle: document.getElementById('live-toggle'),
  
  indRegime: document.getElementById('ind-regime'),
  indAdx: document.getElementById('ind-adx'),
  indRsi: document.getElementById('ind-rsi'),
  indAtr: document.getElementById('ind-atr'),
  
  // Settings
  settingHardStop: document.getElementById('setting-hard-stop'),
  settingTimeLimit: document.getElementById('setting-time-limit'),
  btnApplySettings: document.getElementById('btn-apply-settings'),
  
  // Performance
  perfEquity: document.getElementById('perf-equity'),
  perfPnl: document.getElementById('perf-pnl'),
  perfCount: document.getElementById('perf-count'),
  sharpeRatio: document.getElementById('sharpe-ratio'),

  // Trade History
  tradeHistoryBody: document.getElementById('trade-history-body'),

  btnBuy: document.getElementById('btn-buy'),
  btnSell: document.getElementById('btn-sell'),
};

// Chart setup
const chartWrapper = document.getElementById('candleChart');
const chart = createChart(chartWrapper, {
  layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: '#94a3b8' },
  grid: { vertLines: { color: 'rgba(255,255,255,0.05)' }, horzLines: { color: 'rgba(255,255,255,0.05)' } },
  crosshair: { mode: 0 },
  rightPriceScale: { borderColor: 'rgba(255,255,255,0.1)' },
  timeScale: { borderColor: 'rgba(255,255,255,0.1)' },
});
const candlestickSeries = chart.addSeries(CandlestickSeries, {
  upColor: '#10b981', downColor: '#ef4444', borderVisible: false,
  wickUpColor: '#10b981', wickDownColor: '#ef4444',
});

// Resize chart
new ResizeObserver(entries => {
  if (entries.length === 0 || entries[0].target !== chartWrapper) return;
  const newRect = entries[0].contentRect;
  chart.applyOptions({ height: newRect.height, width: newRect.width });
}).observe(chartWrapper);

// Fetchers
async function get(path) {
  try { const r = await fetch(API + path); return r.ok ? r.json() : null; } catch { return null; }
}
async function post(path, body) {
  try {
    pendingConfigUpdate = true;
    await fetch(API + path, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body) });
    // Lock UI sync for a few seconds to let backend restart
    setTimeout(() => { pendingConfigUpdate = false; refreshAll(); }, 4000);
  } catch(e) { console.error(e); }
}

// Config State
let currentConfig = { symbol: 'BTC/USDT', auto_portfolio: false, paper: true, futures: false };
let isUpdating = false;
let pendingConfigUpdate = false;

// Event Listeners for UI Controls
el.symbolSelect.addEventListener('change', (e) => {
  if(currentConfig.auto_portfolio) return; // ignore if auto
  post('/config', { symbol: e.target.value });
});
el.autoToggle.addEventListener('change', (e) => {
  el.symbolSelect.disabled = e.target.checked;
  post('/config', { auto_portfolio: e.target.checked });
});
el.futuresToggle.addEventListener('change', (e) => {
  post('/config', { futures: e.target.checked });
});
el.liveToggle.addEventListener('change', (e) => {
  const isLive = e.target.checked;
  if (isLive && !confirm("WARNING: Switching to LIVE mode will place real orders on Binance. Continue?")) {
    e.target.checked = false;
    return;
  }
  post('/config', { paper: !isLive });
});

if (el.chartSymbolSelect) {
  el.chartSymbolSelect.addEventListener('change', () => {
    refreshAll();
  });
}

window.setChartSymbol = function(symbol) {
  if (el.chartSymbolSelect) {
    let exists = Array.from(el.chartSymbolSelect.options).some(opt => opt.value === symbol);
    if (!exists) {
      const opt = document.createElement('option');
      opt.value = symbol;
      opt.text = symbol;
      el.chartSymbolSelect.add(opt);
    }
    el.chartSymbolSelect.value = symbol;
    refreshAll();
  }
};

// Manual Trade Listeners
el.btnBuy.addEventListener('click', async () => {
  el.btnBuy.disabled = true;
  await fetch(API + '/trade/manual', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({action: 'LONG'}) });
  setTimeout(() => el.btnBuy.disabled = false, 2000);
  refreshAll();
});
el.btnSell.addEventListener('click', async () => {
  el.btnSell.disabled = true;
  await fetch(API + '/trade/manual', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({action: 'SHORT'}) });
  setTimeout(() => el.btnSell.disabled = false, 2000);
  refreshAll();
});

function showToast(msg, type = 'info') {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.innerHTML = `<div>${msg}</div>`;
  container.appendChild(toast);
  
  setTimeout(() => {
    toast.style.animation = 'fadeOut 0.3s ease-out forwards';
    setTimeout(() => toast.remove(), 300);
  }, 5000);
}

// Sidebar Logic
const profileBtn = document.getElementById('profile-btn');
const closeSidebarBtn = document.getElementById('close-sidebar-btn');
const sidebar = document.getElementById('assets-sidebar');

if (profileBtn && sidebar) {
  profileBtn.addEventListener('click', () => sidebar.classList.add('open'));
}
if (closeSidebarBtn && sidebar) {
  closeSidebarBtn.addEventListener('click', () => sidebar.classList.remove('open'));
}

// Trade History State
let tradePage = 1;
let tradeLimit = 10;
const btnPrevPage = document.getElementById('btn-prev-page');
const btnNextPage = document.getElementById('btn-next-page');
const pageIndicator = document.getElementById('page-indicator');
const startDateInput = document.getElementById('trade-start-date');
const endDateInput = document.getElementById('trade-end-date');
const btnRefreshTrades = document.getElementById('btn-refresh-trades');
const btnResetHistory = document.getElementById('btn-reset-history');
const thSortPnl = document.getElementById('th-sort-pnl');
const activeSortSelect = document.getElementById('active-sort-select');

let historySortOrder = null;

if (thSortPnl) {
  thSortPnl.addEventListener('click', () => {
    if (historySortOrder === 'desc') historySortOrder = 'asc';
    else historySortOrder = 'desc';
    fetchTrades();
  });
}

if (btnResetHistory) {
  btnResetHistory.addEventListener('click', async () => {
    if (!confirm("Are you sure you want to permanently delete all trade history?")) return;
    const res = await fetch(API + '/history/clear', { method: 'POST' });
    if (res.ok) {
      showToast("Trade history cleared successfully", "success");
      tradePage = 1;
      fetchTrades();
    } else {
      showToast("Failed to clear trade history", "error");
    }
  });
}

if (activeSortSelect) {
  activeSortSelect.addEventListener('change', () => refreshAll());
}

async function fetchTrades() {
  let url = `/trades?page=${tradePage}&limit=${tradeLimit}`;
  if (startDateInput && startDateInput.value) url += `&start_date=${startDateInput.value}`;
  if (endDateInput && endDateInput.value) url += `&end_date=${endDateInput.value}`;
  
  const res = await get(url);
  if (!res) return;
  
  if (btnPrevPage) btnPrevPage.disabled = res.page <= 1;
  if (btnNextPage) btnNextPage.disabled = res.page >= res.pages;
  if (pageIndicator) pageIndicator.textContent = `Page ${res.page} / ${Math.max(1, res.pages)}`;
  
  if (res.trades && res.trades.length > 0) {
    if (historySortOrder === 'desc') {
      res.trades.sort((a, b) => b.pnl - a.pnl);
    } else if (historySortOrder === 'asc') {
      res.trades.sort((a, b) => a.pnl - b.pnl);
    }
    
    el.tradeHistoryBody.innerHTML = res.trades.map(t => {
      const pnlColor = t.pnl >= 0 ? 'var(--green)' : 'var(--red)';
      const pnlSign = t.pnl >= 0 ? '+' : '';
      return `
        <tr>
          <td style="padding: 0.5rem; font-family: var(--font-display); font-weight: 600;">${t.symbol}</td>
          <td style="padding: 0.5rem;"><span class="badge ${t.side === 'LONG'?'long':'short'}">${t.side}</span></td>
          <td style="padding: 0.5rem; font-family: var(--font-mono);">$${t.entry.toFixed(2)}</td>
          <td style="padding: 0.5rem; font-family: var(--font-mono);">$${t.exit.toFixed(2)}</td>
          <td style="padding: 0.5rem; font-family: var(--font-mono); color: ${pnlColor};">${pnlSign}$${t.pnl.toFixed(4)}</td>
          <td style="padding: 0.5rem; font-family: var(--font-mono); color: ${pnlColor};">${pnlSign}${(t.roe || 0).toFixed(2)}%</td>
          <td style="padding: 0.5rem; font-size: 0.75rem;">${t.reason}</td>
        </tr>
      `;
    }).join('');
  } else {
    el.tradeHistoryBody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: #94a3b8; padding: 2rem;">No trades yet</td></tr>';
  }
}

if (btnPrevPage) btnPrevPage.addEventListener('click', () => { tradePage--; fetchTrades(); });
if (btnNextPage) btnNextPage.addEventListener('click', () => { tradePage++; fetchTrades(); });
if (btnRefreshTrades) btnRefreshTrades.addEventListener('click', () => { tradePage = 1; fetchTrades(); });

// Expose forceClose to global for inline onclick
window.forceClose = async function(symbol) {
  if (!confirm(`Are you sure you want to FORCE CLOSE the active position for ${symbol}?`)) return;
  await fetch(API + '/trade/close', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ symbol })
  });
  refreshAll();
};

let prevActiveSymbols = new Set();
let prevTradeCount = -1;
let prevLogsCount = 0;

// Update UI
async function refreshAll() {
  if (isUpdating) return;
  isUpdating = true;

  const [status, acc, logs] = await Promise.all([
    get('/status'), get('/account'), get('/logs')
  ]);

  if (!status) {
    el.statusInd.className = 'indicator offline'; el.statusText.textContent = 'Offline';
    isUpdating = false; return;
  }
  
  el.statusInd.className = 'indicator pulse online'; el.statusText.textContent = 'Online';

  // Sync Toggles (if changed externally or on load)
  if (!pendingConfigUpdate) {
    currentConfig = { symbol: status.symbol, auto_portfolio: status.auto_portfolio, paper: status.paper, futures: status.futures };
    el.symbolSelect.value = status.symbol;
    el.symbolSelect.disabled = status.auto_portfolio;
    el.autoToggle.checked = status.auto_portfolio;
    el.futuresToggle.checked = status.futures;
    el.liveToggle.checked = !status.paper;
  }

  // Render Account
  if (acc && !acc.error) {
    const renderBal = (dataObj) => {
      if (!dataObj || Object.keys(dataObj).length === 0) return '<div class="loading">No assets</div>';
      return Object.entries(dataObj).map(([asset, data]) => `
        <div class="acc-item">
          <div class="asset">${asset}</div>
          <div class="val">${Number(data.free).toFixed(4)}</div>
        </div>
      `).join('');
    };
    el.spotGrid.innerHTML = renderBal(acc.spot);
    el.futGrid.innerHTML = renderBal(acc.futures);
  } else {
    const errHtml = `<div class="loading" style="color: #ef4444;">Please set Binance API keys in .env</div>`;
    el.spotGrid.innerHTML = errHtml;
    el.futGrid.innerHTML = errHtml;
  }

  // Render Chart
  const selectedChartSym = el.chartSymbolSelect ? el.chartSymbolSelect.value : status.symbol;
  const candles = await get('/candles?symbol=' + encodeURIComponent(selectedChartSym));
  if (candles && candles.length > 0) {
    const firstClose = candles[0].close;
    let prec = 2;
    if (firstClose < 0.001) prec = 6;
    else if (firstClose < 0.01) prec = 5;
    else if (firstClose < 1) prec = 4;
    else if (firstClose < 10) prec = 3;
    
    candlestickSeries.applyOptions({
      priceFormat: {
        type: 'price',
        precision: prec,
        minMove: 1 / Math.pow(10, prec)
      }
    });
    candlestickSeries.setData(candles);
  }

  // Render Indicators
  if (status.indicators) {
    el.indRegime.textContent = status.regime || '--';
    el.indAdx.textContent = status.indicators.adx?.toFixed(1) || '0.0';
    el.indRsi.textContent = status.indicators.rsi?.toFixed(1) || '0.0';
    el.indAtr.textContent = (status.indicators.atr_pct * 100)?.toFixed(1) + '%' || '0%';
  }

  // Render Positions
  if (status.positions && status.positions.length > 0) {
    let sortedPositions = [...status.positions];
    if (activeSortSelect) {
      const sortVal = activeSortSelect.value;
      if (sortVal === 'newest') sortedPositions.sort((a, b) => new Date(b.opened_at || 0) - new Date(a.opened_at || 0));
      else if (sortVal === 'oldest') sortedPositions.sort((a, b) => new Date(a.opened_at || 0) - new Date(b.opened_at || 0));
      else if (sortVal === 'profit-high') sortedPositions.sort((a, b) => (b.unrealized_pnl || 0) - (a.unrealized_pnl || 0));
      else if (sortVal === 'profit-low') sortedPositions.sort((a, b) => (a.unrealized_pnl || 0) - (b.unrealized_pnl || 0));
    }
    
    el.posList.innerHTML = sortedPositions.map(p => {
      const uPnl = p.unrealized_pnl || 0;
      const uRoe = p.unrealized_roe || 0;
      const uPnlColor = uPnl >= 0 ? 'var(--green)' : 'var(--red)';
      const uPnlSign = uPnl >= 0 ? '+' : '-';
      const absPnl = Math.abs(uPnl);
      const uRoeStr = uRoe >= 0 ? `+${uRoe.toFixed(2)}` : `${uRoe.toFixed(2)}`;
      
      const isDummySl = p.sl === 0 || p.sl >= 9999999999;
      const isDummyTp = p.tp === 0 || p.tp >= 9999999999;
      const slStr = isDummySl ? 'None' : '$' + p.sl.toFixed(4);
      const tpStr = isDummyTp ? 'None' : '$' + p.tp.toFixed(4);

      return `
        <div class="pos-item" style="display: flex; justify-content: space-between; align-items: center;">
          <div>
            <div class="pos-sym" onclick="window.setChartSymbol('${p.symbol}')" style="cursor: pointer; text-decoration: underline; text-decoration-color: rgba(255,255,255,0.2); transition: color 0.2s;" onmouseover="this.style.color='var(--accent)'" onmouseout="this.style.color='inherit'">${p.symbol} <span class="badge ${p.side === 'LONG'?'long':'short'}">${p.side} ${p.leverage ? p.leverage+'x' : ''}</span></div>
            <div style="font-size:0.8rem; color:#94a3b8; margin-top:4px;">Entry: $${p.entry.toFixed(4)} | Qty: ${p.qty}</div>
            <div style="font-size:0.75rem; color:#64748b; margin-top:2px;">TP: ${tpStr} | SL: ${slStr}</div>
          </div>
          <div style="display: flex; flex-direction: column; align-items: flex-end; gap: 4px;">
            <div style="display: flex; gap: 8px; align-items: center;">
              <span style="font-size:0.85rem; font-family: var(--font-mono); color: ${uPnlColor}; background: rgba(${uPnl >= 0 ? '34,197,94':'239,68,68'}, 0.1); padding: 2px 6px; border-radius: 4px;">${uRoeStr}%</span>
              <span style="font-size:0.9rem; font-family: var(--font-mono); color: ${uPnlColor}; font-weight: 600;">${uPnlSign}$${absPnl.toFixed(2)}</span>
            </div>
            <button class="btn-force-close" onclick="window.forceClose('${p.symbol}')">✖ Close</button>
          </div>
        </div>
      `;
    }).join('');
  } else {
    el.posList.innerHTML = '<div style="color:#94a3b8; font-size:0.9rem;">No active positions</div>';
  }

  // Notifications for new positions and trades
  if (prevTradeCount !== -1) {
    // Check new trades
    if (status.trade_count > prevTradeCount) {
      fetchTrades();
      const newTrades = status.trade_count - prevTradeCount;
      const latest = status.recent_trades ? status.recent_trades[status.recent_trades.length - 1] : null;
      if (latest) {
        const pnlStr = latest.pnl >= 0 ? `+$${latest.pnl.toFixed(2)}` : `-$${Math.abs(latest.pnl).toFixed(2)}`;
        showToast(`Closed ${latest.side} on ${latest.symbol}<br>PnL: ${pnlStr}`, latest.pnl >= 0 ? 'success' : 'info');
      }
    }
    
    // Check new positions
    const currentSymbols = new Set(status.positions?.map(p => p.symbol) || []);
    for (let sym of currentSymbols) {
      if (!prevActiveSymbols.has(sym)) {
        const p = status.positions.find(x => x.symbol === sym);
        showToast(`Opened ${p.side} position on ${sym}`, 'info');
      }
    }
    prevActiveSymbols = currentSymbols;
  } else {
    prevActiveSymbols = new Set(status.positions?.map(p => p.symbol) || []);
  }

  // Render Performance
  if (status.equity !== undefined) {
    el.perfEquity.textContent = '$' + status.equity.toFixed(2);
    const pnl = status.equity_pnl || 0;
    el.perfPnl.textContent = (pnl >= 0 ? '+$' : '-$') + Math.abs(pnl).toFixed(2);
    el.perfPnl.style.color = pnl >= 0 ? 'var(--green)' : 'var(--red)';
  }
  if (el.perfCount) el.perfCount.textContent = status.trade_count || 0;
  if (el.sharpeRatio && status.sharpe_ratio !== undefined) {
    el.sharpeRatio.textContent = status.sharpe_ratio.toFixed(2);
  }

  // Fetch Trades on first load
  if (prevTradeCount === -1) {
    fetchTrades();
  }

  // Render Console Logs
  if (logs && logs.length > 0) {
    el.console.innerHTML = logs.map(log => {
      let color = '#94a3b8';
      if (log.includes('Order failed')) color = 'var(--red)';
      if (log.includes('ENTRY:') || log.includes('🚀')) color = 'var(--green)';
      if (log.includes('Ignored') || log.includes('⚠️')) color = '#eab308';
      return `<div style="color: ${color}; margin-bottom: 0.3rem;">${log}</div>`;
    }).join('');
    if(logs.length !== prevLogsCount) {
      el.console.scrollTop = el.console.scrollHeight;
      prevLogsCount = logs.length;
    }
  }

  prevTradeCount = status.trade_count || 0;
  isUpdating = false;
}

// Settings Logic
async function fetchSettings() {
  try {
    const res = await get('/settings');
    if (res && res.hard_stop !== undefined) {
      if(el.settingHardStop) el.settingHardStop.value = res.hard_stop;
      if(el.settingTimeLimit) el.settingTimeLimit.value = res.time_limit;
    }
  } catch(e) {}
}

if (el.btnApplySettings) {
  el.btnApplySettings.addEventListener('click', async () => {
    const payload = {};
    if (el.settingHardStop && el.settingHardStop.value) payload.hard_stop = parseFloat(el.settingHardStop.value);
    if (el.settingTimeLimit && el.settingTimeLimit.value) payload.time_limit = parseFloat(el.settingTimeLimit.value);
    
    el.btnApplySettings.textContent = 'Applying...';
    try {
      await fetch(API + '/settings', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload)
      });
      el.btnApplySettings.textContent = 'Applied!';
      el.btnApplySettings.style.background = 'var(--green)';
      setTimeout(() => {
        el.btnApplySettings.textContent = 'Apply Settings';
        el.btnApplySettings.style.background = 'var(--border-color)';
      }, 2000);
    } catch(e) {
      el.btnApplySettings.textContent = 'Error';
    }
  });
}

// Init loop
fetchSettings();
refreshAll();
setInterval(refreshAll, 5000);
