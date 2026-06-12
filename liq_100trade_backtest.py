"""Liquidity Hunter 100-Trade Backtest with Component Analysis"""
import json, sys, time
from datetime import datetime
import numpy as np
import requests
from liq_engine import (
    OrderBlockDetector, FVGBalancer, LiquiditySweepDetector,
    SwingPointDetector, VolumeProfileAnalyzer, CVDAnalyzer, DeltaPatternDetector,
    calc_adx, calc_bb_width, detect_market_regime,
)
ENDPOINTS = ["https://api.binance.com", "https://api1.binance.com",
    "https://api2.binance.com", "https://api3.binance.com", "https://api4.binance.com"]
RISK_PER_TRADE = 2.0
SL_ATR_MULT = 1.5
TP_ATR_MULT = 3.0
TX_TOTAL = 0.2
SLIPPAGE = 0.05
def fetch_klines(symbol, interval, limit=3000):
    s = requests.Session()
    s.headers.update({"User-Agent": "LiqBT/3.0"})
    bu = None
    for b in ENDPOINTS:
        try:
            r = s.get(b + "/api/v3/klines", params={"symbol": symbol, "interval": interval, "limit": 1}, timeout=10)
            r.raise_for_status()
            bu = b; break
        except: continue
    else: raise RuntimeError("All endpoints failed")
    all_c, rem, et = [], limit, None
    while rem > 0:
        p = {"symbol": symbol, "interval": interval, "limit": min(500, rem)}
        if et: p["endTime"] = et
        try:
            r = s.get(bu + "/api/v3/klines", params=p, timeout=15)
            r.raise_for_status()
            batch = r.json()
            if not batch: break
            for k in batch:
                all_c.append({"time": k[0]//1000, "open": float(k[1]), "high": float(k[2]),
                    "low": float(k[3]), "close": float(k[4]), "volume": float(k[5])})
            rem -= len(batch); et = batch[-1][0]
            if len(batch) < 500: break
            time.sleep(0.15)
        except Exception as e:
            print("Fetch error: %s" % e, file=sys.stderr); break
    return all_c
def calc_atr(candles, period=14):
    if len(candles) < period+1: return 0
    trs = []
    for i in range(1, len(candles)):
        h,l = candles[i]["high"], candles[i]["low"]
        pc = candles[i-1]["close"]
        trs.append(max(h-l, abs(h-pc), abs(l-pc)))
    if len(trs) < period: return float(np.mean(trs)) if trs else 0
    a = float(np.mean(trs[:period]))
    for i in range(period, len(trs)): a = (a*(period-1)+trs[i])/period
    return a
def sma(candles, period):
    if len(candles) < period: return None
    return sum(c["close"] for c in candles[-period:]) / period
def avg_volume(candles, period=20):
    p = min(period, len(candles)) if len(candles) < period else period
    return sum(c.get("volume",0) for c in candles[-p:]) / max(p,1)
def is_bullish(c): return c["close"] > c["open"]
def is_bearish(c): return c["close"] < c["open"]
def sim(entry, direction, future_candles, atr, risk_pct=RISK_PER_TRADE):
    if atr <= 0: return {"r":"T","p":0,"b":0,"exit":0}
    if direction=="L":
        entry = entry*(1+SLIPPAGE/100)
        sl,tp = entry-atr*SL_ATR_MULT, entry+atr*TP_ATR_MULT
    else:
        entry = entry*(1-SLIPPAGE/100)
        sl,tp = entry+atr*SL_ATR_MULT, entry-atr*TP_ATR_MULT
    win_pnl = risk_pct*(TP_ATR_MULT/SL_ATR_MULT)
    loss_pnl = -risk_pct
    for i,c in enumerate(future_candles):
        if direction=="L":
            if c["low"]<=sl: return {"r":"L","p":loss_pnl-TX_TOTAL,"b":i+1,"exit":sl}
            if c["high"]>=tp: return {"r":"W","p":win_pnl-TX_TOTAL,"b":i+1,"exit":tp}
        else:
            if c["high"]>=sl: return {"r":"L","p":loss_pnl-TX_TOTAL,"b":i+1,"exit":sl}
            if c["low"]<=tp: return {"r":"W","p":win_pnl-TX_TOTAL,"b":i+1,"exit":tp}
    if future_candles:
        last = future_candles[-1]
        move = (last["close"]-entry)/entry*100 if direction=="L" else (entry-last["close"])/entry*100
        risk_pct_val = atr*SL_ATR_MULT/entry*100
        actual_r = move/risk_pct_val if risk_pct_val>0 else 0
        pnl = actual_r*risk_pct - TX_TOTAL
        pnl = max(loss_pnl, min(win_pnl, pnl))
        return {"r":"W" if pnl>0 else "L","p":round(pnl,4),"b":len(future_candles),"exit":last["close"]}
    return {"r":"T","p":0,"b":0,"exit":0}
print("Script created. Running component tests...")
