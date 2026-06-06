import { useState, useEffect, useRef, useCallback } from 'react';

// ─── Mock Data Generators ──────────────────────────────────
const generateChartData = (points = 80) => {
  const data = [];
  let price = 48250 + Math.random() * 300;
  for (let i = 0; i < points; i++) {
    const change = (Math.random() - 0.48) * price * 0.008;
    price += change;
    data.push({
      time: Date.now() - (points - i) * 300000,
      open: data[i - 1]?.close ?? price,
      close: price,
      high: price + Math.random() * price * 0.005,
      low: price - Math.random() * price * 0.005,
      volume: 50 + Math.random() * 200,
    });
  }
  return data;
};

const ASSETS = [
  { symbol: 'BTC/USD', name: 'Bitcoin', qty: 2.45, price: 48320.50, change: 2.34, color: '#F59E0B' },
  { symbol: 'ETH/USD', name: 'Ethereum', qty: 18.7, price: 3750.80, change: -0.87, color: '#8B5CF6' },
  { symbol: 'SOL/USD', name: 'Solana', qty: 120.0, price: 142.30, change: 5.12, color: '#10B981' },
  { symbol: 'LINK/USD', name: 'Chainlink', qty: 450, price: 18.45, change: 1.56, color: '#3B82F6' },
  { symbol: 'AVAX/USD', name: 'Avalanche', qty: 85.0, price: 38.20, change: -2.10, color: '#EF4444' },
];

const TOTAL_PORTFOLIO = ASSETS.reduce((sum, a) => sum + a.qty * a.price, 0);
const PORTFOLIO_CHANGE = 3.42;
const INITIAL_CHART = generateChartData();

// ─── Price Roll-up Digit (Luxury Slot Machine Effect) ──────
function RollingDigit({ digit, prevDigit, up }) {
  const elRef = useRef(null);
  const [animPhase, setAnimPhase] = useState('idle');
  const direction = up ? -1 : 1;

  useEffect(() => {
    if (prevDigit !== digit) {
      setAnimPhase('exiting');
      const t = setTimeout(() => setAnimPhase('idle'), 500);
      return () => clearTimeout(t);
    }
  }, [digit, prevDigit]);

  // When idle, render the current digit plainly — no animation overhead
  if (animPhase === 'idle') {
    return (
      <span ref={elRef} className="inline-block tabular-nums w-[0.6em] text-center" style={{ fontVariantNumeric: 'tabular-nums' }}>
        {digit}
      </span>
    );
  }

  return (
    <span className="inline-block tabular-nums relative overflow-hidden h-[1em] w-[0.6em] text-center" style={{ fontVariantNumeric: 'tabular-nums' }}>
      {/* Old digit slides out */}
      <span
        className={`absolute inset-0 flex items-center justify-center transition-all duration-[450ms] opacity-0 ${direction < 0 ? '-translate-y-full' : 'translate-y-full'}`}
        style={{ transitionTimingFunction: 'cubic-bezier(0.16, 1, 0.3, 1)' }}
      >
        {prevDigit}
      </span>
      {/* New digit in final position (appears instantly, no transition needed) */}
      <span className="absolute inset-0 flex items-center justify-center opacity-100 translate-y-0">
        {digit}
      </span>
    </span>
  );
}

function AnimatedPrice({ value, prevValue, prefix = '', suffix = '', decimals = 2, className = '' }) {
  const parts = (value || 0).toFixed(decimals).split('');
  const prevParts = (prevValue || 0).toFixed(decimals).split('');
  const up = value >= prevValue;

  return (
    <span className={`inline-flex items-baseline gap-0 ${className} ${up ? 'text-emerald-400' : 'text-cherry-50'}`}>
      {prefix}
      {parts.map((ch, i) =>
        ch === '.' ? (
          <span key={i} className="opacity-50">.</span>
        ) : (
          <RollingDigit key={i} digit={ch} prevDigit={prevParts[i]} up={up} />
        )
      )}
      {suffix}
    </span>
  );
}

