"""
BACKBAT v3 -- Layer 2: Detection & Filtering
ATR, Sweeps, Zones, Classifier, Volume Profile
"""
import logging
from collections import defaultdict
from typing import List, Optional
from config import DEFAULT_CONFIG
logger = logging.getLogger("backbat.detection")


class ATR:
    def __init__(self, period=20):
        self.period, self.vals = period, []
    def add(self, h, l, pc):
        tr = h - l
        if self.vals:
            tr = max(tr, abs(h-pc), abs(l-pc))
        self.vals.append(tr)
        if len(self.vals) > self.period*3:
            self.vals = self.vals[-self.period*3:]
        return self.cur()
    def cur(self):
        if not self.vals: return 0.0
        return sum(self.vals[-self.period:]) / min(self.period, len(self.vals[-self.period:]))


class SweepDetect:
    def __init__(self, mult=1.3, min_pct=0.0005):
        self.mult, self.min_pct = mult, min_pct
    def check(self, price, level, atr):
        return abs(price-level) > max(atr*self.mult, price*self.min_pct) if atr > 0 else abs(price-level) > price*self.min_pct


class SwingDetect:
    def __init__(self, lb=5, lf=5):
        self.lb, self.lf = lb, lf
    def low(self, vals, i):
        if i < self.lb or i >= len(vals)-self.lf: return False
        v = vals[i]
        return all(vals[i-j] > v for j in range(1,self.lb+1)) and all(vals[i+j] > v for j in range(1,self.lf+1))
    def high(self, vals, i):
        if i < self.lb or i >= len(vals)-self.lf: return False
        v = vals[i]
        return all(vals[i-j] < v for j in range(1,self.lb+1)) and all(vals[i+j] < v for j in range(1,self.lf+1))


class Zone:
    def __init__(self, zt, price, strength=1.0):
        self.type, self.price, self.strength = zt, price, strength
        self.outcomes = []
    def classify(self, after):
        if not after: return "unknown"
        if self.type == "resistance":
            mx, mn = max(after), min(after)
            if mx > self.price*1.003: return "breakout"
            if mn < self.price*0.998: return "bounce"
            return "sweep_reverse"
        else:
            mn, mx = min(after), max(after)
            if mn < self.price*0.997: return "breakout"
            if mx > self.price*1.002: return "bounce"
            return "sweep_reverse"
    def br(self, t):
        if not self.outcomes: return 0.0
        return sum(1 for o in self.outcomes if o==t)/len(self.outcomes)
    def to_dict(self):
        return {"type":self.type,"price":self.price,"strength":self.strength,
                "outcomes":self.outcomes,
                "base_rates":{"bounce":self.br("bounce"),
                             "sweep_reverse":self.br("sweep_reverse"),
                             "breakout":self.br("breakout")}}


class Classifier:
    def __init__(self, min_samples=10):
        self.min_samples, self.zones = min_samples, []
    def add(self, z, after):
        z.outcomes.append(z.classify(after))
        self.zones.append(z)
    def br(self, zt, t):
        rel = [z for z in self.zones if z.type==zt and len(z.outcomes)>=self.min_samples]
        if not rel: return 0.0
        outs = [o for z in rel for o in z.outcomes]
        return sum(1 for o in outs if o==t)/len(outs) if outs else 0.0


class VolProf:
    def __init__(self, window=100, hvn=1.3):
        self.window, self.hvn = window, hvn
        self.levels = defaultdict(list)
    def add(self, h, l, vol):
        self.levels[round((h+l)/20)*20].append(vol)
    def dens(self, price):
        vols = self.levels.get(round(price/20)*20, [])
        all_v = [v for vals in self.levels.values() for v in vals]
        if not all_v: return 1.0
        return (sum(vols)/len(vols))/(sum(all_v)/len(all_v)) if vols else 0
    def is_hvn(self, p):
        return self.dens(p) >= self.hvn


class DetectLayer:
    def __init__(self, config=None):
        self.cfg = config or DEFAULT_CONFIG
        df = self.cfg.detection_filter
        self.atr = ATR(df.atr_length)
        self.sweep = SweepDetect(df.sweep_atr_multiplier, df.sweep_min_pct if hasattr(df, 'sweep_min_pct') else 0.0005)
        self.swing = SwingDetect(df.swing_lookback, df.swing_lookforward)
        self.clf = Classifier(df.zone_classifier_min_samples)
        self.vp = VolProf(self.cfg.scoring.vp_window_bars, self.cfg.scoring.vp_hvn_threshold_mult)
        self.zones, self._h, self._l = [], [], []
    def process(self, o, h, l, c, vol, idx):
        prev = self._l[-1] if self._l else o
        atr = self.atr.add(h, l, prev)
        self.vp.add(h, l, vol)
        sig = {"atr": atr, "sweeps": [], "new_zones": []}
        self._h.append(h); self._l.append(l)
        ph = [i for i in range(len(self._h)) if self.swing.high(self._h, i)][-3:]
        pl = [i for i in range(len(self._l)) if self.swing.low(self._l, i)][-3:]
        for p in ph:
            if p >= idx-2:
                z = Zone("resistance", self._h[p])
                self.zones.append(z); sig["new_zones"].append(z.to_dict())
        for p in pl:
            if p >= idx-2:
                z = Zone("support", self._l[p])
                self.zones.append(z); sig["new_zones"].append(z.to_dict())
        for z in self.zones[-20:]:
            if self.sweep.check(c, z.price, atr):
                sig["sweeps"].append({"price":z.price,"type":z.type})
        return sig
    def near_zone(self, price, atr):
        for z in self.zones:
            if abs(price-z.price) <= atr*self.cfg.signal_gate.db_zone_distance_max_atr:
                return z
        return None
