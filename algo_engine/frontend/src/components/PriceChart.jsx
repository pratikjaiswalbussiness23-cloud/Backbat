import { useRef, useEffect, useState, useMemo } from 'react';

const C = { up: '#10B981', down: '#DC2626', wick: 'rgba(255,255,255,0.3)', upFill: '#10B981', downFill: '#DC2626' };

export default function PriceChart({ candles = [], signals = [] }) {
  const containerRef = useRef(null);
  const [width, setWidth] = useState(800);

  useEffect(() => {
    const resize = () => {
      if (containerRef.current) setWidth(containerRef.current.clientWidth);
    };
    resize();
    window.addEventListener('resize', resize);
    return () => window.removeEventListener('resize', resize);
  }, []);

  const data = candles.slice(-80);
  const sigs = signals.filter(s => s.entry_price).slice(-10);

  const { mx, mn, range, isUp, lastClose, prevClose } = useMemo(() => {
    if (data.length < 5) return { mx: 0, mn: 0, range: 1, isUp: true, lastClose: 0, prevClose: 0 };
    const mx = Math.max(...data.map(d => d.high));
    const mn = Math.min(...data.map(d => d.low));
    const lc = data[data.length - 1]?.close || 0;
    const pc = data[data.length - 2]?.close || lc;
    return { mx, mn, range: mx - mn || 1, isUp: lc >= pc, lastClose: lc, prevClose: pc };
  }, [data]);

  if (data.length < 5) {
    return (
      <div className="glass rounded-2xl p-5" ref={containerRef}>
        <h3 className="text-sm font-semibold text-white mb-4">Price Chart</h3>
        <div className="h-[300px] flex items-center justify-center">
          <p className="text-xs text-silver/30">Waiting for candle data...</p>
        </div>
      </div>
    );
  }

  const pad = { t: 20, r: 16, b: 32, l: 60 };
  const ch = 300 - pad.t - pad.b;
  const cw = width - pad.l - pad.r;
  const candleWidth = Math.max(1, (cw / data.length) * 0.6);

  const xScale = (i) => pad.l + (i / (data.length - 1)) * cw;
  const yScale = (v) => pad.t + ch - ((v - mn) / range) * ch;

  const lineColor = isUp ? C.up : C.down;
  const linePath = data.map((d, i) => `${i === 0 ? 'M' : 'L'}${xScale(i)},${yScale(d.close)}`).join(' ');
  const areaPath = linePath + ` L${xScale(data.length - 1)},${pad.t + ch} L${pad.l},${pad.t + ch} Z`;

  // ── Draw candles instead of just a line ──
  const candlePaths = data.map((d, i) => {
    const x = pad.l + (i / (data.length - 1)) * cw;
    const open = d.open, close = d.close, high = d.high, low = d.low;
    const isBull = close >= open;
    const bodyTop = yScale(Math.max(open, close));
    const bodyBot = yScale(Math.min(open, close));
    const bodyH = Math.max(1, bodyBot - bodyTop);
    const wickTop = yScale(high);
    const wickBot = yScale(low);
    const cColor = isBull ? C.upFill : C.downFill;
    return (
      <g key={i}>
        <line x1={x} y1={wickTop} x2={x} y2={wickBot} stroke={C.wick} strokeWidth="1" />
        <rect x={x - candleWidth / 2} y={bodyTop} width={candleWidth} height={bodyH} fill={cColor} rx="1" />
      </g>
    );
  });

  // ── Signal markers ──
  const signalMarkers = sigs.map((sig, i) => {
    const idx = data.findIndex(d => Math.abs(d.close - sig.entry_price) / sig.entry_price < 0.005);
    if (idx < 0) return null;
    const x = xScale(idx);
    const y = yScale(sig.entry_price);
    const isLong = sig.direction === 'long';
    return (
      <g key={`sig-${i}`}>
        <line x1={x - 6} y1={y} x2={x + 6} y2={y} stroke={isLong ? C.up : C.down} strokeWidth="2" />
        <polygon points={isLong ? `${x},${y - 8} ${x - 4},${y - 4} ${x + 4},${y - 4}` : `${x},${y + 8} ${x - 4},${y + 4} ${x + 4},${y + 4}`}
          fill={isLong ? C.up : C.down} />
      </g>
    );
  });

  const gridLines = 5;
  const gridYs = Array.from({ length: gridLines }, (_, i) => pad.t + (ch / (gridLines - 1)) * i);
  const gridLabels = gridYs.map(y => mn + ((pad.t + ch - y) / ch) * range);

  return (
    <div className="glass rounded-2xl p-5" ref={containerRef}>
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <h3 className="text-sm font-semibold text-white">Price Chart</h3>
          <span className={`text-lg font-bold font-mono ${isUp ? 'text-emerald' : 'text-cherry'}`}>
            ${lastClose.toFixed(2)}
          </span>
          <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded ${isUp ? 'bg-emerald/10 text-emerald' : 'bg-cherry/10 text-cherry'}`}>
            {((lastClose - prevClose) / prevClose * 100).toFixed(2)}%
          </span>
        </div>
        <div className="flex items-center gap-1">
          {['15m', '1H', '4H', '1D'].map(p => (
            <button key={p} className="px-2 py-1 rounded text-[10px] font-medium text-silver/50 hover:text-white hover:bg-white/6 transition-all">{p}</button>
          ))}
        </div>
      </div>
      <svg viewBox={`0 0 ${width} 300`} className="w-full" style={{ maxWidth: '100%', height: 'auto' }}>
        <defs>
          <linearGradient id="areaG" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={lineColor} stopOpacity="0.12" />
            <stop offset="100%" stopColor={lineColor} stopOpacity="0" />
          </linearGradient>
        </defs>

        {gridYs.map((y, i) => (
          <g key={i}>
            <line x1={pad.l} y1={y} x2={pad.l + cw} y2={y} stroke="rgba(255,255,255,0.04)" strokeWidth="1" />
            <text x={pad.l - 8} y={y + 4} textAnchor="end" fill="rgba(255,255,255,0.25)" fontSize="10" fontFamily="'JetBrains Mono', monospace">
              ${gridLabels[i].toFixed(0)}
            </text>
          </g>
        ))}

        {candlePaths}

        <path d={areaPath} fill="url(#areaG)" />
        <path d={linePath} fill="none" stroke={lineColor} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" opacity="0.6" />

        {signalMarkers}
      </svg>
    </div>
  );
}
