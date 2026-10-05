"""P4-T10: engine no-lookahead defences (ROADMAP §4.5, defence-table row → P4-T10).

P2-T7 proved the *indicators* are lookahead-free. This file proves the layer
that turns signals into trades — ``nlbt.engine`` — is too, which is where a peek
silently yields plausible-but-wrong P&L rather than an error.

Three defences, weakest to strongest:

1. ``test_run_truncation_invariance_of_trade_log`` — running the engine on
   ``bars[:n+k]`` must produce exactly the same trades (signal/entry/exit time,
   price, shares, reason) as running it on ``bars[:n]``, for every trade that had
   already EXITED inside the prefix.

2. ``test_engine_signal_truncation_invariance`` / ``..._poison_...`` — the
   engine's own ``evaluate_rule`` must give identical boolean arrays over the
   prefix whether the series is truncated, or whether every bar at/after a
   cutoff is scaled by an absurd factor. Poisoning is the defence that actually
   bites: a peek surfaces as a *different value* leaking backwards.

3. ``test_canary_leaky_indicator_is_caught`` — registers a deliberately leaky
   indicator whose value at bar ``t`` reads bar ``t+1`` and asserts the poison
   harness DETECTS the corruption reaching into the prefix. Without this, 1 and
   2 could be silently vacuous (a harness that compares nothing always passes),
   and the canary is defined here, in-test, so no change to the real indicators
   can accidentally repair it. This is Gate 4's "canary red" requirement.

Why signal-level rather than trade-log-only for the poison: a 1-bar lookahead
can only influence the decision at the bar immediately before the cutoff, whose
trade necessarily fills ON or after the cutoff. Such a trade is still open when
the prefix ends, so a "closed before cutoff" trade-log comparison cannot see it.
Testing ``evaluate_rule`` directly closes that gap without weakening anything.

Every test carries ``@pytest.mark.lookahead`` AND ``@pytest.mark.property``
(P4-T9 marker, registered 2026-10-05) because these are property/invariant tests
over generated series. ``deadline=None`` matches the P2-T7 profile: Windows
scheduling jitter makes per-example deadlines flaky. This is a flakiness guard,
NOT a reduced workload — ``max_examples`` still forces the full count.

Draw order matters for VALIDITY (P2-T7 convention): the series is drawn long
enough that a cutoff always leaves ``WARMUP + 4`` bars before it and at least 4
poisonable bars after it, otherwise the poison window is empty and the assertion
degenerates into a no-op.

No engine logic lives in this file — only fixtures, the harness and the canary.
If hypothesis finds a counterexample it is a REAL bug (AGENTS.md): stop, document
it in docs/OPEN_QUESTIONS.md, do NOT suppress it or shrink the example budget.
"""

from __future__ import annotations

from typing import Any

import hypothesis.strategies as st
import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings

from nlbt.data.models import Bars
from nlbt.engine.backtest import run
from nlbt.engine.signals import evaluate_rule
from nlbt.indicators.registry import IndicatorSpec, Registry
from nlbt.spec.models import StrategySpec

pytestmark = [pytest.mark.lookahead, pytest.mark.property]

#: PR-CI example budget (P2-T7 profile); nightly can raise it.
EXAMPLES = 100

#: SMA(5) needs 4 bars of history before its first valid output.
WARMUP = 5

PROFILE = settings(max_examples=EXAMPLES, deadline=None)

_ENTRY_RULE: dict[str, Any] = {"all": [{"left": "close", "op": ">", "right": "sma5"}]}
_EXIT_RULE: dict[str, Any] = {"all": [{"left": "close", "op": "<", "right": "sma5"}]}

# NOTE: the engine is imported at module scope, not through a pytest fixture.
# Hypothesis refuses function-scoped fixtures (FailedHealthCheck), so a fixture
# here would make every @given test below unrunnable.


# --------------------------------------------------------------------------- #
# Fixtures and helpers                                                          #
# --------------------------------------------------------------------------- #


def _bars_from(closes: list[float]) -> Bars:
    """Valid OHLCV bars where open == close, high/low are close ± 1."""
    idx = pd.date_range("2024-01-01", periods=len(closes), freq="D", tz="UTC")
    frame = pd.DataFrame(
        {
            "open": [float(c) for c in closes],
            "high": [float(c) + 1.0 for c in closes],
            "low": [float(c) - 1.0 for c in closes],
            "close": [float(c) for c in closes],
            "volume": [1000.0] * len(closes),
        },
        index=idx,
    )
    return Bars(frame)


