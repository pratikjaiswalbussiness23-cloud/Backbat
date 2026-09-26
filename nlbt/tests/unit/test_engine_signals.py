"""P4-T2 tests: signal evaluation (nlbt.engine.signals) — criteria S1-S12.

Stage note (R14): written from the acceptance criteria ONLY; no engine code was
read (there is none yet). Tests request a fixture that lazily imports
``nlbt.engine.signals``, so they collect today and ERROR at fixture setup
until the builder lands the module — the expected state at the test-author
stage. Never mocked, never skipped.

PINNED API under test (docs/OPEN_QUESTIONS.md OQ-0049):

    from nlbt.engine.signals import (
        compare,        # compare(left, op, right) -> array-like of bool
        crosses_above,  # crosses_above(a, b) -> array-like of bool (§4.2)
        crosses_below,  # crosses_below(a, b) -> array-like of bool (§4.2)
        lag,            # lag(values, k) -> values shifted k bars back
        logical_and,    # logical_and(a, b) elementwise
        logical_or,     # logical_or(a, b) elementwise
        logical_not,    # logical_not(a) elementwise
        evaluate_rule,  # evaluate_rule(rule, bars, indicators) -> bool array
    )

    Operators for ``compare`` are the §4.2 op strings: ``>``, ``>=``, ``<``,
    ``<=``. NaN comparisons are ALWAYS False (§4.2). ``evaluate_rule`` takes a
    nlbt.spec.models Condition/Rule, a nlbt.data.models.Bars frame, and the
    spec's indicators map (name -> nlbt.spec.models.IndicatorDef); indicator
    columns are computed with leading NaN during warm-up, so warm-up bars
    cannot signal.

Expected-value provenance (R4): every expected vector is hand-computed with
the arithmetic shown in the docstring. S12's SMA vector is additionally
cross-checked against an independent oracle named explicitly in the test:
``pandas`` ``Series.rolling(5).mean()``. Booleans compare EXACTLY (no float
tolerance); float operand values compare exactly where dyadic (10, 11, 12,
13) — all asserted with plain ``==`` on Python bools/floats extracted from
the returned array-like.
"""

from __future__ import annotations

import importlib
from types import ModuleType

import numpy as np
import pandas as pd
import pytest

from nlbt.data.models import Bars
from nlbt.spec.models import Condition, IndicatorDef


@pytest.fixture()
def signals_mod() -> ModuleType:
    """Lazily import the (not yet existing) signals module.

    Fixture setup runs before the test body, so while ``nlbt.engine`` is
    missing every test using this fixture ERRORs while collection succeeds.
    """
    return importlib.import_module("nlbt.engine.signals")


def _bools(result: object) -> list[bool]:
    """Normalise any array-like of bool to a plain Python list (exact compare)."""
    return [bool(x) for x in np.asarray(result).tolist()]


def _make_bars(closes: list[float]) -> Bars:
    """Minimal valid Bars frame: flat OHLC around each close, constant volume."""
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


# --------------------------------------------------------------------------- #
# S1 — simple comparison
# --------------------------------------------------------------------------- #


def test_s1_simple_comparison(signals_mod: ModuleType) -> None:
    """S1: close > 100 on prices = [90, 95, 101, 98, 105].

    bar 0:  90 > 100 -> False
    bar 1:  95 > 100 -> False
    bar 2: 101 > 100 -> True   (criterion: signal at index 2)
    bar 3:  98 > 100 -> False
    bar 4: 105 > 100 -> True   (criterion: signal at index 4)

    Expected: [False, False, True, False, True] — booleans, EXACT equality.
    """
    prices = [90.0, 95.0, 101.0, 98.0, 105.0]
    signal = _bools(signals_mod.compare(prices, ">", 100.0))
    assert signal == [False, False, True, False, True]


# --------------------------------------------------------------------------- #
# S2 — NaN comparisons are always False
# --------------------------------------------------------------------------- #


def test_s2_nan_comparison_is_false(signals_mod: ModuleType) -> None:
    """S2: close > 50 on prices = [NaN, 100, NaN].

    bar 0: NaN > 50 -> False  (NaN compared with anything is False, §4.2)
    bar 1: 100 > 50 -> True
    bar 2: NaN > 50 -> False

    Expected: [False, True, False] — EXACT (no tolerance on booleans).
    """
    prices = [float("nan"), 100.0, float("nan")]
    signal = _bools(signals_mod.compare(prices, ">", 50.0))
    assert signal == [False, True, False]


# --------------------------------------------------------------------------- #
# S3 — crosses_above, precise §4.2 definition
# --------------------------------------------------------------------------- #


