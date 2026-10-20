"""Warm-up gate tests — §4.5 "No signal can fire until **all** indicators used
by the rules are valid (warm-up)" and §8.3 I4 (review finding H1).

H1: warm-up was implemented ONLY as "a comparison involving NaN is False".
That guard is inverted by ``not`` and masked by ``any`` arms whose other
operand is a literal, so signals fired while indicators were still NaN.
These tests pin the §4.5 rule at two levels:

* W1-W7, W10-W11 — ``evaluate_rule`` exact firing bars (entry and exit
  framing, nested all/any/not, literal-true ``any`` arms on SMA and EMA,
  lag-k references, RSI warm-ups alongside SMA/EMA).
* W8-W9 — run()-level I4 integration: no entry before the entry rule's
  indicator warm-up; no exit during the exit rule's indicator warm-up.

Expected-value provenance (R4): every expected vector is hand-computed with
the arithmetic shown in each docstring; nothing is copied from the engine.
SMA values are additionally cross-checked against an independent oracle
named explicitly — pandas ``Series.rolling(n).mean()`` (dev-dependency,
unrelated to nlbt.engine). Warm-up cutoffs are hand-derived from the
registry contract (C7, registry docstrings: sma/ema first valid at
``period-1`` — ADR-0002; rsi first valid at ``period`` — ADR-0003) and
cross-checked at runtime against ``REGISTRY.warmup_fn`` in each test, so a
registry drift fails loudly here too. Booleans compare EXACTLY.
"""

from __future__ import annotations

import importlib
from types import ModuleType

import numpy as np
import pandas as pd
import pytest

from nlbt.data.models import Bars
from nlbt.engine.backtest import run
from nlbt.indicators.registry import REGISTRY
from nlbt.spec.models import (
    AllRule,
    AnyRule,
    Condition,
    IndicatorDef,
    IndicatorOperand,
    NotRule,
    StrategySpec,
)


@pytest.fixture()
def signals_mod() -> ModuleType:
    """Lazily import the engine signals module (same convention as
    test_engine_signals.py)."""
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


def _warmup(period: int, kind: str) -> int:
    """Registry warm-up cutoff (C7 single source of truth), asserted against
    the hand-derived constant from the docstring."""
    spec = REGISTRY.get(kind)
    resolved = {name: pspec.default for name, pspec in spec.params.items()}
    resolved["period"] = period
    return spec.warmup_fn(resolved)


# S12 fixture (pinned in test_engine_signals.py with the pandas oracle):
# closes = [10]*5 + [20]*5
#   sma5 = [nan,nan,nan,nan, 10, 12, 14, 16, 18, 20]
_SMA5_FIRST_VALID = 4  # hand: period - 1
_FIXTURE_CLOSES = [10.0, 10.0, 10.0, 10.0, 10.0, 20.0, 20.0, 20.0, 20.0, 20.0]
_SMA5 = {"sma5": IndicatorDef(type="sma", params={"period": 5}, source="close")}


# --------------------------------------------------------------------------- #
# W1 — NOT entry rule must stay False during warm-up
# --------------------------------------------------------------------------- #


def test_w1_not_entry_fires_only_after_warmup(signals_mod: ModuleType) -> None:
    """W1: entry rule ``not (close > sma5)`` on the S12 fixture.

    Hand computation (sma5 = [nan x4, 10, 12, 14, 16, 18, 20]; NaN
    comparisons are False — §4.2):

      i   close>sma5        not(...)         gate (sma5 non-NaN)   expected
      0   NaN>50 -> False   True (BUG path)  False                 False
      1   NaN -> False      True (BUG path)  False                 False
      2   NaN -> False      True (BUG path)  False                 False
      3   NaN -> False      True (BUG path)  False                 False
      4   10 > 10 -> False  True             True                  True
      5   20 > 12 -> True   False            True                  False
      6   20 > 14 -> True   False            True                  False
      7   20 > 16 -> True   False            True                  False
      8   20 > 18 -> True   False            True                  False
      9   20 > 20 -> False  True             True                  True

    §4.5: no signal until all indicators used by the rule are valid, so bars
    0-3 (sma5 NaN) must be False even though ``not`` inverts the NaN-False
    guard. Warm-up cutoff cross-checked against REGISTRY (sma(5) == 4).

    Expected vector: [F,F,F,F,T,F,F,F,F,T] — EXACT.
    """
    assert _warmup(5, "sma") == _SMA5_FIRST_VALID == 4
    bars = _make_bars(_FIXTURE_CLOSES)
    rule = NotRule(kind="not", condition=Condition(left="close", op=">", right="sma5"))

    signal = _bools(signals_mod.evaluate_rule(rule, bars, _SMA5))

    assert signal[0:4] == [False, False, False, False], "warm-up must not signal"
    assert signal == [False, False, False, False, True, False, False, False, False, True]