def _spec() -> StrategySpec:
    """Minimal long-only spec: enter close > sma5, exit close < sma5.

    The exit rule is what makes the trade-log defence non-vacuous: without it
    every position survives to end_of_data and no trade ever "closes before the
    cutoff", so the comparison would be empty on every draw.
    """
    return StrategySpec.model_validate(
        {
            "spec_version": "1.0",
            "name": "p4-t10-lookahead",
            "universe": {"symbols": ["TEST"], "interval": "1d"},
            "period": {"start": "2024-01-01", "end": "2024-12-31"},
            "indicators": {"sma5": {"type": "sma", "params": {"period": 5}, "source": "close"}},
            "rules": {"entry_long": _ENTRY_RULE, "exit_long": _EXIT_RULE},
            "risk": {},
            "sizing": {"method": "percent_of_equity", "value": 100.0, "allow_fractional": False},
            "execution": {
                "fill": "next_open",
                "fee_bps": 0.0,
                "slippage_bps": 0.0,
                "fixed_fee": 0.0,
            },
            "capital": {"initial": 10000.0},
        }
    )


def _leaky_spec() -> StrategySpec:
    """Spec whose entry rule reads the canary indicator instead of sma5."""
    return StrategySpec.model_validate(
        {
            "spec_version": "1.0",
            "name": "p4-t10-canary",
            "universe": {"symbols": ["TEST"], "interval": "1d"},
            "period": {"start": "2024-01-01", "end": "2024-12-31"},
            "indicators": {"leaky": {"type": "leaky", "params": {}, "source": "close"}},
            "rules": {
                "entry_long": {"all": [{"left": "leaky.value", "op": ">", "right": "close"}]}
            },
            "risk": {},
            "sizing": {"method": "percent_of_equity", "value": 100.0, "allow_fractional": False},
            "execution": {
                "fill": "next_open",
                "fee_bps": 0.0,
                "slippage_bps": 0.0,
                "fixed_fee": 0.0,
            },
            "capital": {"initial": 10000.0},
        }
    )


def _fingerprint(trades: list[Any], cutoff: pd.Timestamp) -> list[tuple[Any, ...]]:
    """Identity of every MARKET-CLOSED trade that closed strictly before ``cutoff``.

    Two exclusions, both of which are artifacts of truncation rather than
    evidence of lookahead:

    * trades still open at the cutoff — they are legitimately affected by what
      follows, so including them would assert nothing;
    * ``end_of_data`` exits — the run had no more bars, so the "exit" is caused
      by the data ending, not by any market event the engine could have peeked
      at. Keeping them would compare a real signal-driven close against a
      synthetic one and fail on every draw where a position happens to still be
      open at the truncation point.
    """
    rows: list[tuple[Any, ...]] = []
    for t in trades:
        if t.exit_time >= cutoff or t.exit_reason == "end_of_data":
            continue
        rows.append(
            (
                str(t.signal_time),
                str(t.entry_time),
                float(t.entry_price),
                str(t.exit_time),
                float(t.exit_price),
                round(float(t.shares), 10),
                t.exit_reason,
            )
        )
    return rows


def _poison(bars: Bars, cutoff_i: int, factor: float) -> Bars:
    """Copy of ``bars`` with every bar at/after ``cutoff_i`` scaled by ``factor``.

    ``Bars`` is itself a validated DataFrame subclass (P1-T1), so the copy is
    built by copying the frame and re-wrapping. Scaling rather than substituting
    a constant keeps the bars VALID OHLCV (close stays within [low, high]), so
    the poisoned run cannot be rejected upstream by Bars validation — which
    would mask the very leak we are hunting.
    """
    frame = bars.copy()
    for col in ("open", "high", "low", "close"):
        col_values = frame[col].astype(float)
        col_values.iloc[cutoff_i:] = col_values.iloc[cutoff_i:] * factor
        frame[col] = col_values
    return Bars(frame)


# Series long enough that a cutoff can sit at least WARMUP+4 bars from the end.
_SERIES = st.lists(
    st.floats(min_value=50.0, max_value=150.0, allow_nan=False, allow_infinity=False),
    min_size=WARMUP + 14,
    max_size=80,
)


# --------------------------------------------------------------------------- #
# 1. Trade-log truncation invariance                                            #
# --------------------------------------------------------------------------- #


@PROFILE
@given(closes=_SERIES)
def test_run_truncation_invariance_of_trade_log(closes: list[float]) -> None:
    """Truncating the tail must not change any trade that closed in the prefix."""
    full_bars = _bars_from(closes)
    n = len(closes) - 6
    cutoff = full_bars.index[n]

    full_fp = _fingerprint(run(_spec(), full_bars).trades, cutoff)
    trunc_fp = _fingerprint(run(_spec(), full_bars.iloc[:n]).trades, cutoff)

    assert full_fp == trunc_fp, (
        "truncating bars after the cutoff changed trades that had already closed "
        f"before it: {full_fp!r} vs {trunc_fp!r}"
    )


