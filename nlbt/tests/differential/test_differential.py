"""P4-T11 differential testing: nlbt engine vs backtesting.py 0.6.6 (dev-only oracle).

ROADMAP P4-T11: reproduce simple strategies in an independent, well-known
backtesting library with MATCHED conventions and compare trade lists and
equity within a stated tolerance; every discrepancy must be explained in
docs/differential_notes.md (owner review 2026-10-18).

Owner-ratified conventions (2026-10-18, docs/differential_notes.md entries):
* constant 10 shares both sides (sizing ``fixed_shares``=10 / ``buy(size=10)``);
* ``fixed_fee = 0``; Pass 1 zero costs, Pass 2 fee_bps=10 + slippage_bps=5;
* ``finalize_trades=True`` pinned in EVERY backtesting run (entry #2);
* S1 (buy-and-hold) cannot drain: its settlement exit is EXCLUDED from the
  price comparison (backtesting settles at last OPEN, nlbt at last CLOSE —
  entry #3); entry fill + pre-settlement equity are compared instead;
* S2-S6 drain before the final bar (owner-approved); S6 = fixed
  ``stop_loss_pct``=5 with two designed stop events (one intrabar touch
  filling at the level, one gap-through filling at the open);
* tolerance rule (owner verbatim): EXACT equality on trade count,
  entry/exit timestamps, exit reasons and share counts; prices and equity
  (every equity row) within rel 1e-9 with abs floor 1e-6. Never widen a
  tolerance to make a test pass — explain or log to OPEN_QUESTIONS.md.

Matched cost model (validated by probe, notes #9): backtesting runs with
``spread=0`` and a float ``commission`` rate; slippage enters ONLY through
per-role Open transforms (fill-funding bars get ``open*(1+slip)`` for buys /
``open*(1-slip)`` for sells; S5's/S6's stop levels are pre-slipped). Commission
``|size| * price * rate`` then lands on the slipped fill on both sides,
exactly the §4.5 ``shares * fill * fee_bps/10000`` formula.

Independent implementations: signal arrays below are written from the
documented §4.2/indicator conventions (rolling SMA, §4.2 crossover kernel,
Wilder RSI with SMA seed valid from index ``period``, shift(1) rolling
highest/lowest) — never imported from nlbt. The harness ratchet follows the
ROADMAP §4.5 written rule only (trail = highest high since entry up to
t-1 times (1-pct), ratcheted after bar t's check).

Known, documented differences (see differential_notes.md):
* backtesting's ``strategy.next()`` starts at bar 1 (nlbt can act on a bar-0
  signal); every fixture's first signal is at bar >= 1 so this never bites.
* TrailingStrategy (lib) is NOT used — value levels can never match a
  high-times-(1-pct) trail (notes #8); S5 ratchets by hand in next().
"""

from __future__ import annotations

import math
import warnings
from typing import Any

import numpy as np
import pandas as pd
import pytest
from backtesting import Backtest, Strategy

from nlbt.data.models import Bars
from nlbt.engine.backtest import run as nlbt_run
from nlbt.engine.risk import RiskManager
from nlbt.spec.models import StrategySpec

# --------------------------------------------------------------------------- #
# Owner-pinned constants (2026-10-18)
# --------------------------------------------------------------------------- #

CAPITAL = 10_000.0
SHARES = 10.0
TRAIL_PCT = 3.0  # S5 trail is 3%, not 5% (owner correction 2026-10-18)
STOP_PCT = 5.0  # S6 fixed stop (owner request 2026-10-18)

#: how the harness labels a closure it did NOT place itself (risk exits)
CLOSE_REASON = {
    "signal": "signal",
    "hold": "end_of_data",
    "trail": "trailing_stop",
    "stop": "stop_loss",
}

#: owner tolerance rule: prices and every equity row rel 1e-9, abs floor 1e-6
PRICE_REL = 1e-9
PRICE_ABS = 1e-6

PASSES = [
    ("pass1_zero_cost", 0.0, 0.0),
    ("pass2_costs_fee10bp_slip5bp", 10.0, 5.0),
]

_OHLC_ROWS = list[tuple[float, float, float, float]]


# --------------------------------------------------------------------------- #
# Fixture builders (deterministic, dated; inputs only — no engine logic)
# --------------------------------------------------------------------------- #


def _bars(rows: _OHLC_ROWS) -> Bars:
    """Validated nlbt Bars from explicit (open, high, low, close) rows."""
    idx = pd.date_range("2024-01-01", periods=len(rows), freq="D", tz="UTC")
    frame = pd.DataFrame(
        {
            "open": [float(r[0]) for r in rows],
            "high": [float(r[1]) for r in rows],
            "low": [float(r[2]) for r in rows],
            "close": [float(r[3]) for r in rows],
            "volume": [1000.0] * len(rows),
        },
        index=idx,
    )
    return Bars(frame)


def _bt_frame(rows: _OHLC_ROWS, fills: list[tuple[int, float]]) -> pd.DataFrame:
    """backtesting DataFrame: Open transformed ONLY on bars funding a fill.

    ``fills`` pairs each fill-funding bar with its SIGNED slip rate:
    ``+slip`` for entry fills (adverse for the buy), ``-slip`` for exit
    fills (adverse for the sell). High/low stay raw so hit-tests match
    nlbt's raw-level checks; asserts keep OHLC sane.
    """
    idx = pd.date_range("2024-01-01", periods=len(rows), freq="D", tz="UTC")
    opens = [float(r[0]) for r in rows]
    for b, rate in fills:
        opens[b] = opens[b] * (1.0 + rate)
    for b, _ in fills:
        assert opens[b] < rows[b][1], f"bar {b}: open' {opens[b]} exceeds high {rows[b][1]}"
        assert opens[b] > rows[b][2], f"bar {b}: open' {opens[b]} below low {rows[b][2]}"
    return pd.DataFrame(
        {
            "Open": opens,
            "High": [float(r[1]) for r in rows],
            "Low": [float(r[2]) for r in rows],
            "Close": [float(r[3]) for r in rows],
            "Volume": [1000.0] * len(rows),
        },
        index=idx,
    )


