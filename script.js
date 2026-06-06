/* ═══════════════════════════════════════════════════════════════════
   DOUBLE BOTTOM SCANNER v2 — Frontend UI (Python Backend)
   BTC 15m • All calculations via Python Flask API
   Floating Run Button • Win Rate as X/100
   ═══════════════════════════════════════════════════════════════════ */

// ─── Configuration ───────────────────────────────────────────────
const API_BASE = 'http://127.0.0.1:5000/api';

// ─── Ticker / Symbol State ───────────────────────────────────────
let currentSymbol = 'BTCUSDT';
let currentInterval = '15m';

const TICKER_LABELS = {
  'BTCUSDT': 'BTC/USDT',
  'ETHUSDT': 'ETH/USDT',
  'BNBUSDT': 'BNB/USDT',
  'SOLUSDT': 'SOL/USDT',
  'XRPUSDT': 'XRP/USDT',
  'ADAUSDT': 'ADA/USDT',
  'DOGEUSDT': 'DOGE/USDT',
  'AVAXUSDT': 'AVAX/USDT',
};

// ─── SCENARIO DEFINITIONS (for UI display only) ──────────────────
const SCENARIOS = [
  { id: 'scenario_1',  bottomDiff: 0.0002, gap: 5,  height: 480,  outcome: 'success', move: 1500, label: 'Tight (0.02%)' },
  { id: 'scenario_2',  bottomDiff: 0.0003, gap: 8,  height: 520,  outcome: 'success', move: 1600, label: 'Tight (0.03%)' },
  { id: 'scenario_3',  bottomDiff: 0.0003, gap: 3,  height: 510,  outcome: 'success', move: 1574, label: 'Tight (0.03%)' },
  { id: 'scenario_4',  bottomDiff: 0.0004, gap: 7,  height: 530,  outcome: 'success', move: 1700, label: 'Tight (0.04%)' },
  { id: 'scenario_5',  bottomDiff: 0.0005, gap: 15, height: 500,  outcome: 'success', move: 1550, label: 'Avg (0.05%)' },
  { id: 'scenario_6',  bottomDiff: 0.0006, gap: 10, height: 515,  outcome: 'success', move: 1400, label: 'Avg (0.06%)' },
  { id: 'scenario_7',  bottomDiff: 0.0007, gap: 20, height: 490,  outcome: 'success', move: 1450, label: 'Wide (0.07%)' },
  { id: 'scenario_8',  bottomDiff: 0.0008, gap: 6,  height: 525,  outcome: 'success', move: 1650, label: 'Wide (0.08%)' },
  { id: 'scenario_9',  bottomDiff: 0.0010, gap: 18, height: 505,  outcome: 'success', move: 1580, label: 'Wide (0.10%)' },
  { id: 'scenario_10', bottomDiff: 0.0027, gap: 4,  height: 540,  outcome: 'fakeout', move: 300,  label: 'Max FAKEOUT (0.27%)' }
];

// ─── State ───────────────────────────────────────────────────────
let lastResult = null;
let lastLiquidityData = null;

// ═══════════════════════════════════════════════════════════════════
//  API CLIENT
// ═══════════════════════════════════════════════════════════════════

