/* ============================================================
   Liquidity Identifier v2.1 — Frontend Application
   Tabbed interface: S&R Zones | Depth & Flow | All Zones
   Features: Fast refresh button, auto-refresh interval, keyboard shortcut (R)
   ============================================================ */

(function () {
  'use strict';

  // ─── State ─────────────────────────────────────────────────
  const state = {
    data: null,
    loading: false,
    filter: 'all',
    symbol: 'BTCUSDT',
    interval: '15m',
    priceLines: [],
    activeTab: 'liquidity9',
    autoRefreshTimer: null,
    scanCount: 0,
    deltaLivePollTimer: null,
    deltaData: null,
    previousPatternKeys: null,
    alertCount: 0,
    inLoading: false,
    inSelectedStock: null,
    inStockName: '',
    inData: null,
    instLoading: false,
    instPollTimer: null,
  };

  // ─── DOM refs ──────────────────────────────────────────────
  const $ = (s, ctx) => (ctx || document).querySelector(s);
  const $$ = (s, ctx) => [...(ctx || document).querySelectorAll(s)];

  const els = {
    scanBtn: $('#scanBtn'),
    refreshBtn: $('#refreshBtn'),
    autoRefreshSelect: $('#autoRefreshSelect'),
    symbol: $('#symbolSelect'),
    interval: $('#intervalSelect'),
    price: $('#priceValue'),
    bidLiquidity: $('#bidLiquidity'),
    askLiquidity: $('#askLiquidity'),
    bidAskRatio: $('#bidAskRatio'),
    imbalance: $('#imbalance'),
    activeWalls: $('#activeWalls'),
    totalZones: $('#totalZones'),
    priceChart: $('#priceChart'),
    zoneList: $('#zoneList'),
    zoneTable: $('#zoneBody'),
    zoneTableCount: $('#zoneTableCount'),
    zoneCountBadge: $('#zoneCountBadge'),
    updateTime: $('#updateTime'),
    cacheIndicator: $('#cacheIndicator'),
    cacheDot: $('#cacheDot'),
    cacheLabel: $('#cacheLabel'),
    filterBtns: $$('.zf'),
    structureTag: $('#structureTag'),
    tabBtns: $$('.tab-btn'),
    panels: {
      'liquidity9': $('#panel-liquidity9'),
      'institutional': $('#panel-institutional'),
      'sr-zones': $('#panel-sr-zones'),
      'depth-flow': $('#panel-depth-flow'),
      'delta-patterns': $('#panel-delta-patterns'),
      'all-zones': $('#panel-all-zones'),
      'indian-stocks': $('#panel-indian-stocks'),
    },
    // Indian stock elements
    inStockSearch: $('#inStockSearch'),
    inSearchResults: $('#inSearchResults'),
    inScanBtn: $('#inScanBtn'),
    inIntervalSelect: $('#inIntervalSelect'),
    inInfoBar: $('#inInfoBar'),
    inStockName: $('#inStockName'),
    inStockPrice: $('#inStockPrice'),
    inStockChange: $('#inStockChange'),
    inMetaExchange: $('#inMetaExchange'),
    inMetaSector: $('#inMetaSector'),
    inMetaMcap: $('#inMetaMcap'),
    inSupportCount: $('#inSupportCount'),
    inResistanceCount: $('#inResistanceCount'),
    inVolumeMetric: $('#inVolumeMetric'),
    inTierZones: $('#inTierZones'),
    inPatternCount: $('#inPatternCount'),
    inPriceChart: $('#inPriceChart'),
    inSupportCards: $('#inSupportCards'),
    inResistanceCards: $('#inResistanceCards'),
    inVpWrap: $('#inVpWrap'),
    inVpInfo: $('#inVpInfo'),
    inCvdChart: $('#inCvdChart'),
    inCvdLabel: $('#inCvdLabel'),
    supportCardsBody: $('#supportCardsBody'),
    resistanceCardsBody: $('#resistanceCardsBody'),
    // Depth tab charts
    depthPriceChart: $('#depthPriceChart'),
    cvdChartDepth: $('#cvdChartDepth'),
    depthHistChart: $('#depthHistChart'),
    imbalanceChart: $('#imbalanceChart'),
    powerLabel: $('#powerLabel'),
    powerBar: $('#powerBar'),
    powerKnob: $('#powerKnob'),
    powerBalanceText: $('#powerBalanceText'),
    pmBuyVol: $('#pmBuyVol'),
    pmSellVol: $('#pmSellVol'),
    pmRatio: $('#pmRatio'),
    wallsTableBody: $('#wallsTableBody'),
    wallsCountDepth: $('#wallsCountDepth'),
    depthImbalanceDepth: $('#depthImbalanceDepth'),
    cvdStatusDepth: $('#cvdStatusDepth'),
    imbBadgeDepth: $('#imbBadgeDepth'),
    vpWrap: $('#vpWrap'),
    // Delta Patterns tab
    deltaPatternBadge: $('#deltaPatternBadge'),
    deltaTableWrap: $('#deltaTableWrap'),
    deltaLiveIndicator: $('#deltaLiveIndicator'),
    deltaLiveLabel: $('#deltaLiveLabel'),
    dpActiveCount: $('#dpActiveCount'),
    dpLatestDelta: $('#dpLatestDelta'),
    dpBuyVol: $('#dpBuyVol'),
    dpSellVol: $('#dpSellVol'),
    dpBullBearRatio: $('#dpBullBearRatio'),
    dpPatternsContainer: $('#dpPatternsContainer'),
    vpPocStat: $('#vpPocStat'),
    vpVaStat: $('#vpVaStat'),
    vpVolStat: $('#vpVolStat'),
  };

  // ─── Color & Style Maps ────────────────────────────────────
  const COLORS = {
    support:                  '#10b981',
    resistance:               '#f43f5e',
    order_block_support:      '#22d3ee',
    order_block_resistance:   '#fb7185',
    swing_low:                '#10b981',
    swing_high:               '#f43f5e',
    fvg_support:              '#8b5cf6',
    fvg_resistance:           '#a78bfa',
    liquidity_sweep_support:  '#f59e0b',
    liquidity_sweep_resistance:'#f97316',
    volume_hvn:               '#06b6d4',
    order_wall_support:       '#34d399',
    order_wall_resistance:    '#fb7185',
  };

  const SUBTYPE_LABELS = {
    order_block:     'OB',
    fvg:             'FVG',
    liquidity_sweep: 'SWP',
    swing_low:       'SWL',
    swing_high:      'SWH',
    volume_hvn:      'HVN',
    order_wall:      'WAL',
  };

  const SUBTYPE_COLORS = {
    order_block:     '#22d3ee',
    fvg:             '#8b5cf6',
    liquidity_sweep: '#f59e0b',
    swing_low:       '#10b981',
    swing_high:      '#f43f5e',
    volume_hvn:      '#06b6d4',
    order_wall:      '#34d399',
  };

  const SUBTYPE_CSS = {
    order_block:     'ob',
    fvg:             'fvg',
    liquidity_sweep: 'sweep',
    swing_low:       'swing',
    swing_high:      'swing',
    volume_hvn:      'hvn',
    order_wall:      'wall',
  };

  function zoneColor(z) {
    const key = (z.subtype || z.source || '') + '_' + z.type;
    return COLORS[key] || (z.type === 'support' ? COLORS.support : COLORS.resistance);
  }

  function zoneLineStyle(z) {
    const st = z.subtype || z.source || '';
    if (st.includes('order_block')) return 0;
    if (st.includes('liquidity_sweep')) return 0;
    if (st.includes('order_wall')) return 0;
    if (st.includes('fvg')) return 2;
    if (st.includes('volume_hvn')) return 1;
    if (st.includes('swing')) return 3;
    return 0;
  }

  function zoneLineWidth(z) {
    const st = z.subtype || z.source || '';
    const tier = z.tier || 'D';
    const base = tier === 'A+' || tier === 'A' ? 2 : 1;
    if (st.includes('order_block') || st.includes('liquidity_sweep')) return Math.max(base, 2);
    return base;
  }

  function shortSubtype(z) {
    const st = z.subtype || z.source || '';
    return SUBTYPE_LABELS[st] || st.slice(0, 3).toUpperCase();
  }

  function subtypeCssClass(z) {
    const st = z.subtype || z.source || '';
    return SUBTYPE_CSS[st] || 'default';
  }

  function subtypeColor(z) {
    const st = z.subtype || z.source || '';
    return SUBTYPE_COLORS[st] || '#4a5478';
  }

  // ─── Charts ────────────────────────────────────────────────
  let pc = null;
  let priceSeries = null;
  // Liquidity9 chart
  let liq9Pc = null;
  let liq9PriceSeries = null;
  let liq9PriceLines = [];
  // Depth tab charts
  let dpc = null, cvcDepth = null, dhc = null, imbChart = null;
  let depthPriceSeries = null;
  let cvdLineSeriesDepth = null;
  let depthBidHistSeries = null, depthAskHistSeries = null;
  let imbBidSeries = null, imbAskSeries = null;
  // Indian stock charts
  let inPc = null, inPriceSeries = null, inCvc = null, inCvdLineSeries = null;
  let inPriceLines = [];
  // Institutional charts
  let instWhaleBar = null, instWhaleBarSeries = null;
  let instNetflowCh = null, instNetflowSeries = null;
  let instOICh = null, instOISeries = null;
  let instFundCh = null, instFundSeries = null;
  let instCVDCh = null, instSpotCvdSeries = null, instFutsCvdSeries = null;
  let instData = null;
  // No delta chart — using numeric table instead

  function initLiquidity9Chart() {
    const el = document.getElementById('liq9PriceChart');
    if (!el) return;
    liq9Pc = LightweightCharts.createChart(el, {
      layout: { background: { type: 'solid', color: '#ffffff' }, textColor: '#5a5a7a' },
      grid: { vertLines: { color: '#e2e6ef' }, horzLines: { color: '#e2e6ef' } },
      crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
      timeScale: { borderColor: '#e2e6ef', timeVisible: true, secondsVisible: false },
      rightPriceScale: { borderColor: '#e2e6ef' },
      width: el.clientWidth || 600,
      height: 340,
    });
    liq9PriceSeries = liq9Pc.addCandlestickSeries({
      upColor: '#10b981', downColor: '#f43f5e',
      borderUpColor: '#10b981', borderDownColor: '#f43f5e',
      wickUpColor: '#10b981', wickDownColor: '#f43f5e',
    });
  }

  function initCharts() {
    // Main price chart (S&R tab)
    if (els.priceChart) {
      pc = LightweightCharts.createChart(els.priceChart, {
        layout: { background: { type: 'solid', color: '#ffffff' }, textColor: '#5a5a7a' },
        grid: { vertLines: { color: '#e2e6ef' }, horzLines: { color: '#e2e6ef' } },
        crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
        timeScale: { borderColor: '#e2e6ef', timeVisible: true, secondsVisible: false },
        rightPriceScale: { borderColor: '#e2e6ef' },
        width: els.priceChart.clientWidth || 600,
        height: 340,
      });
      priceSeries = pc.addCandlestickSeries({
        upColor: '#10b981', downColor: '#f43f5e',
        borderUpColor: '#10b981', borderDownColor: '#f43f5e',
        wickUpColor: '#10b981', wickDownColor: '#f43f5e',
      });
    }

    // ═══ Depth Tab Charts ═══

    // Depth Price Chart (candles + wall markers)
    if (els.depthPriceChart) {
      dpc = LightweightCharts.createChart(els.depthPriceChart, {
        layout: { background: { type: 'solid', color: '#ffffff' }, textColor: '#5a5a7a' },
        grid: { vertLines: { color: '#e2e6ef' }, horzLines: { color: '#e2e6ef' } },
        crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
        timeScale: { borderColor: '#e2e6ef', timeVisible: true, secondsVisible: false },
        rightPriceScale: { borderColor: '#e2e6ef' },
        width: els.depthPriceChart.clientWidth || 400,
        height: 300,
      });
      depthPriceSeries = dpc.addCandlestickSeries({
        upColor: '#10b981', downColor: '#f43f5e',
        borderUpColor: '#10b981', borderDownColor: '#f43f5e',
        wickUpColor: '#10b981', wickDownColor: '#f43f5e',
      });
    }

    // CVD Chart (Depth tab)
    if (els.cvdChartDepth) {
      cvcDepth = LightweightCharts.createChart(els.cvdChartDepth, {
        layout: { background: { type: 'solid', color: '#ffffff' }, textColor: '#5a5a7a' },
        grid: { vertLines: { color: '#e2e6ef' }, horzLines: { color: '#e2e6ef' } },
        timeScale: { borderColor: '#e2e6ef', visible: false },
        rightPriceScale: { borderColor: '#e2e6ef', visible: true },
        width: els.cvdChartDepth.clientWidth || 400,
        height: 300,
      });
      cvdLineSeriesDepth = cvcDepth.addLineSeries({
        color: '#8b5cf6', lineWidth: 2,
        priceLineVisible: false, lastValueVisible: true,
      });
    }

    // Depth Histogram (order book depth)
    if (els.depthHistChart) {
      dhc = LightweightCharts.createChart(els.depthHistChart, {
        layout: { background: { type: 'solid', color: '#ffffff' }, textColor: '#5a5a7a' },
        grid: { vertLines: { color: '#e2e6ef' }, horzLines: { color: '#e2e6ef' } },
        timeScale: { borderColor: '#e2e6ef', visible: false },
        rightPriceScale: { borderColor: '#e2e6ef', visible: true },
        width: els.depthHistChart.clientWidth || 300,
        height: 200,
      });
      depthBidHistSeries = dhc.addHistogramSeries({
        color: '#10b981', priceFormat: { type: 'volume' },
        priceLineVisible: false, lastValueVisible: false,
      });
      depthAskHistSeries = dhc.addHistogramSeries({
        color: '#f43f5e', priceFormat: { type: 'volume' },
        priceLineVisible: false, lastValueVisible: false,
      });
    }

    // Imbalance by level chart
    if (els.imbalanceChart) {
      imbChart = LightweightCharts.createChart(els.imbalanceChart, {
        layout: { background: { type: 'solid', color: '#ffffff' }, textColor: '#5a5a7a' },
        grid: { vertLines: { color: '#e2e6ef' }, horzLines: { color: '#e2e6ef' } },
        timeScale: { borderColor: '#e2e6ef', visible: false },
        rightPriceScale: { borderColor: '#e2e6ef', visible: true },
        width: els.imbalanceChart.clientWidth || 300,
        height: 200,
      });
      imbBidSeries = imbChart.addHistogramSeries({
        color: '#10b981', priceFormat: { type: 'volume' },
        priceLineVisible: false, lastValueVisible: false,
      });
      imbAskSeries = imbChart.addHistogramSeries({
        color: '#f43f5e', priceFormat: { type: 'volume' },
        priceLineVisible: false, lastValueVisible: false,
      });
    }
  }

  // ═══ Indian Stock Charts Init ═══
  // ═══ Institutional Charts Init ═══
  function initInstitutionalCharts() {
    const chartOpts = (h) => ({
      layout: { background: { type: 'solid', color: '#ffffff' }, textColor: '#5a5a7a' },
      grid: { vertLines: { color: '#e2e6ef' }, horzLines: { color: '#e2e6ef' } },
      timeScale: { borderColor: '#e2e6ef', visible: false },
      rightPriceScale: { borderColor: '#e2e6ef', visible: true },
      width: 300, height: h,
    });

    const whaleEl = document.getElementById('instWhaleBarChart');
    if (whaleEl) {
      instWhaleBar = LightweightCharts.createChart(whaleEl, { ...chartOpts(200), width: whaleEl.clientWidth || 300 });
      instWhaleBarSeries = instWhaleBar.addHistogramSeries({ priceLineVisible: false, lastValueVisible: false });
    }

    const nfEl = document.getElementById('instNetflowChart');
    if (nfEl) {
      instNetflowCh = LightweightCharts.createChart(nfEl, { ...chartOpts(200), width: nfEl.clientWidth || 300 });
      instNetflowSeries = instNetflowCh.addHistogramSeries({ priceLineVisible: false, lastValueVisible: false });
    }

    const oiEl = document.getElementById('instOIChart');
    if (oiEl) {
      instOICh = LightweightCharts.createChart(oiEl, { ...chartOpts(220), width: oiEl.clientWidth || 300 });
      instOISeries = instOICh.addAreaSeries({ lineColor: '#06b6d4', topColor: 'rgba(6,182,212,0.2)', bottomColor: 'rgba(6,182,212,0.02)', lineWidth: 2, priceLineVisible: false, lastValueVisible: true });
    }

    const frEl = document.getElementById('instFundingChart');
    if (frEl) {
      instFundCh = LightweightCharts.createChart(frEl, { ...chartOpts(220), width: frEl.clientWidth || 300 });
      instFundSeries = instFundCh.addHistogramSeries({ priceLineVisible: false, lastValueVisible: false });
    }

    const cvdEl = document.getElementById('instCrossCVDChart');
    if (cvdEl) {
      instCVDCh = LightweightCharts.createChart(cvdEl, { ...chartOpts(220), width: cvdEl.clientWidth || 300 });
      instSpotCvdSeries = instCVDCh.addLineSeries({ color: '#10b981', lineWidth: 2, priceLineVisible: false, lastValueVisible: true, title: 'Spot' });
      instFutsCvdSeries = instCVDCh.addLineSeries({ color: '#f43f5e', lineWidth: 2, priceLineVisible: false, lastValueVisible: true, title: 'Futures' });
    }
  }

  function initIndianCharts() {
    if (els.inPriceChart) {
      inPc = LightweightCharts.createChart(els.inPriceChart, {
        layout: { background: { type: 'solid', color: '#ffffff' }, textColor: '#5a5a7a' },
        grid: { vertLines: { color: '#e2e6ef' }, horzLines: { color: '#e2e6ef' } },
        crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
        timeScale: { borderColor: '#e2e6ef', timeVisible: true, secondsVisible: false },
        rightPriceScale: { borderColor: '#e2e6ef' },
        width: els.inPriceChart.clientWidth || 600,
        height: 340,
      });
      inPriceSeries = inPc.addCandlestickSeries({
        upColor: '#10b981', downColor: '#f43f5e',
        borderUpColor: '#10b981', borderDownColor: '#f43f5e',
        wickUpColor: '#10b981', wickDownColor: '#f43f5e',
      });
    }
    // CVD chart
    if (els.inCvdChart) {
      inCvc = LightweightCharts.createChart(els.inCvdChart, {
        layout: { background: { type: 'solid', color: '#ffffff' }, textColor: '#5a5a7a' },
        grid: { vertLines: { color: '#e2e6ef' }, horzLines: { color: '#e2e6ef' } },
        timeScale: { borderColor: '#e2e6ef', visible: false },
        rightPriceScale: { borderColor: '#e2e6ef', visible: true },
        width: els.inCvdChart.clientWidth || 400,
        height: 200,
      });
      inCvdLineSeries = inCvc.addLineSeries({
        color: '#8b5cf6', lineWidth: 2,
        priceLineVisible: false, lastValueVisible: true,
      });
    }
  }

  function resizeCharts() {
    if (liq9Pc) {
      const w = document.getElementById('liq9PriceChart')?.clientWidth || 600;
      liq9Pc.applyOptions({ width: w, height: 340 });
    }
    if (pc) {
      const w = els.priceChart.clientWidth || 600;
      pc.applyOptions({ width: w, height: 340 });
    }
    if (dpc) {
      const w = els.depthPriceChart.clientWidth || 400;
      dpc.applyOptions({ width: w, height: 300 });
    }
    if (cvcDepth) {
      const w = els.cvdChartDepth.clientWidth || 400;
      cvcDepth.applyOptions({ width: w, height: 300 });
    }
    if (dhc) {
      const w = els.depthHistChart.clientWidth || 300;
      dhc.applyOptions({ width: w, height: 200 });
    }
    if (imbChart) {
      const w = els.imbalanceChart.clientWidth || 300;
      imbChart.applyOptions({ width: w, height: 200 });
    }
    // Institutional charts
    if (instWhaleBar) { const w = document.getElementById('instWhaleBarChart')?.clientWidth || 300; instWhaleBar.applyOptions({ width: w, height: 200 }); }
    if (instNetflowCh) { const w = document.getElementById('instNetflowChart')?.clientWidth || 300; instNetflowCh.applyOptions({ width: w, height: 200 }); }
    if (instOICh) { const w = document.getElementById('instOIChart')?.clientWidth || 300; instOICh.applyOptions({ width: w, height: 220 }); }
    if (instFundCh) { const w = document.getElementById('instFundingChart')?.clientWidth || 300; instFundCh.applyOptions({ width: w, height: 220 }); }
    if (instCVDCh) { const w = document.getElementById('instCrossCVDChart')?.clientWidth || 300; instCVDCh.applyOptions({ width: w, height: 220 }); }
    // No delta chart to resize (using numeric table)
    if (inPc) {
      const w = els.inPriceChart.clientWidth || 600;
      inPc.applyOptions({ width: w, height: 340 });
    }
    if (inCvc) {
      const w = els.inCvdChart.clientWidth || 400;
      inCvc.applyOptions({ width: w, height: 200 });
    }
    // Re-render zone bands to align with new chart dimensions
    if (state.data && pc) {
      renderZoneBands(state.data);
    }
    if (state.data && liq9Pc) {
      renderLiquidity9ZoneBands(state.data);
    }
  }

  // ─── Chart Zones ───────────────────────────────────────────

  function clearZoneLines() {
    state.priceLines.forEach(pl => {
      try { priceSeries.removePriceLine(pl); } catch (e) {}
    });
    state.priceLines = [];
  }

  function renderZoneLines(data) {
    if (!priceSeries || !pc) return;
    clearZoneLines();
    const zones = data.zones || [];
    if (!zones.length) return;
    zones.forEach(z => {
      const color = zoneColor(z);
      const pl = priceSeries.createPriceLine({
        price: z.price,
        color: color,
        lineWidth: zoneLineWidth(z),
        lineStyle: zoneLineStyle(z),
        axisLabelVisible: true,
        axisLabelColor: color,
        axisLabelTextColor: '#fff',
        title: shortSubtype(z) + ' ' + (z.tier || ''),
      });
      state.priceLines.push(pl);
    });
    // Also render shaded zone bands on the overlay
    renderZoneBands(data);
  }

  // ─── Zone Bands (Shaded Rectangles on Chart) ──────────────

  function renderZoneBands(data) {
    try {
      const overlay = document.getElementById('zoneOverlay');
      if (!overlay) return;
      overlay.innerHTML = ''; // Clear existing bands

      if (!pc) return;
      const priceScale = pc.priceScale('right');
      if (!priceScale || typeof priceScale.priceToCoordinate !== 'function') return;

      const zones = data.zones || [];
      if (!zones.length) return;

      zones.forEach(z => {
        // Determine top (higher price) and bottom (lower price) of the zone band
        let topPrice, bottomPrice;
        if (z.priceLow != null && z.priceHigh != null && z.priceHigh > z.priceLow) {
          topPrice = z.priceHigh;
          bottomPrice = z.priceLow;
        } else if (z.priceLow != null) {
          // Only low given — create a band above it
          const buffer = z.price * 0.002;
          topPrice = z.price + buffer;
          bottomPrice = z.priceLow;
        } else if (z.priceHigh != null) {
          const buffer = z.price * 0.002;
          topPrice = z.priceHigh;
          bottomPrice = z.price - buffer;
        } else {
          // No range — create a small band around the center price
          const buffer = z.price * 0.002;
          topPrice = z.price + buffer;
          bottomPrice = z.price - buffer;
        }

        // Ensure sane ordering
        if (topPrice < bottomPrice) {
          const tmp = topPrice;
          topPrice = bottomPrice;
          bottomPrice = tmp;
        }

        const topY = priceScale.priceToCoordinate(topPrice);
        const bottomY = priceScale.priceToCoordinate(bottomPrice);

        if (topY == null || bottomY == null) return;

        const height = bottomY - topY;
        // Skip bands that are too small to see (< 3px) — they'll still have the price line
        if (height < 3) return;

        // Determine CSS class based on subtype
        const subtype = z.subtype || z.source || '';
        let bandClass = 'zone-band';
        if (z.type === 'support') {
          bandClass += ' zone-band-support';
        } else {
          bandClass += ' zone-band-resistance';
        }

        if (subtype.includes('order_block')) bandClass += ' ob';
        else if (subtype.includes('fvg')) bandClass += ' fvg';
        else if (subtype.includes('liquidity_sweep')) bandClass += ' sweep';
        else if (subtype.includes('swing')) bandClass += ' swing';
        else if (subtype.includes('volume_hvn')) bandClass += ' hvn';
        else if (subtype.includes('order_wall')) bandClass += ' wall';

        // Create the band element
        const band = document.createElement('div');
        band.className = bandClass;
        band.style.top = Math.round(topY) + 'px';
        band.style.height = Math.max(3, Math.round(height)) + 'px';
        // Opacity based on strength (0.2 to 0.9)
        band.style.opacity = Math.max(0.15, Math.min(0.9, 0.15 + (z.strength || 0.3) * 0.75));

        // Add a small label on the band
        const label = document.createElement('span');
        label.className = 'zone-band-label';
        const stLabel = shortSubtype(z);
        label.textContent = stLabel + ' ' + (z.tier || '');
        label.style.color = zoneColor(z);
        band.appendChild(label);

        overlay.appendChild(band);
      });
    } catch (e) {
      // Zone bands are a visual enhancement — never block core functionality
      if (typeof console !== 'undefined' && console.warn) {
        console.warn('Zone bands render error (non-critical):', e);
      }
    }
  }

  function renderStructureMarkers(data) {
    if (!priceSeries || !pc) return;
    const structure = data.structure || [];
    if (!structure.length) return;
    const markers = structure.map(ev => {
      const isBull = ev.direction === 'up' || ev.direction === 'bullish';
      const color = ev.type === 'CHoCH'
        ? (isBull ? '#10b981' : '#f43f5e')
        : (isBull ? '#22d3ee' : '#f43f5e');
      return {
        time: ev.time,
        position: isBull ? 'belowBar' : 'aboveBar',
        color,
        shape: ev.type === 'CHoCH' ? 'arrowDown' : 'arrowUp',
        text: ev.type + (ev.direction ? ' ' + ev.direction : ''),
      };
    }).filter(m => m.time > 0);
    if (markers.length) priceSeries.setMarkers(markers);
  }


  // ─── Delta Table (Numeric, replaces histogram chart) ────

  function updateDeltaTable(data) {
    if (!els.deltaTableWrap) return;
    const cvd = data.cvd;
    if (!cvd || !cvd.perCandleDelta || !cvd.perCandleDelta.length) {
      els.deltaTableWrap.innerHTML = '<div class="delta-table-empty">Waiting for delta data...</div>';
      return;
    }

    const deltas = cvd.perCandleDelta;
    // Show last 20 candles
    const recent = deltas.slice(-20);

    let html = '';
    // Header row
    html += `<div class="delta-table-header">
      <span class="dt-col-time">Time</span>
      <span class="dt-col-delta">Delta</span>
      <span class="dt-col-buy">Buy Vol</span>
      <span class="dt-col-sell">Sell Vol</span>
      <span class="dt-col-vol">Volume</span>
    </div>`;

    // Rows
    html += '<div class="delta-table-rows">';
    recent.forEach((d, idx) => {
      const isLatest = idx === recent.length - 1;
      const deltaVal = d.delta || 0;
      const isPos = deltaVal >= 0;
      const sign = isPos ? '+' : '';
      const valColor = isPos ? '#10b981' : '#f43f5e';
      const arrow = isPos ? '▲' : '▼';
      const buyVol = d.buyVolume || 0;
      const sellVol = d.sellVolume || 0;
      const totalVol = buyVol + sellVol;

      // Format time as HH:MM
      const dateObj = new Date((d.time || 0) * 1000);
      const timeStr = dateObj.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false });

      // Volume bar (relative to max in this set)
      const maxVol = Math.max(...recent.map(dd => (dd.buyVolume || 0) + (dd.sellVolume || 0)), 1);
      const volPct = Math.max(2, (totalVol / maxVol) * 100);

      html += `<div class="delta-row${isLatest ? ' is-latest' : ''}">
        <span class="dt-col-time">${timeStr}</span>
        <span class="dt-col-delta ${isPos ? 'positive' : 'negative'}">
          <span class="delta-arrow">${arrow}</span>${sign}${deltaVal.toFixed(0)}
        </span>
        <span class="dt-col-buy">${buyVol.toFixed(0)}</span>
        <span class="dt-col-sell">${sellVol.toFixed(0)}</span>
        <div class="vol-bar-wrap">
          <div class="vol-bar-fill" style="width:${volPct}%;background:${valColor}"></div>
        </div>
      </div>`;
    });
    html += '</div>';

    els.deltaTableWrap.innerHTML = html;

    // Update live indicator
    const lastDelta = deltas.length ? (deltas[deltas.length - 1].delta || 0) : 0;
    if (els.deltaLiveIndicator) {
      els.deltaLiveIndicator.style.background = lastDelta >= 0 ? '#10b981' : '#f43f5e';
      els.deltaLiveIndicator.style.boxShadow = lastDelta >= 0
        ? '0 0 6px rgba(16,185,129,0.6)'
        : '0 0 6px rgba(244,63,94,0.6)';
    }
    if (els.deltaLiveLabel) {
      const age = data.timestamp ? Math.floor((Date.now() / 1000) - data.timestamp) : 0;
      els.deltaLiveLabel.textContent = age <= 5 ? 'Live' : age + 's ago';
      els.deltaLiveLabel.style.color = age <= 5 ? '#10b981' : '#f59e0b';
    }
  }


  // ─── Delta Pattern Cards ───────────────────────────────────

  function updateDeltaPatterns(data) {
    const patterns = data.deltaPatterns;
    const cvd = data.cvd || {};

    // Update badge count
    const count = patterns?.activeCount || 0;
    if (els.deltaPatternBadge) {
      els.deltaPatternBadge.textContent = count;
      els.deltaPatternBadge.style.background = count > 0
        ? 'rgba(245,158,11,0.2)'
        : 'rgba(74,84,120,0.2)';
      els.deltaPatternBadge.style.color = count > 0 ? '#f59e0b' : '#4a5478';
    }

    // Update summary stats
    const latestCandle = cvd.latestCandle || {};
    if (els.dpActiveCount) els.dpActiveCount.textContent = count;
    if (els.dpLatestDelta) {
      const delta = latestCandle.delta || 0;
      els.dpLatestDelta.textContent = (delta > 0 ? '+' : '') + delta.toFixed(2);
      els.dpLatestDelta.style.color = delta > 0 ? '#10b981' : delta < 0 ? '#f43f5e' : '#f59e0b';
    }
    if (els.dpBuyVol) {
      const bv = latestCandle.buyVolume || 0;
      els.dpBuyVol.textContent = bv.toFixed(2);
    }
    if (els.dpSellVol) {
      const sv = latestCandle.sellVolume || 0;
      els.dpSellVol.textContent = sv.toFixed(2);
    }
    if (els.dpBullBearRatio) {
      const bb = latestCandle.bullRatio || 0;
      const bear = 1 - bb;
      els.dpBullBearRatio.textContent = (bb * 100).toFixed(0) + '/' + (bear * 100).toFixed(0);
    }

    // Render pattern cards
    if (!els.dpPatternsContainer) return;
    if (!patterns || !patterns.patterns || !patterns.patterns.length) {
      els.dpPatternsContainer.innerHTML = '<div class="dp-empty">No delta patterns detected in the latest candle. Patterns appear when live market conditions match one of the 4 signatures.</div>';
      return;
    }

    // Sort by significance descending
    const sorted = [...patterns.patterns].sort((a, b) => (b.significance || 0) - (a.significance || 0));

    els.dpPatternsContainer.innerHTML = sorted.map(p => {
      const sigPct = ((p.significance || 0) * 100).toFixed(0);
      const isBull = p.direction === 'bullish';
      const dirIcon = isBull ? '🟢' : '🔴';
      const dirColor = isBull ? '#10b981' : '#f43f5e';
      const sigColor = sigPct >= 70 ? '#10b981' : sigPct >= 40 ? '#f59e0b' : '#f43f5e';
      const pClass = 'dp-p' + p.pattern;

      return `
        <div class="dp-card fade-in ${pClass}">
          <div class="dp-card-header">
            <span class="dp-pattern-num">P${p.pattern}</span>
            <span class="dp-pattern-name" style="color:${dirColor}">${dirIcon} ${p.name}</span>
            <span class="dp-significance" style="color:${sigColor};background:${sigColor}15">${sigPct}%</span>
          </div>
          <div class="dp-card-body">
            <p class="dp-desc">${p.description}</p>
            <p class="dp-insight">💡 ${p.insight}</p>
          </div>
          <div class="dp-card-metrics">
            ${p.delta !== undefined ? `<span class="dp-metric" style="color:${p.delta > 0 ? '#10b981' : '#f43f5e'}">Δ ${p.delta > 0 ? '+' : ''}${p.delta.toFixed(2)}</span>` : ''}
            ${p.volRatio !== undefined ? `<span class="dp-metric">Vol ${p.volRatio.toFixed(1)}x</span>` : ''}
            ${p.rangeRatio !== undefined ? `<span class="dp-metric">Range ${p.rangeRatio.toFixed(1)}x</span>` : ''}
            ${p.breakDepth !== undefined ? `<span class="dp-metric">Break ${p.breakDepth.toFixed(2)}%</span>` : ''}
            ${p.priceChange !== undefined ? `<span class="dp-metric">Chg $${p.priceChange.toFixed(2)}</span>` : ''}
            ${p.avgDelta !== undefined ? `<span class="dp-metric">Avg Δ ${p.avgDelta.toFixed(2)}</span>` : ''}
            ${p.bodyPct !== undefined ? `<span class="dp-metric">Body ${p.bodyPct}%</span>` : ''}
          </div>
        </div>`;
    }).join('');
  }


  // ─── Price Chart ───────────────────────────────────────────

  function updatePriceChart(data) {
    if (!pc || !priceSeries) return;
    const candles = data.candles || [];
    if (!candles.length) return;
    priceSeries.setData(candles.map(c => ({ time: c.time, open: c.open, high: c.high, low: c.low, close: c.close })));
    renderZoneLines(data);
    renderStructureMarkers(data);
    pc.timeScale().fitContent();
  }


  // ─── POWER METER ────────────────────────────────────────────

  function updatePowerMeter(data) {
    if (!els.powerBar || !els.powerKnob || !els.powerBalanceText) return;
    const s = data.marketSummary || {};
    const imb = s.imbalance || 0;

    const pct = 50 + (imb * 50);
    const clampedPct = Math.max(2, Math.min(98, pct));

    els.powerBar.style.width = clampedPct + '%';
    els.powerKnob.style.left = clampedPct + '%';

    if (imb > 0.2) {
      const intensity = Math.min(1, imb * 2);
      els.powerBar.style.background = `linear-gradient(90deg, #10b981, ${intensity > 0.6 ? '#059669' : '#10b981'})`;
      els.powerKnob.style.borderColor = '#10b981';
      els.powerKnob.style.boxShadow = '0 0 20px rgba(16,185,129,0.4)';
      els.powerBalanceText.textContent = `BUYERS +${(imb * 100).toFixed(0)}%`;
      els.powerBalanceText.style.color = '#10b981';
      if (els.powerLabel) {
        els.powerLabel.textContent = '\u{1F7E2} Buyers in Control';
        els.powerLabel.style.color = '#10b981';
        els.powerLabel.style.background = 'rgba(16,185,129,0.12)';
      }
    } else if (imb < -0.2) {
      els.powerBar.style.background = `linear-gradient(90deg, ${Math.abs(imb) * 2 > 1.2 ? '#e11d48' : '#f43f5e'}, #f43f5e)`;
      els.powerKnob.style.borderColor = '#f43f5e';
      els.powerKnob.style.boxShadow = '0 0 20px rgba(244,63,94,0.4)';
      els.powerBalanceText.textContent = `SELLERS +${(Math.abs(imb) * 100).toFixed(0)}%`;
      els.powerBalanceText.style.color = '#f43f5e';
      if (els.powerLabel) {
        els.powerLabel.textContent = '\u{1F534} Sellers in Control';
        els.powerLabel.style.color = '#f43f5e';
        els.powerLabel.style.background = 'rgba(244,63,94,0.12)';
      }
    } else {
      els.powerBar.style.background = '#f59e0b';
      els.powerKnob.style.borderColor = '#f59e0b';
      els.powerKnob.style.boxShadow = '0 0 20px rgba(245,158,11,0.3)';
      els.powerBalanceText.textContent = '\u2696\uFE0F Balanced';
      els.powerBalanceText.style.color = '#f59e0b';
      if (els.powerLabel) {
        els.powerLabel.textContent = '\u2696\uFE0F Market Balanced';
        els.powerLabel.style.color = '#f59e0b';
        els.powerLabel.style.background = 'rgba(245,158,11,0.1)';
      }
    }

    if (els.pmBuyVol) els.pmBuyVol.textContent = 'Bid: ' + (s.totalBidLiquidity || 0).toFixed(2);
    if (els.pmSellVol) els.pmSellVol.textContent = 'Ask: ' + (s.totalAskLiquidity || 0).toFixed(2);
    if (els.pmRatio) els.pmRatio.textContent = 'Ratio: ' + (s.bidAskRatio || 0).toFixed(2);
  }


  // ─── ACTIVE WALLS TABLE ────────────────────────────────────

  function updateWallsTable(data) {
    if (!els.wallsTableBody || !els.wallsCountDepth) return;
    const depth = data.depth;
    if (!depth) return;

    const bidWalls = depth.bidWalls || [];
    const askWalls = depth.askWalls || [];
    const allWalls = [
      ...bidWalls.map(w => ({ ...w, side: 'bid' })),
      ...askWalls.map(w => ({ ...w, side: 'ask' })),
    ];
    allWalls.sort((a, b) => (b.strength || 0) - (a.strength || 0));

    els.wallsCountDepth.textContent = allWalls.length + ' walls';

    if (!allWalls.length) {
      els.wallsTableBody.innerHTML = '<div class="walls-empty">No significant liquidity walls detected</div>';
      return;
    }

    const maxVol = Math.max(...allWalls.map(w => w.volume || 0), 1);

    els.wallsTableBody.innerHTML = allWalls.map(w => {
      const sideClass = w.side === 'bid' ? 'wall-side-bid' : 'wall-side-ask';
      const volPct = ((w.volume || 0) / maxVol * 100).toFixed(0);
      const volColor = w.side === 'bid' ? '#10b981' : '#f43f5e';
      const strength = ((w.strength || 0) * 100).toFixed(0);
      return `
        <div class="wall-row fade-in">
          <span class="wall-side ${sideClass}">${w.side === 'bid' ? 'BID' : 'ASK'}</span>
          <span class="wall-price" style="color:${volColor}">$${w.price.toLocaleString('en-US', { minimumFractionDigits: 2 })}</span>
          <div class="wall-vol-bar-wrap">
            <div class="wall-vol-bar-fill" style="width:${volPct}%;background:${volColor}"></div>
          </div>
          <span class="wall-volume">${(w.volume || 0).toFixed(4)}</span>
          <span class="wall-strength" style="color:${strength > 50 ? volColor : '#4a5478'}">${strength}%</span>
        </div>`;
    }).join('');
  }


  // ─── Depth Price Chart (with Wall Markers) ─────────────────

  let depthWallLines = [];

  function updateDepthPriceChart(data) {
    if (!dpc || !depthPriceSeries) return;
    const candles = data.candles || [];
    if (!candles.length) return;

    depthPriceSeries.setData(candles.map(c => ({ time: c.time, open: c.open, high: c.high, low: c.low, close: c.close })));

    depthWallLines.forEach(pl => {
      try { depthPriceSeries.removePriceLine(pl); } catch (e) {}
    });
    depthWallLines = [];

    const depth = data.depth;
    if (!depth) { dpc.timeScale().fitContent(); return; }

    const bidWalls = depth.bidWalls || [];
    const askWalls = depth.askWalls || [];
    const cp = data.currentPrice || 0;

    bidWalls.forEach(w => {
      const pl = depthPriceSeries.createPriceLine({
        price: w.price, color: '#10b981', lineWidth: 2, lineStyle: 2,
        axisLabelVisible: true, axisLabelColor: '#10b981', axisLabelTextColor: '#fff', title: 'Bid Wall',
      });
      depthWallLines.push(pl);
    });

    askWalls.forEach(w => {
      const pl = depthPriceSeries.createPriceLine({
        price: w.price, color: '#f43f5e', lineWidth: 2, lineStyle: 2,
        axisLabelVisible: true, axisLabelColor: '#f43f5e', axisLabelTextColor: '#fff', title: 'Ask Wall',
      });
      depthWallLines.push(pl);
    });

    if (cp) {
      const pl = depthPriceSeries.createPriceLine({
        price: cp, color: '#f59e0b', lineWidth: 1, lineStyle: 0,
        axisLabelVisible: true, axisLabelColor: '#f59e0b', axisLabelTextColor: '#fff', title: 'Price',
      });
      depthWallLines.push(pl);
    }

    dpc.timeScale().fitContent();
  }


  // ─── Depth Tab CVD Chart ───────────────────────────────────

  function updateDepthCVDChart(data) {
    if (!cvcDepth || !cvdLineSeriesDepth) return;
    const cvd = data.cvd;
    if (!cvd || !cvd.cvd || !cvd.cvd.length) return;
    cvdLineSeriesDepth.setData(cvd.cvd.map(c => ({ time: c.time, value: c.value })));
    cvcDepth.timeScale().fitContent();

    const divs = cvd.divergences || [];
    const lastDiv = divs.length ? divs[divs.length - 1] : null;
    const cur = cvd.currentCVD || 0;
    if (els.cvdStatusDepth) {
      if (lastDiv && lastDiv.type === 'bullish') {
        els.cvdStatusDepth.textContent = 'Bullish Div \u2726';
        els.cvdStatusDepth.style.color = '#10b981';
        els.cvdStatusDepth.style.background = 'rgba(16,185,129,0.12)';
      } else if (lastDiv && lastDiv.type === 'bearish') {
        els.cvdStatusDepth.textContent = 'Bearish Div \u2726';
        els.cvdStatusDepth.style.color = '#f43f5e';
        els.cvdStatusDepth.style.background = 'rgba(244,63,94,0.12)';
      } else if (cur > 50) {
        els.cvdStatusDepth.textContent = '\u{1F7E2} Bullish';
        els.cvdStatusDepth.style.color = '#10b981';
        els.cvdStatusDepth.style.background = 'rgba(16,185,129,0.12)';
      } else if (cur < -50) {
        els.cvdStatusDepth.textContent = '\u{1F534} Bearish';
        els.cvdStatusDepth.style.color = '#f43f5e';
        els.cvdStatusDepth.style.background = 'rgba(244,63,94,0.12)';
      } else {
        els.cvdStatusDepth.textContent = 'Neutral';
        els.cvdStatusDepth.style.color = '#f59e0b';
        els.cvdStatusDepth.style.background = 'rgba(245,158,11,0.1)';
      }
    }
  }


  // ─── Depth Histogram & Imbalance Chart ─────────────────────

  function updateDepthHistogram(data) {
    if (!dhc || !depthBidHistSeries || !depthAskHistSeries) return;
    const depth = data.depth;
    if (!depth) return;
    const bids = (depth.bids || []).slice(0, 30);
    const asks = (depth.asks || []).slice(0, 30);
    depthBidHistSeries.setData(bids.map((b, i) => ({ time: i, value: b.volume * b.price, color: '#10b981' })));
    depthAskHistSeries.setData(asks.map((a, i) => ({ time: i, value: a.volume * a.price, color: '#f43f5e' })));
    dhc.timeScale().fitContent();

    const imb = depth.imbalance || 0;
    if (els.depthImbalanceDepth) {
      if (imb > 0.1) {
        els.depthImbalanceDepth.textContent = 'Bid Heavy ' + (imb * 100).toFixed(0) + '%';
        els.depthImbalanceDepth.style.color = '#10b981';
        els.depthImbalanceDepth.style.background = 'rgba(16,185,129,0.12)';
      } else if (imb < -0.1) {
        els.depthImbalanceDepth.textContent = 'Ask Heavy ' + (Math.abs(imb) * 100).toFixed(0) + '%';
        els.depthImbalanceDepth.style.color = '#f43f5e';
        els.depthImbalanceDepth.style.background = 'rgba(244,63,94,0.12)';
      } else {
        els.depthImbalanceDepth.textContent = 'Balanced';
        els.depthImbalanceDepth.style.color = '#f59e0b';
        els.depthImbalanceDepth.style.background = 'rgba(245,158,11,0.1)';
      }
    }
  }

  function updateImbalanceChart(data) {
    if (!imbChart || !imbBidSeries || !imbAskSeries) return;
    const depth = data.depth;
    if (!depth) return;
    const bids = (depth.bids || []).slice(0, 15);
    const asks = (depth.asks || []).slice(0, 15);

    const levels = [];
    const maxLen = Math.max(bids.length, asks.length);
    for (let i = 0; i < maxLen; i++) {
      const bVol = bids[i] ? bids[i].volume : 0;
      const aVol = asks[i] ? asks[i].volume : 0;
      const total = bVol + aVol;
      const imb = total > 0 ? (bVol - aVol) / total : 0;
      const isBuy = imb >= 0;
      levels.push({
        time: i,
        value: Math.abs(imb * 100),
        color: isBuy ? '#10b981' : '#f43f5e',
      });
    }

    imbBidSeries.setData(levels.filter(l => l.color === '#10b981'));
    imbAskSeries.setData(levels.filter(l => l.color === '#f43f5e'));
    imbChart.timeScale().fitContent();

    const avgImb = levels.length ? levels.reduce((s, l) => s + (l.color === '#10b981' ? l.value : -l.value), 0) / levels.length : 0;
    if (els.imbBadgeDepth) {
      els.imbBadgeDepth.textContent = (avgImb).toFixed(1) + '%';
      els.imbBadgeDepth.style.color = avgImb > 5 ? '#10b981' : avgImb < -5 ? '#f43f5e' : '#f59e0b';
    }
  }


  // ─── Volume Profile (Depth tab) ──────────────────────────

  function updateVolumeProfile(data) {
    if (!els.vpWrap) return;
    const vp = data.volumeProfile;
    if (!vp || !vp.bins || !vp.bins.length) {
      els.vpWrap.innerHTML = '<div class="vp-empty">No volume profile data</div>';
      return;
    }

    const { bins, poc, pocVolume, valueAreaHigh, valueAreaLow, totalVolume } = vp;
    const maxVol = Math.max(...bins.map(b => b.volume || 0), 1);
    const cp = data.currentPrice || 0;

    // Update stat badges
    if (els.vpPocStat) els.vpPocStat.textContent = 'POC: ' + poc.toLocaleString('en-US', { minimumFractionDigits: 2 });
    if (els.vpVaStat) els.vpVaStat.textContent = 'VA: ' + (valueAreaLow || 0).toFixed(0) + '\u2013' + (valueAreaHigh || 0).toFixed(0);
    if (els.vpVolStat) els.vpVolStat.textContent = 'Vol: ' + (totalVolume || 0).toFixed(0);

    // Determine value area index range for highlight
    const vaLowIdx = valueAreaLow ? bins.findIndex(b => b.priceLow <= valueAreaLow && b.priceHigh >= valueAreaLow) : -1;
    const vaHighIdx = valueAreaHigh ? bins.findIndex(b => b.priceLow <= valueAreaHigh && b.priceHigh >= valueAreaHigh) : -1;

    // Render rows from lowest price (bottom) to highest (top)
    const rowsHtml = bins.map((b, i) => {
      const vol = b.volume || 0;
      const pct = Math.max(2, (vol / maxVol) * 100);
      const priceMid = (b.priceLow + b.priceHigh) / 2;
      // Check if this bin is the POC (Point of Control)
      const isPocByPrice = Math.abs(priceMid - poc) / Math.max(poc, 1) < 0.0005;

      const binType = b.type || 'normal';
      let barClass = 'vp-bar-' + binType;
      let rowClass = 'vp-row';
      if (isPocByPrice) {
        rowClass += ' vp-row-poc';
        barClass = ''; // override with POC style
      } else if (binType === 'HVN') {
        rowClass += ' vp-row-hvn';
      } else if (binType === 'LVN') {
        rowClass += ' vp-row-lvn';
      }

      // Value area highlight for this row
      const inVa = vaLowIdx >= 0 && vaHighIdx >= 0 && i >= Math.min(vaLowIdx, vaHighIdx) && i <= Math.max(vaLowIdx, vaHighIdx);

      const priceLabel = priceMid.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 });
      const volLabel = vol.toFixed(0);

      const barFillStyle = isPocByPrice
        ? ''
        : `style="width:${pct}%"`;

      const pocBadge = isPocByPrice
        ? '<span class="vp-poc-indicator">\u25C9 POC</span>'
        : '';

      const vaAttr = inVa ? ' data-in-va="1"' : '';

      return `
        <div class="${rowClass} fade-in"${vaAttr}>
          <span class="vp-price-label">${priceLabel}</span>
          <div class="vp-bar-track">
            <div class="vp-bar-fill ${barClass}" ${barFillStyle}></div>
          </div>
          <span class="vp-vol-badge">${volLabel}</span>
          ${pocBadge}
        </div>`;
    }).join('');

    els.vpWrap.innerHTML = `<div class="vp-rows" style="display:flex;flex-direction:column;gap:1px">${rowsHtml}</div>`;

    // Apply POC bar widths (need a separate pass since POC overrides class)
    const pocRow = els.vpWrap.querySelector('.vp-row-poc');
    if (pocRow) {
      const barFill = pocRow.querySelector('.vp-bar-fill');
      if (barFill) {
        const pocBin = bins.find(b => Math.abs((b.priceLow + b.priceHigh) / 2 - poc) / Math.max(poc, 1) < 0.0005);
        const pct = pocBin ? Math.max(2, (pocBin.volume / maxVol) * 100) : 80;
        barFill.style.width = pct + '%';
      }
    }

    // Scroll to POC row (only if depth-flow tab is visible)
    if (pocRow && state.activeTab === 'depth-flow') {
      setTimeout(() => {
        pocRow.scrollIntoView({ block: 'center', behavior: 'smooth' });
      }, 100);
    }
  }


  // ─── Zone Cards (S&R Tab) ────────────────────────────────

  function renderZoneCards(data) {
    if (!els.supportCardsBody || !els.resistanceCardsBody) return;

    const zones = (data.zones || []).filter(z => state.filter === 'all' || z.type === state.filter);
    const supports = zones.filter(z => z.type === 'support');
    const resistances = zones.filter(z => z.type === 'resistance');
    const cp = data.currentPrice || 0;

    const suppCount = $('#supportCardsCount');
    const resCount = $('#resistanceCardsCount');
    if (suppCount) suppCount.textContent = supports.length;
    if (resCount) resCount.textContent = resistances.length;

    els.supportCardsBody.innerHTML = supports.length
      ? supports.map(z => buildZoneCard(z, cp)).join('')
      : '<div class="zone-empty">No support zones</div>';

    els.resistanceCardsBody.innerHTML = resistances.length
      ? resistances.map(z => buildZoneCard(z, cp)).join('')
      : '<div class="zone-empty">No resistance zones</div>';
  }

  function buildZoneCard(z, cp) {
    const color = subtypeColor(z);
    const stLabel = shortSubtype(z);
    const cssClass = subtypeCssClass(z);
    const tier = z.tier || 'D';
    const dist = z.distance != null ? z.distance : (cp ? Math.abs(z.price - cp) / cp * 100 : 0);
    const strength = ((z.strength || 0) * 100).toFixed(0);

    return `
      <div class="zone-card fade-in ${cssClass}" title="${stLabel} | Strength: ${strength}% | Score: ${(z.score || 0).toFixed(2)}">
        <span class="zc-subtype zc-st-${cssClass}">${stLabel}</span>
        <span class="zc-price" style="color:${color}">${z.price.toLocaleString('en-US', { minimumFractionDigits: 2 })}</span>
        <div class="zc-meta">
          <span>\u2726 ${strength}%</span>
          <span>\u2195 ${dist.toFixed(1)}%</span>
        </div>
        <span class="zc-tier" style="color:${color}">${tier}</span>
        <span class="zc-dist">${dist.toFixed(1)}%</span>
      </div>`;
  }


  // ─── Sidebar Zone List ─────────────────────────────────────

  function updateZoneList(data) {
    if (!els.zoneList) return;
    const zones = (data.zones || []).filter(z => state.filter === 'all' || z.type === state.filter);
    if (!zones.length) {
      els.zoneList.innerHTML = '<div class="zone-empty">No zones found</div>';
      return;
    }
    els.zoneList.innerHTML = zones.map(z => {
      const color = zoneColor(z);
      return `
        <div class="zone-item fade-in">
          <span class="zone-type ${z.type === 'support' ? 'zt-support' : 'zt-resistance'}">${z.type === 'support' ? 'Sup' : 'Res'}</span>
          <span style="font-size:8px;color:${color};font-weight:700;min-width:24px">${shortSubtype(z)}</span>
          <span class="zone-price">${z.price.toLocaleString('en-US', { minimumFractionDigits: 2 })}</span>
          <div class="zone-bar"><div class="zone-bar-fill" style="width:${Math.min((z.score || 0) * 100, 100)}%;background:${color}"></div></div>
          <span class="zone-tier" style="color:${color}">${z.tier || 'D'}</span>
        </div>`;
    }).join('');
  }


  // ─── Zone Table ────────────────────────────────────────────

  function updateZoneTable(data) {
    if (!els.zoneTable) return;
    const zones = data.zones || [];
    if (els.zoneTableCount) els.zoneTableCount.textContent = zones.length + ' zones';
    if (!zones.length) {
      els.zoneTable.innerHTML = '<tr><td colspan="8" class="empty">Run a scan to detect liquidity zones</td></tr>';
      return;
    }
    els.zoneTable.innerHTML = zones.map(z => {
      const st = z.subtype || z.source || '\u2014';
      const color = zoneColor(z);
      return `
        <tr class="fade-in">
          <td><span class="tier-badge" style="background:${color}22;color:${color}">${z.tier || 'D'}</span></td>
          <td><span style="color:${color};font-weight:600">${z.type}</span></td>
          <td style="color:var(--text-secondary)">${st.replace(/_/g, ' ')}</td>
          <td>${z.price.toLocaleString('en-US', { minimumFractionDigits: 2 })}</td>
          <td>${(z.distance || 0).toFixed(2)}%</td>
          <td>${((z.strength || 0) * 100).toFixed(0)}%</td>
          <td>${(z.score || 0).toFixed(2)}</td>
          <td>${(z.confluence || 0) > 0 ? '\u00d7' + (z.confluence || 0).toFixed(1) : '\u2014'}</td>
        </tr>`;
    }).join('');
  }


  // ─── Metrics ───────────────────────────────────────────────

  function updateMetrics(data) {
    const cp = data.currentPrice || 0;
    if (els.price) els.price.textContent = cp.toLocaleString('en-US', { minimumFractionDigits: 2 });
    const s = data.marketSummary || {};
    if (els.bidLiquidity) els.bidLiquidity.textContent = (s.totalBidLiquidity || 0).toFixed(2);
    if (els.askLiquidity) els.askLiquidity.textContent = (s.totalAskLiquidity || 0).toFixed(2);
    if (els.bidAskRatio) els.bidAskRatio.textContent = (s.bidAskRatio || 0).toFixed(2);
    if (els.imbalance) els.imbalance.textContent = ((s.imbalance || 0) * 100).toFixed(1) + '%';
    if (els.activeWalls) els.activeWalls.textContent = s.activeWalls || 0;
    if (els.totalZones) els.totalZones.textContent = data.zoneCounts?.total || 0;
    if (els.zoneCountBadge) els.zoneCountBadge.textContent = (data.zoneCounts?.total || 0) + ' zones';

    const structure = data.structure || [];
    const lastStruct = structure.length ? structure[structure.length - 1] : null;
    if (els.structureTag) {
      if (lastStruct) {
        els.structureTag.textContent = lastStruct.type + ' ' + lastStruct.direction;
        els.structureTag.style.color = lastStruct.direction === 'up' || lastStruct.direction === 'bullish' ? '#10b981' : '#f43f5e';
      } else {
        els.structureTag.textContent = '\u2014';
      }
    }
  }


  // ─── Cache Indicator ───────────────────────────────────────

  function updateCacheIndicator(data) {
    if (!els.cacheDot || !els.cacheLabel) return;
    const fromCache = data.cached === true;
    const scanCount = state.scanCount;

    if (els.cacheDot) {
      els.cacheDot.style.background = fromCache ? '#f59e0b' : '#10b981';
      els.cacheDot.style.boxShadow = fromCache
        ? '0 0 8px rgba(245,158,11,0.6)'
        : '0 0 8px rgba(16,185,129,0.6)';
    }
    if (els.cacheLabel) {
      els.cacheLabel.textContent = fromCache ? 'Cached' : 'Live';
      els.cacheLabel.style.color = fromCache ? '#f59e0b' : '#10b981';
    }
  }


  // ═══ Indian Stock Functions ═══════════════════════════════════

  async function searchIndianStocks(query) {
    try {
      const r = await fetch('/api/indian/stocks?q=' + encodeURIComponent(query));
      const d = await r.json();
      if (!d.success || !d.stocks) { els.inSearchResults.style.display = 'none'; return; }
      const results = d.stocks;
      if (!results.length) {
        els.inSearchResults.style.display = 'none';
        return;
      }
      els.inSearchResults.innerHTML = results.map(s =>
        `<div class="in-sr-item" data-symbol="${s.symbol}" data-name="${s.name}">
          <span class="in-sr-symbol">${s.symbol.replace('.NS','')}</span>
          <span class="in-sr-name">${s.name}</span>
          <span class="in-sr-exchange">${s.exchange}</span>
        </div>`
      ).join('');
      els.inSearchResults.style.display = 'block';
      // Click handler for results
      els.inSearchResults.querySelectorAll('.in-sr-item').forEach(item => {
        item.addEventListener('mousedown', (e) => {
          const symbol = item.dataset.symbol;
          const name = item.dataset.name;
          selectIndianStock(symbol, name);
        });
      });
    } catch (e) {
      els.inSearchResults.innerHTML = '<div class="in-sr-empty">Search failed. Check server.</div>';
      els.inSearchResults.style.display = 'block';
    }
  }

  function selectIndianStock(symbol, name) {
    state.inSelectedStock = symbol;
    state.inStockName = name;
    els.inStockSearch.value = name;
    els.inSearchResults.style.display = 'none';
    // Update info bar
    if (els.inInfoBar) els.inInfoBar.style.display = 'flex';
    if (els.inStockName) els.inStockName.textContent = name || symbol;
    if (els.inMetaExchange) els.inMetaExchange.textContent = symbol.includes('.NS') ? 'NSE' : 'INDEX';
    // Run scan automatically
    scanIndianStock(true);
  }

  function updateIndianPriceChart(data) {
    if (!inPc || !inPriceSeries) return;
    const candles = data.candles || [];
    if (!candles.length) return;
    inPriceSeries.setData(candles.map(c => ({
      time: c.time, open: c.open, high: c.high, low: c.low, close: c.close
    })));
    // Clear old lines
    inPriceLines.forEach(pl => { try { inPriceSeries.removePriceLine(pl); } catch(e) {} });
    inPriceLines = [];
    // Render zone lines
    const zones = data.zones || [];
    zones.forEach(z => {
      const color = zoneColor(z);
      const pl = inPriceSeries.createPriceLine({
        price: z.price, color, lineWidth: zoneLineWidth(z),
        lineStyle: zoneLineStyle(z),
        axisLabelVisible: true, axisLabelColor: color,
        axisLabelTextColor: '#fff',
        title: shortSubtype(z) + ' ' + (z.tier || ''),
      });
      inPriceLines.push(pl);
    });
    inPc.timeScale().fitContent();
  }

  function updateIndianCVDChart(data) {
    if (!inCvc || !inCvdLineSeries) return;
    const cvd = data.cvd;
    if (!cvd || !cvd.cvd || !cvd.cvd.length) return;
    inCvdLineSeries.setData(cvd.cvd.map(c => ({ time: c.time, value: c.value })));
    inCvc.timeScale().fitContent();
    const cur = cvd.currentCVD || 0;
    if (els.inCvdLabel) {
      els.inCvdLabel.textContent = cur > 0 ? '🟢 +' + cur.toFixed(0) : cur < 0 ? '🔴 ' + cur.toFixed(0) : '⚪ 0';
      els.inCvdLabel.style.color = cur > 0 ? '#10b981' : cur < 0 ? '#f43f5e' : '#f59e0b';
    }
  }

  function updateIndianVolumeProfile(data) {
    if (!els.inVpWrap) return;
    const vp = data.volumeProfile;
    if (!vp || !vp.bins || !vp.bins.length) {
      els.inVpWrap.innerHTML = '<div class="in-vp-empty">No volume profile data</div>';
      return;
    }
    const { bins, poc, valueAreaHigh, valueAreaLow, totalVolume } = vp;
    if (els.inVpInfo) els.inVpInfo.textContent = 'POC: ' + poc.toFixed(0);
    const maxVol = Math.max(...bins.map(b => b.volume || 0), 1);
    els.inVpWrap.innerHTML = bins.map(b => {
      const pct = Math.max(2, (b.volume / maxVol) * 100);
      const mid = (b.priceLow + b.priceHigh) / 2;
      const isPoc = Math.abs(mid - poc) / Math.max(poc, 1) < 0.0005;
      return `<div class="in-vp-row${isPoc ? ' in-vp-poc' : ''}">
        <span class="in-vp-price">${mid.toFixed(0)}</span>
        <div class="in-vp-track"><div class="in-vp-fill" style="width:${pct}%"></div></div>
        <span class="in-vp-vol">${b.volume.toFixed(0)}</span>
      </div>`;
    }).join('');
  }

  function updateIndianZoneCards(data) {
    const zones = data.zones || [];
    const cp = data.currentPrice || 0;
    const supports = zones.filter(z => z.type === 'support');
    const resistances = zones.filter(z => z.type === 'resistance');
    if (els.inSupportCount) els.inSupportCount.textContent = supports.length;
    if (els.inResistanceCount) els.inResistanceCount.textContent = resistances.length;
    // Metrics
    if (els.inVolumeMetric) {
      const vol = data.candles?.length ? data.candles[data.candles.length-1]?.volume || 0 : 0;
      els.inVolumeMetric.textContent = vol > 0 ? vol.toLocaleString('en-IN', { maximumFractionDigits: 0 }) : '--';
    }
    if (els.inTierZones) {
      const topTier = zones.filter(z => z.tier === 'A+' || z.tier === 'A').length;
      els.inTierZones.textContent = topTier;
    }
    if (els.inPatternCount) {
      const count = data.deltaPatterns?.activeCount || 0;
      els.inPatternCount.textContent = count;
    }
    // Zone cards
    if (els.inSupportCards) {
      els.inSupportCards.innerHTML = supports.length
        ? supports.map(z => buildZoneCard(z, cp)).join('')
        : '<div class="in-zone-empty">No support zones</div>';
    }
    if (els.inResistanceCards) {
      els.inResistanceCards.innerHTML = resistances.length
        ? resistances.map(z => buildZoneCard(z, cp)).join('')
        : '<div class="in-zone-empty">No resistance zones</div>';
    }
  }

  function updateIndianUI(data) {
    state.inData = data;
    const info = data.info || {};
    const cp = data.currentPrice || 0;
    // Info bar
    if (els.inStockPrice) els.inStockPrice.textContent = '₹' + cp.toLocaleString('en-US', { minimumFractionDigits: 2 });
    if (els.inStockChange) {
      const chg = info.change || 0;
      const chgPct = info.changePercent || 0;
      els.inStockChange.textContent = (chg > 0 ? '+' : '') + chg.toFixed(2) + ' (' + chgPct.toFixed(2) + '%)';
      els.inStockChange.style.color = chg >= 0 ? '#10b981' : '#f43f5e';
    }
    if (els.inMetaSector) els.inMetaSector.textContent = info.sector || '--';
    if (els.inMetaMcap) {
      const mcap = info.marketCap || 0;
      els.inMetaMcap.textContent = mcap > 0 ? '₹' + (mcap / 10000000).toFixed(1) + 'Cr' : '--';
    }
    // Charts
    updateIndianPriceChart(data);
    updateIndianCVDChart(data);
    updateIndianVolumeProfile(data);
    updateIndianZoneCards(data);
  }

  async function scanIndianStock(forceRefresh = true) {
    if (!state.inSelectedStock) {
      showError('Search and select an Indian stock first');
      return;
    }
    if (state.inLoading) return;
    state.inLoading = true;
    if (els.inScanBtn) {
      els.inScanBtn.classList.add('loading');
      els.inScanBtn.innerHTML = '<span class="spinner"></span>';
    }
    try {
      const r = await fetch('/api/indian/scan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          symbol: state.inSelectedStock,
          interval: els.inIntervalSelect ? els.inIntervalSelect.value : '15m',
        }),
      });
      const d = await r.json();
      if (d.success) {
        updateIndianUI(d);
      } else {
        showError(d.error || 'Indian stock scan failed');
      }
    } catch (e) {
      showError('Failed to scan Indian stock: ' + e.message);
    } finally {
      state.inLoading = false;
      if (els.inScanBtn) {
        els.inScanBtn.classList.remove('loading');
        els.inScanBtn.textContent = 'Scan';
      }
    }
  }

  // ─── Institutional Panel ─────────────────────────────────

  async function fetchInstitutional(symbol) {
    if (state.instLoading) return;
    state.instLoading = true;
    try {
      const r = await fetch('/api/institutional', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol }),
      });
      const d = await r.json();
      if (d.success) {
        instData = d;
        updateInstitutionalPanel(d);
      }
    } catch (e) {
      // Silently fail
    } finally {
      state.instLoading = false;
    }
  }

  function startInstitutionalPolling() {
    stopInstitutionalPolling();
    // Poll every 30 seconds (institutional endpoint is heavier)
    state.instPollTimer = setInterval(() => {
      if (state.activeTab === 'institutional' && !state.instLoading) {
        fetchInstitutional(state.symbol);
      }
    }, 30000);
    // Fire immediately
    fetchInstitutional(state.symbol);
  }

  function stopInstitutionalPolling() {
    if (state.instPollTimer) {
      clearInterval(state.instPollTimer);
      state.instPollTimer = null;
    }
  }

  function updateInstitutionalPanel(data) {
    if (!data) return;
    const score = data.score || {};
    const whales = data.whales || {};
    const oi = data.openInterest || {};
    const funding = data.funding || {};
    const anomalies = data.anomalies || data.spoofing || {};
    const pressure = data.pressure || data.netflow || {};
    const crossCVD = data.crossCVD || {};

    // ─── Overall Score ───
    const gradeEl = document.getElementById('instGrade');
    const verdictEl = document.getElementById('instVerdict');
    const scoreFill = document.getElementById('instScoreFill');
    const signalCountEl = document.getElementById('instSignalCount');
    const badgeEl = document.getElementById('instBadge');

    if (gradeEl) {
      gradeEl.textContent = score.gradeDisplay || score.grade || 'D';
      const gradeColor = score.score >= 0.7 ? '#10b981' : score.score >= 0.5 ? '#06b6d4' : score.score >= 0.3 ? '#f59e0b' : score.score >= 0.15 ? '#f97316' : '#4a5478';
      gradeEl.style.color = gradeColor;
      gradeEl.style.textShadow = `0 0 20px ${gradeColor}44`;
    }
    if (verdictEl) {
      verdictEl.textContent = score.verdict || 'Loading...';
      if (score.incomplete) {
        verdictEl.style.color = '#f59e0b';
        verdictEl.style.fontWeight = '700';
      } else {
        verdictEl.style.color = '';
        verdictEl.style.fontWeight = '';
      }
    }
    if (scoreFill) {
      const pct = Math.min(100, (score.score || 0) * 100);
      scoreFill.style.width = pct + '%';
      scoreFill.style.background = score.score >= 0.5 ? '#10b981' : score.score >= 0.3 ? '#f59e0b' : '#f43f5e';
    }
    if (signalCountEl) signalCountEl.textContent = score.activeSignalCount || 0;
    if (badgeEl) {
      const n = score.activeSignalCount || 0;
      badgeEl.textContent = n > 0 ? n : '—';
      badgeEl.style.background = n > 0 ? 'rgba(16,185,129,0.2)' : 'rgba(74,84,120,0.2)';
      badgeEl.style.color = n > 0 ? '#10b981' : '#4a5478';
    }

    // ─── Signal Cards ───
    const setInstCard = (id, val, badgeId, badgeText, badgeColor) => {
      const valEl = document.getElementById(id);
      if (valEl) valEl.textContent = val;
      const bEl = document.getElementById(badgeId);
      if (bEl) {
        bEl.textContent = badgeText;
        bEl.style.color = badgeColor;
        bEl.style.background = badgeColor + '18';
      }
    };

    const whaleSummary = whales.summary || {};
    setInstCard('instWhaleVal', whaleSummary.count ? whaleSummary.count + ' trades' : '—', 'instWhaleBadge',
      whales.signal === 'accumulation' ? 'BUY' : whales.signal === 'distribution' ? 'SELL' : '—',
      whales.signal === 'accumulation' ? '#10b981' : whales.signal === 'distribution' ? '#f43f5e' : '#4a5478');

    setInstCard('instOIVal', oi.currentOI ? '$' + (oi.currentOI / 1e9).toFixed(2) + 'B' : '—', 'instOIBadge',
      oi.trend?.direction === 'increasing' ? 'UP' : oi.trend?.direction === 'decreasing' ? 'DOWN' : '—',
      oi.trend?.direction === 'increasing' ? '#10b981' : oi.trend?.direction === 'decreasing' ? '#f43f5e' : '#4a5478');

    setInstCard('instFundingVal', funding.currentRatePct !== undefined ? funding.currentRatePct.toFixed(4) + '%' : '—', 'instFundingBadge',
      funding.classification?.includes('long') ? 'LONG+' : funding.classification?.includes('short') ? 'SHORT+' : '—',
      funding.classification?.includes('long') ? '#f43f5e' : funding.classification?.includes('short') ? '#10b981' : '#4a5478');

    const anomalySum = anomalies.summary || {};
    setInstCard('instAnomalyVal', anomalySum.totalSignals ? anomalySum.totalSignals + ' anomalies' : '—', 'instAnomalyBadge',
      anomalySum.overallRisk === 'high' ? 'HIGH' : anomalySum.overallRisk === 'medium' ? 'MED' : 'LOW',
      anomalySum.overallRisk === 'high' ? '#f43f5e' : anomalySum.overallRisk === 'medium' ? '#f59e0b' : '#10b981');

    const prSum = pressure.summary || {};
    setInstCard('instPressureVal', prSum.sellPct !== undefined ? prSum.sellPct.toFixed(0) + '% sell' : '—', 'instPressureBadge',
      pressure.classification?.includes('buy') ? 'BUY' : pressure.classification?.includes('sell') ? 'SELL' : '—',
      pressure.classification?.includes('buy') ? '#10b981' : pressure.classification?.includes('sell') ? '#f43f5e' : '#4a5478');

    const cvdSum = crossCVD.summary || {};
    setInstCard('instCVDVal', cvdSum.divergence !== undefined ? cvdSum.divergence.toFixed(0) : '—', 'instCVDBadge',
      crossCVD.signal === 'strong_divergence' ? 'DIV' : crossCVD.signal === 'moderate_divergence' ? 'MILD' : '—',
      crossCVD.signal !== 'aligned' ? '#f59e0b' : '#4a5478');

    // ─── Whale Bar Chart ───
    if (instWhaleBarSeries && whaleSummary.totalVolume) {
      const buyP = whaleSummary.buyVolume || 0;
      const sellP = whaleSummary.sellVolume || 0;
      instWhaleBarSeries.setData([
        { time: 0, value: buyP, color: '#10b981' },
        { time: 1, value: sellP, color: '#f43f5e' },
      ]);
    }
    setText('instWhaleCount', (whaleSummary.count || 0) + ' whale trades');

    // ─── Netflow Chart ───
    if (instNetflowSeries && pressure.periods) {
      instNetflowSeries.setData(pressure.periods.map(p => ({
        time: p.time, value: p.notional * (p.pressure >= 0 ? 1 : -1) / 1000000,
        color: p.pressure >= 0 ? '#10b981' : '#f43f5e',
      })));
    }

    // ─── OI Chart ───
    if (instOISeries && oi.history) {
      instOISeries.setData(oi.history.map(h => ({ time: h.time, value: h.oi })));
    }
    setText('instOITrend', oi.trend ? oi.trend.direction + ' (' + (oi.trend.changePct >= 0 ? '+' : '') + oi.trend.changePct.toFixed(1) + '%)' : '—');

    // ─── Funding Chart ───
    if (instFundSeries && funding.history) {
      instFundSeries.setData(funding.history.map(h => ({
        time: h.time, value: h.rate * 10000,
        color: h.rate >= 0 ? '#f43f5e' : '#10b981',
      })));
    }
    setText('instFRClass', funding.classification || '—');

    // ─── Reliability indicator ───
    const relEl = document.getElementById('instReliability');
    if (relEl) {
      const rl = score.reliabilityLabel || '';
      const rp = score.reliability || 1.0;
      relEl.textContent = rl;
      relEl.style.color = rp >= 0.8 ? '#10b981' : rp >= 0.6 ? '#f59e0b' : '#f43f5e';
    }
    setText('instSpoofRisk', anomalySum.totalSignals ? 'Anomalies: ' + anomalySum.totalSignals + ' (Risk: ' + anomalySum.overallRisk + ')' : '—');

    // ─── Order Book Anomaly Signals ───
    const spoofEl = document.getElementById('instSpoofSignals');
    if (spoofEl) {
      const sigs = anomalies.signals || [];
      if (!sigs.length) {
        spoofEl.innerHTML = '<div class="inst-empty">No order book anomalies detected</div>';
      } else {
        spoofEl.innerHTML = sigs.slice(0, 8).map(s => {
          const isHigh = s.severity === 'high';
          return `<div class="inst-spoof-row" style="border-left-color:${isHigh ? '#f43f5e' : '#f59e0b'}">
            <span class="inst-spoof-type">${s.type.replace(/_/g, ' ')}</span>
            <span class="inst-spoof-price">$${s.price.toLocaleString()}</span>
            <span class="inst-spoof-notional">$${(s.notional/1000).toFixed(0)}k</span>
            <span class="inst-spoof-tag" style="color:${isHigh ? '#f43f5e' : '#f59e0b'}">${s.severity}</span>
          </div>`;
        }).join('');
      }
    }

    // ─── Cross-Exchange CVD Chart ───
    if (instSpotCvdSeries && instFutsCvdSeries && crossCVD.aligned) {
      instSpotCvdSeries.setData(crossCVD.aligned.map(a => ({ time: a.time, value: a.spotCVD })));
      instFutsCvdSeries.setData(crossCVD.aligned.map(a => ({ time: a.time, value: a.futsCVD })));
    }
    setText('instCVDSignal', crossCVD.signal ? crossCVD.signal.replace(/_/g, ' ') + (cvdSum.percentile ? ' (P' + cvdSum.percentile + ')' : '') : '—');

    // ─── Whale Clusters ───
    const clustersEl = document.getElementById('instClusters');
    if (clustersEl) {
      const clusters = whales.clusters || [];
      if (!clusters.length) {
        clustersEl.innerHTML = '<div class="inst-empty">No whale clusters detected</div>';
      } else {
        clustersEl.innerHTML = clusters.slice(0, 10).map(c => {
          const isBuy = c.dominant === 'buy';
          const color = isBuy ? '#10b981' : c.dominant === 'sell' ? '#f43f5e' : '#f59e0b';
          return `<div class="inst-cluster-row">
            <span class="inst-cl-price" style="color:${color}">$${c.price.toLocaleString()}</span>
            <span class="inst-cl-count">${c.tradeCount} trades</span>
            <span class="inst-cl-vol">$${(c.totalNotional/1000).toFixed(0)}k</span>
            <span class="inst-cl-dom" style="color:${color}">${c.dominant}</span>
          </div>`;
        }).join('');
      }
    }

    // ─── Active Signals List ───
    const signalsEl = document.getElementById('instSignalsList');
    if (signalsEl) {
      const sigs = score.signals || [];
      if (!sigs.length) {
        signalsEl.innerHTML = '<div class="inst-empty">No active institutional signals detected</div>';
      } else {
        signalsEl.innerHTML = sigs.map(s => {
          const confPct = (s.confidence * 100).toFixed(0);
          const color = confPct >= 70 ? '#10b981' : confPct >= 40 ? '#f59e0b' : '#f43f5e';
          return `<div class="inst-signal-row">
            <span class="inst-sig-row-name">${s.name}${s.isProxy ? ' <span style="color:#f59e0b;font-size:8px" title="Proxy data">*</span>' : ''}</span>
            <span class="inst-sig-row-signal" style="color:${color}">${s.signal.replace(/_/g, ' ')}</span>
            <div class="inst-sig-row-bar"><div class="inst-sig-row-fill" style="width:${confPct}%;background:${color}"></div></div>
            <span class="inst-sig-row-conf">${confPct}%</span>
            <span class="inst-sig-row-insight">${s.insight}</span>
          </div>`;
        }).join('');
      }
    }
  }

  // ─── Tab Switching ─────────────────────────────────────────

  // ─── Liquidity9 Panel ────────────────────────────────────

  function updateLiquidity9Panel(data) {
    if (!data) return;
    // Update chart title
    const titleEl = document.getElementById('liq9ChartTitle');
    if (titleEl) {
      const label = ({ BTCUSDT: 'BTC/USDT', ETHUSDT: 'ETH/USDT', BNBUSDT: 'BNB/USDT', SOLUSDT: 'SOL/USDT', XRPUSDT: 'XRP/USDT', ADAUSDT: 'ADA/USDT', DOGEUSDT: 'DOGE/USDT', AVAXUSDT: 'AVAX/USDT' })[state.symbol] || state.symbol;
      titleEl.textContent = label + ' \u2014 Liquidity Zones';
    }

    // Update metrics
    const zones = data.zones || [];
    const supports = zones.filter(z => z.type === 'support');
    const resistances = zones.filter(z => z.type === 'resistance');
    const s = data.marketSummary || {};
    const cp = data.currentPrice || 0;

    setText('liq9SupportCount', supports.length);
    setText('liq9ResistanceCount', resistances.length);
    setText('liq9Walls', s.activeWalls || 0);
    setText('liq9Imbalance', ((s.imbalance || 0) * 100).toFixed(1) + '%');
    setText('liq9Price', cp.toLocaleString('en-US', { minimumFractionDigits: 2 }));
    setText('liq9SupCount', supports.length);
    setText('liq9ResCount', resistances.length);

    // Update chart
    renderLiquidity9Chart(data);

    // Render zone cards
    renderLiquidity9ZoneCards(data);

    // Update timestamp
    const now = new Date();
    setText('liq9UpdateTime', 'Last scan: ' + now.toLocaleTimeString());
  }

  function setText(id, val) {
    const el = document.getElementById(id);
    if (el) el.textContent = val;
  }

  function renderLiquidity9Chart(data) {
    if (!liq9Pc || !liq9PriceSeries) return;
    const candles = data.candles || [];
    if (!candles.length) return;

    liq9PriceSeries.setData(candles.map(c => ({ time: c.time, open: c.open, high: c.high, low: c.low, close: c.close })));

    // Clear old lines
    liq9PriceLines.forEach(pl => {
      try { liq9PriceSeries.removePriceLine(pl); } catch (e) {}
    });
    liq9PriceLines = [];

    // Render zone lines: green for support, red for resistance
    const zones = data.zones || [];
    zones.forEach(z => {
      const color = z.type === 'support' ? '#10b981' : '#f43f5e';
      const pl = liq9PriceSeries.createPriceLine({
        price: z.price,
        color: color,
        lineWidth: zoneLineWidth(z),
        lineStyle: zoneLineStyle(z),
        axisLabelVisible: true,
        axisLabelColor: color,
        axisLabelTextColor: '#fff',
        title: shortSubtype(z) + ' ' + (z.tier || ''),
      });
      liq9PriceLines.push(pl);
    });

    // Render zone bands
    renderLiquidity9ZoneBands(data);

    liq9Pc.timeScale().fitContent();
  }

  function renderLiquidity9ZoneBands(data) {
    try {
      const overlay = document.getElementById('liq9ZoneOverlay');
      if (!overlay || !liq9Pc) return;
      overlay.innerHTML = '';

      const priceScale = liq9Pc.priceScale('right');
      if (!priceScale || typeof priceScale.priceToCoordinate !== 'function') return;

      const zones = data.zones || [];
      if (!zones.length) return;

      zones.forEach(z => {
        let topPrice, bottomPrice;
        if (z.priceLow != null && z.priceHigh != null && z.priceHigh > z.priceLow) {
          topPrice = z.priceHigh;
          bottomPrice = z.priceLow;
        } else if (z.priceLow != null) {
          const buffer = z.price * 0.002;
          topPrice = z.price + buffer;
          bottomPrice = z.priceLow;
        } else if (z.priceHigh != null) {
          const buffer = z.price * 0.002;
          topPrice = z.priceHigh;
          bottomPrice = z.price - buffer;
        } else {
          const buffer = z.price * 0.002;
          topPrice = z.price + buffer;
          bottomPrice = z.price - buffer;
        }

        if (topPrice < bottomPrice) {
          const tmp = topPrice;
          topPrice = bottomPrice;
          bottomPrice = tmp;
        }

        const topY = priceScale.priceToCoordinate(topPrice);
        const bottomY = priceScale.priceToCoordinate(bottomPrice);
        if (topY == null || bottomY == null) return;

        const height = bottomY - topY;
        if (height < 3) return;

        const isSupport = z.type === 'support';
        const band = document.createElement('div');
        band.className = 'zone-band ' + (isSupport ? 'zone-band-support' : 'zone-band-resistance');
        band.style.top = Math.round(topY) + 'px';
        band.style.height = Math.max(3, Math.round(height)) + 'px';
        band.style.opacity = Math.max(0.15, Math.min(0.9, 0.15 + (z.strength || 0.3) * 0.75));

        const label = document.createElement('span');
        label.className = 'zone-band-label';
        label.textContent = shortSubtype(z) + ' ' + (z.tier || '');
        label.style.color = isSupport ? '#10b981' : '#f43f5e';
        band.appendChild(label);
        overlay.appendChild(band);
      });
    } catch (e) {
      // Non-critical visual enhancement
    }
  }

  function renderLiquidity9ZoneCards(data) {
    const zones = data.zones || [];
    const cp = data.currentPrice || 0;
    const supports = zones.filter(z => z.type === 'support').slice(0, 20);
    const resistances = zones.filter(z => z.type === 'resistance').slice(0, 20);

    const supEl = document.getElementById('liq9SupportZones');
    const resEl = document.getElementById('liq9ResistanceZones');

    if (supEl) {
      supEl.innerHTML = supports.length
        ? supports.map(z => buildLiquidity9ZoneCard(z, cp, 'support')).join('')
        : '<div class="liq9-empty">No support zones detected</div>';
    }
    if (resEl) {
      resEl.innerHTML = resistances.length
        ? resistances.map(z => buildLiquidity9ZoneCard(z, cp, 'resistance')).join('')
        : '<div class="liq9-empty">No resistance zones detected</div>';
    }
  }

  function buildLiquidity9ZoneCard(z, cp, type) {
    const color = type === 'support' ? '#10b981' : '#f43f5e';
    const st = shortSubtype(z);
    const tier = z.tier || 'D';
    const dist = z.distance != null ? z.distance : (cp ? Math.abs(z.price - cp) / cp * 100 : 0);
    const strength = ((z.strength || 0) * 100).toFixed(0);
    const score = (z.score || 0).toFixed(2);

    return `
      <div class="liq9-zone-card ${type}" title="${st} | Strength: ${strength}% | Score: ${score}">
        <div class="liq9-zc-left">
          <span class="liq9-zc-tag" style="background:${color}22;color:${color}">${st}</span>
          <span class="liq9-zc-price" style="color:${color}">$${z.price.toLocaleString('en-US', { minimumFractionDigits: 2 })}</span>
        </div>
        <div class="liq9-zc-right">            <div class="liq9-zc-score-bar">
            <div class="liq9-zc-score-fill" style="width:${Math.min(score * 100, 100)}%;background:${color}"></div>
          </div>
          <span class="liq9-zc-tier" style="color:${color}">${tier}</span>
          <span class="liq9-zc-dist">${dist.toFixed(1)}%</span>
        </div>
      </div>`;
  }

  function switchTab(tabId) {
    state.activeTab = tabId;
    els.tabBtns.forEach(b => b.classList.toggle('active', b.dataset.tab === tabId));
    Object.keys(els.panels).forEach(key => {
      const panel = els.panels[key];
      if (panel) panel.classList.toggle('active', key === tabId);
    });
    setTimeout(() => {
      resizeCharts();
      if ((tabId === 'liquidity9' || tabId === 'institutional' || tabId === 'sr-zones' || tabId === 'depth-flow' || tabId === 'delta-patterns') && state.data) {
        if (tabId === 'liquidity9') updateLiquidity9Panel(state.data);
        if (tabId === 'institutional') startInstitutionalPolling();
        else stopInstitutionalPolling();
        if (tabId === 'sr-zones') updatePriceChart(state.data);
        if (tabId === 'depth-flow') {
          // Re-render all depth chart data when switching to the depth-flow tab
          updateDepthPriceChart(state.data);
          updateDepthCVDChart(state.data);
          updateDepthHistogram(state.data);
          updateImbalanceChart(state.data);
          updateVolumeProfile(state.data);
          updateWallsTable(state.data);
        }
        if (dpc) {
          const w = els.depthPriceChart.clientWidth || 400;
          dpc.applyOptions({ width: w, height: 300 });
          dpc.timeScale().fitContent();
        }
        if (cvcDepth) {
          const w = els.cvdChartDepth.clientWidth || 400;
          cvcDepth.applyOptions({ width: w, height: 300 });
          cvcDepth.timeScale().fitContent();
        }
        if (dhc) {
          const w = els.depthHistChart.clientWidth || 300;
          dhc.applyOptions({ width: w, height: 200 });
          dhc.timeScale().fitContent();
        }
        if (imbChart) {
          const w = els.imbalanceChart.clientWidth || 300;
          imbChart.applyOptions({ width: w, height: 200 });
          imbChart.timeScale().fitContent();
        }
        // No delta chart to resize (using numeric table)
      }
    }, 50);

    // Refresh delta data immediately when switching to Delta Patterns tab
    if (tabId === 'delta-patterns') {
      fetchDeltaLive();
    }
    // Stop institutional polling when leaving that tab
    if (tabId !== 'institutional') {
      stopInstitutionalPolling();
    }
  }


  // ─── Master Update ─────────────────────────────────────────

  function updateUI(data) {
    state.data = data;
    state.scanCount++;
    updateMetrics(data);
    updateZoneList(data);
    updateZoneTable(data);
    renderZoneCards(data);
    updatePriceChart(data);
    updateLiquidity9Panel(data);
    updatePowerMeter(data);
    updateWallsTable(data);
    updateDepthPriceChart(data);
    updateDepthCVDChart(data);
    updateDepthHistogram(data);
    updateImbalanceChart(data);
    updateVolumeProfile(data);
    updateDeltaTable(data);
    updateDeltaPatterns(data);
    updateCacheIndicator(data);
    // Fetch institutional data in background (not blocking)
    fetchInstitutional(state.symbol);
    if (els.updateTime) {
      const now = new Date();
      els.updateTime.textContent = 'Last scan: ' + now.toLocaleTimeString() + '  \u2022 Scan #' + state.scanCount;
    }
  }


  // ─── Delta Live Polling (fast 5s poll for delta data) ─────

  function startDeltaLivePolling() {
    // Always clear existing timer first
    if (state.deltaLivePollTimer) {
      clearInterval(state.deltaLivePollTimer);
      state.deltaLivePollTimer = null;
    }
    // Poll every 5 seconds — ultra lightweight endpoint
    state.deltaLivePollTimer = setInterval(() => {
      if (!state.loading) fetchDeltaLive();
    }, 5000);
    // Fire immediately
    fetchDeltaLive();
  }

  function stopDeltaLivePolling() {
    if (state.deltaLivePollTimer) {
      clearInterval(state.deltaLivePollTimer);
      state.deltaLivePollTimer = null;
    }
  }

  async function fetchDeltaLive() {
    try {
      const r = await fetch('/api/delta-live', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          symbol: state.symbol,
          interval: state.interval,
          forceRefresh: false,
        }),
      });
      const d = await r.json();
      if (d.success) {
        state.deltaData = d;
        // Always update badge count even if on different tab
        if (d.deltaPatterns && d.deltaPatterns.activeCount !== undefined) {
          const count = d.deltaPatterns.activeCount;
          if (els.deltaPatternBadge) {
            els.deltaPatternBadge.textContent = count;
            els.deltaPatternBadge.style.background = count > 0
              ? 'rgba(245,158,11,0.2)'
              : 'rgba(74,84,120,0.2)';
            els.deltaPatternBadge.style.color = count > 0 ? '#f59e0b' : '#4a5478';
          }
        }
        // Check for new patterns and trigger alerts
        checkForNewPatterns(d);

        // Full update if on delta patterns tab
        if (state.activeTab === 'delta-patterns') {
          updateDeltaTable(d);
          updateDeltaPatterns(d);
          if (els.updateTime) {
            const now = new Date();
            els.updateTime.textContent = 'Last scan: ' + now.toLocaleTimeString() + '  • Live Δ';
          }
        }
      }
    } catch (e) {
      // Silently fail — don't spam errors for polling
      if (els.deltaLiveIndicator) {
        els.deltaLiveIndicator.style.background = '#4a5478';
        els.deltaLiveIndicator.style.boxShadow = 'none';
      }
      if (els.deltaLiveLabel) {
        els.deltaLiveLabel.textContent = 'Offline';
        els.deltaLiveLabel.style.color = '#f43f5e';
      }
    }
  }


  // ─── Audio / Visual Alerts for New Delta Patterns ─────────

  // Reusable AudioContext (created once, reused)
  let _alertAudioCtx = null;

  function getAlertAudioCtx() {
    if (!_alertAudioCtx) {
      try {
        _alertAudioCtx = new (window.AudioContext || window.webkitAudioContext)();
      } catch (e) {
        return null;
      }
    }
    return _alertAudioCtx;
  }

  function playAlertSound() {
    try {
      const ctx = getAlertAudioCtx();
      if (!ctx) return;

      // Resume if suspended (browser autoplay policy)
      if (ctx.state === 'suspended') ctx.resume();

      const now = ctx.currentTime;
      // "Intezaar Hogayi Intezaar Ki" inspired melody
      // Melodic phrase: A4 -> C5 -> B4 -> A4 -> G4 -> F4 -> E4 (descending resolution)
      const melody = [
        { freq: 440.00, time: 0,      dur: 0.18 },  // A4  - "in"
        { freq: 523.25, time: 0.15,   dur: 0.22 },  // C5  - "te"
        { freq: 493.88, time: 0.35,   dur: 0.20 },  // B4  - "zaar"
        { freq: 440.00, time: 0.55,   dur: 0.25 },  // A4  - "ho"
        { freq: 392.00, time: 0.75,   dur: 0.20 },  // G4  - "ga"
        { freq: 349.23, time: 0.95,   dur: 0.22 },  // F4  - "yi"
        { freq: 329.63, time: 1.15,   dur: 0.35 },  // E4  - "ki" (final resolution)
      ];

      melody.forEach(note => {
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.type = 'sine';
        osc.frequency.value = note.freq;
        gain.gain.setValueAtTime(0, now + note.time);
        gain.gain.linearRampToValueAtTime(0.08, now + note.time + 0.02);
        gain.gain.exponentialRampToValueAtTime(0.001, now + note.time + note.dur);
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.start(now + note.time);
        osc.stop(now + note.time + note.dur + 0.01);
      });
    } catch (e) {
      // Audio not supported — silently ignore
    }
  }

  function showDeltaAlert(pattern) {
    const sigPct = ((pattern.significance || 0) * 100).toFixed(0);
    const isBull = pattern.direction === 'bullish';
    const dirEmoji = isBull ? '🟢' : '🔴';
    const dirText = isBull ? 'Bullish' : 'Bearish';
    const borderColor = isBull ? '#10b981' : '#f43f5e';
    const pClass = 'dp-p' + pattern.pattern;

    // Stack multiple alerts with vertical offset
    state.alertCount++;
    const topOffset = 20 + (state.alertCount % 5) * 82;

    const el = document.createElement('div');
    el.className = 'dp-alert-toast';
    el.style.top = topOffset + 'px';

    const inner = document.createElement('div');
    inner.className = 'dpat-inner';
    inner.style.borderLeftColor = borderColor;

    inner.innerHTML = `
      <div class="dpat-header">
        <span class="dpat-icon">${dirEmoji}</span>
        <span class="dpat-pattern-badge ${pClass}">P${pattern.pattern}</span>
        <span class="dpat-title">${pattern.name}</span>
        <span class="dpat-close">×</span>
      </div>
      <div class="dpat-body">
        <span class="dpat-dir" style="color:${borderColor}">${dirText}</span>
        <span class="dpat-sig" style="color:${sigPct >= 70 ? '#10b981' : '#f59e0b'}">${sigPct}% significance</span>
      </div>
      <div class="dpat-desc">${pattern.description}</div>
    `;

    el.appendChild(inner);
    document.body.appendChild(el);

    // Close button with proper event listener
    const closeBtn = el.querySelector('.dpat-close');
    if (closeBtn) {
      closeBtn.addEventListener('click', () => {
        el.style.opacity = '0';
        el.style.transform = 'translateX(100%)';
        el.style.transition = 'all 0.3s ease';
        setTimeout(() => el.remove(), 300);
      });
    }

    // Auto-dismiss after 5 seconds
    const dismissTimer = setTimeout(() => {
      el.style.opacity = '0';
      el.style.transform = 'translateX(100%)';
      el.style.transition = 'all 0.4s ease';
      setTimeout(() => el.remove(), 400);
    }, 5000);

    // Store timer on element so close button can cancel it
    el._dismissTimer = dismissTimer;

    // Cancel auto-dismiss on hover
    el.addEventListener('mouseenter', () => {
      clearTimeout(el._dismissTimer);
      el.style.transition = 'none';
      el.style.opacity = '1';
      el.style.transform = 'translateX(0)';
    });

    // Restart auto-dismiss on mouse leave
    el.addEventListener('mouseleave', () => {
      el._dismissTimer = setTimeout(() => {
        el.style.opacity = '0';
        el.style.transform = 'translateX(100%)';
        el.style.transition = 'all 0.4s ease';
        setTimeout(() => el.remove(), 400);
      }, 3000);
    });
  }

  function getPatternKey(pattern) {
    return pattern.pattern + '-' + pattern.direction;
  }

  function checkForNewPatterns(deltaData) {
    const patterns = deltaData?.deltaPatterns?.patterns || [];
    if (!patterns.length) {
      // No active patterns — reset state so patterns can re-alert later
      state.previousPatternKeys = null;
      return;
    }

    const currentKeys = new Set(patterns.map(getPatternKey));

    if (!state.previousPatternKeys) {
      // First poll — just record patterns, don't alert
      state.previousPatternKeys = currentKeys;
      return;
    }

    // Find patterns that are in current but were NOT in previous poll (fresh appearance)
    const newPatterns = patterns.filter(p => {
      const key = getPatternKey(p);
      return !state.previousPatternKeys.has(key);
    });

    if (newPatterns.length > 0) {
      playAlertSound();
      newPatterns.forEach(p => {
        showDeltaAlert(p);
        // Also trigger alerts via backend
        sendEmailAlert(p);
        sendTelegramAlert(p);
      });
    }

    // Update previous state for next poll comparison
    state.previousPatternKeys = currentKeys;
  }

  async function sendEmailAlert(pattern) {
    try {
      await fetch('/api/send-email-alert', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          pattern: pattern,
          symbol: state.symbol,
          interval: state.interval,
        }),
      });
      // Fire-and-forget — don't block the UI
    } catch (e) {
      // Silently fail — email is best-effort
    }
  }

  async function sendTelegramAlert(pattern) {
    try {
      await fetch('/api/send-telegram-alert', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          pattern: pattern,
          symbol: state.symbol,
          interval: state.interval,
        }),
      });
      // Fire-and-forget — don't block the UI
    } catch (e) {
      // Silently fail — Telegram is best-effort
    }
  }

  async function sendTestTelegram() {
    const btn = document.getElementById('liq9TestTelegramBtn');
    if (!btn) return;
    btn.disabled = true;
    btn.classList.add('sending');
    btn.innerHTML = '<span class="spinner" style="width:10px;height:10px;border-width:1.5px"></span> Sending...';
    try {
      const r = await fetch('/api/telegram/test');
      const d = await r.json();
      if (d.success && d.sent) {
        showToast('✅ ' + d.message, '#10b981');
      } else {
        showToast('❌ ' + (d.error || 'Failed to send'), '#f43f5e', 6000);
        if (d.hint) showToast('💡 ' + d.hint, '#f59e0b', 6000);
      }
    } catch (e) {
      showToast('❌ Connection error — is the server running?', '#f43f5e');
    } finally {
      btn.disabled = false;
      btn.classList.remove('sending');
      btn.innerHTML = `
        <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
          <path d="M11.944 0A12 12 0 000 12a12 12 0 0012 12 12 12 0 0012-12A12 12 0 0012 0a12 12 0 00-.056 0zm4.962 7.224c.1-.002.321.023.465.14a.506.506 0 01.171.325c.016.093.036.306.02.472-.18 1.898-.962 6.502-1.36 8.627-.168.9-.499 1.201-.82 1.23-.696.065-1.225-.46-1.9-.902-1.056-.693-1.653-1.124-2.678-1.8-1.185-.78-.417-1.21.258-1.91.177-.184 3.247-2.977 3.307-3.23.007-.032.014-.15-.056-.212s-.174-.041-.249-.024c-.106.024-1.793 1.14-5.061 3.345-.48.33-.913.49-1.302.48-.428-.008-1.252-.241-1.865-.44-.752-.245-1.349-.374-1.297-.789.027-.216.325-.437.893-.663 3.498-1.524 5.83-2.529 6.998-3.014 3.332-1.386 4.025-1.627 4.476-1.635z"/>
        </svg>
        Test Telegram`;
    }
  }

  function showToast(msg, color = '#10b981', duration = 4000) {
    const existing = document.querySelector('.liq9-toast');
    if (existing) existing.remove();
    const t = document.createElement('div');
    t.className = 'liq9-toast';
    t.textContent = msg;
    Object.assign(t.style, {
      position: 'fixed', bottom: '20px', right: '20px', zIndex: '99999',
      background: color, color: '#fff',
      padding: '10px 18px', borderRadius: '6px', fontSize: '12px',
      fontWeight: '600', maxWidth: '400px',
      boxShadow: `0 4px 20px ${color}44`,
      animation: 'slideInRight 0.3s ease-out',
    });
    document.body.appendChild(t);
    setTimeout(() => {
      t.style.opacity = '0';
      t.style.transition = 'opacity 0.3s';
      setTimeout(() => t.remove(), 300);
    }, duration);
  }


  // ─── Auto-Refresh ──────────────────────────────────────────

  function updateAutoRefresh() {
    if (state.autoRefreshTimer) {
      clearInterval(state.autoRefreshTimer);
      state.autoRefreshTimer = null;
    }
    const secs = parseInt(els.autoRefreshSelect.value, 10);
    if (secs > 0) {
      state.autoRefreshTimer = setInterval(() => {
        if (!state.loading) runScan(false);
      }, secs * 1000);
    }
  }


  // ─── API ───────────────────────────────────────────────────

  async function runScan(forceRefresh = true) {
    if (state.loading) return;
    state.loading = true;
    els.scanBtn.classList.add('loading');
    els.scanBtn.innerHTML = '<span class="spinner"></span> Scanning';
    if (els.refreshBtn) {
      els.refreshBtn.classList.add('loading');
      els.refreshBtn.disabled = true;
    }
    try {
      const r = await fetch('/api/quick-scan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          symbol: state.symbol,
          interval: state.interval,
          forceRefresh: forceRefresh,
        }),
      });
      const d = await r.json();
      if (d.success) {
        updateUI(d);
      } else {
        showError(d.error || 'Scan failed');
      }
    } catch (e) {
      showError('Connection error \u2014 is the server running?');
    } finally {
      state.loading = false;
      els.scanBtn.classList.remove('loading');
      els.scanBtn.textContent = 'Scan Now';
      if (els.refreshBtn) {
        els.refreshBtn.classList.remove('loading');
        els.refreshBtn.disabled = false;
      }
    }
  }

  function showError(msg) {
    const existing = document.querySelector('.error-toast');
    if (existing) existing.remove();
    const t = document.createElement('div');
    t.className = 'error-toast';
    t.textContent = msg;
    Object.assign(t.style, {
      position: 'fixed', bottom: '20px', right: '20px',
      background: '#f43f5e', color: '#fff',
      padding: '10px 18px', borderRadius: '6px', fontSize: '12px',
      zIndex: '9999', boxShadow: '0 4px 20px rgba(244,63,94,0.3)',
    });
    document.body.appendChild(t);
    setTimeout(() => {
      t.style.opacity = '0';
      t.style.transition = 'opacity 0.3s';
      setTimeout(() => t.remove(), 300);
    }, 4000);
  }


  // ─── Events ────────────────────────────────────────────────

  function bindEvents() {
    // Main scan button
    els.scanBtn.addEventListener('click', () => runScan(true));

    // Refresh button (force refresh)
    if (els.refreshBtn) {
      els.refreshBtn.addEventListener('click', () => runScan(true));
    }

    // Auto-refresh interval change
    if (els.autoRefreshSelect) {
      els.autoRefreshSelect.addEventListener('change', updateAutoRefresh);
    }

    // Symbol/Interval change triggers scan
    els.symbol.addEventListener('change', () => {
      state.symbol = els.symbol.value;
      runScan(true);
    });
    els.interval.addEventListener('change', () => {
      state.interval = els.interval.value;
      runScan(true);
    });

    // Tab switching
    els.tabBtns.forEach(b => b.addEventListener('click', () => switchTab(b.dataset.tab)));

    // Zone filter buttons
    els.filterBtns.forEach(b => b.addEventListener('click', () => {
      els.filterBtns.forEach(x => x.classList.remove('active'));
      b.classList.add('active');
      state.filter = b.dataset.f;
      if (state.data) {
        updateZoneList(state.data);
        renderZoneCards(state.data);
      }
    }));

    // Keyboard shortcut: R or r to refresh
    document.addEventListener('keydown', (e) => {
      // Only if not typing in an input/select
      const tag = e.target.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
      if (e.key === 'r' || e.key === 'R') {
        e.preventDefault();
        runScan(true);
      }
    });

    // Telegram test button
    const testTgBtn = document.getElementById('liq9TestTelegramBtn');
    if (testTgBtn) {
      testTgBtn.addEventListener('click', sendTestTelegram);
    }

    // Window resize
    window.addEventListener('resize', resizeCharts);

    // Indian stock search (with debounce)
    let inSearchTimer = null;
    if (els.inStockSearch) {
      els.inStockSearch.addEventListener('input', (e) => {
        const q = e.target.value.trim();
        if (q.length < 1) {
          els.inSearchResults.style.display = 'none';
          return;
        }
        if (inSearchTimer) clearTimeout(inSearchTimer);
        inSearchTimer = setTimeout(() => searchIndianStocks(q), 200);
      });
      els.inStockSearch.addEventListener('blur', () => {
        setTimeout(() => { els.inSearchResults.style.display = 'none'; }, 200);
      });
      els.inStockSearch.addEventListener('focus', () => {
        if (els.inSearchResults.children.length) {
          els.inSearchResults.style.display = 'block';
        }
      });
    }

    // Indian stock scan button
    if (els.inScanBtn) {
      els.inScanBtn.addEventListener('click', () => scanIndianStock(true));
    }

    // Indian stock interval change
    if (els.inIntervalSelect) {
      els.inIntervalSelect.addEventListener('change', () => {
        if (state.inSelectedStock) {
          scanIndianStock(true);
        }
      });
    }
  } // ← closes bindEvents()


  // ─── Init ──────────────────────────────────────────────────

  function init() {
    initCharts();
    initLiquidity9Chart();
    initInstitutionalCharts();
    initIndianCharts();
    bindEvents();
    resizeCharts();
    updateAutoRefresh();
    // Start delta live polling immediately (fast 5s updates)
    startDeltaLivePolling();
    // Initial scan with retry if server not ready
    setTimeout(() => runScan(true), 800);
    // Retry once after 4s if the first scan didn't succeed
    setTimeout(() => {
      if (!state.data && !state.loading) {
        runScan(true);
      }
    }, 4000);
  }

  document.readyState === 'loading'
    ? document.addEventListener('DOMContentLoaded', init)
    : init();

})();