# --------------------------------------------------------------------------- #
# W2 — NOT exit rule (RSI) must stay False during warm-up
# --------------------------------------------------------------------------- #


def test_w2_not_exit_rule_fires_only_after_warmup(signals_mod: ModuleType) -> None:
    """W2: EXIT rule ``not (rsi2 > 50)`` on flat closes — exit signals are
    signals too (§4.5: "no signal can fire", not "no ENTRY signal").

    Hand computation (flat prices: RSI is the task-mandated 50.0 case —
    zero average gain AND zero average loss, ADR-0003 / registry docstring;
    rsi(2) first valid at index period = 2):

      i   rsi2        rsi2>50        not(...)      gate (rsi2 non-NaN)  expected
      0   NaN         False          True (BUG)    False                False
      1   NaN         False          True (BUG)    False                False
      2   50          50>50 False    True          True                 True
      3   50          False          True          True                 True
      ... 50 all the way to 9 ...

    Before the gate, a warm-up exit would slam a position shut the instant
    it opened; the exit-side effect is demonstrated end-to-end in W9.

    Expected vector: [F,F,T,T,T,T,T,T,T,T] — EXACT.
    """
    assert _warmup(2, "rsi") == 2, "rsi(period) first valid at index period"
    closes = [10.0] * 10
    bars = _make_bars(closes)
    indicators = {"rsi2": IndicatorDef(type="rsi", params={"period": 2}, source="close")}
    rule = NotRule(kind="not", condition=Condition(left="rsi2", op=">", right=50.0))

    signal = _bools(signals_mod.evaluate_rule(rule, bars, indicators))

    assert signal[0:2] == [False, False], "warm-up must not emit exit signals"
    assert signal == [False, False, True, True, True, True, True, True, True, True]


# --------------------------------------------------------------------------- #
# W3 — ANY with a literal-true arm must not hide the NaN arm
# --------------------------------------------------------------------------- #


def test_w3_any_literal_arm_does_not_mask_warmup(signals_mod: ModuleType) -> None:
    """W3: entry rule ``any(1 > 0, sma5 > 0)`` on the S12 fixture.

    Hand computation: the literal arm ``1 > 0`` is True at every bar, so the
    raw ``any`` is True everywhere; §4.5 still requires sma5 (referenced by
    the second arm) to be valid:

      i   1>0   sma5>0        any raw        gate (sma5 non-NaN)  expected
      0   T     NaN>0 False   T (BUG)        False                False
      1   T     False         T (BUG)        False                False
      2   T     False         T (BUG)        False                False
      3   T     False         T (BUG)        False                False
      4   T     10>0 True     T              True                 True
      5-9 T     True          T              True                 True

    Expected vector: [F,F,F,F,T,T,T,T,T,T] — EXACT.
    """
    bars = _make_bars(_FIXTURE_CLOSES)
    rule = AnyRule(
        kind="any",
        conditions=[
            Condition(left=1.0, op=">", right=0.0),
            Condition(left="sma5", op=">", right=0.0),
        ],
    )

    signal = _bools(signals_mod.evaluate_rule(rule, bars, _SMA5))

    assert signal[0:4] == [False, False, False, False], "warm-up must not signal"
    assert signal == [False, False, False, False, True, True, True, True, True, True]


# --------------------------------------------------------------------------- #
# W4 — lag-k reference: valid from first_valid + k
# --------------------------------------------------------------------------- #


