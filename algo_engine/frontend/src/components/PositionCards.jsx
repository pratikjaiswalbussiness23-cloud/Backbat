export default function PositionCards({ activeSignals, stateStats }) {
  const signals = activeSignals || [];
  const stats = stateStats || {};

  return (
    <div className="glass rounded-2xl p-5">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold text-white">Active Positions</h3>
        <span className="text-[11px] text-silver/50">{signals.length} active</span>
      </div>

      {signals.length === 0 ? (
        <div className="text-center py-8">
          <div className="w-12 h-12 rounded-full bg-white/4 mx-auto flex items-center justify-center mb-3">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="rgba(255,255,255,0.2)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <rect x="2" y="3" width="20" height="14" rx="2" ry="2" />
              <line x1="8" y1="21" x2="16" y2="21" />
              <line x1="12" y1="17" x2="12" y2="21" />
            </svg>
          </div>
          <p className="text-xs text-silver/40">No active positions</p>
          <p className="text-[10px] text-silver/30 mt-1">Waiting for signal with Trend Gate confirmation</p>
        </div>
      ) : (
        <div className="space-y-3">
          {signals.map((sig, i) => (
            <div key={sig.id || i}
              className="relative overflow-hidden rounded-xl bg-white/[0.03] border border-white/8 p-4">
              <div className={`absolute inset-0 opacity-5 ${sig.direction === 'long' ? 'bg-gradient-to-r from-emerald/20' : 'bg-gradient-to-r from-cherry/20'}`} />
              <div className="relative z-10">
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2">
                    <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${
                      sig.direction === 'long' ? 'bg-emerald/15 text-emerald' : 'bg-cherry/15 text-cherry'
                    }`}>
                      {sig.direction}
                    </span>
                    <span className="text-xs text-silver/50">{sig.symbol || '--'}</span>
                  </div>
                  <span className="text-[10px] font-mono text-silver/40">ID: {(sig.id || '').slice(0, 8)}</span>
                </div>
                <div className="grid grid-cols-3 gap-3">
                  <div>
                    <p className="text-[10px] text-silver/40 uppercase tracking-wider">Entry Zone</p>
                    <p className="text-xs font-mono font-semibold text-white mt-0.5">
                      ${sig.entry_zone?.low?.toFixed(2) || '---'} — ${sig.entry_zone?.high?.toFixed(2) || '---'}
                    </p>
                  </div>
                  <div>
                    <p className="text-[10px] text-silver/40 uppercase tracking-wider">Stop Loss</p>
                    <p className="text-xs font-mono font-semibold text-cherry mt-0.5">${sig.sl_price?.toFixed(2) || '---'}</p>
                  </div>
                  <div>
                    <p className="text-[10px] text-silver/40 uppercase tracking-wider">Take Profit</p>
                    <p className="text-xs font-mono font-semibold text-emerald mt-0.5">${sig.tp_price?.toFixed(2) || '---'}</p>
                  </div>
                </div>
                <div className="flex items-center justify-between mt-3 pt-3 border-t border-white/6">
                  <div className="flex items-center gap-2">
                    <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${
                      sig.confidence === 'HIGH' ? 'bg-emerald/10 text-emerald-50' :
                      sig.confidence === 'MEDIUM' ? 'bg-gold/10 text-gold-50' :
                      'bg-silver/10 text-silver'
                    }`}>{sig.confidence || 'NONE'}</span>
                    <span className="text-[10px] text-silver/40 font-mono">∑ {sig.score?.toFixed(2) || '0.00'}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] font-mono text-silver/50">
                      {(sig.components || []).join(' + ')}
                    </span>
                    <span className={`text-[10px] font-medium ${
                      sig.state === 'ACTIVE' ? 'text-gold' : 'text-ocean'
                    }`}>{sig.state}</span>
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {Object.keys(stats).length > 0 && (
        <div className="grid grid-cols-3 gap-3 mt-4 pt-4 border-t border-white/5">
          <div className="text-center">
            <p className="text-lg font-bold font-mono text-white">{stats.total || 0}</p>
            <p className="text-[10px] text-silver/40">Total</p>
          </div>
          <div className="text-center">
            <p className="text-lg font-bold font-mono text-emerald">
              {stats.wins || 0}
            </p>
            <p className="text-[10px] text-silver/40">Wins</p>
          </div>
          <div className="text-center">
            <p className="text-lg font-bold font-mono text-cherry">
              {stats.losses || 0}
            </p>
            <p className="text-[10px] text-silver/40">Losses</p>
          </div>
        </div>
      )}
    </div>
  );
}
