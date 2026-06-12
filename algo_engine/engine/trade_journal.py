"""
Algo Engine v1.0 — SQLite Trade Journal
"""
import sqlite3, json, os
from typing import Dict, List, Optional

DB_PATH = "data/trade_journal.db"

class TradeJournal:
    def __init__(self, db_path=None):
        self.db_path = db_path or DB_PATH
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS signals (
            id TEXT PRIMARY KEY, symbol TEXT, interval TEXT, direction TEXT,
            state TEXT, entry_zone_low REAL, entry_zone_high REAL,
            sl_price REAL, tp_price REAL, entry_price REAL, exit_price REAL,
            pnl_pct REAL, confidence TEXT, components TEXT, score REAL,
            detected_at INT, activated_at INT, closed_at INT,
            bars_held INT, reasoning TEXT, regime TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS perf_summary (
            id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT,
            total_trades INT, wins INT, losses INT, win_rate REAL,
            total_pnl REAL, max_drawdown REAL, profit_factor REAL)""")
        conn.commit()
        conn.close()

    def log(self, d):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        ez = d.get("entry_zone") or {}
        c.execute("INSERT OR REPLACE INTO signals VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (d.get("id"), d.get("symbol"), d.get("interval"), d.get("direction"), d.get("state"),
             ez.get("low"), ez.get("high"), d.get("sl_price"), d.get("tp_price"),
             d.get("entry_price"), d.get("exit_price"), d.get("pnl_pct"), d.get("confidence"),
             json.dumps(d.get("components", [])), d.get("score"),
             d.get("detected_at"), d.get("activated_at"), d.get("closed_at"), d.get("bars_held"),
             json.dumps(d.get("reasoning", [])), json.dumps(d.get("regime", {}))))
        # Also log state transitions in a separate table for history tracking
        c.execute("""CREATE TABLE IF NOT EXISTS transitions (
            signal_id TEXT, from_state TEXT, to_state TEXT,
            price REAL, timestamp INT, pnl_pct REAL)""")
        conn.commit()
        conn.close()

    def log_transition(self, signal_id, from_state, to_state, price, timestamp, pnl_pct=None):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("INSERT INTO transitions VALUES (?,?,?,?,?,?)",
            (signal_id, from_state, to_state, price, timestamp, pnl_pct))
        conn.commit()
        conn.close()

    def history(self, limit=100, symbol=None):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        if symbol:
            rows = c.execute("SELECT * FROM signals WHERE symbol=? ORDER BY detected_at DESC LIMIT ?", (symbol, limit)).fetchall()
        else:
            rows = c.execute("SELECT * FROM signals ORDER BY detected_at DESC LIMIT ?", (limit,)).fetchall()
        conn.close()
        res = []
        for r in rows:
            rd = dict(r)
            rd["components"] = json.loads(rd.get("components") or "[]")
            rd["reasoning"] = json.loads(rd.get("reasoning") or "[]")
            rd["regime"] = json.loads(rd.get("regime") or "{}")
            res.append(rd)
        return res

    def transitions(self, signal_id=None, limit=100):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        if signal_id:
            rows = c.execute("SELECT * FROM transitions WHERE signal_id=? ORDER BY timestamp", (signal_id,)).fetchall()
        else:
            rows = c.execute("SELECT * FROM transitions ORDER BY timestamp DESC LIMIT ?", (limit,)).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def stats(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        t = c.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
        w = c.execute("SELECT COUNT(*) FROM signals WHERE state='TP_HIT'").fetchone()[0]
        l = c.execute("SELECT COUNT(*) FROM signals WHERE state='SL_HIT'").fetchone()[0]
        e = c.execute("SELECT COUNT(*) FROM signals WHERE state='EXPIRED'").fetchone()[0]
        a = c.execute("SELECT COUNT(*) FROM signals WHERE state='ACTIVE'").fetchone()[0]
        d = c.execute("SELECT COUNT(*) FROM signals WHERE state='DETECTED'").fetchone()[0]
        p = c.execute("SELECT COALESCE(SUM(pnl_pct),0) FROM signals").fetchone()[0]
        conn.close()
        return {"total": t, "wins": w, "losses": l, "expired": e,
                "active": a, "detected": d, "total_pnl_pct": round(p, 2),
                "win_rate": round(w / max(w + l, 1) * 100, 1)}