def test_w4_lagged_reference_warmup_boundary(signals_mod: ModuleType) -> None:
    """W4: entry rule ``not (sma5.lag1 > 10)`` — a lag-k reference is valid
    from ``first_valid + k`` (§4.2 lag semantics + §4.5 warm-up).

    Hand computation: lagged sma5 = [nan, nan, nan, nan, nan, 10, 12, 14,
    16, 18] (lag shifts the whole series back one bar, validity moves from
    bar 4 to bar 5):

      i   lagged sma5   lagged>10   not(...)     gate (lagged non-NaN)  expected
      0-4 NaN           False       True (BUG)   False                  False
      5   10            10>10 False True         True                   True
      6   12            True        False        True                   False
      7   14            True        False        True                   False
      8   16            True        False        True                   False
      9   18            True        False        True                   False

    Bar 5 is a legitimate post-warm-up signal (the lagged value 10 exists
    and 10 > 10 is False); bars 0-4 must be gated.

    Expected vector: [F,F,F,F,F,T,F,F,F,F] — EXACT.
    """
    bars = _make_bars(_FIXTURE_CLOSES)
    rule = NotRule(
        kind="not",
        condition=Condition(
            left=IndicatorOperand(kind="indicator", name="sma5", lag=1),
            op=">",
            right=10.0,
        ),
    )

    signal = _bools(signals_mod.evaluate_rule(rule, bars, _SMA5))

    assert signal[0:5] == [False] * 5, "lagged reference warms up at first_valid + k"
    assert signal == [False, False, False, False, False, True, False, False, False, False]


# --------------------------------------------------------------------------- #
# W5 — EMA never valid inside the window
# --------------------------------------------------------------------------- #


def test_w5_not_rule_with_indicator_never_valid(signals_mod: ModuleType) -> None:
    """W5: entry rule ``not (close > ema20)`` on 10 bars — EMA(20) seeds with
    the SMA of its first 20 values (ADR-0002), so it is NaN at EVERY bar of
    a 10-bar window. The inner comparison is therefore False everywhere and
    ``not`` would be True everywhere; §4.5 requires the whole rule to be
    False everywhere (the indicator is never valid in this window).

    Expected vector: all False — EXACT.
    """
    bars = _make_bars(_FIXTURE_CLOSES)
    indicators = {"ema20": IndicatorDef(type="ema", params={"period": 20}, source="close")}
    assert _warmup(20, "ema") == 19, "ema(20) needs 20 bars to seed; 10 < 20"
    rule = NotRule(kind="not", condition=Condition(left="close", op=">", right="ema20"))

    signal = _bools(signals_mod.evaluate_rule(rule, bars, indicators))

    assert signal == [False] * 10


# --------------------------------------------------------------------------- #
# W6 — EMA boundary: valid from exactly period - 1
# --------------------------------------------------------------------------- #


def test_w6_ema_warmup_boundary_exact_index(signals_mod: ModuleType) -> None:
    """W6: entry rule ``not (close < ema20)`` on 25 rising bars (close = 1..25)
    pins the EMA warm-up boundary at EXACTLY index period-1 = 19.

    Hand computation: rising closes put close above every trailing average,
    so ``close < ema20`` is False at every valid bar and ``not`` is True
    there. EMA(20) seeds with mean(1..20) = 210/20 = 10.5 at index 19
    (ADR-0002), so bars 0-18 are warm-up (gated False) and bars 19-24 are
    legitimate signals:

      i   0-18 (ema20 NaN)   -> False (gated)
      19  close=20, ema=10.5 -> 20 < 10.5 False -> not True
      20-24 close keeps rising above ema -> not True

    Expected vector: [F]*19 + [T]*6 — EXACT.
    """
    assert _warmup(20, "ema") == 19
    closes = [float(c) for c in range(1, 26)]
    bars = _make_bars(closes)
    indicators = {"ema20": IndicatorDef(type="ema", params={"period": 20}, source="close")}
    rule = NotRule(kind="not", condition=Condition(left="close", op="<", right="ema20"))

    signal = _bools(signals_mod.evaluate_rule(rule, bars, indicators))

    assert signal[0:19] == [False] * 19, "bars before ema(20).first_valid must be gated"
    assert signal == [False] * 19 + [True] * 6


