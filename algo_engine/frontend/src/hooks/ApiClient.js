// In dev mode (Vite proxy), use relative URLs for REST
// but connect SSE directly to the backend to avoid proxy buffering issues
const API_BASE = '/api/v2';
const SSE_BASE = window.location.hostname === 'localhost'
  ? 'http://localhost:5003/api/v2'
  : API_BASE;

async function post(endpoint, data = {}) {
  const res = await fetch(`${API_BASE}${endpoint}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  return res.json();
}

async function get(endpoint, params = {}) {
  const qs = new URLSearchParams(params).toString();
  const url = `${API_BASE}${endpoint}${qs ? '?' + qs : ''}`;
  const res = await fetch(url);
  return res.json();
}

export const api = {
  health: () => get('/health'),
  signal: (symbol = 'BTCUSDT', interval = '15m') => post('/signal', { symbol, interval }),
  state: (symbol) => get('/state', { ...(symbol && { symbol }) }),
  journal: (limit = 50, symbol) => get('/journal', { limit, ...(symbol && { symbol }) }),
  reset: () => post('/reset'),
  streamUrl: (symbol = 'BTCUSDT', interval = '15m') =>
    `${SSE_BASE}/stream?symbol=${symbol}&interval=${interval}`,
};

export function connectStream(symbol = 'BTCUSDT', interval = '15m', onData) {
  const url = `${SSE_BASE}/stream?symbol=${symbol}&interval=${interval}`;
  const evtSource = new EventSource(url);

  evtSource.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      if (data.error) return;
      onData(data);
    } catch (e) {
      console.error('[SSE] Parse error:', e);
    }
  };

  evtSource.onerror = () => {};

  return () => evtSource.close();
}
