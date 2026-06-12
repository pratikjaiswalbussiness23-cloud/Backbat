export default function Header({ symbol, setSymbol, interval, setInterval }) {
  return (
    <header className="sticky top-0 z-40 glass border-b border-white/[0.04]">
      <div className="max-w-7xl mx-auto px-6 h-14 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-gold to-lavender flex items-center justify-center shadow-lg shadow-lavender/20">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#0B0C10" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
            </svg>
          </div>
          <div>
            <h1 className="text-base font-bold tracking-tight">ALGO ENGINE</h1>
            <p className="text-[10px] text-silver tracking-[0.15em] uppercase -mt-0.5">Signal Terminal v1.0</p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <select value={symbol} onChange={e => setSymbol(e.target.value)}
            className="bg-white/6 border border-white/8 rounded-lg px-3 py-1.5 text-xs font-medium text-white outline-none focus:border-gold/30">
            <option value="BTCUSDT" className="bg-obsidian-100">BTC/USDT</option>
            <option value="ETHUSDT" className="bg-obsidian-100">ETH/USDT</option>
            <option value="SOLUSDT" className="bg-obsidian-100">SOL/USDT</option>
          </select>
          <select value={interval} onChange={e => setInterval(e.target.value)}
            className="bg-white/6 border border-white/8 rounded-lg px-3 py-1.5 text-xs font-medium text-white outline-none focus:border-gold/30">
            <option value="15m" className="bg-obsidian-100">15m</option>
            <option value="1h" className="bg-obsidian-100">1H</option>
            <option value="4h" className="bg-obsidian-100">4H</option>
            <option value="1d" className="bg-obsidian-100">1D</option>
          </select>
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-white/4 border border-white/6">
            <div className="w-2 h-2 rounded-full bg-emerald shadow-[0_0_6px_rgba(16,185,129,0.5)] animate-pulse" />
            <span className="text-xs text-silver font-medium">Live</span>
          </div>
        </div>
      </div>
    </header>
  );
}