# --------------------------------------------------------------------------- #
# W7 — nested any([not, not]) with different warm-ups
# --------------------------------------------------------------------------- #


def test_w7_nested_any_of_nots_mixed_warmups(signals_mod: ModuleType) -> None:
    """W7: entry rule ``any(not(close > sma5), not(close > sma3))`` on the
    S12 fixture — nested all/any/not, two indicators with DIFFERENT
    warm-ups (sma5: 4, sma3: 2) → the gate uses the MAX cutoff (bar 4).

    Hand computation (sma3 = [nan, nan, 10, 10, 10, 13.33, 16.67, 20, 20,
    20], oracle-backed by pandas rolling(3).mean in the assertion below):

      i   close>sma5   not5      close>sma3   not3      any raw    gate  expected
      0   NaN F        True(BUG) NaN F        True(BUG) True(BUG)  F     F
      1   NaN F        True(BUG) NaN F        True(BUG) True(BUG)  F     F
      2   NaN F        True(BUG) 10>10 F      True      True(BUG)  F     F
      3   NaN F        True(BUG) 10>10 F      True      True(BUG)  F     F
      4   10>10 F      True      10>10 F      True      True       T     T
      5   20>12 T      False     20>13.33 T   False     False      T     F
      6   20>14 T      False     20>16.67 T   False     False      T     F
      7   20>16 T      False     20>20 F      True      True       T     T
      8   20>18 T      False     20>20 F      True      True       T     T
      9   20>20 F      True     20>20 F      True      True       T     T

    Expected vector: [F,F,F,F,T,F,F,T,T,T] — EXACT.
    """
    bars = _make_bars(_FIXTURE_CLOSES)

    # Independent oracle: pandas rolling means (named, not nlbt.engine).
    rolling = pd.Series(_FIXTURE_CLOSES)
    assert [None if pd.isna(v) else round(float(v), 3) for v in rolling.rolling(5).mean()][4:] == [
        10.0,
        12.0,
        14.0,
        16.0,
        18.0,
        20.0,
    ]
    assert [None if pd.isna(v) else round(float(v), 3) for v in rolling.rolling(3).mean()][2:] == [
        10.0,
        10.0,
        10.0,
        13.333,
        16.667,
        20.0,
        20.0,
        20.0,
    ]

    indicators = {
        **_SMA5,
        "sma3": IndicatorDef(type="sma", params={"period": 3}, source="close"),
    }
    rule = AnyRule(
        kind="any",
        conditions=[
            NotRule(kind="not", condition=Condition(left="close", op=">", right="sma5")),
            NotRule(kind="not", condition=Condition(left="close", op=">", right="sma3")),
        ],
    )

    signal = _bools(signals_mod.evaluate_rule(rule, bars, indicators))

    assert signal[0:4] == [False] * 4, "gate cutoff is the MAX warm-up over references"
    assert signal == [False, False, False, False, True, False, False, True, True, True]


# --------------------------------------------------------------------------- #
# W10 — ANY literal-true arm with an EMA reference, EXIT framing
# --------------------------------------------------------------------------- #


def test_w10_any_literal_arm_exit_ema_warmup(signals_mod: ModuleType) -> None:
    """W10: EXIT rule ``any(1 > 0, ema3 > 0)`` on flat closes (EMA variant
    of W3, exit framing): the literal-true arm must not mask the EMA's
    warm-up on the exit side either.

    Hand computation (flat closes: ema3 seeds with SMA(10, 10, 10) = 10 at
    index 2 — ADR-0002 — and stays 10; alpha = 2/(3+1) = 0.5 applied to
    equal values changes nothing):

      i   ema3     ema3>0   1>0   any raw         gate (ema3 non-NaN)  expected
      0   NaN      False    T     T (BUG)         False                False
      1   NaN      False    T     T (BUG)         False                False
      2   10       True     T     T               True                 True
      3-9 10       True     T     T               True                 True

    Expected vector: [F,F,T,T,T,T,T,T,T,T] — EXACT.
    """
    assert _warmup(3, "ema") == 2, "ema(period) first valid at index period-1"
    bars = _make_bars([10.0] * 10)
    indicators = {"ema3": IndicatorDef(type="ema", params={"period": 3}, source="close")}
    rule = AnyRule(
        kind="any",
        conditions=[
            Condition(left=1.0, op=">", right=0.0),
            Condition(left="ema3", op=">", right=0.0),
        ],
    )

    signal = _bools(signals_mod.evaluate_rule(rule, bars, indicators))

    assert signal[0:2] == [False, False], "warm-up must not emit exit signals"
    assert signal == [False, False, True, True, True, True, True, True, True, True]