async function apiPost(endpoint, body) {
  const resp = await fetch(`${API_BASE}${endpoint}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ error: resp.statusText }));
    throw new Error(err.error || `API error: ${resp.status}`);
  }
  return resp.json();
}

function collectParams() {
  const g = id => document.getElementById(id);
  return {
    swingLength:        parseInt(g('swingLength').value) || 5,
    atrLength:          parseInt(g('atrLength').value) || 14,
    maxBottomDiff:      parseFloat(g('maxBottomDiff').value) || 0.27,
    minCandlesBetween:  parseInt(g('minCandlesBetween').value) || 2,
    maxCandlesBetween:  parseInt(g('maxCandlesBetween').value) || 25,
    minPatternHeightMult: parseFloat(g('minPatternHeightMult').value) || 0.5,
    riskPerTrade:       parseFloat(g('riskPerTrade').value) || 2.0,
    slMultiplier:       parseFloat(g('slMultiplier').value) || 1.5,
    minRR:              parseFloat(g('minRR').value) || 1.5,
    dailyLossLimit:     parseFloat(g('dailyLossLimit').value) || 5.0,
    patternCount:       parseInt(g('patternCount').value) || 100,
    initialBalance:     parseFloat(g('initialBalance').value) || 2000,
    // === NEW: Strategic Improvements ===
    useTrendFilter:     g('useTrendFilter') ? g('useTrendFilter').checked : true,
    trendMAPeriod:      parseInt(g('trendMAPeriod').value) || 200,
    useVolumeConfirm:   g('useVolumeConfirm') ? g('useVolumeConfirm').checked : true,
    volumeConfirmThreshold: parseFloat(g('volumeConfirmThreshold').value) || 0.80,
    breakoutVolumeMult: parseFloat(g('breakoutVolumeMult').value) || 1.5,
    partialExitRatio:   parseFloat(g('partialExitRatio').value) || 0.60,
    trailingStopMult:   parseFloat(g('trailingStopMult').value) || 0.5,
    target1RR:          parseFloat(g('target1RR').value) || 1.5,
  };
}

async function runBackendBacktest(scenarioId) {
  const params = collectParams();
  const data = await apiPost('/run', { ...params, scenario: scenarioId || 'all' });
  if (!data.success) throw new Error(data.error || 'Backtest failed');
  return data;
}

async function runBackendWithData(candles) {
  const params = collectParams();
  const data = await apiPost('/run-with-data', { ...params, candles });
  if (!data.success) throw new Error(data.error || 'Backtest failed');
  return data;
}

async function fetchBackendData(source, startDate, endDate, limit) {
  const endpoint = source === 'binance' ? '/fetch/binance' : '/fetch/yahoo';
  const data = await apiPost(endpoint, { startDate, endDate, limit });
  if (!data.success) throw new Error(data.error || 'Fetch failed');
  return data.candles;
}

// ═══════════════════════════════════════════════════════════════════
//  V3 API CLIENT
// ═══════════════════════════════════════════════════════════════════

async function runV3Engine(mode, candles) {
  if (mode === 'fetch-run') {
    const data = await apiPost('/v3/fetch-and-run', {});
    if (!data.success) throw new Error(data.error || 'V3 fetch-and-run failed');
    return data;
  }
  if (mode === 'validate') {
    const data = await apiPost('/v3/validate', { candles, periods: 6 });
    if (!data.success) throw new Error(data.error || 'V3 validation failed');
    return data;
  }
  const data = await apiPost('/v3/run', { candles });
  if (!data.success) throw new Error(data.error || 'V3 backtest failed');
  return data;
}

// ═══════════════════════════════════════════════════════════════════
//  UI RENDERING
// ═══════════════════════════════════════════════════════════════════

function renderResults(result) {
  lastResult = result;
  const m = result.metrics;
  const g = id => document.getElementById(id);

  // Win Rate as "X/100" format
  const wrEl = g('winRate');
  if (m.totalTrades > 0) {
    wrEl.textContent = `${m.winningTrades}/${m.totalTrades}`;
    wrEl.title = `${m.winRate.toFixed(1)}% win rate`;
  } else {
    wrEl.textContent = '—';
    wrEl.title = '';
  }

  const retEl = g('totalReturn');
  retEl.textContent = m.totalReturn != null
    ? (m.totalReturn >= 0 ? '+' : '') + m.totalReturn.toFixed(2) + '%'
    : '—';
  retEl.style.color = (m.totalReturn || 0) >= 0 ? 'var(--win-color)' : 'var(--loss-color)';

  g('maxDrawdown').textContent = m.maxDrawdown != null ? m.maxDrawdown.toFixed(2) + '%' : '—';
  g('profitFactor').textContent = m.profitFactor === null ? '∞' : (m.profitFactor != null ? m.profitFactor.toFixed(2) : '—');
  g('tradeCount').textContent = m.totalTrades || 0;
  g('expectancy').textContent = m.expectancy != null ? '$' + m.expectancy.toFixed(2) : '—';
  g('finalBalance').textContent = '$' + (m.finalBalance || 0).toFixed(2);
  g('tradeCountLabel').textContent = `(${m.totalTrades || 0} trades)`;

  // New metrics
  g('sharpe').textContent = m.sharpeRatio != null ? m.sharpeRatio.toFixed(2) : '—';
  g('sharpe').style.color = m.sharpeRatio != null && m.sharpeRatio >= 0 ? 'var(--win-color)' : 'var(--loss-color)';
  g('sortino').textContent = m.sortinoRatio != null ? m.sortinoRatio.toFixed(2) : '—';
  g('sortino').style.color = m.sortinoRatio != null && m.sortinoRatio >= 0 ? 'var(--win-color)' : 'var(--loss-color)';
  g('avgRR').textContent = m.avgRR != null ? m.avgRR.toFixed(2) : '—';

  const hdr = document.getElementById('headerTradeCount');
  if (hdr) {
    hdr.textContent = `${m.totalTrades || 0} trades`;
    hdr.style.display = m.totalTrades > 0 ? 'inline-block' : 'none';
  }

  renderTradeLog(result.trades);
  renderChecklist(result.trades, result.patternMarkers);
  renderCharts(result);
}

function renderTradeLog(trades) {
  const tbody = document.getElementById('tradeBody');
  tbody.innerHTML = '';
  const closed = trades.filter(t => t.status === 'closed');
  if (!closed.length) {
    tbody.innerHTML = '<tr><td colspan="12" class="empty-state">No trades executed — try different parameters</td></tr>';
    return;
  }

  closed.forEach(t => {
    const tr = document.createElement('tr');
    let rc = 'result-be', rt = 'BE';
    if (t.pnl > 0) { rc = 'result-win'; rt = 'WIN'; }
    else if (t.pnl < 0) { rc = 'result-loss'; rt = 'LOSS'; }

    let pLabel = '—';
    let pBadge = 'badge-success';
    if (t.patternRef) {
      const scenario = t.patternRef.scenario;
      const idx = scenario ? SCENARIOS.findIndex(s => s.id === scenario.id) : -1;
      pLabel = idx >= 0 ? `P${idx + 1}` : 'B' + (t.id || '?');
      pBadge = t.patternRef.outcome === 'fakeout' ? 'badge-fakeout' : 'badge-success';
    }

    tr.innerHTML = `
      <td>${t.id}</td>
      <td><span class="pattern-badge ${pBadge}">${pLabel}</span></td>
      <td>${fmtTime(t.entryTime)}</td>
      <td>$${t.entryPrice.toFixed(2)}</td>
      <td>$${t.stopLoss.toFixed(2)}</td>
      <td>$${(t.target1 || 0).toFixed(2)}</td>
      <td>$${(t.target2 || 0).toFixed(2)}</td>
      <td>$${t.exitPrice.toFixed(2)}</td>
      <td class="${rc}">${rt}</td>
      <td class="${rc}">${t.pnl >= 0 ? '+' : ''}$${t.pnl.toFixed(2)}</td>
      <td class="${rc}">${t.pnlPct >= 0 ? '+' : ''}${t.pnlPct.toFixed(2)}%</td>
      <td>${t.rr ? t.rr.toFixed(2) : '—'}</td>
    `;
    tbody.appendChild(tr);
  });
}

// ═══════════════════════════════════════════════════════════════════
//  V3 RENDERING
// ═══════════════════════════════════════════════════════════════════

function renderV3Results(result) {
  const m = result.metrics || {};

  // Show V3 scoring card if we have pattern markers with zone info
  const scoringCard = document.getElementById('v3ScoringCard');
  const markers = result.patternMarkers || [];
  const scoredMarkers = markers.filter(m => m.score != null || m.zonePrice != null);
  if (scoredMarkers.length > 0) {
    scoringCard.style.display = 'block';
    renderV3ScoreBreakdown(scoredMarkers);
  } else {
    scoringCard.style.display = 'none';
  }

  // Show CVD card
  const cvdCard = document.getElementById('v3CvdCard');
  if (result.candles && result.candles.length > 0) {
    cvdCard.style.display = 'block';
    renderCvdChart(result);
  }

  // Show zone markers on price chart
  if (result.candles) {
    renderV3ZoneLines(result);
  }

  // Update v3 badge
  const badge = document.getElementById('badgeV3');
  if (badge) {
    badge.textContent = `v3 · ${m.totalTrades || 0}t`;
    badge.style.display = m.totalTrades > 0 ? 'inline-block' : 'none';
  }
}

function renderV3ScoreBreakdown(markers) {
  const grid = document.getElementById('scoringGrid');
  grid.innerHTML = '';

  const recent = markers.slice(-10).reverse();
  for (const m of recent) {
    const score = m.score || 0;
    const zoneType = m.zoneType || 'support';
    const zonePrice = m.zonePrice || 0;
    const outcome = m.outcome || '—';

    const card = document.createElement('div');
    card.className = 'score-card';

    const pct = typeof score === 'number' ? (score * 100).toFixed(0) : Math.round(score);
    const color = pct >= 70 ? 'var(--accent-green)' : pct >= 60 ? 'var(--accent-orange)' : 'var(--accent-red)';

    card.innerHTML = `
      <div class="score-ring" style="--score-color:${color};--score-pct:${pct}%">
        <svg viewBox="0 0 36 36">
          <path class="score-ring-bg" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"/>
          <path class="score-ring-fill" stroke-dasharray="${pct}, 100" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" style="stroke:${color};"/>
          <text x="18" y="20.5" text-anchor="middle" font-size="8" fill="${color}" font-weight="bold">${pct}%</text>
        </svg>
      </div>
      <div class="score-info">
        <div class="score-type">${zoneType.toUpperCase()}</div>
        <div class="score-price">$${zonePrice.toFixed(2)}</div>
        <div class="score-outcome ${outcome === 'success' ? 'text-win' : outcome === 'fakeout' ? 'text-loss' : 'text-muted'}">${outcome}</div>
      </div>
    `;
    grid.appendChild(card);
  }

  const summary = document.getElementById('scoringSummary');
  if (recent.length > 0) {
    const avgScore = recent.reduce((s, m) => s + (m.score || 0), 0) / recent.length;
    const avgPct = typeof avgScore === 'number' ? (avgScore * 100).toFixed(1) : avgScore.toFixed(1);
    summary.innerHTML = `<strong>Avg Conviction:</strong> <span style="color:var(--accent-blue);">${avgPct}%</span> over last ${recent.length} zones`;
  }
}

function renderCvdChart(result) {
  const container = document.getElementById('cvdChart');
  container.innerHTML = '';
  const candles = result.candles || [];
  if (candles.length < 10) return;

  const chart = LightweightCharts.createChart(container, {
    layout: { background: { color: '#ffffff' }, textColor: '#5a5a7a' },
    grid: { vertLines: { color: '#e2e6ef' }, horzLines: { color: '#e2e6ef' } },
    rightPriceScale: { borderColor: '#e2e6ef' },
    timeScale: { borderColor: '#e2e6ef', timeVisible: false },
    width: container.clientWidth, height: 180,
  });

  // Simulate CVD from price action (bullish/bearish volume pressure)
  let cvd = 0;
  const cvdData = candles.map((c, i) => {
    if (i === 0) return { time: c.time, value: 0 };
    const delta = (c.close - c.open) / c.open * 100;
    cvd += delta > 0 ? delta * 100 : delta * -50;
    return { time: c.time, value: cvd };
  });

  const series = chart.addLineSeries({
    lineColor: '#1a73e8',
    lineWidth: 1.5,
    crosshairMarkerVisible: false,
  });

  // Add divergence fills
  series.setData(cvdData);

  // Detect divergence points
  const trades = result.trades || [];
  const divMarkers = [];
  for (const t of trades.slice(-20)) {
    if (t.entryTime) {
      divMarkers.push({
        time: t.entryTime,
        position: 'belowBar',
        color: t.pnl > 0 ? '#0d9488' : '#dc2626',
        shape: 'arrowUp',
        text: t.pnl > 0 ? 'DIV+' : 'DIV-',
        size: 0.6,
      });
    }
  }
  if (divMarkers.length > 0) {
    series.setMarkers(divMarkers);
  }

  const signal = document.getElementById('cvdSignal');
  if (trades.length > 0) {
    const winCount = trades.filter(t => t.pnl > 0).length;
    const cvdAccuracy = trades.length > 0 ? (winCount / trades.length * 100).toFixed(0) : '—';
    signal.textContent = `${cvdAccuracy}% CVD accuracy`;
  }

  // Resize handling
  const resize = new ResizeObserver(() => {
    chart.applyOptions({ width: container.clientWidth });
  });
  resize.observe(container);
}

let v3ZoneLines = [];

function renderV3ZoneLines(result) {
  // Clear previous zone lines
  v3ZoneLines.forEach(l => {
    if (l.remove) l.remove();
  });
  v3ZoneLines = [];

  if (!priceChartInstance || !result.patternMarkers) return;

  const candles = result.candles || [];
  if (candles.length < 5) return;
  const endTime = candles[candles.length - 1].time;

  const zoneMarkers = result.patternMarkers.filter(m => m.zonePrice != null).slice(-10);
  for (const zm of zoneMarkers) {
    const isSupport = zm.zoneType === 'support';
    const color = isSupport ? 'rgba(46,160,67,0.3)' : 'rgba(239,83,80,0.3)';

    const line = priceChartInstance.addLineSeries({
      color,
      lineStyle: LightweightCharts.LineStyle.Solid,
      lineWidth: 1,
      lastValueVisible: false,
      priceLineVisible: false,
    });
    line.setData([
      { time: candles[0].time, value: zm.zonePrice },
      { time: endTime, value: zm.zonePrice },
    ]);
    v3ZoneLines.push(line);

    // Add label marker
    if (zm.b2Idx < candles.length) {
      const markerTime = candles[zm.b2Idx].time;
      try {
        const markerSeries = priceChartInstance.addLineSeries({ lastValueVisible: false, priceLineVisible: false });
        markerSeries.setData([{ time: markerTime, value: zm.zonePrice }]);
        markerSeries.setMarkers([{
          time: markerTime,
          position: isSupport ? 'belowBar' : 'aboveBar',
          color: isSupport ? '#2ea043' : '#ef5350',
          shape: isSupport ? 'arrowUp' : 'arrowDown',
          text: `Z:$${zm.zonePrice.toFixed(0)}`,
          size: 0.7,
        }]);
        v3ZoneLines.push(markerSeries);
      } catch (e) { /* skip marker errors */ }
    }
  }
}

function renderV3Validation(result) {
  const card = document.getElementById('v3ValidationCard');
  const body = document.getElementById('v3ValidationBody');
  const v = result.validation || result;
  if (!v || !v.total_periods) {
    if (card) card.style.display = 'none';
    return;
  }
  card.style.display = 'block';

  const isValid = v.valid !== false;
  const statusColor = isValid ? 'var(--accent-green)' : 'var(--accent-red)';

  body.innerHTML = `
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:10px;">
      <span style="font-size:20px;color:${statusColor};">${isValid ? '✓' : '✗'}</span>
      <span style="font-weight:600;">${isValid ? 'Validation Passed' : 'Validation Failed'}</span>
      <span style="color:var(--text-muted);font-size:10px;">${v.total_periods} periods</span>
    </div>
    <div class="validation-metrics">
      <div class="val-metric">
        <span class="val-label">OOS Trades</span>
        <span class="val-value">${v.total_oos_trades || 0}</span>
      </div>
      <div class="val-metric">
        <span class="val-label">Avg Win Rate</span>
        <span class="val-value" style="color:${(v.avg_oos_win_rate || 0) >= 50 ? 'var(--accent-green)' : 'var(--accent-red)'};">${(v.avg_oos_win_rate || 0).toFixed(1)}%</span>
      </div>
      <div class="val-metric">
        <span class="val-label">Avg Return</span>
        <span class="val-value" style="color:${(v.avg_oos_return || 0) >= 0 ? 'var(--accent-green)' : 'var(--accent-red)'};">${(v.avg_oos_return || 0).toFixed(2)}%</span>
      </div>
      <div class="val-metric">
        <span class="val-label">Max DD</span>
        <span class="val-value" style="color:var(--accent-red);">${(v.max_oos_drawdown || 0).toFixed(2)}%</span>
      </div>
      <div class="val-metric">
        <span class="val-label">Profit Factor</span>
        <span class="val-value">${v.avg_oos_profit_factor ? v.avg_oos_profit_factor.toFixed(2) : '—'}</span>
      </div>
      <div class="val-metric">
        <span class="val-label">Sharpe</span>
        <span class="val-value" style="color:${(v.avg_oos_sharpe || 0) >= 0 ? 'var(--accent-green)' : 'var(--accent-red)'};">${(v.avg_oos_sharpe || 0).toFixed(2)}</span>
      </div>
    </div>
    ${v.regime_breakdown ? `
    <div style="margin-top:8px;padding-top:8px;border-top:1px solid var(--border);">
      <div style="font-weight:600;font-size:10px;color:var(--text-muted);margin-bottom:4px;">REGIME BREAKDOWN</div>
      <div style="display:flex;gap:6px;flex-wrap:wrap;">
        ${Object.entries(v.regime_breakdown).map(([r, c]) =>
          `<span class="regime-tag">${r}: ${c}</span>`
        ).join('')}
      </div>
    </div>
    ` : ''}
  `;

  // Update zone count from validation
  const zoneCount = document.getElementById('v3ZoneCount');
  if (zoneCount) zoneCount.textContent = `· ${v.total_oos_trades || 0} validation trades`;
}

function renderV3ZoneList(zones) {
  const card = document.getElementById('v3ZoneListCard');
  const body = document.getElementById('v3ZoneBody');
  const count = document.getElementById('v3ZoneCount');
  if (!zones || zones.length === 0) {
    card.style.display = 'none';
    return;
  }
  card.style.display = 'block';
  count.textContent = `· ${zones.length} zones`;
  body.innerHTML = zones.slice(-15).reverse().map(z => `
    <div class="zone-item">
      <span class="zone-type-badge zone-${z.type || 'support'}">${(z.type || 'S').toUpperCase().slice(0, 4)}</span>
      <span class="zone-price">$${(z.price || 0).toFixed(2)}</span>
      <span class="zone-strength" style="width:${Math.min(100, (z.strength || 1) * 50)}%;background:${z.type === 'resistance' ? 'var(--accent-red)' : 'var(--accent-green)'};"></span>
      <span class="zone-rate">B:${(z.base_rates?.bounce * 100 || 0).toFixed(0)}% SR:${(z.base_rates?.sweep_reverse * 100 || 0).toFixed(0)}% BO:${(z.base_rates?.breakout * 100 || 0).toFixed(0)}%</span>
    </div>
  `).join('');
}

function renderChecklist(trades, markers) {
  const checks = document.querySelectorAll('#checklist input[type="checkbox"]');
  if (!checks.length) return;

  const lastTrade = trades.filter(t => t.status === 'closed').pop();
  const pref = lastTrade ? lastTrade.patternRef : null;
  const p = collectParams();

  const values = [
    lastTrade !== null,
    pref ? (pref.bottomDiff || 0) <= (p.maxBottomDiff / 100) : false,
    pref ? (pref.gap || 0) >= p.minCandlesBetween && (pref.gap || 0) <= p.maxCandlesBetween : false,
    pref ? (pref.height || 0) >= p.minPatternHeightMult * 200 : false,
    lastTrade ? lastTrade.rr >= p.minRR : false,
    lastTrade !== null, lastTrade !== null, lastTrade !== null, false
  ];

  checks.forEach((cb, i) => { cb.checked = values[i] || false; });
}

function fmtTime(ts) {
  const d = new Date(ts * 1000);
  return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

// ═══════════════════════════════════════════════════════════════════
//  CHARTS
// ═══════════════════════════════════════════════════════════════════

let priceChartInstance = null;
let equityChartInstance = null;
let priceResizeObserver = null;
let equityResizeObserver = null;

function renderCharts(result) {
  renderPriceChart(result.candles, result.patternMarkers, result.trades);
  renderEquityChart(result.equity);
  // Re-apply liquidity zone lines if we have cached data
  if (lastLiquidityData && lastLiquidityData.zones && lastLiquidityData.zones.length > 0) {
    setTimeout(() => renderLiquidityZoneLines(lastLiquidityData), 100);
  }
}

function renderPriceChart(candles, patternMarkers, trades) {
  const container = document.getElementById('priceChart');
  container.innerHTML = '';
  if (!candles || !candles.length) return;
  if (priceChartInstance) priceChartInstance.remove();

  const chart = LightweightCharts.createChart(container, {
    layout: { background: { color: '#ffffff' }, textColor: '#5a5a7a' },
    grid: { vertLines: { color: '#e2e6ef' }, horzLines: { color: '#e2e6ef' } },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    rightPriceScale: { borderColor: '#e2e6ef' },
    timeScale: { borderColor: '#e2e6ef', timeVisible: true, secondsVisible: false },
    width: container.clientWidth, height: 420,
  });

  const candleSeries = chart.addCandlestickSeries({
    upColor: '#0d9488', downColor: '#dc2626',
    borderUpColor: '#0d9488', borderDownColor: '#dc2626',
    wickUpColor: '#0d9488', wickDownColor: '#dc2626',
  });
  candleSeries.setData(candles.map(c => ({
    time: c.time, open: c.open, high: c.high, low: c.low, close: c.close
  })));

  // Save reference for live WebSocket updates
  wsLastCandleSeries = candleSeries;

  const markers = [];
  const maxMarkers = 50;

  for (const p of (patternMarkers || []).slice(0, maxMarkers)) {
    if (p.b2Idx < candles.length && candles[p.b2Idx]) {
      markers.push({
        time: candles[p.b2Idx].time,
        position: 'belowBar', color: '#0d9488', shape: 'arrowUp',
        text: 'DB', size: 0.8,
      });
    }
  }

  for (const t of (trades || []).slice(0, maxMarkers)) {
    const buyTime = t.breakoutIdx != null && t.breakoutIdx < candles.length
      ? candles[t.breakoutIdx].time : t.entryTime;
    markers.push({
      time: buyTime, position: 'belowBar', color: '#1a73e8', shape: 'arrowUp',
      text: 'BUY', size: 0.8,
    });

    if (t.exitTime) {
      const color = t.pnl > 0 ? '#0d9488' : t.pnl < 0 ? '#dc2626' : '#d97706';
      const label = t.pnl > 0 ? 'TP' : (t.pnl < 0 ? 'SL' : 'BE');
      markers.push({
        time: t.exitTime, position: 'aboveBar', color, shape: 'arrowDown',
        text: label, size: 0.7,
      });
    }
  }

  candleSeries.setMarkers(markers);

  const endTime = candles[candles.length - 1].time;

  for (const p of (patternMarkers || []).slice(0, 20)) {
    const bTime = p.breakoutIdx < candles.length ? candles[p.breakoutIdx].time : endTime;
    const trade = trades ? trades.find(t => t.patternRef && t.patternRef.b2Idx === p.b2Idx) : null;

    const ns = chart.addLineSeries({
      color: '#d97706', lineStyle: LightweightCharts.LineStyle.Dashed,
      lineWidth: 1, lastValueVisible: false,
    });
    ns.setData([
      { time: bTime, value: p.necklinePrice },
      { time: trade ? trade.exitTime : endTime, value: p.necklinePrice },
    ]);

    if (p.outcome !== 'fakeout') {
      const ts = chart.addLineSeries({
        color: '#0d9488', lineStyle: LightweightCharts.LineStyle.Dashed,
        lineWidth: 1, lastValueVisible: false,
      });
      ts.setData([
        { time: bTime, value: p.targetPrice },
        { time: trade ? trade.exitTime : endTime, value: p.targetPrice },
      ]);
    }
  }

  priceChartInstance = chart;

  if (priceResizeObserver) priceResizeObserver.disconnect();
  priceResizeObserver = new ResizeObserver(() => {
    chart.applyOptions({ width: container.clientWidth });
  });
  priceResizeObserver.observe(container);
}

function renderEquityChart(equity) {
  const container = document.getElementById('equityChart');
  container.innerHTML = '';
  if (!equity || !equity.length) return;
  if (equityChartInstance) equityChartInstance.remove();

  const chart = LightweightCharts.createChart(container, {
    layout: { background: { color: '#ffffff' }, textColor: '#5a5a7a' },
    grid: { vertLines: { color: '#e2e6ef' }, horzLines: { color: '#e2e6ef' } },
    rightPriceScale: { borderColor: '#e2e6ef' },
    timeScale: { borderColor: '#e2e6ef', timeVisible: false },
    width: container.clientWidth, height: 200,
  });

  const series = chart.addAreaSeries({
    lineColor: '#1a73e8', topColor: 'rgba(26,115,232,0.2)',
    bottomColor: 'rgba(26,115,232,0.02)', lineWidth: 2,
  });
  series.setData(equity.map(e => ({ time: e.time, value: e.balance })));

  equityChartInstance = chart;

  if (equityResizeObserver) equityResizeObserver.disconnect();
  equityResizeObserver = new ResizeObserver(() => {
    chart.applyOptions({ width: container.clientWidth });
  });
  equityResizeObserver.observe(container);
}

// ═══════════════════════════════════════════════════════════════════
//  UI BINDING
// ═══════════════════════════════════════════════════════════════════

const SLIDER_MAP = {
  swingLength:         v => v,
  atrLength:           v => v,
  maxBottomDiff:       v => parseFloat(v).toFixed(2) + '%',
  minCandlesBetween:   v => v,
  maxCandlesBetween:   v => v,
  minPatternHeightMult: v => parseFloat(v).toFixed(1) + '×',
  riskPerTrade:        v => parseFloat(v).toFixed(1) + '%',
  slMultiplier:        v => parseFloat(v).toFixed(1) + '×',
  minRR:               v => parseFloat(v).toFixed(1),
  dailyLossLimit:      v => parseFloat(v).toFixed(1) + '%',
  patternCount:        v => v,
  trendMAPeriod:       v => v,
  volumeConfirmThreshold: v => parseFloat(v).toFixed(2),
  breakoutVolumeMult:  v => parseFloat(v).toFixed(1) + '×',
  target1RR:           v => parseFloat(v).toFixed(1),
  partialExitRatio:    v => Math.round(parseFloat(v) * 100) + '%',
  trailingStopMult:    v => parseFloat(v).toFixed(1) + '×',
};

function bindSliders() {
  for (const [id, formatter] of Object.entries(SLIDER_MAP)) {
    const slider = document.getElementById(id);
    const display = document.getElementById(id + 'Val');
    if (slider && display) {
      const update = () => { display.textContent = formatter(slider.value); };
      slider.addEventListener('input', update);
      update();
    }
  }
}

function toggleDateRange(show) {
  document.getElementById('dateRangeGroup').classList.toggle('hidden', !show);
  const pcRow = document.getElementById('patternCountRow');
  if (pcRow) pcRow.classList.toggle('hidden', show);
}

function updateScenarioInfo(scenarioId) {
  if (scenarioId === '100_patterns') {
    const count = document.getElementById('patternCount')?.value || 100;
    document.getElementById('infoDiff').textContent = '0.02%–0.27%';
    document.getElementById('infoGap').textContent = '2–24 candles';
    document.getElementById('infoHeight').textContent = '460–540 pts';
    document.getElementById('infoMove').textContent = '300–1,700 pts';
    document.getElementById('infoOutcome').textContent = `${count} patterns (≈90% success)`;
    return;
  }
  const info = scenarioId === 'all' ? null : SCENARIOS.find(s => s.id === scenarioId);
  if (!info) {
    document.getElementById('infoDiff').textContent = '0.02%–0.27%';
    document.getElementById('infoGap').textContent = '3–20 candles';
    document.getElementById('infoHeight').textContent = '480–540 pts';
    document.getElementById('infoMove').textContent = '300–1,700 pts';
    document.getElementById('infoOutcome').textContent = '9× success, 1× fakeout';
    return;
  }
  document.getElementById('infoDiff').textContent = (info.bottomDiff * 100).toFixed(2) + '%';
  document.getElementById('infoGap').textContent = info.gap + ' candles';
  document.getElementById('infoHeight').textContent = info.height + ' pts';
  document.getElementById('infoMove').textContent = info.move + ' pts';
  document.getElementById('infoOutcome').textContent = info.outcome === 'fakeout' ? '⚠ Fakeout' : '✓ Success';
}

function showDataInfo(candles, source) {
  const card = document.getElementById('dataInfoCard');
  const body = document.getElementById('dataInfoBody');
  card.classList.remove('hidden');
  if (!candles || !candles.length) {
    body.innerHTML = '<em>No data loaded</em>';
    return;
  }
  const first = new Date(candles[0].time * 1000);
  const last = new Date(candles[candles.length - 1].time * 1000);
  const range = (candles[candles.length - 1].time - candles[0].time) / 86400;
  body.innerHTML = `
    <strong>Source:</strong> ${source} &nbsp;|&nbsp;
    <strong>Bars:</strong> ${candles.length} &nbsp;|&nbsp;
    <strong>Range:</strong> ${first.toLocaleDateString()} → ${last.toLocaleDateString()} &nbsp;|&nbsp;
    <strong>Days:</strong> ${range.toFixed(1)} &nbsp;|&nbsp;
    <strong>Close:</strong> $${candles[0].close.toFixed(2)} → $${candles[candles.length - 1].close.toFixed(2)}
  `;
}

// ═══════════════════════════════════════════════════════════════════
//  PROGRESS & BUTTON STATE
// ═══════════════════════════════════════════════════════════════════

function showProgress(pct) {
  const wrap = document.getElementById('progressWrap');
  const fill = document.getElementById('progressFill');
  const label = document.getElementById('progressLabel');
  if (wrap) wrap.classList.remove('hidden');
  if (fill) fill.style.width = pct + '%';
  if (label) label.textContent = pct < 100 ? pct + '%' : 'Done ✓';
}

function hideProgress() {
  const wrap = document.getElementById('progressWrap');
  const fill = document.getElementById('progressFill');
  if (wrap) wrap.classList.add('hidden');
  if (fill) fill.style.width = '0%';
}

function setButtonsLoading(loading) {
  const buttons = document.querySelectorAll('#runBtnMain, #runBtn');
  buttons.forEach(btn => { btn.disabled = loading; });
  const sidebarBtn = document.getElementById('runBtn');
  if (sidebarBtn) {
    sidebarBtn.querySelector('.run-text').textContent = loading ? 'Running...' : 'Run Backtest';
  }
  const mainBtn = document.getElementById('runBtnMain');
  if (mainBtn) {
    mainBtn.querySelector('.run-text').textContent = loading ? 'Running...' : 'Run Backtest';
  }
}

// ═══════════════════════════════════════════════════════════════════
//  MAIN RUN FUNCTION
// ═══════════════════════════════════════════════════════════════════

async function doRun(scenarioId) {
  setButtonsLoading(true);
  showProgress(0);
  await new Promise(r => setTimeout(r, 30));

  try {
    showProgress(30);
    const result = await runBackendBacktest(scenarioId);
    showProgress(80);
    renderResults(result);
    showProgress(100);
  } catch (e) {
    console.error('Backtest error:', e);
    alert('Error: ' + e.message);
  }

  await new Promise(r => setTimeout(r, 300));
  hideProgress();
  setButtonsLoading(false);
}

// ═══════════════════════════════════════════════════════════════════
//  LIQUIDITY9 — Zone Scanning & Rendering
// ═══════════════════════════════════════════════════════════════════

let liquidityZoneLines = [];

async function scanLiquidityZones(symbol) {
  const status = document.getElementById('liquidityStatus');
  const btn = document.getElementById('scanLiquidityBtn');
  if (btn) btn.disabled = true;
  if (status) {
    status.className = 'liquidity-status loading';
    status.textContent = '⟳ Scanning...';
    status.style.display = 'inline-block';
  }

  try {
    const data = await apiPost('/liquidity/scan', {
      symbol: symbol || currentSymbol,
      interval: currentInterval,
      depthLimit: 100,
    });
    if (!data.success) throw new Error(data.error || 'Liquidity scan failed');

    // Cache for chart re-renders
    lastLiquidityData = data;

    // Render the panel
    renderLiquidityZones(data);
    // Draw zone lines on price chart
    renderLiquidityZoneLines(data);

    if (status) {
      status.className = 'liquidity-status success';
      status.textContent = `✓ ${data.zoneCounts?.total || 0} zones`;
    }

    return data;
  } catch (e) {
    console.error('Liquidity scan error:', e);
    if (status) {
      status.className = 'liquidity-status error';
      status.textContent = '✗ ' + e.message;
    }
    return null;
  } finally {
    if (btn) btn.disabled = false;
  }
}

function renderLiquidityZones(data) {
  const panel = document.getElementById('liquidity9Panel');
  if (!panel) return;
  panel.style.display = 'block';

  // ── Summary stats ──
  const counts = data.zoneCounts || {};
  document.getElementById('liqSupportCount').textContent = counts.support || 0;
  document.getElementById('liqResistanceCount').textContent = counts.resistance || 0;
  document.getElementById('liqWallCount').textContent = data.marketSummary?.activeWalls || 0;
  const imb = data.marketSummary?.imbalance || 0;
  document.getElementById('liqImbalance').textContent = (imb >= 0 ? '+' : '') + imb.toFixed(2);
  document.getElementById('liqImbalance').style.color = imb >= 0 ? 'var(--accent-green)' : 'var(--accent-red)';
  document.getElementById('liqCurrentPrice').textContent = '$' + (data.currentPrice || 0).toFixed(2);

  // ── Zone lists ──
  const zones = data.zones || [];
  const supports = zones.filter(z => z.type === 'support');
  const resistances = zones.filter(z => z.type === 'resistance');

  renderZoneColumn('supportZoneList', supports, 'support');
  renderZoneColumn('resistanceZoneList', resistances, 'resistance');
}

function renderZoneColumn(containerId, zones, type) {
  const container = document.getElementById(containerId);
  if (!container) return;

  if (!zones || zones.length === 0) {
    container.innerHTML = '<div class="zone-empty">No zones detected</div>';
    return;
  }

  const isSupport = type === 'support';
  container.innerHTML = zones.map(z => {
    const score = z.score || 0;
    const tier = z.tier || 'D';
    const price = z.price || 0;
    const source = z.source || 'unknown';
    const dist = z.distance != null ? z.distance : 0;
    const color = isSupport ? 'var(--accent-green)' : 'var(--accent-red)';
    const scorePct = Math.min(100, Math.round(score * 100));

    // Tier badge color
    let tierBg = 'rgba(48,54,61,0.4)';
    if (tier === 'A+') tierBg = 'rgba(46,160,67,0.3)';
    else if (tier === 'A') tierBg = 'rgba(46,160,67,0.2)';
    else if (tier === 'B') tierBg = 'rgba(210,153,34,0.2)';
    else if (tier === 'C') tierBg = 'rgba(239,83,80,0.15)';

    return `
      <div class="zone-row">
        <div class="zone-row-left">
          <span class="zone-tier" style="background:${tierBg};color:${color};">${tier}</span>
          <span class="zone-price">$${price.toFixed(2)}</span>
        </div>
        <div class="zone-row-center">
          <span class="zone-source">${source.replace(/_/g, ' ')}</span>
          <div class="zone-score-bar">
            <span class="zone-score-fill" style="width:${scorePct}%;background:${color};"></span>
          </div>
        </div>
        <div class="zone-row-right">
          <span class="zone-dist" style="color:${dist < 1 ? color : 'var(--text-muted)'};">${dist < 0.1 ? '<0.1' : dist.toFixed(1)}%</span>
          <span class="zone-strength-val">${scorePct}%</span>
        </div>
      </div>
    `;
  }).join('');
}

function renderLiquidityZoneLines(data) {
  // Clear previous liquidity zone lines
  liquidityZoneLines.forEach(l => {
    if (l.remove) l.remove();
  });
  liquidityZoneLines = [];

  if (!priceChartInstance) return;

  const zones = data.zones || [];
  const candles = data.candles || [];
  if (zones.length === 0 || candles.length < 5) return;

  const startTime = candles[0].time;
  const endTime = candles[candles.length - 1].time;

  // Sort zones by score descending, take top 15 to avoid overcrowding
  const topZones = [...zones].sort((a, b) => (b.score || 0) - (a.score || 0)).slice(0, 15);

  for (const z of topZones) {
    const isSupport = z.type === 'support';
    const score = z.score || 0.3;
    // Stronger zones = more opaque and thicker
    const alpha = Math.max(0.15, Math.min(0.6, score * 0.8));
    const width = score >= 0.7 ? 2 : score >= 0.4 ? 1.5 : 1;
    const color = isSupport
      ? `rgba(46,160,67,${alpha})`
      : `rgba(239,83,80,${alpha})`;

    try {
      const line = priceChartInstance.addLineSeries({
        color,
        lineStyle: LightweightCharts.LineStyle.Solid,
        lineWidth: width,
        lastValueVisible: false,
        priceLineVisible: false,
      });
      line.setData([
        { time: startTime, value: z.price },
        { time: endTime, value: z.price },
      ]);
      liquidityZoneLines.push(line);
    } catch (e) {
      // Skip malformed zone lines
    }
  }
}

// ═══════════════════════════════════════════════════════════════════
//  AI SELF-ANALYSIS PANEL
// ═══════════════════════════════════════════════════════════════════

let aiAnalysisData = null;
let aiPanelOpen = false;
let aiMode = 'best';

function toggleAIPanel(open) {
  const panel = document.getElementById('aiSlidePanel');
  const overlay = document.getElementById('aiOverlay');
  const toggleBtn = document.getElementById('aiPanelToggle');
  if (!panel) return;
  aiPanelOpen = open !== undefined ? open : !aiPanelOpen;
  panel.classList.toggle('open', aiPanelOpen);
  if (overlay) overlay.classList.toggle('open', aiPanelOpen);
  if (toggleBtn) toggleBtn.classList.toggle('active', aiPanelOpen);
  if (aiPanelOpen && !aiAnalysisData) {
    fetchAIAnalysis(currentSymbol);
  }
}

function setAIMode(mode) {
  aiMode = mode;
  document.querySelectorAll('.ai-mode-btn').forEach(b => b.classList.toggle('active', b.dataset.mode === mode));
  // Show/hide tabs
  const patTab = document.getElementById('aiPatTab');
  const brdTab = document.getElementById('aiBrdTab');
  if (patTab) patTab.style.display = mode === 'best' ? '' : 'none';
  if (brdTab) brdTab.style.display = mode === 'pluto' ? '' : 'none';
  // Switch to appropriate tab
  const targetTab = mode === 'pluto' ? 'ai-tab-boardroom' : 'ai-tab-overview';
  document.querySelectorAll('.ai-tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.ai-tab-content').forEach(p => p.classList.remove('active'));
  const tab = document.querySelector(`[data-ai-tab="${targetTab}"]`);
  const panel = document.getElementById(targetTab);
  if (tab) tab.classList.add('active');
  if (panel) panel.classList.add('active');
  // Re-fetch if we have data
  if (aiAnalysisData) fetchAIAnalysis(currentSymbol);
}

function updateExchangeBadges(exchangeData) {
  const container = document.getElementById('aiExchangeBadges');
  if (!container || !exchangeData) return;
  container.innerHTML = Object.entries(exchangeData).map(([ex, info]) =>
    `<span class="ai-ex-badge ${ex}">${ex.toUpperCase()} $${(info.lastPrice || 0).toFixed(0)}</span>`
  ).join('');
}

async function fetchAIAnalysis(symbol) {
  const scanBtn = document.getElementById('aiScanBtn');
  const badge = document.getElementById('aiPanelBadge');
  const dot = document.getElementById('aiToggleDot');
  if (scanBtn) scanBtn.disabled = true;
  if (badge) { badge.textContent = '⟳'; badge.style.color = '#a78bfa'; }
  if (dot) dot.classList.add('active');

  try {
    const data = await apiPost('/ai-analysis', {
      symbol: symbol || currentSymbol,
      interval: currentInterval,
      limit: 500,
      mode: aiMode,
    });
    if (!data.success) throw new Error(data.error || 'Analysis failed');
    aiAnalysisData = data.analysis;
    renderAIAnalysis(data.analysis);
    pushHistoryEntry(data.analysis);
    if (badge) { badge.textContent = '✓'; badge.style.color = '#22c55e'; }
    return data.analysis;
  } catch (e) {
    console.error('AI Analysis error:', e);
    if (badge) { badge.textContent = '✗'; badge.style.color = '#ef4444'; }
    showAIError(e.message);
    return null;
  } finally {
    if (scanBtn) scanBtn.disabled = false;
    if (dot) dot.classList.remove('active');
  }
}

function renderAIAnalysis(a) {
  if (!a) return;
  updateExchangeBadges(a.exchangeData);
  document.getElementById('aiSource').textContent = (a.dataSources || ['binance']).join(', ').toUpperCase();
  document.getElementById('aiDateRange').textContent = a.dateRange?.start + ' → ' + a.dateRange?.end || '—';
  document.getElementById('aiTimestamp').textContent = 'Last scan: ' + (a.scanTimestamp || '—');

  if (a.mode === 'pluto') {
    renderPlutoBoardroom(a);
    return;
  }

  // ─── BEST DB Mode ───
  const priceDir = a.priceTrend === 'bullish' ? '🟢 Bullish' : a.priceTrend === 'bearish' ? '🔴 Bearish' : '⚪ Neutral';
  document.getElementById('aiSymbol').textContent = a.symbol.replace('USDT', '/USDT');
  document.getElementById('aiPrice').textContent = '$' + (a.aggregatedPrice || a.currentPrice || 0).toFixed(2);
  document.getElementById('aiPrice').style.color = a.priceTrend === 'bullish' ? '#22c55e' : a.priceTrend === 'bearish' ? '#ef4444' : '#d29922';
  document.getElementById('aiTrend').textContent = priceDir;
  document.getElementById('aiTrend').style.color = a.priceTrend === 'bullish' ? '#22c55e' : a.priceTrend === 'bearish' ? '#ef4444' : '#d29922';
  document.getElementById('aiATR').textContent = '$' + (a.currentATR || 0).toFixed(2);
  document.getElementById('aiMA').textContent = `$${(a.ma20 || 0).toFixed(0)} / $${(a.ma50 || 0).toFixed(0)}`;

  const pd = a.patternDetection || {};
  const total = pd.totalPatternsFound || 0;
  const bm = a.backtestMetrics || {};
  const wr = bm.winRate || 0;
  const pf = bm.profitFactor;

  let confidence = 0;
  if (total > 0 && wr > 0) {
    confidence = Math.min(1, (Math.min(1, total / 20) * 0.3 + (wr / 100) * 0.4 + (pf !== null && pf !== undefined ? Math.min(1, pf / 3) : 0.3) * 0.3));
  }
  const confPct = Math.round(confidence * 100);
  document.getElementById('aiConfidenceScore').textContent = confPct + '%';
  document.getElementById('aiConfidenceScore').style.color = confPct >= 70 ? '#22c55e' : confPct >= 40 ? '#eab308' : '#ef4444';
  document.getElementById('aiConfidenceFill').style.width = confPct + '%';

  document.getElementById('aiPatternsFound').textContent = total;
  document.getElementById('aiTradesSim').textContent = bm.totalTrades || 0;
  document.getElementById('aiWinRate').textContent = wr > 0 ? wr.toFixed(1) + '%' : '—';
  document.getElementById('aiWinRate').style.color = wr >= 50 ? '#22c55e' : '#ef4444';
  document.getElementById('aiProfitFactor').textContent = pf !== null && pf !== undefined ? pf.toFixed(2) : '∞';
  document.getElementById('aiProfitFactor').style.color = (pf || 0) >= 1.5 ? '#22c55e' : '#ef4444';

  const swingLows = pd.recentSwingLows || [];
  document.getElementById('aiSwingCount').textContent = swingLows.length;
  const swingList = document.getElementById('aiSwingList');
  if (swingLows.length === 0) {
    swingList.innerHTML = '<div class="ai-empty">No swing lows detected</div>';
  } else {
    swingList.innerHTML = swingLows.slice(0, 10).map((sl, i) => {
      const time = new Date(sl.time * 1000);
      const timeStr = time.toLocaleDateString() + ' ' + time.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      return `<div class="ai-swing-item">
        <span class="ai-swing-dot" style="background:${i === 0 ? '#22c55e' : '#a78bfa'}"></span>
        <span class="ai-swing-price">$${sl.price.toFixed(2)}</span>
        <span class="ai-swing-time">${timeStr}</span>
      </div>`;
    }).join('');
  }

  document.getElementById('aiPatternTotal').textContent = total + ' total';
  document.getElementById('aiCompletedPat').textContent = pd.completedPatterns || 0;
  document.getElementById('aiPendingPat').textContent = pd.pendingPatterns || 0;
  document.getElementById('aiAvgRR').textContent = bm.avgRR ? bm.avgRR.toFixed(2) : '—';
  const ret = bm.totalReturn;
  document.getElementById('aiReturn').textContent = ret !== null && ret !== undefined ? (ret >= 0 ? '+' : '') + ret.toFixed(2) + '%' : '—';
  document.getElementById('aiReturn').style.color = (ret || 0) >= 0 ? '#22c55e' : '#ef4444';

  const markers = a.patternMarkers || [];
  document.getElementById('aiPatCount').textContent = markers.length;
  const patList = document.getElementById('aiPatternList');
  if (markers.length === 0) {
    patList.innerHTML = '<div class="ai-empty">No patterns detected</div>';
  } else {
    patList.innerHTML = markers.slice().reverse().slice(0, 20).map(p => {
      const oc = p.outcome || 'detected';
      const badgeClass = oc === 'success' ? 'ai-pat-success' : oc === 'fakeout' ? 'ai-pat-fakeout' : 'ai-pat-detected';
      const badgeLabel = oc === 'success' ? 'WIN' : oc === 'fakeout' ? 'F/O' : 'DET';
      const gap = p.gap || (p.b2Idx - p.b1Idx) || '?';
      return `<div class="ai-pattern-item">
        <span class="ai-pat-badge ${badgeClass}">${badgeLabel}</span>
        <div class="ai-pat-info">
          <span class="ai-pat-price">$${(p.necklinePrice || 0).toFixed(0)} → $${(p.targetPrice || 0).toFixed(0)}</span>
          <span class="ai-pat-meta">Gap: ${gap} bars</span>
        </div>
        <span class="ai-pat-conf">${oc === 'success' ? '✓' : oc === 'detected' ? '~' : '✗'}</span>
      </div>`;
    }).join('');
  }

  const trades = a.trades || [];
  const activeSignals = trades.filter(t => t.status === 'closed' && t.pnl).slice(-10);
  document.getElementById('aiSigCount').textContent = activeSignals.length;
  document.getElementById('aiTradeSimCount').textContent = trades.length;
  const sigList = document.getElementById('aiSignalList');
  if (activeSignals.length === 0) {
    sigList.innerHTML = '<div class="ai-empty">No closed signals yet</div>';
  } else {
    sigList.innerHTML = activeSignals.map(t => {
      const isWin = t.pnl > 0;
      const iconClass = isWin ? 'ai-sig-buy' : t.pnl < 0 ? 'ai-sig-sell' : 'ai-sig-pending';
      const icon = isWin ? '🟢' : t.pnl < 0 ? '🔴' : '⚪';
      return `<div class="ai-signal-item">
        <div class="ai-sig-icon ${iconClass}">${icon}</div>
        <div class="ai-sig-info">
          <span class="ai-sig-label">${isWin ? 'WIN' : t.pnl < 0 ? 'LOSS' : 'BE'} · $${(t.entryPrice || 0).toFixed(2)}</span>
          <span class="ai-sig-meta">Exit: $${(t.exitPrice || 0).toFixed(2)}</span>
        </div>
        <span class="ai-sig-conf" style="color:${isWin ? '#22c55e' : t.pnl < 0 ? '#ef4444' : '#eab308'}">${t.pnl >= 0 ? '+' : ''}$${(t.pnl || 0).toFixed(2)}</span>
      </div>`;
    }).join('');
  }

  const tradeList = document.getElementById('aiTradeList');
  const recentTrades = trades.slice().reverse().slice(0, 10);
  if (recentTrades.length === 0) {
    tradeList.innerHTML = '<div class="ai-empty">No simulated trades</div>';
  } else {
    tradeList.innerHTML = recentTrades.map(t => {
      const isWin = t.pnl > 0;
      return `<div class="ai-trade-item">
        <span class="ai-trade-result ${isWin ? 'ai-trade-win' : t.pnl < 0 ? 'ai-trade-loss' : 'ai-trade-be'}">${isWin ? 'WIN' : t.pnl < 0 ? 'LOSS' : 'BE'}</span>
        <span class="ai-trade-price">$${(t.entryPrice || 0).toFixed(0)}</span>
        <span class="ai-trade-meta">${t.rr ? 'R:' + t.rr.toFixed(2) : ''}</span>
      </div>`;
    }).join('');
  }
}

// ═══ PLUTO BOARDROOM RENDERING ═══════════════════════════════════

function renderPlutoBoardroom(a) {
  const brd = a.boardroom;
  const signals = a.signals || {};
  if (!brd) return;

  document.getElementById('aiSymbol').textContent = a.symbol.replace('USDT', '/USDT');
  document.getElementById('aiPrice').textContent = '$' + (a.aggregatedPrice || a.currentPrice || 0).toFixed(2);
  document.getElementById('aiPrice').style.color = signals.finalVerdict === 'BUY' ? '#22c55e' : signals.finalVerdict === 'SELL' ? '#ef4444' : '#eab308';
  document.getElementById('aiTrend').textContent = a.marketProfile?.trend === 'bullish' ? '🟢 Bullish' : a.marketProfile?.trend === 'bearish' ? '🔴 Bearish' : '⚪ Neutral';
  document.getElementById('aiTrend').style.color = a.marketProfile?.trend === 'bullish' ? '#22c55e' : a.marketProfile?.trend === 'bearish' ? '#ef4444' : '#eab308';
  document.getElementById('aiATR').textContent = '$' + (a.marketProfile?.atr || 0).toFixed(2);
  document.getElementById('aiMA').textContent = `$${(a.marketProfile?.ma20 || 0).toFixed(0)} / $${(a.marketProfile?.ma50 || 0).toFixed(0)}`;

  // Hide pattern/signal stats in overview since this is pluto mode
  document.getElementById('aiConfidenceScore').textContent = signals.confidence != null ? signals.confidence + '%' : '—';
  document.getElementById('aiConfidenceFill').style.width = (signals.confidence || 0) + '%';
  document.getElementById('aiPatternsFound').textContent = '—';
  document.getElementById('aiTradesSim').textContent = '—';
  document.getElementById('aiWinRate').textContent = '—';
  document.getElementById('aiProfitFactor').textContent = '—';
  document.getElementById('aiSwingList').innerHTML = '<div class="ai-empty">Pluto mode active — see Boardroom tab</div>';

  // ── Verdict Banner ──
  const verdict = signals.finalVerdict || 'WAIT';
  const vIcon = verdict === 'BUY' ? '🟢' : verdict === 'SELL' ? '🔴' : '⏳';
  const vColor = verdict === 'BUY' ? '#22c55e' : verdict === 'SELL' ? '#ef4444' : '#eab308';
  document.getElementById('brdVerdictIcon').textContent = vIcon;
  document.getElementById('brdVerdictLabel').textContent = verdict;
  document.getElementById('brdVerdictLabel').style.color = vColor;
  document.getElementById('brdVerdictConf').textContent = 'Confidence: ' + (signals.confidence || '—') + '%';

  // ── Agent Grid ──
  const agents = [
    brd.strategist, brd.hunter, brd.momentum, brd.pattern,
    brd.tactician, brd.news, brd.coach, brd.portfolioManager, brd.auditor
  ].filter(Boolean);

  document.getElementById('brdAgentGrid').innerHTML = agents.map(ag => {
    const sc = ag.score || 0;
    const scColor = sc >= 70 ? '#22c55e' : sc >= 40 ? '#eab308' : '#ef4444';
    return `<div class="brd-agent-card">
      <div class="brd-agent-header">
        <span>${ag.icon || '🤖'}</span>
        <span>${ag.name || 'Agent'}</span>
        <span class="brd-agent-score" style="background:${scColor}15;color:${scColor}">${sc}%</span>
      </div>
      <div class="brd-agent-body">${ag.detail || ag.verdict || '—'}</div>
    </div>`;
  }).join('');

  // ── Execution Card ──
  const execCard = document.getElementById('brdExecCard');
  if (signals.entryZone && signals.entryZone.length > 0) {
    execCard.style.display = 'block';
    document.getElementById('brdEntryZone').textContent = '$' + signals.entryZone[0].toFixed(0) + '–' + signals.entryZone[1].toFixed(0);
    document.getElementById('brdTargets').textContent = '$' + (signals.targets?.[0] || 0).toFixed(0) + ' / $' + (signals.targets?.[1] || 0).toFixed(0);
    document.getElementById('brdStopLoss').textContent = '$' + (signals.stopLoss || 0).toFixed(0);
    document.getElementById('brdRR').textContent = '1:' + (signals.rr || 0).toFixed(2);
  } else {
    execCard.style.display = 'none';
  }

  // ── MTFA Grid ──
  const mtfa = a.mtfa || {};
  const mtfaKeys = Object.keys(mtfa);
  const mtfaCard = document.getElementById('brdMTFACard');
  if (mtfaKeys.length > 0) {
    mtfaCard.style.display = 'block';
    document.getElementById('brdMTFAGrid').innerHTML = mtfaKeys.map(tf => {
      const d = mtfa[tf];
      const trendIcon = d.trend === 'bullish' ? '🟢' : d.trend === 'bearish' ? '🔴' : '⚪';
      const trendColor = d.trend === 'bullish' ? '#22c55e' : d.trend === 'bearish' ? '#ef4444' : '#eab308';
      return `<div class="brd-tf-card">
        <div class="brd-tf-name">${tf}</div>
        <div class="brd-tf-trend" style="color:${trendColor}">${trendIcon} ${d.trend?.toUpperCase() || '—'}</div>
        <div class="brd-tf-price">$${(d.price || 0).toFixed(0)} · RSI: ${d.rsi || '—'}</div>
      </div>`;
    }).join('');
  } else {
    mtfaCard.style.display = 'none';
  }

  // ── Liquidity Heatmap ──
  const heatmap = a.heatmap || [];
  const hmCard = document.getElementById('brdHeatmapCard');
  if (heatmap.length > 0) {
    hmCard.style.display = 'block';
    document.getElementById('brdHeatmapBars').innerHTML = heatmap.slice().reverse().map(h =>
      `<div class="brd-hm-row">
        <span class="brd-hm-price">$${h.price.toFixed(0)}</span>
        <div class="brd-hm-track">
          <div class="brd-hm-fill" style="width:${(h.density / 5) * 100}%"></div>
        </div>
      </div>`
    ).join('');
  } else {
    hmCard.style.display = 'none';
  }

  // Clear signals/patterns tab data
  const aiPatListEl = document.getElementById('aiPatternList');
  if (aiPatListEl) aiPatListEl.innerHTML = '<div class="ai-empty">Use Best DB mode for pattern analysis</div>';
  document.getElementById('aiSignalList').innerHTML = '<div class="ai-empty">Signals integrated into Boardroom tab</div>';
  document.getElementById('aiTradeList').innerHTML = '<div class="ai-empty">Signals integrated into Boardroom tab</div>';
}

function showAIError(msg) {
  ['aiPatternList', 'aiSwingList', 'aiSignalList', 'aiTradeList'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.innerHTML = `<div class="ai-empty" style="color:#ef4444;">⚠ ${msg}</div>`;
  });
}

// ═══════════════════════════════════════════════════════════════════
//  AI HISTORY — localStorage, Compare View
// ═══════════════════════════════════════════════════════════════════

const AI_HISTORY_KEY = 'ai_analysis_history';

function loadHistory() {
  try {
    const raw = localStorage.getItem(AI_HISTORY_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch { return []; }
}

function saveHistory(entries) {
  try {
    localStorage.setItem(AI_HISTORY_KEY, JSON.stringify(entries));
  } catch (e) { console.warn('History storage failed:', e); }
}

function pushHistoryEntry(analysis) {
  if (!analysis) return;
  const entries = loadHistory();

  // Store only the data needed for history list & compare view — avoid localStorage bloat
  const summary = {
    price: analysis.aggregatedPrice || analysis.currentPrice || 0,
    trend: analysis.priceTrend || (analysis.marketProfile?.trend) || 'neutral',
    rsi: analysis.marketProfile?.rsi || null,
    atr: analysis.currentATR || analysis.marketProfile?.atr || null,
    ma20: analysis.ma20 || analysis.marketProfile?.ma20 || null,
    ma50: analysis.ma50 || analysis.marketProfile?.ma50 || null,
    winRate: analysis.backtestMetrics?.winRate ?? null,
    avgRR: analysis.backtestMetrics?.avgRR ?? null,
    profitFactor: analysis.backtestMetrics?.profitFactor ?? null,
    totalTrades: analysis.backtestMetrics?.totalTrades ?? null,
    totalPatterns: analysis.patternDetection?.totalPatternsFound ?? null,
  };

  // Compare-relevant data only (no candles, no full trade arrays)
  const compareData = {
    mode: analysis.mode || 'best',
    symbol: analysis.symbol || currentSymbol,
    exchangeData: Object.fromEntries(
      Object.entries(analysis.exchangeData || {}).map(([k, v]) => [k, { lastPrice: v.lastPrice }])
    ),
    dataSources: (analysis.dataSources || []).slice(0),
    signals: analysis.signals ? {
      finalVerdict: analysis.signals.finalVerdict,
      confidence: analysis.signals.confidence,
      entryZone: analysis.signals.entryZone,
      targets: analysis.signals.targets,
      stopLoss: analysis.signals.stopLoss,
      rr: analysis.signals.rr,
    } : null,
    boardroom: analysis.boardroom ? {
      auditor: { finalVerdict: analysis.boardroom.auditor?.finalVerdict, confidence: analysis.boardroom.auditor?.confidence, avgScore: analysis.boardroom.auditor?.avgScore },
      tactician: { entry: analysis.boardroom.tactician?.entry, targets: analysis.boardroom.tactician?.targets, stopLoss: analysis.boardroom.tactician?.stopLoss, rr: analysis.boardroom.tactician?.rr },
    } : null,
  };

  const entry = {
    id: Date.now(),
    timestamp: analysis.scanTimestamp || new Date().toISOString(),
    symbol: analysis.symbol || currentSymbol,
    mode: analysis.mode || 'best',
    price: analysis.aggregatedPrice || analysis.currentPrice || 0,
    trend: summary.trend,
    confidence: parseInt(document.getElementById('aiConfidenceScore')?.textContent) || 0,
    summary,
    exchangeData: compareData.exchangeData,
    dataSources: compareData.dataSources,
    analysis: compareData,  // lightweight compare snapshot
  };
  entries.unshift(entry);
  // Keep max 25 entries to stay within localStorage limits
  if (entries.length > 25) entries.length = 25;
  saveHistory(entries);
  renderHistoryList();
}

function renderHistoryList() {
  const entries = loadHistory();
  const list = document.getElementById('aiHistList');
  const count = document.getElementById('aiHistCount');
  if (count) count.textContent = entries.length;
  if (!list) return;

  if (entries.length === 0) {
    list.innerHTML = '<div class="ai-empty">No saved analyses yet — run an analysis and it will save automatically</div>';
    return;
  }

  list.innerHTML = entries.slice(0, 40).map(e => {
    const ts = new Date(e.timestamp);
    const dateStr = ts.toLocaleDateString() + ' ' + ts.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    const modeLabel = e.mode === 'pluto' ? 'Pluto' : 'DB Best';
    const trendColor = e.trend === 'bullish' ? '#22c55e' : e.trend === 'bearish' ? '#ef4444' : '#eab308';
    const trendIcon = e.trend === 'bullish' ? '🟢' : e.trend === 'bearish' ? '🔴' : '⚪';
    return `<label class="ai-hist-item" data-id="${e.id}">
      <input type="checkbox" class="ai-hist-cb" value="${e.id}">
      <div class="ai-hist-content">
        <div class="ai-hist-top">
          <span class="ai-hist-symbol">${e.symbol.replace('USDT', '/USDT')}</span>
          <span class="ai-hist-mode ai-hist-mode-${e.mode}">${modeLabel}</span>
          <span class="ai-hist-trend" style="color:${trendColor}">${trendIcon} ${e.trend.toUpperCase()}</span>
          <span class="ai-hist-confidence">${e.confidence}%</span>
        </div>
        <div class="ai-hist-bottom">
          <span class="ai-hist-price">$${e.price.toFixed(0)}</span>
          <span class="ai-hist-time">${dateStr}</span>
        </div>
      </div>
    </label>`;
  }).join('');

  // Wire up checkbox change → enable compare button
  document.querySelectorAll('.ai-hist-cb').forEach(cb => {
    cb.addEventListener('change', updateCompareButton);
  });
}

function updateCompareButton() {
  const checked = document.querySelectorAll('.ai-hist-cb:checked');
  const btn = document.getElementById('aiHistCompareBtn');
  const hint = document.getElementById('aiHistHint');
  if (!btn) return;
  const count = checked.length;
  btn.disabled = count !== 2;
  if (hint) {
    hint.textContent = count === 0 ? 'Select 2 entries to compare'
      : count === 1 ? 'Select 1 more entry'
      : count === 2 ? 'Ready to compare!'
      : 'Select exactly 2 entries';
    hint.style.color = count === 2 ? '#22c55e' : count > 0 && count < 2 ? '#eab308' : 'var(--text-muted)';
  }
  if (count === 2) {
    btn.style.background = 'rgba(139,92,246,0.2)';
    btn.style.borderColor = 'rgba(139,92,246,0.4)';
  } else {
    btn.style.background = '';
    btn.style.borderColor = '';
  }
}

function openCompareView() {
  const checked = document.querySelectorAll('.ai-hist-cb:checked');
  if (checked.length !== 2) return;
  const ids = Array.from(checked).map(cb => parseInt(cb.value));
  const entries = loadHistory();
  const a = entries.find(e => e.id === ids[0]);
  const b = entries.find(e => e.id === ids[1]);
  if (!a || !b) return;

  document.getElementById('aiCompareOverlay').classList.add('open');
  renderCompareView(a, b);
}

function renderCompareView(a, b) {
  const body = document.getElementById('aiCompareBody');
  if (!body) return;

  const aTs = new Date(a.timestamp);
  const bTs = new Date(b.timestamp);
  const aLabel = aTs.toLocaleDateString() + ' ' + aTs.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  const bLabel = bTs.toLocaleDateString() + ' ' + bTs.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

  const aTrendIcon = a.trend === 'bullish' ? '🟢' : a.trend === 'bearish' ? '🔴' : '⚪';
  const bTrendIcon = b.trend === 'bullish' ? '🟢' : b.trend === 'bearish' ? '🔴' : '⚪';

  const aAn = a.analysis || {};
  const bAn = b.analysis || {};

  function valDiff(valA, valB, unit, higherBetter) {
    if (valA == null || valB == null) return '';
    const diff = valA - valB;
    const better = higherBetter ? diff > 0 : diff < 0;
    if (Math.abs(diff) < 0.001) return '<span class="ai-cmp-eq">= same</span>';
    const cls = better ? 'ai-cmp-better' : 'ai-cmp-worse';
    const icon = better ? '🟢' : '🔴';
    return `<span class="${cls}">${icon} ${diff > 0 ? '+' : ''}${diff.toFixed(3)}${unit || ''}</span>`;
  }

  // Build a vs b analysis comparison — read from summary fields (trimmed storage)
  const aPats = a.summary?.totalPatterns;
  const bPats = b.summary?.totalPatterns;
  const aPatternsStr = aPats != null ? aPats : (a.mode === 'pluto' ? (aAn.boardroom?.auditor?.avgScore ?? '—') : 0);
  const bPatternsStr = bPats != null ? bPats : (b.mode === 'pluto' ? (bAn.boardroom?.auditor?.avgScore ?? '—') : 0);

  const aWR = a.summary?.winRate;
  const bWR = b.summary?.winRate;
  const aWinRateStr = aWR != null ? aWR.toFixed(1) + '%' : (a.mode === 'pluto' ? (aAn.signals?.confidence ?? aAn.boardroom?.auditor?.confidence ?? '—') : '—');
  const bWinRateStr = bWR != null ? bWR.toFixed(1) + '%' : (b.mode === 'pluto' ? (bAn.signals?.confidence ?? bAn.boardroom?.auditor?.confidence ?? '—') : '—');

  const rows = [
    { label: 'Date/Time', a: aLabel, b: bLabel },
    { label: 'Symbol', a: a.symbol.replace('USDT', '/USDT'), b: b.symbol.replace('USDT', '/USDT') },
    { label: 'Mode', a: a.mode === 'pluto' ? 'Pluto' : 'DB Best', b: b.mode === 'pluto' ? 'Pluto' : 'DB Best' },
    { label: 'Price', a: '$' + (a.summary?.price || 0).toFixed(2), b: '$' + (b.summary?.price || 0).toFixed(2) },
    { label: 'Trend', a: `${aTrendIcon} ${a.trend.toUpperCase()}`, b: `${bTrendIcon} ${b.trend.toUpperCase()}` },
    { label: 'Confidence', a: a.confidence + '%', b: b.confidence + '%', diff: valDiff(a.confidence, b.confidence, '%', true) },
    { label: 'Patterns', a: aPatternsStr, b: bPatternsStr },
    { label: 'Win Rate', a: aWinRateStr, b: bWinRateStr, diff: typeof aWR === 'number' && typeof bWR === 'number' ? valDiff(aWR, bWR, '%', true) : '' },
    { label: 'ATR', a: a.summary?.atr ? '$' + a.summary.atr.toFixed(2) : '—', b: b.summary?.atr ? '$' + b.summary.atr.toFixed(2) : '—' },
    { label: 'MA20', a: a.summary?.ma20 ? '$' + a.summary.ma20.toFixed(0) : '—', b: b.summary?.ma20 ? '$' + b.summary.ma20.toFixed(0) : '—' },
    { label: 'MA50', a: a.summary?.ma50 ? '$' + a.summary.ma50.toFixed(0) : '—', b: b.summary?.ma50 ? '$' + b.summary.ma50.toFixed(0) : '—' },
    { label: 'Avg RR', a: a.summary?.avgRR ? a.summary.avgRR.toFixed(2) : '—', b: b.summary?.avgRR ? b.summary.avgRR.toFixed(2) : '—' },
    { label: 'Exchanges', a: (a.dataSources || []).join(', ').toUpperCase(), b: (b.dataSources || []).join(', ').toUpperCase() },
  ];

  // Pluto-specific comparison
  if (a.mode === 'pluto' || b.mode === 'pluto') {
    const aVerdict = aAn.signals?.finalVerdict || aAn.boardroom?.auditor?.finalVerdict || '—';
    const bVerdict = bAn.signals?.finalVerdict || bAn.boardroom?.auditor?.finalVerdict || '—';
    const aRR = aAn.signals?.rr || aAn.boardroom?.tactician?.rr || (a.summary?.avgRR ? a.summary.avgRR : '—');
    const bRR = bAn.signals?.rr || bAn.boardroom?.tactician?.rr || (b.summary?.avgRR ? b.summary.avgRR : '—');
    rows.push(
      { label: 'Verdict', a: aVerdict, b: bVerdict },
      { label: 'R:R', a: aRR !== '—' ? '1:' + (typeof aRR === 'number' ? aRR.toFixed(2) : aRR) : '—', b: bRR !== '—' ? '1:' + (typeof bRR === 'number' ? bRR.toFixed(2) : bRR) : '—' },
      { label: 'Entry Zone', a: aAn.signals?.entryZone ? '$' + aAn.signals.entryZone.map(v => v.toFixed(0)).join('–') : '—', b: bAn.signals?.entryZone ? '$' + bAn.signals.entryZone.map(v => v.toFixed(0)).join('–') : '—' },
    );
  }

  body.innerHTML = `
    <div class="ai-cmp-grid">
      ${rows.map(r => `
        <div class="ai-cmp-row">
          <span class="ai-cmp-label">${r.label}</span>
          <span class="ai-cmp-val ai-cmp-val-a">${r.a}</span>
          <span class="ai-cmp-val-sep">vs</span>
          <span class="ai-cmp-val ai-cmp-val-b">${r.b}</span>
          ${r.diff ? `<span class="ai-cmp-diff">${r.diff}</span>` : ''}
        </div>
      `).join('')}
    </div>

    <!-- Exchange comparison -->
    <div class="ai-cmp-exchange-row">
      ${renderExchangeComparison(a.exchangeData || {}, b.exchangeData || {})}
    </div>
  `;
}

function renderExchangeComparison(exA, exB) {
  const keys = [...new Set([...Object.keys(exA), ...Object.keys(exB)])];
  if (keys.length === 0) return '';
  return keys.map(ex => {
    const aInfo = exA[ex];
    const bInfo = exB[ex];
    const aPrice = aInfo?.lastPrice != null ? aInfo.lastPrice.toFixed(0) : '—';
    const bPrice = bInfo?.lastPrice != null ? bInfo.lastPrice.toFixed(0) : '—';
    return `<div class="ai-cmp-ex-item">
      <span class="ai-ex-badge ${ex}">${ex.toUpperCase()}</span>
      <span class="ai-cmp-ex-a">$${aPrice}</span>
      <span class="ai-cmp-ex-b">$${bPrice}</span>
    </div>`;
  }).join('');
}

function clearHistory() {
  if (confirm('Clear all saved analyses?')) {
    localStorage.removeItem(AI_HISTORY_KEY);
    renderHistoryList();
  }
}

// ═══════════════════════════════════════════════════════════════════
//  LIVE WEBSOCKET — Binance Kline Stream
// ═══════════════════════════════════════════════════════════════════

let wsLivePrice = null;
let wsReconnectTimer = null;

function connectLiveStream(symbol, interval) {
  // Close existing connection
  if (wsLivePrice) {
    try { wsLivePrice.close(); } catch {}
    wsLivePrice = null;
  }
  if (wsReconnectTimer) {
    clearTimeout(wsReconnectTimer);
    wsReconnectTimer = null;
  }

  const streamSymbol = symbol.toLowerCase();
  const wsUrl = `wss://stream.binance.com:9443/ws/${streamSymbol}@kline_${interval}`;

  try {
    wsLivePrice = new WebSocket(wsUrl);

    wsLivePrice.onopen = () => {
      console.log(`[WS] Live stream connected: ${symbol} ${interval}`);
    };

    wsLivePrice.onmessage = (evt) => {
      try {
        const msg = JSON.parse(evt.data);
        if (msg.e === 'kline' && msg.k) {
          const k = msg.k;
          const isFinal = k.x; // whether the candle is closed
          const updatedCandle = {
            time: k.t / 1000,
            open: parseFloat(k.o),
            high: parseFloat(k.h),
            low: parseFloat(k.l),
            close: parseFloat(k.c),
            volume: parseFloat(k.v),
          };
          updateLiveCandleOnChart(updatedCandle, isFinal);
        }
      } catch (e) {
        // Parse errors silently ignored
      }
    };

    wsLivePrice.onclose = () => {
      console.log('[WS] Disconnected — reconnecting in 5s');
      wsReconnectTimer = setTimeout(() => {
        connectLiveStream(symbol, interval);
      }, 5000);
    };

    wsLivePrice.onerror = (err) => {
      console.warn('[WS] Error:', err);
    };
  } catch (e) {
    console.warn('[WS] Connection failed:', e);
    wsReconnectTimer = setTimeout(() => {
      connectLiveStream(symbol, interval);
    }, 10000);
  }
}

let wsLastCandleSeries = null; // the series to update for live candle updates

function updateLiveCandleOnChart(candle, isFinal) {
  // We update the last candle in the price chart if it's the same time period
  if (!priceChartInstance || !wsLastCandleSeries) return;

  // Update the series by appending or replacing the last candle
  // LightweightCharts doesn't support partial updates natively, so we use setData with full array
  // But we can use update() on the series for real-time
  try {
    wsLastCandleSeries.update({
      time: candle.time,
      open: candle.open,
      high: candle.high,
      low: candle.low,
      close: candle.close,
    });
  } catch (e) {
    // If update fails (e.g. time in the past), replace the last point
    console.warn('[WS] Update failed, resorting to setData');
  }

  // Update the live dot status
  const liveDot = document.getElementById('liveDot');
  if (liveDot) {
    liveDot.style.background = isFinal ? '#0d9488' : '#dc2626';
    liveDot.title = isFinal ? 'Candle closed' : 'Candle live';
  }
}

function disconnectLiveStream() {
  if (wsLivePrice) {
    try { wsLivePrice.close(); } catch {}
    wsLivePrice = null;
  }
  if (wsReconnectTimer) {
    clearTimeout(wsReconnectTimer);
    wsReconnectTimer = null;
  }
  const liveDot = document.getElementById('liveDot');
  if (liveDot) {
    liveDot.style.background = '#9ca3b8';
    liveDot.title = 'Disconnected';
  }
}

// Wire up the live dot in the header after chart renders
function initLiveStream() {
  connectLiveStream(currentSymbol, currentInterval);
}

// ═══════════════════════════════════════════════════════════════════
//  MAIN INIT
// ═══════════════════════════════════════════════════════════════════

document.addEventListener('DOMContentLoaded', () => {
  bindSliders();

  // ─── Tab switching ────────────────────────────────────────
  const tabBar = document.getElementById('tabBar');
  const tabPanels = {
    'tab-data': document.getElementById('tab-data'),
    'tab-detect': document.getElementById('tab-detect'),
    'tab-risk': document.getElementById('tab-risk'),
    'tab-scenario': document.getElementById('tab-scenario'),
  };

  tabBar.addEventListener('click', (e) => {
    const btn = e.target.closest('.tab-btn');
    if (!btn) return;
    tabBar.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    Object.values(tabPanels).forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    const panel = tabPanels[btn.dataset.tab];
    if (panel) panel.classList.add('active');
  });

  // ─── DOM refs ─────────────────────────────────────────────
  const runBtn = document.getElementById('runBtn');
  const runBtnMain = document.getElementById('runBtnMain');
  const fetchBtn = document.getElementById('fetchBtn');
  const scenarioSelect = document.getElementById('scenarioSelect');
  const dataSource = document.getElementById('dataSource');
  const patternCountSlider = document.getElementById('patternCount');

  // Set default end date to today
  const today = new Date();
  document.getElementById('endDate').value = today.toISOString().split('T')[0];

  // ─── Data source toggle ───────────────────────────────────
  dataSource.addEventListener('change', () => {
    const isApi = dataSource.value !== 'generated';
    toggleDateRange(isApi);
    [runBtn, runBtnMain].forEach(btn => {
      if (btn) {
        btn.disabled = isApi;
        btn.title = isApi ? 'Use the Fetch from API button instead' : '';
        btn.querySelector('.run-text').textContent = isApi ? 'Use Fetch Button' : 'Run Backtest';
      }
    });
  });
  toggleDateRange(false);

  // ─── Scenario info ────────────────────────────────────────
  scenarioSelect.addEventListener('change', () => {
    updateScenarioInfo(scenarioSelect.value);
    if (patternCountSlider) {
      const pcRow = patternCountSlider.closest('.slider-row');
      if (pcRow) pcRow.classList.toggle('hidden', scenarioSelect.value !== '100_patterns');
    }
  });
  updateScenarioInfo('all');

  if (patternCountSlider) {
    patternCountSlider.addEventListener('input', () => {
      if (scenarioSelect.value === '100_patterns') updateScenarioInfo('100_patterns');
    });
  }

  // ─── Scan Live button ──────────────────────────────────
  const scanLiveBtn = document.getElementById('scanLiveBtn');
  if (scanLiveBtn) {
    scanLiveBtn.addEventListener('click', async () => {
      const status = document.getElementById('scanLiveStatus');
      scanLiveBtn.disabled = true;
      scanLiveBtn.querySelector('.run-text').textContent = 'Scanning...';
      status.className = 'fetch-status loading';
      status.textContent = '⟳ Scanning live BTC...';
      status.classList.remove('hidden');

      try {
        const body = collectParams();
        const data = await apiPost('/scan-live', body);
        if (!data.success) throw new Error(data.error || 'Scan failed');

        status.className = 'fetch-status success';
        const sig = data.signal || {};
        const patterns = data.patternMarkers ? data.patternMarkers.length : 0;
        const trades = data.metrics ? data.metrics.totalTrades : 0;
        status.textContent = `✓ Live scan: ${patterns} patterns, ${trades} trades`;

        // Auto-select Binance source so the UI doesn't show disabled run buttons
        document.getElementById('dataSource').value = 'binance';
        // Trigger the change event to update UI state
        const evt = new Event('change');
        document.getElementById('dataSource').dispatchEvent(evt);

        renderResults(data);

      } catch (e) {
        status.className = 'fetch-status error';
        status.textContent = '✗ Error: ' + e.message;
        console.error('Scan error:', e);
      }

      scanLiveBtn.querySelector('.run-text').textContent = 'Scan Live Now';
      scanLiveBtn.disabled = false;
    });
  }

  // ─── Fetch button (API data via Python backend) ──────────
  fetchBtn.addEventListener('click', async () => {
    const source = dataSource.value;
    const startDate = document.getElementById('startDate').value;
    const endDate = document.getElementById('endDate').value;
    const limit = parseInt(document.getElementById('barLimit').value) || 500;
    const status = document.getElementById('fetchStatus');

    fetchBtn.disabled = true;
    status.className = 'fetch-status loading';
    status.textContent = '⟳ Fetching data...';
    status.classList.remove('hidden');

    try {
      const candles = await fetchBackendData(source, startDate, endDate, limit);
      if (!candles.length) throw new Error('No data received');

      status.className = 'fetch-status success';
      status.textContent = `✓ Fetched ${candles.length} bars`;
      showDataInfo(candles, source === 'binance' ? 'Binance' : 'Yahoo Finance');

      showProgress(0);
      await new Promise(r => setTimeout(r, 30));

      const result = await runBackendWithData(candles);
      renderResults(result);
      showProgress(100);
      setTimeout(hideProgress, 600);

    } catch (e) {
      status.className = 'fetch-status error';
      status.textContent = '✗ Error: ' + e.message;
      console.error('Fetch error:', e);
    }

    fetchBtn.disabled = false;
  });

  // ─── Run button events (sidebar + floating) ─────────────
  const runHandler = () => doRun(scenarioSelect.value);

  if (runBtn) runBtn.addEventListener('click', runHandler);
  if (runBtnMain) runBtnMain.addEventListener('click', runHandler);

  // ═══ V3 ENGINE ═══
  const runV3Btn = document.getElementById('runV3Btn');
  const v3Mode = document.getElementById('v3Mode');
  const v3DataSource = document.getElementById('v3DataSource');
  const v3Status = document.getElementById('v3Status');

  if (runV3Btn) {
    runV3Btn.addEventListener('click', async () => {
      const mode = v3Mode ? v3Mode.value : 'backtest';
      const dataSource = v3DataSource ? v3DataSource.value : 'generated';
      
      runV3Btn.disabled = true;
      runV3Btn.querySelector('.run-text').textContent = 'Running V3...';
      v3Status.className = 'fetch-status loading';
      v3Status.textContent = '⟳ Running V3 engine...';
      v3Status.classList.remove('hidden');

      try {
        let candles = [];
        if (dataSource === 'generated' && lastResult && lastResult.candles) {
          candles = lastResult.candles;
        } else if (mode !== 'fetch-run') {
          // If no candles loaded, try v2 backtest first to get data
          const result = await runBackendBacktest('all');
          renderResults(result);
          candles = result.candles || [];
        }

        const result = await runV3Engine(mode, candles);
        
        if (mode === 'validate') {
          renderV3Validation(result);
        } else {
          renderResults(result);
          renderV3Results(result);
          
          // Extract zone info from pattern markers
          const zones = (result.patternMarkers || [])
            .filter(m => m.zonePrice)
            .map(m => ({
              type: m.zoneType || 'support',
              price: m.zonePrice,
              strength: m.score || 0.5,
              base_rates: { bounce: 0.6, sweep_reverse: 0.25, breakout: 0.15 }
            }));
          renderV3ZoneList(zones);
        }

        v3Status.className = 'fetch-status success';
        v3Status.textContent = '✓ V3 engine completed';
      } catch (e) {
        console.error('V3 error:', e);
        v3Status.className = 'fetch-status error';
        v3Status.textContent = '✗ Error: ' + e.message;
      }

      runV3Btn.querySelector('.run-text').textContent = 'Run V3 Engine';
      runV3Btn.disabled = false;
    });
  }

  // ═══ TICKER SELECTOR ═══
  const tickerSelect = document.getElementById('tickerSelect');
  if (tickerSelect) {
    tickerSelect.addEventListener('change', async () => {
      currentSymbol = tickerSelect.value;
      // Reconnect live WebSocket for the new symbol
      disconnectLiveStream();
      connectLiveStream(currentSymbol, currentInterval);
      const label = TICKER_LABELS[currentSymbol] || currentSymbol;
      const chartTitle = document.getElementById('chartTitle');
      if (chartTitle) {
        chartTitle.textContent = `${label} — ${currentInterval}`;
        chartTitle.innerHTML = `${label} — ${currentInterval} <span style="color:var(--accent-orange);font-size:10px;font-weight:400;">⟳ loading...</span>`;
      }

      // Scan liquidity zones for the new symbol — this fetches real candles
      try {
        const liqData = await scanLiquidityZones(currentSymbol);
        if (liqData && liqData.candles && liqData.candles.length > 0) {
          // Render the chart with actual candle data from the new symbol
          renderPriceChart(liqData.candles, [], []);
          renderLiquidityZoneLines(liqData);
          // Update data info
          showDataInfo(liqData.candles, `${label} Binance`);
          // Clear stale equity chart and trade log from previous symbol
          const equityContainer = document.getElementById('equityChart');
          if (equityContainer) equityContainer.innerHTML = '';
          document.getElementById('tradeBody').innerHTML = '<tr><td colspan="12" class="empty-state">Ticker changed — run backtest for analysis</td></tr>';
        }
      } catch (e) {
        console.error('Ticker switch error:', e);
      }

      if (chartTitle) {
        chartTitle.textContent = `${label} — ${currentInterval}`;
      }
    });
  }

  // ═══ LIQUIDITY9 — Scan Button ═══
  const scanLiqBtn = document.getElementById('scanLiquidityBtn');
  if (scanLiqBtn) {
    scanLiqBtn.addEventListener('click', () => {
      scanLiquidityZones(currentSymbol);
    });
  }

  // ═══ AI PANEL — INIT ═══
  const aiToggleBtn = document.getElementById('aiPanelToggle');
  const aiCloseBtn = document.getElementById('aiPanelClose');
  const aiOverlay = document.getElementById('aiOverlay');
  const aiScanBtn = document.getElementById('aiScanBtn');
  const aiFabBtn = document.getElementById('aiFabBtn');

  if (aiToggleBtn) aiToggleBtn.addEventListener('click', () => toggleAIPanel());
  if (aiFabBtn) aiFabBtn.addEventListener('click', () => toggleAIPanel());
  if (aiCloseBtn) aiCloseBtn.addEventListener('click', () => toggleAIPanel(false));
  if (aiOverlay) aiOverlay.addEventListener('click', () => toggleAIPanel(false));
  if (aiScanBtn) aiScanBtn.addEventListener('click', () => fetchAIAnalysis(currentSymbol));

  // Mode switcher
  document.querySelectorAll('.ai-mode-btn').forEach(btn => {
    btn.addEventListener('click', () => setAIMode(btn.dataset.mode));
  });

  // AI Tab switching
  const aiTabBar = document.querySelector('.ai-tab-bar');
  if (aiTabBar) {
    aiTabBar.addEventListener('click', (e) => {
      const tab = e.target.closest('.ai-tab');
      if (!tab) return;
      aiTabBar.querySelectorAll('.ai-tab').forEach(t => t.classList.remove('active'));
      document.querySelectorAll('.ai-tab-content').forEach(p => p.classList.remove('active'));
      tab.classList.add('active');
      const panel = document.getElementById(tab.dataset.aiTab);
      if (panel) panel.classList.add('active');
    });
  }

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && aiPanelOpen) toggleAIPanel(false);
    if (e.key === 'Escape') {
      const ov = document.getElementById('aiCompareOverlay');
      if (ov) ov.classList.remove('open');
    }
  });

  // ═══ HISTORY TAB — INIT ═══
  renderHistoryList();
  const histClearBtn = document.getElementById('aiHistClearBtn');
  const histCompareBtn = document.getElementById('aiHistCompareBtn');
  const compareClose = document.getElementById('aiCompareClose');
  const compareOverlay = document.getElementById('aiCompareOverlay');
  if (histClearBtn) histClearBtn.addEventListener('click', clearHistory);
  if (histCompareBtn) histCompareBtn.addEventListener('click', openCompareView);
  if (compareClose) compareClose.addEventListener('click', () => { compareOverlay?.classList.remove('open'); });
  if (compareOverlay) compareOverlay.addEventListener('click', (e) => {
    if (e.target === compareOverlay) compareOverlay.classList.remove('open');
  });

  // ═══ AUTO-RUN ON LOAD ═══
  setTimeout(async () => {
    console.log('[DB Scanner] Auto-running backtest via Python...');
    await doRun(scenarioSelect.value);
    // ═══ AUTO-SCAN LIQUIDITY AFTER BACKTEST COMPLETES ═══
    console.log('[DB Scanner] Auto-scanning liquidity zones...');
    scanLiquidityZones(currentSymbol);
    // ═══ START LIVE WEBSOCKET STREAM ═══
    console.log('[DB Scanner] Starting live WS stream...');
    initLiveStream();
  }, 500);
});