# --------------------------------------------------------------------------- #
# 2. Signal-level truncation and poison (the engine's own evaluate_rule)         #
# --------------------------------------------------------------------------- #


@PROFILE
@given(closes=_SERIES)
def test_engine_signal_truncation_invariance(closes: list[float]) -> None:
    """Signals on bars[:n] must equal signals[:n] computed on bars[:n+k]."""
    bars = _bars_from(closes)
    spec = _spec()
    n = len(closes) - 6

    short = evaluate_rule(spec.rules.entry_long, bars.iloc[:n], spec.indicators)
    long = evaluate_rule(spec.rules.entry_long, bars, spec.indicators)[:n]

    assert np.array_equal(short, long), (
        f"engine signal array changed under truncation at {len(np.flatnonzero(short != long))} bars"
    )


@PROFILE
@given(
    closes=_SERIES,
    factor=st.floats(min_value=2.0, max_value=25.0, allow_nan=False, allow_infinity=False),
)
def test_engine_signal_poison_invariance(closes: list[float], factor: float) -> None:
    """Poisoning every bar at/after the cutoff must not move earlier signals."""
    bars = _bars_from(closes)
    spec = _spec()
    cutoff_i = len(closes) - 6

    clean = evaluate_rule(spec.rules.entry_long, bars, spec.indicators)[:cutoff_i]
    poisoned = evaluate_rule(
        spec.rules.entry_long, _poison(bars, cutoff_i, factor), spec.indicators
    )[:cutoff_i]

    assert np.array_equal(clean, poisoned), (
        f"poisoning bars from {bars.index[cutoff_i]} by x{factor} changed earlier "
        f"signals at {len(np.flatnonzero(clean != poisoned))} bars — the engine "
        "read future data"
    )


# --------------------------------------------------------------------------- #
# 3. Canary — prove the defences are armed, not vacuous                          #
# --------------------------------------------------------------------------- #


def _leaky_registry() -> Registry:
    """A fresh Registry holding ONLY a deliberately leaky 'leaky' indicator.

    ``compute_fn`` returns, at bar ``t``, the mean of ``close[t-1..t+1]`` — it
    reads the FUTURE bar. Any signal built on it is a pure lookahead bug.
    Defined here rather than in src/ so no indicator change can accidentally
    repair the canary (P2-T7 convention).
    """
    reg = Registry()

    def _leaky_compute(bars: Bars, params: dict[str, Any], source: str) -> pd.DataFrame:
        values = bars[source].to_numpy(dtype=float)
        n = len(values)
        out = [float("nan")] * n
        for i in range(1, n - 1):
            # window reaches one bar into the FUTURE (i+1) — the leak
            out[i] = float(values[i - 1 : i + 2].mean())
        return pd.DataFrame({"value": out}, index=bars.index)

    reg.register(
        IndicatorSpec(
            name="leaky",
            outputs=("value",),
            params={},
            allowed_sources=("close",),
            warmup_fn=lambda _p: 2,
            compute_fn=_leaky_compute,
            description="CANARY ONLY: reads bar t+1. Must never reach src/.",
        )
    )
    return reg


def test_canary_leaky_indicator_is_caught() -> None:
    """The poison harness must FLAG a lookahead leak.

    If this ever passes, the harness has stopped comparing anything and every
    other test in this file is meaningless.

    The fixture puts a sharp DOWN-step at the cutoff bar so that poisoning it
    flips the sign of ``leaky.value - close`` at the bar immediately BEFORE the
    cutoff — the only bar a 1-bar lookahead can influence:
      clean   leaky[t-1] = mean(100, 100,   5) = 68.3  -> 68.3 > 100 is FALSE
      poisoned leaky[t-1] = mean(100, 100, 200) = 133.3 -> 133.3 > 100 is TRUE
    """
    closes = [100.0] * 21 + [5.0, 100.0, 100.0, 100.0, 100.0]
    bars = _bars_from(closes)
    cutoff_i = 21
    reg = _leaky_registry()
    spec = _leaky_spec()

    clean = evaluate_rule(spec.rules.entry_long, bars, spec.indicators, registry=reg)
    poisoned = evaluate_rule(
        spec.rules.entry_long, _poison(bars, cutoff_i, 40.0), spec.indicators, registry=reg
    )

    assert not np.array_equal(clean[:cutoff_i], poisoned[:cutoff_i]), (
        "canary FAILED to be caught: the poison harness reported no change even "
        "though the canary indicator reads bar t+1. Either the leak is not real "
        "on this fixture, or the harness is vacuous — investigate before trusting "
        "the other tests in this file."
    )