# --------------------------------------------------------------------------- #
# W11 — one tree nesting all + any + not, two indicators
# --------------------------------------------------------------------------- #


def test_w11_nested_all_any_not_gate(signals_mod: ModuleType) -> None:
    """W11: entry rule ``all(any(close < 0, not(close > sma5)),
    not(close > sma3))`` — a single tree nesting ALL three §4.2 operators
    over two indicators with different warm-ups (sma5: 4, sma3: 2).

    Hand computation (S12 fixture; closes are always > 0 so ``close < 0``
    is False everywhere):

      i   any(False, not5)   not3      all raw       gate (max warm-up 4)  expected
      0   not5 = T (BUG)     T         T (BUG)       F                     F
      1   T (BUG)            T         T (BUG)       F                     F
      2   T (BUG)            T         T (BUG)       F                     F
      3   T (BUG)            T         T (BUG)       F                     F
      4   not5: 10>10 F -> T not5=T   T             T                     T
      5   not5: 20>12 T -> F          F             F                     T   F
      6   not5: T -> F                F             F                     T   F
      7   not5: T -> F                not3: 20>20 F -> T  F               T   F
      8   not5: T -> F                not3 -> T     F                     T   F
      9   not5: 20>20 F -> T          not3 -> T     T                     T   T

    Expected vector: [F,F,F,F,T,F,F,F,F,T] — EXACT (raw ``all`` would be
    [T,T,T,T,T,F,F,F,F,T]; only the warm-up gate removes bars 0-3).
    """
    bars = _make_bars(_FIXTURE_CLOSES)
    indicators = {
        **_SMA5,
        "sma3": IndicatorDef(type="sma", params={"period": 3}, source="close"),
    }
    rule = AllRule(
        kind="all",
        conditions=[
            AnyRule(
                kind="any",
                conditions=[
                    Condition(left="close", op="<", right=0.0),
                    NotRule(kind="not", condition=Condition(left="close", op=">", right="sma5")),
                ],
            ),
            NotRule(kind="not", condition=Condition(left="close", op=">", right="sma3")),
        ],
    )

    signal = _bools(signals_mod.evaluate_rule(rule, bars, indicators))

    assert signal[0:4] == [False] * 4, "warm-up must not signal"
    assert signal == [False, False, False, False, True, False, False, False, False, True]


# --------------------------------------------------------------------------- #
# W8 — run() level: no ENTRY trade before entry-rule warm-up (I4)
# --------------------------------------------------------------------------- #


