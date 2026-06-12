import { useState } from 'react';

export default function TradeJournal({ journalData }) {
  const [sortField, setSortField] = useState('detected_at');
  const [sortDir, setSortDir] = useState('desc');
  const entries = (journalData?.history || []).filter(e => e.state === 'TP_HIT' || e.state === 'SL_HIT');

  const sorted = [...entries].sort((a, b) => {
    const av = a[sortField] || 0;
    const bv = b[sortField] || 0;
    return sortDir === 'desc' ? (bv - av) : (av - bv);
  });

  const toggleSort = (field) => {
    if (sortField === field) setSortDir(d => d === 'desc' ? 'asc' : 'desc');
    else { setSortField(field); setSortDir('desc'); }
  };

  const SortIcon = ({ field }) => (
    <span className="inline-block ml-1 opacity-40">{sortField === field ? (sortDir === 'desc' ? '▼' : '▲') : '⇅'}</span>
  );

  return (
    <div className="glass rounded-2xl p-5">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold text-white">Trade Journal</h3>
        <span className="text-[11px] text-silver/50">{journalData?.stats?.total || 0} total · {journalData?.stats?.win_rate || 0}% WR</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-left">
          <thead>
            <tr className="text-[10px] text-silver/50 uppercase tracking-wider">
              <th className="pb-2 font-medium cursor-pointer hover:text-silver" onClick={() => toggleSort('direction')}>Dir <SortIcon field="direction" /></th>
              <th className="pb-2 font-medium cursor-pointer hover:text-silver" onClick={() => toggleSort('state')}>Result <SortIcon field="state" /></th>
              <th className="pb-2 font-medium cursor-pointer hover:text-silver" onClick={() => toggleSort('entry_price')}>Entry <SortIcon field="entry_price" /></th>
              <th className="pb-2 font-medium cursor-pointer hover:text-silver" onClick={() => toggleSort('exit_price')}>Exit <SortIcon field="exit_price" /></th>
              <th className="pb-2 font-medium cursor-pointer hover:text-silver" onClick={() => toggleSort('pnl_pct')}>PnL% <SortIcon field="pnl_pct" /></th>
              <th className="pb-2 font-medium cursor-pointer hover:text-silver" onClick={() => toggleSort('score')}>Score <SortIcon field="score" /></th>
              <th className="pb-2 font-medium text-right cursor-pointer hover:text-silver" onClick={() => toggleSort('detected_at')}>Time <SortIcon field="detected_at" /></th>
            </tr>
          </thead>
          <tbody className="text-xs">
            {sorted.length === 0 && (
              <tr><td colSpan={7} className="text-center py-8 text-silver/30">No closed trades yet</td></tr>
            )}
            {sorted.slice(0, 50).map((t, i) => (
              <tr key={t.id || i} className="border-t border-white/4 hover:bg-white/[0.02] transition-colors">
                <td className={`py-2.5 font-bold ${t.direction === 'long' ? 'text-emerald' : 'text-cherry'}`}>
                  {t.direction?.toUpperCase() || '--'}
                </td>
                <td className="py-2.5">
                  <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${
                    t.state === 'TP_HIT' ? 'bg-emerald/10 text-emerald' :
                    t.state === 'SL_HIT' ? 'bg-cherry/10 text-cherry' :
                    'bg-silver/10 text-silver'
                  }`}>
                    {t.state === 'TP_HIT' ? 'WIN' : t.state === 'SL_HIT' ? 'LOSS' : t.state}
                  </span>
                </td>
                <td className="py-2.5 font-mono text-white">${t.entry_price?.toFixed(2)}</td>
                <td className="py-2.5 font-mono text-white">${t.exit_price?.toFixed(2) || '---'}</td>
                <td className={`py-2.5 font-mono font-semibold ${(t.pnl_pct || 0) >= 0 ? 'text-emerald' : 'text-cherry'}`}>
                  {t.pnl_pct ? `${t.pnl_pct >= 0 ? '+' : ''}${t.pnl_pct.toFixed(2)}%` : '---'}
                </td>
                <td className="py-2.5 font-mono text-silver/60">{t.score?.toFixed(3)}</td>
                <td className="py-2.5 text-silver/40 text-right font-mono text-[10px]">
                  {t.closed_at ? new Date(t.closed_at * 1000).toLocaleTimeString() : ''}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
