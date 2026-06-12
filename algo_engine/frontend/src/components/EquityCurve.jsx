import { useState, useMemo } from 'react';

export default function EquityCurve({ journalData }) {
  const [view, setView] = useState('cumulative');

  const equity = useMemo(() => {
    const trades = (journalData?.history || [])
      .filter(t => t.state === 'TP_HIT' || t.state === 'SL_HIT')
      .sort((a, b) => (a.closed_at || 0) - (b.closed_at || 0));
    if (trades.length < 2) return [];

    return trades.map((t, i) => ({
      trade: i + 1,
      pnl: t.pnl_pct || 0,
      cumulative: trades.slice(0, i + 1).reduce((s, x) => s + (x.pnl_pct || 0), 0),
      drawdown: 0,
      direction: t.direction,
    }));
  }, [journalData]);

  const maxEquity = useMemo(() => Math.max(...equity.map(e => e[view === 'cumulative' ? 'cumulative' : 'pnl']), 1), [equity, view]);
  const minEquity = useMemo(() => Math.min(...equity.map(e => e[view === 'cumulative' ? 'cumulative' : 'pnl']), -1), [equity, view]);
  const range = maxEquity - minEquity || 1;

  if (equity.length < 2) {
    return (
      <div className="glass rounded-2xl p-5">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold text-white">Equity Curve</h3>
        </div>
        <div className="h-[200px] flex items-center justify-center">
          <p className="text-xs text-silver/30">Need at least 2 closed trades for equity curve</p>
        </div>
      </div>
    );
  }

  const w = 600;
  const h = 180;
  const pad = { t: 16, r: 12, b: 24, l: 48 };
  const cw = w - pad.l - pad.r;
  const ch = h - pad.t - pad.b;

  const series = view === 'cumulative' ? equity.map(e => e.cumulative) : equity.map(e => e.pnl);
  const isPositive = series[series.length - 1] >= 0;
  const lineColor = isPositive ? '#10B981' : '#DC2626';

  const scaleX = (i) => pad.l + (i / (equity.length - 1)) * cw;
  const scaleY = (v) => pad.t + ch - ((v - minEquity) / range) * ch;

  const areaPath = equity.map((e, i) => `${i === 0 ? 'M' : 'L'}${scaleX(i)},${scaleY(series[i])}`).join(' ') +
    ` L${scaleX(equity.length - 1)},${pad.t + ch} L${pad.l},${pad.t + ch} Z`;
  const linePath = equity.map((e, i) => `${i === 0 ? 'M' : 'L'}${scaleX(i)},${scaleY(series[i])}`).join(' ');

  const gridLines = 5;
  const gridYs = Array.from({ length: gridLines }, (_, i) => pad.t + (ch / (gridLines - 1)) * i);
  const gridLabels = gridYs.map(y => minEquity + ((pad.t + ch - y) / ch) * range);

  const lastPnl = series[series.length - 1];
  const best = Math.max(...series);
  const worst = Math.min(...series);

  return (
    <div className="glass rounded-2xl p-5">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-3">
          <h3 className="text-sm font-semibold text-white">Equity Curve</h3>
          <span className={`text-sm font-bold font-mono ${lastPnl >= 0 ? 'text-emerald' : 'text-cherry'}`}>
            {lastPnl >= 0 ? '+' : ''}{lastPnl.toFixed(2)}%
          </span>
        </div>
        <div className="flex items-center gap-1 bg-white/4 rounded-lg p-0.5">
          <button onClick={() => setView('cumulative')}
            className={`px-2.5 py-1 rounded text-[10px] font-medium transition-all ${view === 'cumulative' ? 'bg-lavender/20 text-lavender-50' : 'text-silver/50 hover:text-white'}`}>
            Cumulative
          </button>
          <button onClick={() => setView('per_trade')}
            className={`px-2.5 py-1 rounded text-[10px] font-medium transition-all ${view === 'per_trade' ? 'bg-lavender/20 text-lavender-50' : 'text-silver/50 hover:text-white'}`}>
            Per Trade
          </button>
        </div>
      </div>

      <svg viewBox={`0 0 ${w} ${h}`} className="w-full" style={{ height: h }}>
        <defs>
          <linearGradient id="eqG" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={lineColor} stopOpacity="0.12" />
            <stop offset="100%" stopColor={lineColor} stopOpacity="0" />
          </linearGradient>
        </defs>

        {gridYs.map((y, i) => (
          <g key={i}>
            <line x1={pad.l} y1={y} x2={pad.l + cw} y2={y} stroke="rgba(255,255,255,0.04)" strokeWidth="1" />
            <text x={pad.l - 6} y={y + 3} textAnchor="end" fill="rgba(255,255,255,0.2)" fontSize="9" fontFamily="'JetBrains Mono', monospace">
              {gridLabels[i].toFixed(1)}%
            </text>
          </g>
        ))}

        <path d={areaPath} fill="url(#eqG)" />
        <path d={linePath} fill="none" stroke={lineColor} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />

        {/* Zero line */}
        {minEquity < 0 && maxEquity > 0 && (
          <line x1={pad.l} y1={scaleY(0)} x2={pad.l + cw} y2={scaleY(0)}
            stroke="rgba(255,255,255,0.08)" strokeWidth="1" strokeDasharray="4 4" />
        )}
      </svg>

      <div className="flex items-center justify-between mt-3 pt-3 border-t border-white/5">
        <div>
          <p className="text-[10px] text-silver/40">Best Trade</p>
          <p className="text-xs font-mono font-semibold text-emerald">+{best.toFixed(2)}%</p>
        </div>
        <div>
          <p className="text-[10px] text-silver/40">Worst Trade</p>
          <p className="text-xs font-mono font-semibold text-cherry">{worst.toFixed(2)}%</p>
        </div>
        <div>
          <p className="text-[10px] text-silver/40">Total Trades</p>
          <p className="text-xs font-mono font-semibold text-white">{equity.length}</p>
        </div>
        <div>
          <p className="text-[10px] text-silver/40">Win Rate</p>
          <p className="text-xs font-mono font-semibold text-white">
            {((equity.filter(e => e.pnl > 0).length / equity.length) * 100).toFixed(0)}%
          </p>
        </div>
      </div>
    </div>
  );
}
