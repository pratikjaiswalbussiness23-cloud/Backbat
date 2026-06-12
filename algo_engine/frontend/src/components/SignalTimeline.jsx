export default function SignalTimeline({ signals }) {
  const all = signals || [];
  return (
    <div className="glass rounded-2xl p-5">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold text-white">Signal Timeline</h3>
        <span className="text-[11px] text-silver/50">{all.length} signals</span>
      </div>
      <div className="space-y-2 max-h-[400px] overflow-y-auto">
        {all.length === 0 && (
          <p className="text-xs text-silver/40 text-center py-8">No signals yet. Waiting for confluence...</p>
        )}
        {all.map((sig, i) => (
          <div key={sig.id || i}
            className="flex items-center gap-3 p-3 rounded-xl bg-white/[0.03] border border-white/5 hover:bg-white/[0.06] transition-all">
            <div className={`w-2 h-2 rounded-full shrink-0 ${sig.state === 'TP_HIT' ? 'bg-emerald' : sig.state === 'SL_HIT' ? 'bg-cherry' : sig.state === 'ACTIVE' ? 'bg-gold' : sig.state === 'DETECTED' ? 'bg-ocean' : 'bg-silver/30'}`} />
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className={`text-xs font-bold ${sig.direction === 'long' ? 'text-emerald' : 'text-cherry'}`}>
                  {sig.direction?.toUpperCase()}
                </span>
                <span className="text-[11px] font-mono text-white">${sig.entry_price?.toFixed(2) || '---'}</span>
                <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${
                  sig.confidence === 'HIGH' ? 'bg-emerald/10 text-emerald-50' :
                  sig.confidence === 'MEDIUM' ? 'bg-gold/10 text-gold-50' :
                  'bg-silver/10 text-silver'
                }`}>
                  {sig.confidence}
                </span>
              </div>
              <div className="flex items-center gap-3 mt-1">
                <span className="text-[10px] text-silver/40 font-mono">SL: ${sig.sl_price?.toFixed(2)}</span>
                <span className="text-[10px] text-silver/40 font-mono">TP: ${sig.tp_price?.toFixed(2)}</span>
                <span className="text-[10px] text-silver/40">{sig.components?.join(' + ')}</span>
              </div>
            </div>
            <div className="text-right shrink-0">
              <span className={`text-xs font-mono font-semibold ${
                sig.pnl_pct > 0 ? 'text-emerald' : sig.pnl_pct < 0 ? 'text-cherry' : 'text-silver/40'
              }`}>
                {sig.pnl_pct ? `${sig.pnl_pct > 0 ? '+' : ''}${sig.pnl_pct.toFixed(2)}%` : sig.state}
              </span>
              <p className="text-[10px] text-silver/30 mt-0.5">
                {sig.detected_at ? new Date(sig.detected_at * 1000).toLocaleTimeString() : ''}
              </p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