# --------------------------------------------------------------------------- #
# Independent signal implementations (documented conventions, NOT nlbt code)
# --------------------------------------------------------------------------- #


def _sma(values: np.ndarray, window: int) -> np.ndarray:
    """Plain rolling mean, min_periods=window (NaN during warm-up)."""
    return (
        pd.Series(values, dtype=float)
        .rolling(window, min_periods=window)
        .mean()
        .to_numpy(dtype=float)
    )


def _crosses_above(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """§4.2: a[t-1] <= b[t-1] AND a[t] > b[t]; NaN anywhere -> False; idx 0 False."""
    out = np.zeros(len(a), dtype=bool)
    if len(a) < 2:
        return out
    with np.errstate(invalid="ignore"):
        out[1:] = (a[:-1] <= b[:-1]) & (a[1:] > b[1:])
    return out


def _crosses_below(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """§4.2: a[t-1] >= b[t-1] AND a[t] < b[t]; NaN anywhere -> False."""
    out = np.zeros(len(a), dtype=bool)
    if len(a) < 2:
        return out
    with np.errstate(invalid="ignore"):
        out[1:] = (a[:-1] >= b[:-1]) & (a[1:] < b[1:])
    return out


def _rsi(close: np.ndarray, period: int) -> np.ndarray:
    """Wilder RSI, SMA seed placed at index `period` (ADR-0003 convention).

    gains[j] / losses[j] are the change from bar j to j+1; the seed is the
    plain mean of gains/losses[0..period-1] (i.e. changes 1..period) placed at
    bar `period`; recursion afterwards: avg = (avg*(p-1) + x)/p.
    """
    n = len(close)
    out = np.full(n, np.nan)
    diff = np.diff(close)
    gains = np.where(diff > 0.0, diff, 0.0)
    losses = np.where(diff < 0.0, -diff, 0.0)
    if n <= period:
        return out
    avg_gain = float(gains[:period].mean())
    avg_loss = float(losses[:period].mean())
    out[period] = 100.0 - 100.0 / (1.0 + (avg_gain / avg_loss if avg_loss > 0 else math.inf))
    for t in range(period + 1, n):
        avg_gain = (avg_gain * (period - 1) + gains[t - 1]) / period
        avg_loss = (avg_loss * (period - 1) + losses[t - 1]) / period
        out[t] = 100.0 - 100.0 / (1.0 + (avg_gain / avg_loss if avg_loss > 0 else math.inf))
    return out


def _highest_excl(high: np.ndarray, window: int) -> np.ndarray:
    """Highest of the `window` PRIOR highs, excluding the current bar."""
    return (
        pd.Series(high, dtype=float)
        .shift(1)
        .rolling(window, min_periods=window)
        .max()
        .to_numpy(dtype=float)
    )


def _lowest_excl(low: np.ndarray, window: int) -> np.ndarray:
    """Lowest of the `window` PRIOR lows, excluding the current bar."""
    return (
        pd.Series(low, dtype=float)
        .shift(1)
        .rolling(window, min_periods=window)
        .min()
        .to_numpy(dtype=float)
    )


# --------------------------------------------------------------------------- #
# Scenarios S1-S5
# --------------------------------------------------------------------------- #


def _spec_payload(
    *,
    entry: dict[str, Any],
    exit_long: dict[str, Any] | None = None,
    indicators: dict[str, Any] | None = None,
    risk: dict[str, Any] | None = None,
    fee_bps: float,
    slippage_bps: float,
    name: str,
) -> StrategySpec:
    """Valid §4.1 StrategySpec: fixed 10 shares, fixed_fee 0, next_open fill."""
    rules: dict[str, Any] = {"entry_long": entry}
    if exit_long is not None:
        rules["exit_long"] = exit_long
    return StrategySpec.model_validate(
        {
            "spec_version": "1.0",
            "name": name,
            "universe": {"symbols": ["TEST"], "interval": "1d"},
            "period": {"start": "2024-01-01", "end": "2024-12-31"},
            "indicators": indicators or {},
            "rules": rules,
            "risk": risk or {},
            "sizing": {
                "method": "fixed_shares",
                "value": SHARES,
                "allow_fractional": True,
            },
            "execution": {
                "fill": "next_open",
                "fee_bps": fee_bps,
                "slippage_bps": slippage_bps,
                "fixed_fee": 0.0,
            },
            "capital": {"initial": CAPITAL},
        }
    )


def _s1_hold() -> dict[str, Any]:
    """S1 buy-and-hold: enter bar 1 (fill 2), never exit; wide LAST-bar gap
    (open 125 vs close 111) so the settlement-convention divergence is loud."""
    n = 12
    closes = [100.0 + t for t in range(n)]
    rows: _OHLC_ROWS = [(c, c + 1.0, c - 1.0, c) for c in closes]
    rows[-1] = (125.0, 126.0, 110.0, closes[-1])  # low <= min(open, close) ok
    closes_arr = np.array(closes)
    with np.errstate(invalid="ignore"):
        entry_sig = closes_arr > 100.0  # True from bar 1 only (100 > 100 False)
    assert np.flatnonzero(entry_sig)[0] == 1
    return {
        "name": "s1_buy_and_hold",
        "kind": "hold",
        "rows": rows,
        "n": n,
        "entry_sig": entry_sig,
        "exit_sig": None,
        "entry_bars": [1],
        "exit_bars": [],
        "reason": "end_of_data",
        "spec": {
            "entry": {"all": [{"left": "close", "op": ">", "right": 100.0}]},
            "exit_long": None,
            "indicators": None,
            "risk": None,
        },
    }


def _s2_sma_cross() -> dict[str, Any]:
    """S2 SMA cross: down -> rally (up-cross) -> decline (down-cross) -> tail.

    Monotone segments give exactly one crossing each way; exit fills early,
    well before the final bar (drain approved)."""
    closes = (
        [100.0 - t for t in range(12)]
        + [92.0 + 3.0 * k for k in range(10)]
        + [115.0 - 4.0 * k for k in range(10)]
        + [74.5 - 0.5 * k for k in range(8)]
    )
    rows: _OHLC_ROWS = [(c, c + 1.0, c - 1.0, c) for c in closes]
    close = np.array(closes)
    fast, slow = _sma(close, 4), _sma(close, 9)
    entry_sig = _crosses_above(fast, slow)
    exit_sig = _crosses_below(fast, slow)
    assert np.count_nonzero(entry_sig) == 1, "S2 fixture must cross up exactly once"
    assert np.count_nonzero(exit_sig) == 1, "S2 fixture must cross down exactly once"
    e = int(np.flatnonzero(entry_sig)[0])
    x = int(np.flatnonzero(exit_sig)[0])
    assert x + 1 < len(closes) - 1, "S2 must drain before the final bar"
    return {
        "name": "s2_sma_cross",
        "kind": "signal",
        "rows": rows,
        "n": len(closes),
        "entry_sig": entry_sig,
        "exit_sig": exit_sig,
        "entry_bars": [e],
        "exit_bars": [x],
        "reason": "signal",
        "spec": {
            "entry": {"all": [{"left": "fast", "op": "crosses_above", "right": "slow"}]},
            "exit_long": {"all": [{"left": "fast", "op": "crosses_below", "right": "slow"}]},
            "indicators": {
                "fast": {"type": "sma", "params": {"period": 4}, "source": "close"},
                "slow": {"type": "sma", "params": {"period": 9}, "source": "close"},
            },
            "risk": None,
        },
    }


def _s3_rsi_reversion() -> dict[str, Any]:
    """S3 RSI mean-reversion: sawtooth base (RSI stays 30-70), one engineered
    dip (RSI < 30 -> entry), one recovery (RSI > 60 -> exit), flat tail."""
    n = 48
    base = [100.0 + 1.5 * math.sin(0.7 * t) for t in range(n)]
    dip = [0.0] * n
    for t in range(24, 30):
        dip[t] = 3.0 * (t - 23)  # 3 .. 18
    for t in range(30, 41):
        dip[t] = max(18.0 - 1.5 * (t - 29), 1.5)  # 18 .. 1.5
    for t in range(41, n):
        dip[t] = 1.5
    closes = [base[t] - dip[t] for t in range(n)]
    rows: _OHLC_ROWS = [(c, c + 1.5, c - 1.5, c) for c in closes]
    rsi = _rsi(np.array(closes), 14)
    with np.errstate(invalid="ignore"):
        entry_sig = rsi < 30.0
        exit_sig = rsi > 60.0
    e = int(np.flatnonzero(entry_sig)[0])
    x = int(np.flatnonzero(exit_sig)[0])
    assert x > e, "S3 recovery must follow the dip"
    assert x + 1 < n - 1, "S3 must drain before the final bar"
    # after the exit, RSI must never dip below 30 again (no re-entry)
    assert not entry_sig[x + 1 :].any(), "S3 fixture must not re-enter"
    return {
        "name": "s3_rsi_reversion",
        "kind": "signal",
        "rows": rows,
        "n": n,
        "entry_sig": entry_sig,
        "exit_sig": exit_sig,
        "entry_bars": [e],
        "exit_bars": [x],
        "reason": "signal",
        "spec": {
            "entry": {"all": [{"left": "rsi", "op": "<", "right": 30.0}]},
            "exit_long": {"all": [{"left": "rsi", "op": ">", "right": 60.0}]},
            "indicators": {"rsi": {"type": "rsi", "params": {"period": 14}, "source": "close"}},
            "risk": None,
        },
    }


def _s4_donchian() -> dict[str, Any]:
    """S4 Donchian breakout: range base -> breakout (close > prior-20 high)
    -> plateau -> collapse (close < prior-10 low -> drain)."""
    n = 45
    closes: list[float] = [100.0 + 0.8 * math.sin(0.8 * t) for t in range(25)]
    closes += [105.0 + 2.4 * k for k in range(9)]  # bars 25..33 -> 124.2
    closes += [124.2, 123.8, 124.2, 123.8, 124.2]  # plateau 34..38
    closes += [119.2, 114.2, 109.2, 104.2, 99.2, 94.2]  # collapse 39..44
    rows: _OHLC_ROWS = [(c, c + 1.2, c - 1.2, c) for c in closes]
    high = np.array([r[1] for r in rows])
    low = np.array([r[2] for r in rows])
    close = np.array(closes)
    with np.errstate(invalid="ignore"):
        entry_sig = close > _highest_excl(high, 20)
        exit_sig = close < _lowest_excl(low, 10)
    entry_bars = np.flatnonzero(entry_sig)
    exit_bars = np.flatnonzero(exit_sig)
    assert entry_bars[0] == 25, f"S4 entry at {entry_bars[0]}, expected 25"
    x = int(exit_bars[0])
    assert x > entry_bars[0], "S4 exit must follow the entry"
    assert x + 1 < n - 1, "S4 must drain before the final bar"
    assert not entry_sig[x + 1 :].any(), "S4 fixture must not re-enter"
    return {
        "name": "s4_donchian_breakout",
        "kind": "signal",
        "rows": rows,
        "n": n,
        "entry_sig": entry_sig,
        "exit_sig": exit_sig,
        "entry_bars": [25],
        "exit_bars": [x],
        "reason": "signal",
        "spec": {
            "entry": {"all": [{"left": "close", "op": ">", "right": "hh"}]},
            "exit_long": {"all": [{"left": "close", "op": "<", "right": "ll"}]},
            "indicators": {
                "hh": {"type": "highest", "params": {"period": 20}, "source": "high"},
                "ll": {"type": "lowest", "params": {"period": 10}, "source": "low"},
            },
            "risk": None,
        },
    }


def _s5_trailing() -> dict[str, Any]:
    """S5 trailing stop (3%): cross above 100 -> rally (trail ratchets) ->
    one deep trigger bar (drains) -> drift below 100 (no re-entry).

    Entry-bar invariant (owner condition): low[entry] > fill * 0.97 must hold
    for BOTH passes and BOTH sides; asserted from ACTUAL fills in test_s5.
    """
    closes = [95.0, 99.5, 100.5] + [101.5 + 1.2 * k for k in range(11)]
    closes += [114.7]  # bar 14: last pre-trigger bar
    closes += [113.0, 104.0, 101.0, 98.0, 95.5]  # bars 15..19: trigger + drift
    opens = [94.8] + [closes[t - 1] + 0.2 for t in range(1, len(closes))]
    rows: _OHLC_ROWS = [(o, o + 1.0, c - 1.0, c) for o, c in zip(opens, closes, strict=True)]
    rows[15] = (rows[15][0], rows[15][1], 106.0, rows[15][3])  # trigger wick
    n = len(closes)
    assert n == 20
    close = np.array(closes)
    with np.errstate(invalid="ignore"):
        entry_sig = _crosses_above(close, np.full(n, 100.0))
    assert np.count_nonzero(entry_sig) == 1, "S5 must cross 100 exactly once"
    e = int(np.flatnonzero(entry_sig)[0])
    assert e == 2, f"S5 entry bar {e}, expected 2"
    # margins (bt threshold is pre-slipped => slightly looser than nlbt's raw
    # threshold; if bt is safe, nlbt is safe with the same margin):
    fill_bar = e + 1
    trail_high = max(opens[fill_bar] * 1.0005, rows[fill_bar][1])
    for t in range(fill_bar, 15):
        thr = trail_high * (1.0 - TRAIL_PCT / 100.0) * (1.0 - 5.0 / 10_000.0)
        assert rows[t][2] > thr, f"bar {t}: low {rows[t][2]} would trigger trail {thr}"
        trail_high = max(trail_high, rows[t][1])
    thr_trigger = trail_high * (1.0 - TRAIL_PCT / 100.0)
    assert rows[15][2] < thr_trigger, "bar 15 must pierce the trail (both engines)"
    assert rows[15][0] > thr_trigger * (1.0 - 5.0 / 10_000.0), "bar 15 must be non-gap"
    assert not entry_sig[16:].any(), "S5 fixture must not re-enter"
    return {
        "name": "s5_trailing_stop",
        "kind": "trail",
        "rows": rows,
        "n": n,
        "entry_sig": entry_sig,
        "exit_sig": None,
        "entry_bars": [e],
        "exit_bars": [15],
        "reason": "trailing_stop",
        "spec": {
            "entry": {"all": [{"left": "close", "op": "crosses_above", "right": 100.0}]},
            "exit_long": None,
            "indicators": None,
            "risk": {"trailing_stop_pct": TRAIL_PCT},
        },
    }


def _s6_stop_loss() -> dict[str, Any]:
    """S6 fixed stop-loss (5%): two trades, two designed stop events.

    Trade 1 exits via an INTRABAR TOUCH (open above the stop -> fill at the
    level); trade 2 exits via a GAP down through the stop (open below the
    stop -> fill at the open). Both fills are pre-slipped by both engines.
    """
    rows: _OHLC_ROWS = [
        (95.0, 96.0, 94.0, 95.5),
        (95.5, 97.0, 95.0, 96.5),
        (96.5, 100.6, 96.0, 100.4),  # close crosses above 100 -> entry signal
        (100.0, 100.8, 99.0, 99.5),  # entry 1 fill; low clears the stop
        (99.5, 100.2, 98.0, 99.8),
        (99.8, 100.5, 98.5, 100.1),
        (100.1, 100.8, 99.2, 100.3),
        (98.0, 99.0, 93.0, 96.0),  # stop event 1: intrabar TOUCH (non-gap)
        (96.5, 101.8, 96.2, 101.5),  # recovery; close > 100 -> entry signal
        (102.0, 102.8, 101.4, 102.5),  # entry 2 fill; low clears the stop
        (102.5, 103.2, 101.0, 102.8),
        (102.8, 103.5, 101.5, 103.0),
        (90.0, 91.0, 88.0, 89.0),  # stop event 2: GAP down through the stop
        (89.0, 90.0, 87.5, 88.5),
        (88.5, 89.5, 87.0, 88.0),
        (88.0, 89.0, 86.5, 87.5),
        (87.5, 88.5, 86.0, 87.0),
    ]
    n = len(rows)
    assert n == 17
    close = np.array([r[3] for r in rows])
    with np.errstate(invalid="ignore"):
        entry_sig = _crosses_above(close, np.full(n, 100.0))
    entry_bars = [int(b) for b in np.flatnonzero(entry_sig)]
    assert entry_bars == [2, 5, 8], f"S6 entry signals changed: {entry_bars}"
    # bar 5's signal fires while trade 1 is open — both engines ignore
    # entries while in position (§4.5 step 4); the fills happen at 3 and 9
    entry_bars = [2, 8]
    assert not entry_sig[13:].any(), "S6 fixture must not re-enter after the gap"

    # margins, worst case = pass 2 (its stop level is the highest and its
    # pre-slipped bt threshold the lowest of the two passes):
    stop1 = 100.0 * (1.0 + 5.0 / 10_000.0) * (1.0 - STOP_PCT / 100.0)
    stop2 = 102.0 * (1.0 + 5.0 / 10_000.0) * (1.0 - STOP_PCT / 100.0)
    assert rows[3][2] > stop1 and rows[9][2] > stop2, "entry bars must clear the stop"
    for t in (4, 5, 6):
        assert rows[t][2] > stop1, f"bar {t} must not trigger early"
    for t in (10, 11):
        assert rows[t][2] > stop2, f"bar {t} must not trigger early"
    assert rows[7][0] > stop1, "touch bar must be NON-gap (open above the stop)"
    assert rows[7][2] < stop1 * (1.0 - 5.0 / 10_000.0), "touch must pierce bt's threshold"
    assert rows[12][0] < 96.0, "gap bar must open below even pass 1's stop"
    assert rows[12][2] < rows[12][0] * (1.0 - 5.0 / 10_000.0) < rows[12][1]

    return {
        "name": "s6_fixed_stop_loss",
        "kind": "stop",
        "rows": rows,
        "n": n,
        "entry_sig": entry_sig,
        "exit_sig": None,
        "entry_bars": entry_bars,
        "exit_bars": [7, 12],
        "gap_bars": [12],
        "reason": "stop_loss",
        "spec": {
            "entry": {"all": [{"left": "close", "op": "crosses_above", "right": 100.0}]},
            "exit_long": None,
            "indicators": None,
            "risk": {"stop_loss_pct": STOP_PCT},
        },
    }


SCENARIOS = {
    "s1": _s1_hold(),
    "s2": _s2_sma_cross(),
    "s3": _s3_rsi_reversion(),
    "s4": _s4_donchian(),
    "s5": _s5_trailing(),
    "s6": _s6_stop_loss(),
}


# --------------------------------------------------------------------------- #
# Harness: backtesting.py strategy (hand-written, §4.5 rule for the ratchet)
# --------------------------------------------------------------------------- #


def _make_strategy(sc: dict[str, Any], slip_rate: float) -> type[Strategy]:
    """Strategy class for scenario ``sc`` at cost pass ``slip_rate``.

    next() runs AFTER broker.next() each bar, which is exactly §4.5's
    "ratchet AFTER the check": a stop set from bar t's high is first tested
    at bar t+1 (probe b, verified_apis 2026-10-18).
    """
    entry_sig = sc["entry_sig"]
    exit_sig = sc["exit_sig"]
    kind = sc["kind"]
    close_reason = CLOSE_REASON[kind]

    class DiffStrategy(Strategy):
        seeded_trail_raw: float | None = None
        trail_high: float | None = None
        _was_in = False
        _close_pending = False

        def init(self) -> None:
            self.reasons: list[str] = []

        def next(self) -> None:
            i = len(self.data) - 1
            if self.position:
                self._was_in = True
                if kind == "trail":
                    trade = self.trades[-1]
                    base = self.trail_high if self.trail_high is not None else trade.entry_price
                    hh = max(base, float(self.data.High[-1]))
                    self.trail_high = hh
                    level_raw = hh * (1.0 - TRAIL_PCT / 100.0)  # §4.5, from raw highs
                    if self.seeded_trail_raw is None:
                        self.seeded_trail_raw = level_raw  # level for bar entry+1
                    slipped = level_raw * (1.0 - slip_rate)  # fills: nlbt slips the sell
                    trade.sl = max(trade.sl or -math.inf, slipped)
                elif kind == "stop":
                    # fixed stop, same pre-slip method as S5; derived from the
                    # ACTUAL bt entry fill (== open*(1+slip) == nlbt's fill)
                    trade = self.trades[-1]
                    stop_raw = trade.entry_price * (1.0 - STOP_PCT / 100.0)
                    trade.sl = stop_raw * (1.0 - slip_rate)
                if exit_sig is not None and bool(exit_sig[i]) and not self._close_pending:
                    self.position.close()
                    self._close_pending = True
            else:
                if self._was_in:
                    closed_by = "signal" if self._close_pending else close_reason
                    self.reasons.append(closed_by)
                    self._was_in = False
                    self._close_pending = False
                if bool(entry_sig[i]):
                    self.buy(size=SHARES)

    return DiffStrategy


def _run_bt(
    sc: dict[str, Any], slip_bps: float, fee_bps: float
) -> tuple[Any, type[Strategy], pd.DataFrame]:
    """Run scenario ``sc`` under backtesting.py with the matched conventions.

    ``finalize_trades=True`` is pinned (condition 1). Slippage: entry-fill
    bar gets open*(1+slip); signal-exit fill bars get open*(1-slip); S5's
    stop level is pre-slipped inside the strategy (non-gap fixture).
    """
    slip_rate = slip_bps / 10_000.0
    fills: list[tuple[int, float]] = [(b + 1, slip_rate) for b in sc["entry_bars"]]
    if sc["kind"] == "signal":
        fills += [(b + 1, -slip_rate) for b in sc["exit_bars"]]
    fills += [(b, -slip_rate) for b in sc.get("gap_bars", [])]  # gap fills: pre-slip the open
    frame = _bt_frame(sc["rows"], fills)
    strat_cls = _make_strategy(sc, slip_rate)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        stats = Backtest(
            frame,
            strat_cls,
            cash=CAPITAL,
            commission=fee_bps / 10_000.0,  # |size| * price * rate on slipped fill
            spread=0.0,  # slippage enters via the Open transform only
            exclusive_orders=True,
            finalize_trades=True,  # condition 1: pinned in EVERY run
        ).run()
    return stats, stats["_strategy"], frame


def _run_nlbt(sc: dict[str, Any], fee_bps: float, slippage_bps: float) -> Any:
    payload = dict(sc["spec"])
    spec = _spec_payload(
        entry=payload["entry"],
        exit_long=payload["exit_long"],
        indicators=payload["indicators"],
        risk=payload["risk"],
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        name=sc["name"],
    )
    return nlbt_run(spec, _bars(sc["rows"]))


# --------------------------------------------------------------------------- #
# Comparators (owner tolerance rule — never widen)
# --------------------------------------------------------------------------- #


def _close(a: float, b: float) -> bool:
    return math.isclose(float(a), float(b), rel_tol=PRICE_REL, abs_tol=PRICE_ABS)


def _assert_prices(a: float, b: float, label: str) -> None:
    assert _close(a, b), (
        f"{label}: nlbt={a!r} bt={b!r} exceeds tolerance rel={PRICE_REL} abs={PRICE_ABS}"
    )


def _compare_trades(
    sc: dict[str, Any], res: Any, trades_df: pd.DataFrame, idx: pd.DatetimeIndex
) -> None:
    nl = res.trades
    rows = list(trades_df.iterrows())
    assert len(nl) == len(rows), f"trade count: nlbt={len(nl)} bt={len(rows)} (EXACT rule)"
    for k, (n, (_, b)) in enumerate(zip(nl, rows, strict=True)):
        assert n.entry_time == idx[int(b["EntryBar"])], (
            f"trade {k} entry timestamp: nlbt={n.entry_time} bt={idx[int(b['EntryBar'])]}"
        )
        assert n.exit_time == idx[int(b["ExitBar"])], (
            f"trade {k} exit timestamp: nlbt={n.exit_time} bt={idx[int(b['ExitBar'])]}"
        )
        assert n.exit_reason == sc["reason"], f"trade {k} reason: {n.exit_reason!r}"
        assert float(n.shares) == float(b["Size"]) == SHARES, (
            f"trade {k} shares EXACT: nlbt={n.shares} bt={b['Size']}"
        )
        _assert_prices(n.entry_price, b["EntryPrice"], f"trade {k} entry price")
        if sc["kind"] != "hold":
            _assert_prices(n.exit_price, b["ExitPrice"], f"trade {k} exit price")


def _compare_equity(
    nl_vals: list[float],
    bt_vals: list[float],
    *,
    last_row_recon: tuple[float, float, float, float] | None = None,
) -> None:
    """Every equity row rel 1e-9 / abs 1e-6 (owner rule).

    ``last_row_recon=(open_last, close_last, shares, settle_fee)`` compares
    the final row via ``bt_last - shares*(open_last - close_last) + settle_fee``
    — the pre-settlement reconstruction (S1 only). Backtesting's last row is
    POST-settlement: the finalize close fills at the last OPEN and pays the
    exit commission ``shares*open_last*rate`` (verified probe + this suite's
    pass-2 failure delta of exactly 1.25 = 10*125*0.001); nlbt's last row is
    the pre-settlement mark at the last CLOSE. Pass 1 has rate=0, so the
    settle_fee term vanishes there.
    """
    n = len(nl_vals)
    assert len(bt_vals) == n, f"equity row count: nlbt={n} bt={len(bt_vals)}"
    end = n - 1 if last_row_recon is not None else n
    for i in range(end):
        _assert_prices(nl_vals[i], bt_vals[i], f"equity row {i}")
    if last_row_recon is not None:
        open_last, close_last, shares, settle_fee = last_row_recon
        recon = float(bt_vals[-1]) - shares * (open_last - close_last) + settle_fee
        _assert_prices(nl_vals[-1], recon, "equity row last (reconstructed pre-settle)")


# --------------------------------------------------------------------------- #
# Tests — both passes
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("pas", PASSES, ids=[p[0] for p in PASSES])
def test_s1_buy_and_hold(pas: tuple[str, float, float]) -> None:
    """S1: entry fill + pre-settlement equity; settlement exit EXCLUDED
    (backtesting settles at last OPEN, nlbt at last CLOSE — notes #3)."""
    _, fee_bps, slip_bps = pas
    sc = SCENARIOS["s1"]
    res = _run_nlbt(sc, fee_bps, slip_bps)
    stats, _, frame = _run_bt(sc, slip_bps, fee_bps)
    idx = _bars(sc["rows"]).index

    _compare_trades(sc, res, stats["_trades"], idx)

    # excluded settlement trade: both engines' conventions asserted verbatim
    open_last = float(sc["rows"][-1][0])
    close_last = float(sc["rows"][-1][3])
    slip = slip_bps / 10_000.0
    bt_exit = float(stats["_trades"]["ExitPrice"].iloc[0])
    nl_exit = float(res.trades[0].exit_price)
    assert _close(bt_exit, open_last), f"bt settles at last OPEN: {bt_exit} vs {open_last}"
    assert _close(nl_exit, close_last * (1.0 - slip)), (
        f"nlbt settles slipped at last CLOSE: {nl_exit} vs {close_last * (1 - slip)}"
    )
    assert res.trades[0].exit_reason == "end_of_data"
    assert not res.warnings, f"unexpected nlbt warnings: {res.warnings}"

    _compare_equity(
        [float(v) for v in res.equity_curve["equity"]],
        [float(v) for v in stats["_equity_curve"]["Equity"]],
        last_row_recon=(open_last, close_last, SHARES, SHARES * open_last * fee_bps / 10_000.0),
    )
    # sanity: the Open transform touched only the entry-fill bar
    assert float(frame["Open"].iloc[2]) == float(sc["rows"][2][0]) * (1.0 + slip)


@pytest.mark.parametrize("pas", PASSES, ids=[p[0] for p in PASSES])
def test_s2_sma_cross(pas: tuple[str, float, float]) -> None:
    """S2: SMA cross strategy — trade list and full equity identical."""
    _, fee_bps, slip_bps = pas
    sc = SCENARIOS["s2"]
    res = _run_nlbt(sc, fee_bps, slip_bps)
    stats, _, _ = _run_bt(sc, slip_bps, fee_bps)
    assert not res.warnings, f"unexpected nlbt warnings: {res.warnings}"
    _compare_trades(sc, res, stats["_trades"], _bars(sc["rows"]).index)
    assert stats["_strategy"].reasons == ["signal"], "bt must close via the exit signal"
    _compare_equity(
        [float(v) for v in res.equity_curve["equity"]],
        [float(v) for v in stats["_equity_curve"]["Equity"]],
    )


@pytest.mark.parametrize("pas", PASSES, ids=[p[0] for p in PASSES])
def test_s3_rsi_reversion(pas: tuple[str, float, float]) -> None:
    """S3: RSI mean-reversion — trade list and full equity identical."""
    _, fee_bps, slip_bps = pas
    sc = SCENARIOS["s3"]
    res = _run_nlbt(sc, fee_bps, slip_bps)
    stats, _, _ = _run_bt(sc, slip_bps, fee_bps)
    assert not res.warnings, f"unexpected nlbt warnings: {res.warnings}"
    _compare_trades(sc, res, stats["_trades"], _bars(sc["rows"]).index)
    assert stats["_strategy"].reasons == ["signal"], "bt must close via the exit signal"
    _compare_equity(
        [float(v) for v in res.equity_curve["equity"]],
        [float(v) for v in stats["_equity_curve"]["Equity"]],
    )


@pytest.mark.parametrize("pas", PASSES, ids=[p[0] for p in PASSES])
def test_s4_donchian_breakout(pas: tuple[str, float, float]) -> None:
    """S4: Donchian breakout — trade list and full equity identical."""
    _, fee_bps, slip_bps = pas
    sc = SCENARIOS["s4"]
    res = _run_nlbt(sc, fee_bps, slip_bps)
    stats, _, _ = _run_bt(sc, slip_bps, fee_bps)
    assert not res.warnings, f"unexpected nlbt warnings: {res.warnings}"
    _compare_trades(sc, res, stats["_trades"], _bars(sc["rows"]).index)
    assert stats["_strategy"].reasons == ["signal"], "bt must close via the exit signal"
    _compare_equity(
        [float(v) for v in res.equity_curve["equity"]],
        [float(v) for v in stats["_equity_curve"]["Equity"]],
    )


@pytest.mark.parametrize("pas", PASSES, ids=[p[0] for p in PASSES])
def test_s5_trailing_stop(pas: tuple[str, float, float]) -> None:
    """S5: hand-written §4.5 ratchet in the harness (NOT lib.TrailingStrategy).

    Owner conditions (2026-10-18):
    * entry-bar invariant computed from the ACTUAL entry fill of each pass
      and each side: ``low[entry] > fill * (1 - 0.03)``, strict, never
      hard-coded;
    * the level seeded for bar entry+1 must be equal on both sides (explicit
      assertion), with each side's structural formula also asserted.
    """
    _, fee_bps, slip_bps = pas
    sc = SCENARIOS["s5"]
    res = _run_nlbt(sc, fee_bps, slip_bps)
    stats, strat, _ = _run_bt(sc, slip_bps, fee_bps)
    bars = _bars(sc["rows"])
    assert not res.warnings, f"unexpected nlbt warnings: {res.warnings}"

    _compare_trades(sc, res, stats["_trades"], bars.index)
    assert stats["_strategy"].reasons == ["trailing_stop"], "bt must close via the trail"
    _compare_equity(
        [float(v) for v in res.equity_curve["equity"]],
        [float(v) for v in stats["_equity_curve"]["Equity"]],
    )

    fill_bar = sc["entry_bars"][0] + 1
    low_entry = float(sc["rows"][fill_bar][2])
    nl_fill = float(res.trades[0].entry_price)
    bt_fill = float(stats["_trades"]["EntryPrice"].iloc[0])
    trail = 1.0 - TRAIL_PCT / 100.0
    assert low_entry > nl_fill * trail, (
        f"entry-bar invariant (nlbt): low={low_entry} not > fill {nl_fill} * {trail}"
    )
    assert low_entry > bt_fill * trail, (
        f"entry-bar invariant (bt): low={low_entry} not > fill {bt_fill} * {trail}"
    )

    # seeded level for bar entry+1: equal on both sides, explicit assertion
    entry_bar_dict = {
        "open": float(sc["rows"][fill_bar][0]),
        "high": float(sc["rows"][fill_bar][1]),
        "low": low_entry,
        "close": float(sc["rows"][fill_bar][3]),
    }
    rm = RiskManager(entry_price=nl_fill, trailing_stop_pct=TRAIL_PCT)
    assert rm.check(entry_bar_dict) is None, "nlbt must not exit on the entry bar"
    nl_seed = float(rm.trail_level)  # check() ratchets with the entry-bar high
    assert nl_seed == max(nl_fill, entry_bar_dict["high"]) * trail, (
        "nlbt seed structure: max(fill, high[entry]) * (1 - pct)"
    )
    assert strat.seeded_trail_raw is not None, "harness must record its seed"
    _assert_prices(strat.seeded_trail_raw, nl_seed, "seeded trail for bar entry+1")

    # the exit was NON-gap by fixture design, so the fill equals the stop
    # level exactly: the final (ratcheted) SL order must equal the exit fill
    bt_sl = float(stats["_trades"]["SL"].iloc[0])
    _assert_prices(
        bt_sl,
        float(stats["_trades"]["ExitPrice"].iloc[0]),
        "bt SL level == non-gap exit fill",
    )


@pytest.mark.parametrize("pas", PASSES, ids=[p[0] for p in PASSES])
def test_s6_fixed_stop_loss(pas: tuple[str, float, float]) -> None:
    """S6: fixed 5% stop — one INTRABAR TOUCH (fill at the level) and one
    GAP through the stop (fill at the open), both pre-slipped.

    Owner conditions (2026-10-18): entry-bar low clear of the stop, asserted
    from the ACTUAL fill of each pass and each side (no hard-coded price).
    """
    _, fee_bps, slip_bps = pas
    slip = slip_bps / 10_000.0
    sc = SCENARIOS["s6"]
    res = _run_nlbt(sc, fee_bps, slip_bps)
    stats, _, _ = _run_bt(sc, slip_bps, fee_bps)
    bars = _bars(sc["rows"])
    assert not res.warnings, f"unexpected nlbt warnings: {res.warnings}"

    _compare_trades(sc, res, stats["_trades"], bars.index)
    assert stats["_strategy"].reasons == ["stop_loss", "stop_loss"]
    _compare_equity(
        [float(v) for v in res.equity_curve["equity"]],
        [float(v) for v in stats["_equity_curve"]["Equity"]],
    )

    # entry-bar-low-clear: per entry, per side, from the ACTUAL fill
    bt_rows = list(stats["_trades"].iterrows())
    stop_frac = 1.0 - STOP_PCT / 100.0
    for k, entry_bar in enumerate(sc["entry_bars"]):
        low_entry = float(sc["rows"][entry_bar + 1][2])
        nl_fill = float(res.trades[k].entry_price)
        bt_fill = float(bt_rows[k][1]["EntryPrice"])
        assert low_entry > nl_fill * stop_frac, (
            f"trade {k} entry-bar invariant (nlbt): low={low_entry} not > "
            f"stop from fill {nl_fill} * {stop_frac}"
        )
        assert low_entry > bt_fill * stop_frac, (
            f"trade {k} entry-bar invariant (bt): low={low_entry} not > "
            f"stop from fill {bt_fill} * {stop_frac}"
        )

    # the two stop conventions, asserted with the exact formulas:
    # touch -> fill at the slipped LEVEL; gap -> fill at the slipped OPEN
    touch_level = res.trades[0].entry_price * stop_frac * (1.0 - slip)
    gap_open = float(sc["rows"][sc["gap_bars"][0]][0]) * (1.0 - slip)
    assert _close(res.trades[0].exit_price, touch_level), (
        f"touch fill {res.trades[0].exit_price} != slipped level {touch_level}"
    )
    assert _close(float(bt_rows[0][1]["ExitPrice"]), touch_level), (
        f"bt touch fill {bt_rows[0][1]['ExitPrice']} != slipped level {touch_level}"
    )
    assert _close(res.trades[1].exit_price, gap_open), (
        f"gap fill {res.trades[1].exit_price} != slipped open {gap_open}"
    )
    assert _close(float(bt_rows[1][1]["ExitPrice"]), gap_open), (
        f"bt gap fill {bt_rows[1][1]['ExitPrice']} != slipped open {gap_open}"
    )


# --------------------------------------------------------------------------- #
# Deliberate-break check (canary: the comparator must DETECT divergence)
# --------------------------------------------------------------------------- #


def test_deliberate_break_is_detected() -> None:
    """A deliberately corrupted oracle must trip the comparator.

    Corruptions: duplicated trade (count), bumped equity row (5e-4, far
    above float noise, far below any real bug's dollars) and a bumped exit
    price (1e-4) — each must raise, proving the harness is not vacuously
    green. A clean comparison of the same inputs must pass first.
    """
    from types import SimpleNamespace

    idx = pd.DatetimeIndex(pd.date_range("2024-01-01", periods=3, freq="D", tz="UTC"))
    nl_trade = SimpleNamespace(
        entry_time=idx[1],
        exit_time=idx[2],
        exit_reason="signal",
        shares=SHARES,
        entry_price=100.0,
        exit_price=101.0,
    )
    res = SimpleNamespace(trades=[nl_trade])
    sc = {"kind": "signal", "reason": "signal"}
    row = {"EntryBar": 1, "ExitBar": 2, "EntryPrice": 100.0, "ExitPrice": 101.0, "Size": SHARES}
    bt_rows = pd.DataFrame([row])

    _compare_trades(sc, res, bt_rows, idx)  # clean pass first
    with pytest.raises(AssertionError, match=r"trade count"):
        _compare_trades(sc, SimpleNamespace(trades=[nl_trade, nl_trade]), bt_rows, idx)
    with pytest.raises(AssertionError, match=r"exit price"):
        _compare_trades(sc, res, pd.DataFrame([{**row, "ExitPrice": 101.0001}]), idx)
    with pytest.raises(AssertionError, match=r"equity row 1"):
        _compare_equity([10000.0, 200.0, 300.0], [10000.0, 200.0005, 300.0])