def test_s3_crosses_above_definition(signals_mod: ModuleType) -> None:
    """S3: §4.2 — a crosses_above b at t iff
    a[t-1] <= b[t-1] AND a[t] > b[t], all four values non-NaN.

    a = [10, 10, 11, 12, 11]
    b = [11, 10, 10, 10, 10]

    t=0: no previous bar                          -> False
    t=1: a[0]=10 <= b[0]=11  (True)
         a[1]=10 >  b[1]=10  (False, strict >)    -> False
    t=2: a[1]=10 <= b[1]=10  (True, equality counts)
         a[2]=11 >  b[2]=10  (True)               -> True  (crossover)
    t=3: a[2]=11 <= b[2]=10  (False)              -> False
    t=4: a[3]=12 <= b[3]=10  (False)              -> False

    Expected: [False, False, True, False, False] — EXACT.
    """
    a = [10.0, 10.0, 11.0, 12.0, 11.0]
    b = [11.0, 10.0, 10.0, 10.0, 10.0]
    signal = _bools(signals_mod.crosses_above(a, b))
    assert signal == [False, False, True, False, False]


# --------------------------------------------------------------------------- #
# S4 — equality at t-1 counts as a cross
# --------------------------------------------------------------------------- #


def test_s4_crosses_above_equality_at_t_minus_1(signals_mod: ModuleType) -> None:
    """S4: equality at t-1 satisfies the ``<=`` half of the definition.

    a = [10, 11], b = [10, 9]
    t=0: no previous bar -> False
    t=1: a[0]=10 <= b[0]=10  (EQUAL, counts) AND a[1]=11 > b[1]=9 -> True

    Expected: index 0 False, index 1 True — EXACT.
    """
    a = [10.0, 11.0]
    b = [10.0, 9.0]
    signal = _bools(signals_mod.crosses_above(a, b))
    assert signal[0] is False
    assert signal[1] is True


# --------------------------------------------------------------------------- #
# S5 — NaN at t-1 makes the cross False
# --------------------------------------------------------------------------- #


def test_s5_crosses_above_nan_at_t_minus_1(signals_mod: ModuleType) -> None:
    """S5: NaN at t-1 -> False (§4.2 requires all four values non-NaN).

    a = [NaN, 11], b = [10, 9]
    t=1: a[0]=NaN -> the a[t-1] <= b[t-1] half is a NaN comparison = False
         -> whole crossover False.

    Expected: index 1 NOT a cross — EXACT.
    """
    a = [float("nan"), 11.0]
    b = [10.0, 9.0]
    signal = _bools(signals_mod.crosses_above(a, b))
    assert signal[1] is False


# --------------------------------------------------------------------------- #
# S6 — NaN at t makes the cross False
# --------------------------------------------------------------------------- #


def test_s6_crosses_above_nan_at_t(signals_mod: ModuleType) -> None:
    """S6: NaN at t -> False (§4.2 requires all four values non-NaN).

    a = [10, NaN], b = [11, 8]
    t=1: a[t-1]=10 <= b[t-1]=11 -> True, but a[t]=NaN > b[t]=8 is a NaN
         comparison = False (§4.2) -> whole crossover False.

    Expected: index 1 NOT a cross — EXACT.
    """
    a = [10.0, float("nan")]
    b = [11.0, 8.0]
    signal = _bools(signals_mod.crosses_above(a, b))
    assert signal[1] is False


# --------------------------------------------------------------------------- #
# S7 — crosses_below, precise §4.2 definition
# --------------------------------------------------------------------------- #


def test_s7_crosses_below_definition(signals_mod: ModuleType) -> None:
    """S7: §4.2 — a crosses_below b at t iff
    a[t-1] >= b[t-1] AND a[t] < b[t], all four values non-NaN.

    a = [12, 11, 10, 11, 12]
    b = [10, 10, 11, 12, 11]

    t=0: no previous bar                          -> False
    t=1: a[0]=12 >= b[0]=10  (True)
         a[1]=11 <  b[1]=10  (False)              -> False
    t=2: a[1]=11 >= b[1]=10  (True)
         a[2]=10 <  b[2]=11  (True)               -> True  (crossover)
    t=3: a[2]=10 >= b[2]=11  (False)              -> False
    t=4: a[3]=11 >= b[3]=12  (False)              -> False

    Expected: [False, False, True, False, False] — EXACT.
    """
    a = [12.0, 11.0, 10.0, 11.0, 12.0]
    b = [10.0, 10.0, 11.0, 12.0, 11.0]
    signal = _bools(signals_mod.crosses_below(a, b))
    assert signal == [False, False, True, False, False]


# --------------------------------------------------------------------------- #
# S8 — lag support
# --------------------------------------------------------------------------- #


