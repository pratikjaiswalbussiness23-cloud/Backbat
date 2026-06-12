import { useState, useEffect, useCallback, useRef } from 'react';
import Header from './components/Header.jsx';
import SignalTimeline from './components/SignalTimeline.jsx';
import PositionCards from './components/PositionCards.jsx';
import TradeJournal from './components/TradeJournal.jsx';
import EquityCurve from './components/EquityCurve.jsx';
import ComponentHealth from './components/ComponentHealth.jsx';
import PriceChart from './components/PriceChart.jsx';
import { api, connectStream } from './hooks/ApiClient.js';

export default function App() {
  const [symbol, setSymbol] = useState('BTCUSDT');
  const [interval, setInterval] = useState('15m');
  const [loading, setLoading] = useState(true);
  const [signals, setSignals] = useState([]);
  const [lastSignal, setLastSignal] = useState(null);
  const [activeSignals, setActiveSignals] = useState([]);
  const [journalData, setJournalData] = useState({ history: [], stats: {} });
  const [candles, setCandles] = useState([]);
  const [stateStats, setStateStats] = useState({});
  const [health, setHealth] = useState({ status: 'checking' });
  const [error, setError] = useState(null);
  const streamCleanup = useRef(null);

  // ── Poll health, state, journal ──
  const pollState = useCallback(async () => {
    try {
      const [stateRes, journalRes, healthRes] = await Promise.all([
        api.state(symbol),
        api.journal(200, symbol),
        api.health(),
      ]);
      if (stateRes?.success !== false) {
        setActiveSignals(stateRes?.active_signals || stateRes?.active || []);
        setSignals(stateRes?.history || stateRes?.signals || []);
        setStateStats(stateRes?.stats || {});
        if (!lastSignal && (stateRes?.signals || []).length > 0) {
          const all = stateRes?.signals || [];
          setLastSignal(all[all.length - 1]);
        }
      }
      if (journalRes?.success !== false) {
        setJournalData({
          history: journalRes?.history || journalRes?.signals || [],
          stats: journalRes?.stats || {},
        });
      }
      setHealth(healthRes || { status: 'ok' });
      setError(null);
    } catch (e) {
      if (!error) setError('Backend connection failed. Is algo-engine running?');
    }
  }, [symbol, lastSignal, error]);

  // ── Generate a signal on button press ──
  const generateSignal = useCallback(async () => {
    try {
      const res = await api.signal(symbol, interval);
      if (res?.success !== false) {
        setLastSignal(res);
        setSignals(prev => [res, ...prev].slice(0, 200));
        if (res.state === 'ACTIVE' || res.state === 'DETECTED') {
          setActiveSignals(prev => {
            const exists = prev.some(s => s.id === res.id);
            return exists ? prev : [res, ...prev];
          });
        }
        setError(null);
      }
    } catch (e) {
      setError('Signal generation failed');
    }
  }, [symbol, interval]);

  // ── SSE stream for real-time updates ──
  useEffect(() => {
    if (streamCleanup.current) streamCleanup.current();
    streamCleanup.current = connectStream(symbol, interval, (data) => {
      // Always update lastSignal with most recent signal/confluence data
      if (data?.last_signal) {
        setLastSignal(data.last_signal);
      }
      // Only add to timeline when a genuinely NEW signal fires
      if (data?.signal) {
        setSignals(prev => [data.signal, ...prev].slice(0, 200));
      }
      if (data?.candles) setCandles(data.candles);
      if (data?.active) setActiveSignals(data.active);
      if (data?.journal) setJournalData(data.journal);
    });
    return () => {
      if (streamCleanup.current) streamCleanup.current();
    };
  }, [symbol, interval]);

  // ── Polling fallback ──
  useEffect(() => {
    pollState();
    const interval = setInterval(pollState, 10000);
    return () => clearInterval(interval);
  }, [pollState]);

  const isConnected = health?.status === 'ok' || health?.service === 'algo-engine-v2';

  return (
    <div className="min-h-screen bg-obsidian">
      <Header symbol={symbol} setSymbol={setSymbol} interval={interval} setInterval={setInterval} />

      <main className="max-w-7xl mx-auto px-6 py-6 space-y-6 animate-fade-in">
        {/* Status bar */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2">
              <div className={`w-2 h-2 rounded-full ${isConnected ? 'bg-emerald shadow-[0_0_6px_rgba(16,185,129,0.5)] animate-pulse' : 'bg-cherry shadow-[0_0_6px_rgba(220,38,38,0.5)]'}`} />
              <span className={`text-xs font-medium ${isConnected ? 'text-emerald' : 'text-cherry'}`}>
                {isConnected ? 'Connected' : 'Disconnected'}
              </span>
            </div>
            <span className="text-[10px] text-silver/30">ALGO ENGINE v1.0</span>
          </div>
          <div className="flex items-center gap-2">
            <button onClick={generateSignal}
              className="px-4 py-1.5 rounded-lg text-xs font-bold bg-gradient-to-r from-gold to-lavender text-obsidian hover:opacity-90 transition-all shadow-lg shadow-lavender/20">
              Generate Signal
            </button>
            <button onClick={pollState}
              className="px-3 py-1.5 rounded-lg text-xs font-medium bg-white/6 text-silver hover:bg-white/10 transition-all">
              Refresh
            </button>
          </div>
        </div>

        {/* Error banner */}
        {error && (
          <div className="bg-cherry/10 border border-cherry/20 rounded-xl px-4 py-3">
            <p className="text-xs text-cherry-50">{error}</p>
          </div>
        )}

        {/* Top row: Position Cards + Signal Timeline */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2">
            <SignalTimeline signals={signals} />
          </div>
          <div>
            <PositionCards activeSignals={activeSignals} stateStats={stateStats} />
          </div>
        </div>

        {/* Middle row: Price Chart + Component Health */}
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
          <div className="lg:col-span-3">
            <PriceChart candles={candles} signals={signals} />
          </div>
          <div>
            <ComponentHealth lastSignal={lastSignal} />
          </div>
        </div>

        {/* Bottom row: Equity Curve + Trade Journal */}
        <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
          <div className="lg:col-span-2">
            <EquityCurve journalData={journalData} />
          </div>
          <div className="lg:col-span-3">
            <TradeJournal journalData={journalData} />
          </div>
        </div>
      </main>
    </div>
  );
}