def test_w8_no_entry_trade_before_warmup() -> None:
    """W8 (§8.3 I4, run level): entry rule ``not (close > sma5)`` on 25
    rising bars (close = 1..25) must produce ZERO trades.

    Hand computation: sma5 valid from bar 4 with values 3, 4, 5, ... (mean
    of the last 5 integers); close > sma5 is True at every valid bar
    (bar 4: 5 > 3), so ``not(...)`` is False everywhere it is valid, and
    §4.5 gates bars 0-3. No entry signal can ever fire:

      pre-fix (H1): not(NaN comparison False) = True at bars 0-3
        -> signal bar 0 -> trade with signal_time = bars[0] < cutoff
        bars[4] -> I4 violated.
      post-fix: zero trades.

    The cutoff is recomputed OUTSIDE the engine from the registry warm-up
    contract (C7), exactly like the I4 property helper.
    """
    closes = [float(c) for c in range(1, 26)]
    bars = _make_bars(closes)
    spec = StrategySpec.model_validate(
        {
            "spec_version": "1.0",
            "name": "w8-warmup-entry",
            "universe": {"symbols": ["TEST"], "interval": "1d"},
            "period": {"start": "2024-01-01", "end": "2024-12-31"},
            "indicators": {"sma5": {"type": "sma", "params": {"period": 5}, "source": "close"}},
            "rules": {"entry_long": {"not": {"left": "close", "op": ">", "right": "sma5"}}},
            "risk": {},
            "sizing": {"method": "fixed_shares", "value": 1.0, "allow_fractional": True},
            "execution": {
                "fill": "next_open",
                "fee_bps": 0.0,
                "slippage_bps": 0.0,
                "fixed_fee": 0.0,
            },
            "capital": {"initial": 10_000.0},
        }
    )
    cutoff = bars.index[_warmup(5, "sma")]

    result = run(spec, bars)

    early = [t for t in result.trades if t.signal_time < cutoff]
    assert early == [], f"I4 broken: entry signalled during warm-up: {early!r}"
    assert result.trades == [], (
        f"hand-derived expectation: rising closes make not(close>sma5) always "
        f"False once valid, so NO trades; got {result.trades!r}"
    )


# --------------------------------------------------------------------------- #
# W9 — run() level: no EXIT trade during exit-rule warm-up
# --------------------------------------------------------------------------- #


def test_w9_no_exit_trade_during_warmup() -> None:
    """W9 (§4.5 exit side, run level): exit rule ``not (close > sma20)``
    with a position open DURING the exit indicator's warm-up.

    Bars: close = 101 for bars 0-19, then 102, 104, ..., 120 (bars 20-29);
    open = close, fee/slippage 0. Entry rule ``close > 100`` has NO
    indicator → valid from bar 0 → signal bar 0 → fill bar 1 at open 101.

    Hand computation of the exit rule: sma20 valid from bar 19
    (mean(101 x 20) = 101); close > 101 is False at bar 19 (101 > 101) and
    True from bar 20 on (102 > 101.05, ...), so ``not(...)`` is True only
    at bar 19 among valid bars:

      post-fix (§4.5): first exit signal bar 19 -> pending exit fills at
        bar 20 open -> trades[0]: signal bar 0, entry bar 1, exit bar 20,
        reason "signal".
      pre-fix (H1): the not-rule is True while sma20 is NaN (bars 0-18);
        with the position open from bar 1 the first exit signal is bar 1
        -> trades[0] exits at bar 2 (and the flat/re-enter churn repeats
        through the whole warm-up).
    """
    closes = [101.0] * 20 + [102.0 + 2.0 * i for i in range(10)]
    bars = _make_bars(closes)
    spec = StrategySpec.model_validate(
        {
            "spec_version": "1.0",
            "name": "w9-warmup-exit",
            "universe": {"symbols": ["TEST"], "interval": "1d"},
            "period": {"start": "2024-01-01", "end": "2024-12-31"},
            "indicators": {"sma20": {"type": "sma", "params": {"period": 20}, "source": "close"}},
            "rules": {
                "entry_long": {"all": [{"left": "close", "op": ">", "right": 100.0}]},
                "exit_long": {"not": {"left": "close", "op": ">", "right": "sma20"}},
            },
            "risk": {},
            "sizing": {"method": "fixed_shares", "value": 1.0, "allow_fractional": True},
            "execution": {
                "fill": "next_open",
                "fee_bps": 0.0,
                "slippage_bps": 0.0,
                "fixed_fee": 0.0,
            },
            "capital": {"initial": 10_000.0},
        }
    )

    result = run(spec, bars)

    assert result.trades, "sanity: the entry rule must trade on this fixture"
    first = result.trades[0]
    assert first.signal_time == bars.index[0]
    assert first.entry_time == bars.index[1]
    assert first.exit_time == bars.index[19 + 1], (
        f"exit must wait for sma20 warm-up (first valid bar 19, fill next "
        f"bar 20); got exit at {first.exit_time} — exit fired during warm-up"
    )
    assert first.exit_reason == "signal"