def test_s8_lag_returns_value_from_t_minus_k(signals_mod: ModuleType) -> None:
    """S8: lag=k means the value from bar t-k (§4.2).

    a = [10, 11, 12, 13]
    lag(a, 1) at t=3 is a[3-1] = a[2] = 12   (criterion)
    lag(a, 0) at t=3 is a[3-0] = a[3] = 13   (lag 0 = same bar, identity)
    lag(a, 1) at t=0 has no bar -1: MUST be NaN, never a[-1]=13 — Python's
    negative-index wraparound would read the LAST bar (future data), which
    §4.2 forbids ("negative lags are forbidden (future data)").

    Expected: 12, 13, and NaN respectively — 12/13 EXACT (dyadic integers),
    the out-of-range slot asserted via np.isnan.
    """
    a = [10.0, 11.0, 12.0, 13.0]

    lagged = np.asarray(signals_mod.lag(a, 1))
    identity = np.asarray(signals_mod.lag(a, 0))

    assert float(lagged[3]) == 12.0  # a[2]
    assert float(identity[3]) == 13.0  # a[3]
    assert np.isnan(lagged[0]), "lag before bar 0 must be NaN, not a[-1] wraparound"


# --------------------------------------------------------------------------- #
# S9-S11 — boolean combinators
# --------------------------------------------------------------------------- #


def test_s9_and_rule(signals_mod: ModuleType) -> None:
    """S9: AND — both conditions must be true.

    cond1 = [T, T, F, T]
    cond2 = [T, F, T, T]
    AND:     T&T=T, T&F=F, F&T=F, T&T=T

    Expected: [True, False, False, True] — EXACT.
    """
    cond1 = [True, True, False, True]
    cond2 = [True, False, True, True]
    combined = _bools(signals_mod.logical_and(cond1, cond2))
    assert combined == [True, False, False, True]


def test_s10_or_rule(signals_mod: ModuleType) -> None:
    """S10: OR — either condition true.

    cond1 = [T, F, F, T]
    cond2 = [F, T, F, T]
    OR:      T|F=T, F|T=T, F|F=F, T|T=T

    Expected: [True, True, False, True] — EXACT.
    """
    cond1 = [True, False, False, True]
    cond2 = [False, True, False, True]
    combined = _bools(signals_mod.logical_or(cond1, cond2))
    assert combined == [True, True, False, True]


def test_s11_not_rule(signals_mod: ModuleType) -> None:
    """S11: NOT — negation.

    cond = [T, F, T]
    NOT:    F, T, F

    Expected: [False, True, False] — EXACT.
    """
    cond = [True, False, True]
    negated = _bools(signals_mod.logical_not(cond))
    assert negated == [False, True, False]


# --------------------------------------------------------------------------- #
# S12 — no signal before warm-up
# --------------------------------------------------------------------------- #


def test_s12_no_signal_before_indicator_warmup(signals_mod: ModuleType) -> None:
    """S12: SMA(5) on 10 bars — no signal in the first 4 bars.

    Fixture closes = [10, 10, 10, 10, 10, 20, 20, 20, 20, 20], rule
    ``close > sma5`` with sma5 = IndicatorDef(type="sma", period=5).

    Hand computation (SMA(5) first valid at index period-1 = 4; indices 0-3
    are NaN during warm-up and NaN comparisons are False — §4.2):

      i     closes in window          sma5      close>sma5
      0     (warm-up)                 NaN       False
      1     (warm-up)                 NaN       False
      2     (warm-up)                 NaN       False
      3     (warm-up)                 NaN       False
      4     10,10,10,10,10            10.0      10  > 10  -> False
      5     10,10,10,10,20       (50/5)=12.0      20 > 12  -> True
      6     10,10,10,20,20       (60/5)=14.0      20 > 14  -> True
      7     10,10,20,20,20       (70/5)=16.0      20 > 16  -> True
      8     10,20,20,20,20       (80/5)=18.0      20 > 18  -> True
      9     20,20,20,20,20       (100/5)=20.0     20 > 20  -> False (strict >)

    Expected vector: [F,F,F,F,F,T,T,T,T,F]; criterion S12 asserts the first
    four are all False (warm-up), the full vector additionally pins the
    strict-inequality edge at bar 9.

    Independent oracle named explicitly: pandas
    ``Series.rolling(5).mean()`` (dev-dependency, unrelated to nlbt.engine)
    produces exactly [nan,nan,nan,nan,10,12,14,16,18,20].
    """
    closes = [10.0, 10.0, 10.0, 10.0, 10.0, 20.0, 20.0, 20.0, 20.0, 20.0]
    bars = _make_bars(closes)

    # Independent oracle: pandas rolling mean (named, not nlbt.engine).
    sma_oracle = pd.Series(closes).rolling(5).mean()
    assert [None if pd.isna(v) else float(v) for v in sma_oracle[4:]] == [
        10.0,
        12.0,
        14.0,
        16.0,
        18.0,
        20.0,
    ]

    rule = Condition(left="close", op=">", right="sma5")
    indicators = {"sma5": IndicatorDef(type="sma", params={"period": 5}, source="close")}

    signal = _bools(signals_mod.evaluate_rule(rule, bars, indicators))

    assert signal[0:4] == [False, False, False, False], "warm-up must not signal"
    assert signal == [False, False, False, False, False, True, True, True, True, False]
