"""
BACKBAT v3 -- Layer 4: Entry Signal Gate
DB Pattern in 0.5 ATR of Zone, CVD Divergence, Volume Confirmation
"""
import logging
import time
from typing import Dict, List, Optional
from config import DEFAULT_CONFIG
logger = logging.getLogger("backbat.signal_gate")


class DB:
    def __init__(self, b1i, b2i, b1p, b2p, nl, h, b1v, b2v):
        self.b1i, self.b2i, self.b1p, self.b2p = b1i, b2i, b1p, b2p
        self.nl, self.h, self.b1v, self.b2v = nl, h, b1v, b2v
        self.tp = nl + h
    def valid(self, mbd=0.0027, mnc=2, mxc=25, mnh=0.5, atr=200):
        bd = (self.b2p - self.b1p) / self.b1p
        if bd > 0 or bd < -mbd: return False
        g = self.b2i - self.b1i
        if g < mnc or g > mxc: return False
        if self.h < mnh * atr: return False
        return True
    def to_dict(self):
        return {"b1i":self.b1i,"b2i":self.b2i,"b1p":self.b1p,"b2p":self.b2p,
                "nl":self.nl,"h":self.h,"tp":self.tp,"b1v":self.b1v,"b2v":self.b2v}


class CVDDiv:
    def __init__(self, win=5, md=0.3):
        self.win, self.md = win, md
    def check(self, cvd, prices):
        if len(cvd) < self.win+1 or len(prices) < self.win+1: return None
        cc = cvd[-1] - cvd[-(self.win+1)]
        pc = prices[-1] - prices[-(self.win+1)]
        if pc < 0 and cc > 0 and abs(cc) > abs(pc)*self.md: return "bullish"
        if pc > 0 and cc < 0 and abs(cc) > abs(pc)*self.md: return "bearish"
        return None


class EntrySignal:
    def __init__(self, pat, zone, score, div=None):
        self.pat, self.zone, self.score, self.div = pat, zone, score, div
        self.entry = self.sl = 0.0
        self.targets = []
        self.ts = time.time()
    def calc_risk(self, atr, rpct=0.02, sl_atr=1.0, bal=10000.0):
        self.entry = self.pat.nl
        zp = self.zone["price"]
        self.sl = zp - (atr*sl_atr) if self.zone["type"]=="support" else zp + (atr*sl_atr)
        rps = abs(self.entry - self.sl)
        if rps <= 0: return {"valid": False, "reason": "zero_risk"}
        mr = bal * rpct
        pos = mr / rps
        rr = abs((self.pat.tp - self.entry)) / rps
        return {"valid": rr>=1.5, "rr": round(rr,2), "entry":self.entry, "sl":self.sl,
                "target":self.pat.tp, "size":pos, "risk":mr, "rps":rps}


class SignalGate:
    def __init__(self, config=None):
        self.cfg = config or DEFAULT_CONFIG
        sg = self.cfg.signal_gate
        self.cvd = CVDDiv(sg.cvd_divergence_window, sg.cvd_divergence_min_delta)
        self.consec_loss = 0
        self.daily_pnl = 0.0
        self.last_day = ""
    def evaluate(self, pat, zone, score, market, detections, bal, day):
        if day != self.last_day:
            self.daily_pnl = 0.0; self.last_day = day
        if self.daily_pnl <= -self.cfg.signal_gate.daily_loss_limit_pct * bal:
            return None
        if self.consec_loss >= self.cfg.signal_gate.max_consecutive_losses:
            return None
        if score < self.cfg.signal_gate.db_min_conviction_score:
            return None
        atr = detections.get("atr", 0)
        if not pat.valid(atr=atr):
            return None
        div = None
        if self.cfg.signal_gate.require_cvd_divergence:
            cvd_data = market.get("cvd", {})
            cvd_vals = list(cvd_data.get("per_exchange", {}).values()) if cvd_data else []
            if cvd_vals:
                div = self.cvd.check(cvd_vals, [pat.b1p, pat.b2p])
            if not div:
                return None
        if self.cfg.signal_gate.require_expanding_volume:
            if pat.b1v > 0 and pat.b2v > pat.b1v * self.cfg.signal_gate.b2_volume_ratio_max:
                return None
        sig = EntrySignal(pat, zone, score, div)
        risk = sig.calc_risk(atr, self.cfg.signal_gate.risk_per_trade_pct,
                              self.cfg.signal_gate.sl_behind_zone_atr, bal)
        if not risk["valid"]:
            return None
        sig.targets = [risk["target"]]
        return sig
    def record(self, pnl_pct, day):
        self.daily_pnl += pnl_pct
        self.consec_loss = 0 if pnl_pct > 0 else self.consec_loss + 1
    def reset(self):
        self.consec_loss = 0; self.daily_pnl = 0.0; self.last_day = ""