// ─── Particle Burst ────────────────────────────────────────
function ParticleBurst({ x, y, color = '#10B981' }) {
  const particles = Array.from({ length: 20 }, (_, i) => {
    const angle = (i / 20) * Math.PI * 2;
    const dist = 40 + Math.random() * 60;
    return {
      id: i,
      dx: Math.cos(angle) * dist,
      dy: Math.sin(angle) * dist,
      size: 2 + Math.random() * 4,
      delay: Math.random() * 0.1,
      color: i % 5 === 0 ? '#F59E0B' : color,
    };
  });

  return (
    <div className="fixed pointer-events-none z-50" style={{ left: x, top: y }}>
      {particles.map((p) => (
        <div
          key={p.id}
          className="absolute rounded-full"
          style={{
            width: p.size,
            height: p.size,
            background: p.color,
            boxShadow: `0 0 6px ${p.color}`,
            '--dx': `${p.dx}px`,
            '--dy': `${p.dy}px`,
            animation: `particle-fly 0.7s cubic-bezier(0.16, 1, 0.3, 1) ${p.delay}s forwards`,
            left: 0,
            top: 0,
          }}
        />
      ))}
    </div>
  );
}

// ─── Main Price Chart ──────────────────────────────────────
function PriceChart({ data, width = 640, height = 280 }) {
  const pad = { t: 16, r: 16, b: 28, l: 56 };
  const w = width - pad.l - pad.r;
  const h = height - pad.t - pad.b;

  const closes = data.map(d => d.close);
  const mx = Math.max(...data.map(d => d.high));
  const mn = Math.min(...data.map(d => d.low));
  const range = mx - mn || 1;

  const lastClose = closes[closes.length - 1];
  const prevClose = closes[closes.length - 2];
  const isUp = lastClose >= prevClose;
  const lineColor = isUp ? '#10B981' : '#DC2626';

  const xScale = (i) => pad.l + (i / (data.length - 1)) * w;
  const yScale = (v) => pad.t + h - ((v - mn) / range) * h;

  const gridLines = 5;
  const gridYs = Array.from({ length: gridLines }, (_, i) => pad.t + (h / (gridLines - 1)) * i);
  const gridLabels = gridYs.map(y => mn + ((pad.t + h - y) / h) * range);

  const areaPath = data.map((d, i) => `${i === 0 ? 'M' : 'L'}${xScale(i)},${yScale(d.close)}`).join(' ') +
    ` L${xScale(data.length - 1)},${pad.t + h} L${pad.l},${pad.t + h} Z`;

  const linePath = data.map((d, i) => `${i === 0 ? 'M' : 'L'}${xScale(i)},${yScale(d.close)}`).join(' ');

  const candleInterval = Math.max(1, Math.floor(data.length / 30));
  const candlesticks = data.filter((_, i) => i % candleInterval === 0).map(d => ({
    ...d,
    x: xScale(data.indexOf(d)),
    bear: d.close < d.open,
  }));

  const timeLabels = [0, Math.floor(data.length / 2), data.length - 1].map(i => ({
    x: xScale(i),
    label: new Date(data[i].time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
  }));

  return (
    <svg width={width} height={height} className="w-full h-full">
      <defs>
        <linearGradient id="areaGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={lineColor} stopOpacity="0.18" />
          <stop offset="100%" stopColor={lineColor} stopOpacity="0" />
        </linearGradient>
        <filter id="glow">
          <feGaussianBlur stdDeviation="2" result="blur" />
          <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
        </filter>
      </defs>

      {gridYs.map((y, i) => (
        <g key={i}>
          <line x1={pad.l} y1={y} x2={pad.l + w} y2={y} stroke="rgba(255,255,255,0.04)" strokeWidth="1" />
          <text x={pad.l - 8} y={y + 4} textAnchor="end" fill="rgba(255,255,255,0.3)" fontSize="10" fontFamily="Inter, sans-serif">
            ${gridLabels[i].toFixed(0)}
          </text>
        </g>
      ))}

      {timeLabels.map((t, i) => (
        <text key={i} x={t.x} y={pad.t + h + 18} textAnchor="middle" fill="rgba(255,255,255,0.3)" fontSize="10" fontFamily="Inter, sans-serif">
          {t.label}
        </text>
      ))}

      <path d={areaPath} fill="url(#areaGrad)" />
      <path d={linePath} fill="none" stroke={lineColor} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" filter="url(#glow)" />

      {candlesticks.slice(-40).map((c, i) => (
        <g key={i}>
          <line x1={c.x} y1={yScale(c.high)} x2={c.x} y2={yScale(c.low)} stroke={c.bear ? '#DC2626' : '#10B981'} strokeWidth="1" opacity="0.5" />
          <rect x={c.x - 2} y={yScale(Math.max(c.open, c.close))} width="4" height={Math.max(1, Math.abs(yScale(c.open) - yScale(c.close)))} fill={c.bear ? '#DC2626' : '#10B981'} rx="1" />
        </g>
      ))}

      <rect x={pad.l + w - 90} y={pad.t - 4} width="90" height="20" rx="4" fill="rgba(16,185,129,0.12)" />
      <text x={pad.l + w - 8} y={pad.t + 10} textAnchor="end" fill="#10B981" fontSize="11" fontWeight="600" fontFamily="Inter, sans-serif">
        ${lastClose.toFixed(2)}
      </text>
    </svg>
  );
}

// ─── Mini Donut ────────────────────────────────────────────
function MiniDonut({ percentage, color = '#10B981', size = 48 }) {
  const r = size / 2 - 3;
  const circ = 2 * Math.PI * r;
  const offset = circ * (1 - percentage / 100);

  return (
    <svg width={size} height={size} className="shrink-0">
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth="3" />
      <circle
        cx={size / 2} cy={size / 2} r={r}
        fill="none" stroke={color} strokeWidth="3"
        strokeDasharray={circ}
        strokeDashoffset={offset}
        strokeLinecap="round"
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
        style={{ transition: 'stroke-dashoffset 0.8s cubic-bezier(0.16, 1, 0.3, 1)' }}
      />
      <text x={size / 2} y={size / 2} textAnchor="middle" dominantBaseline="central" fill="#F3F4F6" fontSize="10" fontWeight="600" fontFamily="Inter, sans-serif">
        {percentage}%
      </text>
    </svg>
  );
}

// ─── Main App ──────────────────────────────────────────────
export default function App() {
  const [chartData, setChartData] = useState(INITIAL_CHART);
  const prevPriceRef = useRef(INITIAL_CHART[INITIAL_CHART.length - 1].close);
  const [particles, setParticles] = useState([]);
  const [tradeAmount, setTradeAmount] = useState('1.0');
  const [tradeType, setTradeType] = useState('buy');
  const [orderStatus, setOrderStatus] = useState(null);
  const [selectedAsset, setSelectedAsset] = useState('BTC/USD');
  const [activeTab, setActiveTab] = useState('portfolio');
  const chartContainerRef = useRef(null);
  const [chartWidth, setChartWidth] = useState(640);
  const particleIdRef = useRef(0);
  const orderTimersRef = useRef([]);

  // Live price simulation — updates both chartData and prevPriceRef atomically
  useEffect(() => {
    const interval = setInterval(() => {
      setChartData(prev => {
        const last = prev[prev.length - 1];
        prevPriceRef.current = last.close;
        const change = (Math.random() - 0.48) * last.close * 0.002;
        const newClose = last.close + change;
        return [...prev.slice(1), {
          time: Date.now(),
          open: last.close,
          close: newClose,
          high: Math.max(last.high, newClose),
          low: Math.min(last.low, newClose),
          volume: 50 + Math.random() * 100,
        }];
      });
    }, 3000);
    return () => clearInterval(interval);
  }, []);

  // Responsive chart width
  useEffect(() => {
    const resize = () => {
      if (chartContainerRef.current) {
        setChartWidth(chartContainerRef.current.clientWidth);
      }
    };
    resize();
    window.addEventListener('resize', resize);
    return () => window.removeEventListener('resize', resize);
  }, []);

  const currentPrice = chartData[chartData.length - 1]?.close ?? 0;

  // Trade execution with safe particle cleanup by id
  const executeTrade = useCallback((e) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const cx = rect.left + rect.width / 2;
    const cy = rect.top + rect.height / 2;
    const pid = particleIdRef.current++;

    setParticles(prev => [...prev, { id: pid, x: cx, y: cy, color: tradeType === 'buy' ? '#10B981' : '#DC2626' }]);
    setOrderStatus('executing');

    // Track timeouts for cleanup
    const t1 = setTimeout(() => setOrderStatus('filled'), 800);
    const t2 = setTimeout(() => setOrderStatus(null), 2500);
    const t3 = setTimeout(() => {
      setParticles(prev => prev.filter(p => p.id !== pid));
    }, 3000);

    orderTimersRef.current.push(t1, t2, t3);
  }, [tradeType]);

  return (
    <div className="min-h-screen bg-obsidian text-[#F3F4F6] overflow-x-hidden">
      {/* Particles */}
      {particles.map(p => <ParticleBurst key={p.id} x={p.x} y={p.y} color={p.color} />)}

      {/* ═══ HEADER ═══ */}
      <header className="sticky top-0 z-40 glass border-b border-white/[0.04]">
        <div className="max-w-7xl mx-auto px-6 h-14 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-gold to-lavender flex items-center justify-center shadow-lg shadow-lavender/20">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#0B0C10" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
              </svg>
            </div>
            <div>
              <h1 className="text-base font-bold tracking-tight">ALPHA</h1>
              <p className="text-[10px] text-silver tracking-[0.15em] uppercase -mt-0.5">Terminal</p>
            </div>
          </div>

          <nav className="hidden md:flex items-center gap-1">
            {['Portfolio', 'Markets', 'Trading', 'Analytics'].map(tab => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab.toLowerCase())}
                className={`px-4 py-1.5 rounded-lg text-xs font-medium tracking-wide transition-all ${
                  activeTab === tab.toLowerCase()
                    ? 'bg-white/8 text-white'
                    : 'text-silver hover:text-white hover:bg-white/4'
                }`}
              >
                {tab}
              </button>
            ))}
          </nav>

          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-white/4 border border-white/6">
              <div className="w-2 h-2 rounded-full bg-emerald shadow-[0_0_6px_rgba(16,185,129,0.5)] animate-pulse" />
              <span className="text-xs text-silver font-medium">Live</span>
            </div>
            <div className="w-8 h-8 rounded-full bg-gradient-to-br from-gold to-lavender flex items-center justify-center text-[11px] font-bold text-obsidian shadow-lg">
              JD
            </div>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-6 py-8">
        {/* ═══ TOP ROW ═══ */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-8 animate-fade-in">
          {/* Portfolio Card */}
          <div className="lg:col-span-2 glow-gold glow-gold-strong">
            <div className="glass-strong rounded-2xl p-8 relative overflow-hidden">
              <div className="absolute -top-32 -right-32 w-64 h-64 rounded-full bg-gold/5 blur-[100px]" />
              <div className="absolute -bottom-32 -left-32 w-64 h-64 rounded-full bg-lavender/5 blur-[100px]" />

              <div className="relative z-10">
                <div className="flex items-start justify-between mb-6">
                  <div>
                    <p className="text-xs text-silver/70 uppercase tracking-[0.15em] font-medium mb-1">Total Portfolio Value</p>
                    <h2 className="text-4xl md:text-5xl font-bold tracking-tight text-white">
                      <AnimatedPrice value={TOTAL_PORTFOLIO} prevValue={TOTAL_PORTFOLIO - PORTFOLIO_CHANGE * 50} prefix="$" decimals={0} />
                    </h2>
                    <div className="flex items-center gap-2 mt-2 text-emerald-400">
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                        <polyline points="18 15 12 9 6 15" />
                      </svg>
                      <span className="text-lg font-semibold tabular-nums">+{PORTFOLIO_CHANGE}%</span>
                      <span className="text-xs text-silver/50">+$1,842.50 today</span>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="px-3 py-1.5 rounded-lg bg-emerald/10 border border-emerald/20">
                      <span className="text-xs font-semibold text-emerald-50">+3.42%</span>
                    </div>
                    <div className="w-2 h-2 rounded-full bg-emerald animate-pulse shadow-[0_0_8px_rgba(16,185,129,0.4)]" />
                  </div>
                </div>

                <div className="grid grid-cols-3 gap-6 mt-8 pt-6 border-t border-white/6">
                  <div>
                    <p className="text-[11px] text-silver/50 uppercase tracking-wider mb-1">Day Volume</p>
                    <p className="text-sm font-semibold text-white tabular-nums">$2.84M</p>
                  </div>
                  <div>
                    <p className="text-[11px] text-silver/50 uppercase tracking-wider mb-1">Open Positions</p>
                    <p className="text-sm font-semibold text-white">12</p>
                  </div>
                  <div>
                    <p className="text-[11px] text-silver/50 uppercase tracking-wider mb-1">Win Rate</p>
                    <p className="text-sm font-semibold text-emerald-50 tabular-nums">68.4%</p>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Quick Stats */}
          <div className="grid grid-cols-2 gap-4">
            {[
              { label: 'BTC Dominance', value: '52.3%', change: '+1.2%', color: 'text-gold-50' },
              { label: 'Market Sentiment', value: 'Greed', change: '72', color: 'text-emerald-50' },
              { label: 'Gas (Gwei)', value: '24.5', change: '-3.1%', color: 'text-ocean-50' },
              { label: 'Open Interest', value: '$18.2B', change: '+2.8%', color: 'text-lavender-50' },
            ].map((stat) => (
              <div key={stat.label} className="glass rounded-xl p-5 flex flex-col justify-between hover:bg-white/[0.03] transition-all duration-300">
                <p className="text-[11px] text-silver/50 uppercase tracking-wider">{stat.label}</p>
                <div>
                  <p className="text-lg font-bold text-white tabular-nums mt-1">{stat.value}</p>
                  <p className={`text-xs font-medium ${stat.change.startsWith('+') ? 'text-emerald-50' : 'text-cherry-50'}`}>{stat.change}</p>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* ═══ MIDDLE ROW ═══ */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-8">
          {/* Chart */}
          <div className="lg:col-span-2 glass rounded-2xl p-6 animate-slide-up" style={{ animationDelay: '0.1s' }}>
            <div className="flex items-center justify-between mb-5">
              <div className="flex items-center gap-3">
                <h3 className="text-sm font-semibold text-white">{selectedAsset}</h3>
                <span className="text-2xl font-bold tabular-nums text-white">
                  <AnimatedPrice value={currentPrice} prevValue={prevPriceRef.current} prefix="$" decimals={2} />
                </span>
                <span className={`text-xs font-medium px-2 py-0.5 rounded ${
                  currentPrice >= prevPriceRef.current
                    ? 'bg-emerald/10 text-emerald-50'
                    : 'bg-cherry/10 text-cherry-50'
                }`}>
                  {currentPrice >= prevPriceRef.current ? '+' : ''}{((currentPrice - prevPriceRef.current) / prevPriceRef.current * 100).toFixed(2)}%
                </span>
              </div>
              <div className="flex items-center gap-2">
                {['1H', '4H', '1D', '1W'].map(p => (
                  <button key={p} className="px-2.5 py-1 rounded-md text-[11px] font-medium text-silver hover:text-white hover:bg-white/6 transition-all">{p}</button>
                ))}
              </div>
            </div>
            <div ref={chartContainerRef} className="w-full">
              <PriceChart data={chartData} width={chartWidth} />
            </div>
          </div>

          {/* Asset List */}
          <div className="glass rounded-2xl p-6 animate-slide-up" style={{ animationDelay: '0.2s' }}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-semibold text-white">Holdings</h3>
              <span className="text-[11px] text-silver/50">5 assets</span>
            </div>
            <div className="space-y-2.5">
              {ASSETS.map((asset) => {
                const val = asset.qty * asset.price;
                const allocation = (val / TOTAL_PORTFOLIO) * 100;
                return (
                  <button
                    key={asset.symbol}
                    onClick={() => setSelectedAsset(asset.symbol)}
                    className={`w-full flex items-center gap-3 p-3 rounded-xl transition-all duration-200 ${
                      selectedAsset === asset.symbol
                        ? 'bg-white/8 border border-white/10'
                        : 'hover:bg-white/4 border border-transparent'
                    }`}
                  >
                    <div className="w-8 h-8 rounded-lg flex items-center justify-center text-[13px] font-bold shrink-0" style={{ background: `${asset.color}18`, color: asset.color }}>
                      {asset.symbol.slice(0, 3)}
                    </div>
                    <div className="flex-1 min-w-0 text-left">
                      <p className="text-sm font-semibold text-white truncate">{asset.symbol}</p>
                      <p className="text-[11px] text-silver/50">{asset.qty} {asset.name}</p>
                    </div>
                    <div className="text-right">
                      <p className="text-sm font-semibold text-white tabular-nums">${val.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}</p>
                      <div className="flex items-center gap-1 justify-end">
                        <span className={`text-[11px] font-medium ${asset.change >= 0 ? 'text-emerald-50' : 'text-cherry-50'}`}>
                          {asset.change >= 0 ? '+' : ''}{asset.change}%
                        </span>
                        <MiniDonut percentage={Math.round(allocation)} color={asset.color} size={16} />
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>
          </div>
        </div>

        {/* ═══ BOTTOM ROW ═══ */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Trade Panel */}
          <div className="glass rounded-2xl p-6 animate-slide-up" style={{ animationDelay: '0.3s' }}>
            <div className="flex items-center justify-between mb-5">
              <h3 className="text-sm font-semibold text-white">Quick Trade</h3>
              <div className="flex bg-white/6 rounded-lg p-0.5">
                <button
                  onClick={() => setTradeType('buy')}
                  className={`px-4 py-1 rounded-md text-xs font-semibold transition-all ${
                    tradeType === 'buy' ? 'bg-emerald text-white shadow-sm' : 'text-silver hover:text-white'
                  }`}
                >
                  Buy
                </button>
                <button
                  onClick={() => setTradeType('sell')}
                  className={`px-4 py-1 rounded-md text-xs font-semibold transition-all ${
                    tradeType === 'sell' ? 'bg-cherry text-white shadow-sm' : 'text-silver hover:text-white'
                  }`}
                >
                  Sell
                </button>
              </div>
            </div>

            <div className="space-y-4">
              <div>
                <p className="text-[11px] text-silver/50 uppercase tracking-wider mb-1.5">Asset</p>
                <select
                  value={selectedAsset}
                  onChange={e => setSelectedAsset(e.target.value)}
                  className="w-full bg-white/6 border border-white/8 rounded-xl px-4 py-2.5 text-sm text-white font-medium outline-none focus:border-gold/30 transition-all appearance-none cursor-pointer"
                  style={{ backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%239CA3AF' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolyline points='6 9 12 15 18 9'/%3E%3C/svg%3E")`, backgroundRepeat: 'no-repeat', backgroundPosition: 'right 12px center' }}
                >
                  {ASSETS.map(a => (
                    <option key={a.symbol} value={a.symbol} className="bg-obsidian-200">{a.symbol}</option>
                  ))}
                </select>
              </div>

              <div>
                <p className="text-[11px] text-silver/50 uppercase tracking-wider mb-1.5">Amount</p>
                <div className="relative">
                  <input
                    type="text"
                    inputMode="decimal"
                    value={tradeAmount}
                    onChange={e => {
                      const val = e.target.value;
                      if (/^\d*\.?\d*$/.test(val) || val === '') setTradeAmount(val);
                    }}
                    className="w-full bg-white/6 border border-white/8 rounded-xl px-4 py-2.5 text-sm text-white font-semibold outline-none focus:border-gold/30 transition-all tabular-nums"
                  />
                  <span className="absolute right-3 top-1/2 -translate-y-1/2 text-[11px] text-silver/50 font-medium">{selectedAsset.split('/')[0]}</span>
                </div>
              </div>

              <div className="flex items-center justify-between px-1">
                <span className="text-xs text-silver/50">Est. Value</span>
                <span className="text-sm font-semibold text-white tabular-nums">
                  ${(parseFloat(tradeAmount || 0) * currentPrice).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                </span>
              </div>

              <button
                onClick={executeTrade}
                disabled={orderStatus === 'executing'}
                className={`w-full py-3 rounded-xl text-sm font-bold tracking-wide transition-all duration-300 relative overflow-hidden ${
                  tradeType === 'buy'
                    ? 'bg-gradient-to-r from-emerald to-teal text-white hover:shadow-lg hover:shadow-emerald/20'
                    : 'bg-gradient-to-r from-cherry to-rose-600 text-white hover:shadow-lg hover:shadow-cherry/20'
                } disabled:opacity-60 disabled:cursor-not-allowed`}
              >
                {orderStatus === 'executing' ? (
                  <span className="flex items-center justify-center gap-2">
                    <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
                      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" opacity="0.3" />
                      <path d="M4 12a8 8 0 018-8" stroke="currentColor" strokeWidth="4" fill="none" strokeLinecap="round" />
                    </svg>
                    Executing...
                  </span>
                ) : orderStatus === 'filled' ? (
                  <span className="flex items-center justify-center gap-2">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                      <polyline points="20 6 9 17 4 12" />
                    </svg>
                    Order Filled ✓
                  </span>
                ) : (
                  `${tradeType === 'buy' ? 'Buy' : 'Sell'} ${selectedAsset}`
                )}
              </button>

              {orderStatus === 'filled' && (
                <div className="animate-scale-in text-center">
                  <div className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-emerald/8 border border-emerald/20">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#10B981" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M22 11.08V12a10 10 0 11-5.93-9.14" />
                      <polyline points="22 4 12 14.01 9 11.01" />
                    </svg>
                    <span className="text-xs text-emerald-50 font-medium">
                      {tradeType === 'buy' ? 'Bought' : 'Sold'} {tradeAmount} {selectedAsset} @ ${currentPrice.toFixed(2)}
                    </span>
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Recent Trades */}
          <div className="lg:col-span-2 glass rounded-2xl p-6 animate-slide-up" style={{ animationDelay: '0.35s' }}>
            <div className="flex items-center justify-between mb-5">
              <h3 className="text-sm font-semibold text-white">Recent Activity</h3>
              <button className="text-[11px] text-silver/50 hover:text-silver transition-colors">View All</button>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-left">
                <thead>
                  <tr className="text-[11px] text-silver/50 uppercase tracking-wider">
                    <th className="pb-3 font-medium">Pair</th>
                    <th className="pb-3 font-medium">Type</th>
                    <th className="pb-3 font-medium">Amount</th>
                    <th className="pb-3 font-medium">Price</th>
                    <th className="pb-3 font-medium">Total</th>
                    <th className="pb-3 font-medium">P&L</th>
                    <th className="pb-3 font-medium text-right">Time</th>
                  </tr>
                </thead>
                <tbody className="text-sm">
                  {[
                    { pair: 'BTC/USD', type: 'Buy', amount: '0.50', price: '48,320.50', total: '24,160.25', pnl: '+$340.20', pnlUp: true, time: '2m ago' },
                    { pair: 'ETH/USD', type: 'Sell', amount: '5.00', price: '3,750.80', total: '18,754.00', pnl: '-$120.50', pnlUp: false, time: '15m ago' },
                    { pair: 'SOL/USD', type: 'Buy', amount: '25.00', price: '142.30', total: '3,557.50', pnl: '+$89.30', pnlUp: true, time: '1h ago' },
                    { pair: 'LINK/USD', type: 'Buy', amount: '100.00', price: '18.45', total: '1,845.00', pnl: '+$12.40', pnlUp: true, time: '3h ago' },
                    { pair: 'AVAX/USD', type: 'Sell', amount: '20.00', price: '38.20', total: '764.00', pnl: '-$45.80', pnlUp: false, time: '5h ago' },
                  ].map((trade, i) => (
                    <tr key={i} className="border-t border-white/4 hover:bg-white/[0.02] transition-colors">
                      <td className="py-3 font-semibold text-white">{trade.pair}</td>
                      <td className="py-3">
                        <span className={`text-xs font-semibold px-2 py-0.5 rounded ${
                          trade.type === 'Buy' ? 'bg-emerald/10 text-emerald-50' : 'bg-cherry/10 text-cherry-50'
                        }`}>{trade.type}</span>
                      </td>
                      <td className="py-3 text-silver tabular-nums">{trade.amount}</td>
                      <td className="py-3 text-silver tabular-nums">${trade.price}</td>
                      <td className="py-3 text-white font-medium tabular-nums">${trade.total}</td>
                      <td className={`py-3 font-medium tabular-nums ${trade.pnlUp ? 'text-emerald-50' : 'text-cherry-50'}`}>{trade.pnl}</td>
                      <td className="py-3 text-silver/50 text-xs text-right">{trade.time}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        {/* ═══ FOOTER ═══ */}
        <footer className="mt-12 pt-6 border-t border-white/6 flex items-center justify-between text-[11px] text-silver/50">
          <span>© 2026 Alpha Terminal — Institutional Grade</span>
          <div className="flex items-center gap-4">
            <span>System: Online</span>
            <span>Latency: 12ms</span>
            <span>Uptime: 99.97%</span>
          </div>
        </footer>
      </main>
    </div>
  );
}
