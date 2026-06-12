export default function ComponentHealth({ lastSignal }) {
  const sig = lastSignal || {};
  const components = [
    { name: 'FVG', key: 'fvg', color: '#10B981', weight: '40%' },
    { name: 'Swing', key: 'swing', color: '#1A73E8', weight: '30%' },
    { name: 'Delta', key: 'delta', color: '#0D9488', weight: '30%' },
    { name: 'Trend Gate', key: 'trend', color: '#7C3AED', weight: 'gate' },
  ];

  const trendGate = sig.trend_gate || {};
  const trend = trendGate.trend || 'neutral';
  const gateMultLong = trendGate.gate_mult_long || 1.0;
  const gateMultShort = trendGate.gate_mult_short || 1.0;
  const adx = trendGate.adx || 0;
  const emaAlign = trendGate.ema_alignment || 0;

  const compScores = sig.components_scores || {};
  const totalScore = sig.score || 0;

  return (
    <div className="glass rounded-2xl p-5">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold text-white">Component Health</h3>
        <span className={`px-2 py-0.5 rounded text-[10px] font-bold font-mono ${
          totalScore >= 0.6 ? 'bg-emerald/10 text-emerald' :
          totalScore >= 0.4 ? 'bg-gold/10 text-gold' :
          'bg-silver/10 text-silver/60'
        }`}>
          Σ {totalScore.toFixed(2)}
        </span>
      </div>

      <div className="space-y-3 mb-4">
        {components.map(comp => {
          const score = comp.key === 'trend'
            ? (trend === 'bullish' ? 0.8 : trend === 'bearish' ? 0.6 : 0.3)
            : (compScores[comp.key] || 0);
          const barWidth = Math.max(4, score * 100);
          return (
            <div key={comp.key}>
              <div className="flex items-center justify-between mb-1">
                <div className="flex items-center gap-2">
                  <div style={{
                    width: 6, height: 6, borderRadius: '50%',
                    backgroundColor: comp.color,
                    boxShadow: score > 0.3 ? `0 0 6px ${comp.color}80` : 'none',
                  }} />
                  <span className="text-xs text-silver font-medium">{comp.name}</span>
                  {comp.weight !== 'gate' && (
                    <span className="text-[9px] text-silver/30">{comp.weight}</span>
                  )}
                </div>
                <span style={{ color: score >= 0.5 ? '#10B981' : score >= 0.2 ? '#F59E0B' : 'rgba(209,213,219,0.4)' }}
                  className="text-[10px] font-mono font-medium">
                  {(score * 100).toFixed(0)}%
                </span>
              </div>
              <div className="h-1.5 rounded-full bg-white/5 overflow-hidden">
                <div style={{
                  width: `${barWidth}%`,
                  height: '100%',
                  borderRadius: '999px',
                  transition: 'all 0.5s',
                  background: comp.key === 'trend'
                    ? trend === 'bullish'
                      ? 'linear-gradient(90deg, #7C3AED, #10B981)'
                      : trend === 'bearish'
                        ? 'linear-gradient(90deg, #7C3AED, #DC2626)'
                        : 'linear-gradient(90deg, rgba(124,58,237,0.5), rgba(124,58,237,0.2))'
                    : `linear-gradient(90deg, ${comp.color}, ${comp.color}dd)`,
                  opacity: score > 0.3 ? 0.8 : 0.4,
                }} />
              </div>
            </div>
          );
        })}
      </div>

      {trendGate && Object.keys(trendGate).length > 0 && (
        <div className="bg-white/[0.03] rounded-xl p-3 border border-white/6">
          <p className="text-[10px] text-silver/40 uppercase tracking-wider mb-2">Trend Gate Status</p>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <p className="text-[9px] text-silver/40">Direction</p>
              <p className={`text-xs font-bold ${trend === 'bullish' ? 'text-emerald' : trend === 'bearish' ? 'text-cherry' : 'text-silver'}`}>
                {trend.toUpperCase()}
              </p>
            </div>
            <div>
              <p className="text-[9px] text-silver/40">ADX</p>
              <p className="text-xs font-mono text-white">{adx.toFixed(1)}</p>
            </div>
            <div>
              <p className="text-[9px] text-silver/40">Long Mult</p>
              <p className="text-xs font-mono text-white">{gateMultLong.toFixed(2)}x</p>
            </div>
            <div>
              <p className="text-[9px] text-silver/40">Short Mult</p>
              <p className="text-xs font-mono text-white">{gateMultShort.toFixed(2)}x</p>
            </div>
          </div>
          <div className="mt-2">
            <p className="text-[9px] text-silver/40 mb-1">EMA Alignment</p>
            <div className="flex items-center gap-1">
              {['NEUTRAL', 'BULLISH', 'BEARISH'].map(lbl => (
                <span key={lbl} className={`px-2 py-0.5 rounded text-[9px] font-medium ${
                  emaAlign === 1 && lbl === 'BULLISH' ? 'bg-emerald/10 text-emerald' :
                  emaAlign === -1 && lbl === 'BEARISH' ? 'bg-cherry/10 text-cherry' :
                  emaAlign === 0 && lbl === 'NEUTRAL' ? 'bg-silver/10 text-silver' :
                  'text-silver/30'
                }`}>{lbl}</span>
              ))}
            </div>
          </div>
        </div>
      )}

      {(!trendGate || Object.keys(trendGate).length === 0) && (
        <div className="text-center py-4">
          <p className="text-[10px] text-silver/30">Awaiting first signal for Trend Gate analysis</p>
        </div>
      )}
    </div>
  );
}
