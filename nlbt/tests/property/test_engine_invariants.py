"""P4-T9: hypothesis property tests for the §8.3 engine invariants (I1-I14).

The hand-written single-case stubs ``test_i1_…``-``test_i14_…`` in
``tests/unit/test_engine_scenarios.py`` stay exactly as they are — this file
ADDS genuinely generated counterexample-searching property tests alongside
them, one test per invariant:

    I1  equity[t] = cash[t] + position_value[t] for every bar
    I2  cash never negative (unlevered long-only)
    I3  every entry_time strictly after its signal_time (next bar or later)
    I4  no entry before all indicators used by the entry rule are valid
    I5  trades never overlap (one position at a time)
    I6  exit_time >= entry_time; bars_held >= 0
    I7  fees >= 0, slippage cost >= 0; sum(net_pnl) = final - initial when flat
    I8  pre-slippage fill price within [low, high] of its fill bar
    I9  determinism: two runs of the same case are identical
    I10 identical trade sequence + zero slippage: higher fees never higher
        final equity
    I11 doubling capital (fractional, percent sizing, fixed_fee=0) ⇒ identical
        timing and identical percentage returns
    I12 scaling all prices by k > 0 leaves timing unchanged for specs without
        absolute price thresholds
    I13 no NaN/inf in the equity curve or the metrics
    I14 long stop-loss exit fill never above the stop level, take-profit fill
        never below the target (pre-slippage); gap fills at the open

INPUTS ARE GENERATED, NEVER HARDCODED: random OHLCV series (valid bars:
low <= min(open, close) <= max(open, close) <= high, all prices > 0) plus
random VALID StrategySpec knobs — indicator periods, relative vs absolute rule
families, stop/take/trailing/max-holding combinations, all four sizing
methods, fee/slippage/fixed-fee combinations, capital — each drawn case
re-checked through ``StrategySpec.model_validate`` AND the semantic
``validate_spec`` (a generated spec that fails validation fails the test, it
is never quietly accepted).

Profile: ``max_examples = 100`` is the PR-CI budget of §8.1/§8.2, matching
``test_engine_lookahead.py``'s PROFILE style. Nightly path (§8.1: 1,000+
examples): ``NLBT_PROPERTY_EXAMPLES=1000 uv run pytest tests/property -m
property``. ``deadline=None`` is the P2-T7/P4-T10 flakiness guard (Windows
scheduling jitter) — a guard, NOT a reduced workload: ``max_examples`` still
forces the full count.

Expected-value provenance (R4): no number here is copied from an
implementation. Every assertion is the verbatim §8.3 invariant statement, or
an arithmetic identity derived in the docstring (I7's cash-vs-P&L partition,
I14's §4.5 level arithmetic reconstructed from the spec + bars alone).
Tolerances are documented per assertion: 1e-9 on prices (binary roundoff),
1e-4 on money sums (IEEE accumulation), and exact/tight comparisons where
the identity is exact.

If hypothesis finds a counterexample it is a REAL bug (AGENTS.md): stop,
document it in docs/OPEN_QUESTIONS.md, do NOT suppress it, do NOT shrink the
example budget. Some invariants are "run twice, derive the second case from
the first" style (I9, I10, I11, I12) — each of those draws ONE random base
case and derives the comparison run from it with ``dataclasses.replace``,
never with a second independent draw.

All 14 invariants are fuzzed here; none is left to the hand-written tests
alone. Invariants whose interesting cases need a specific fixture (e.g. I14
gap-through-stop) still get random coverage here AND keep the pinned
hand-computed case in the unit suite.

No engine logic lives in this file — only strategy generation, fixtures and
assertions.
"""

from __future__ import annotations

import itertools
import os
from dataclasses import dataclass, replace
from typing import Any

import hypothesis.strategies as st
import numpy as np
import pandas as pd
import pytest
from hypothesis import assume, given, settings

from nlbt.data.models import Bars
from nlbt.engine.backtest import Trade, run
from nlbt.indicators.registry import REGISTRY
from nlbt.spec.models import (
    AllRule,
    AnyRule,
    Condition,
    IndicatorOperand,
    NotRule,
    StrategySpec,
)
from nlbt.spec.validate import validate_spec

pytestmark = pytest.mark.property

#: PR-CI example budget (§8.1: PR 100 · nightly 1,000+). Nightly path:
#: ``NLBT_PROPERTY_EXAMPLES=1000 uv run pytest tests/property -m property``.
EXAMPLES = int(os.environ.get("NLBT_PROPERTY_EXAMPLES", "100"))

#: Binary-roundoff tolerance on PRICES (reconstructions below divide the
#: recorded fill by the exact slippage factor, which recovers the level to
#: within a few ulps — a convention error would differ by cents).
PRICE_TOL = 1e-9

#: IEEE-accumulation tolerance on money SUMS (up to ~90 bars, magnitudes
#: up to ~5e5 → accumulated rounding well below 1e-4; a missing fee or a
#: phantom fill would be orders of magnitude larger).
MONEY_TOL = 1e-4

PROFILE = settings(max_examples=EXAMPLES, deadline=None)

# NOTE: the engine is imported at module scope, not through a pytest fixture.
# Hypothesis refuses function-scoped fixtures (FailedHealthCheck), so a fixture
# here would make every @given test below unrunnable.

_PRICE = st.floats(min_value=50.0, max_value=150.0, allow_nan=False, allow_infinity=False)
_WIG = st.floats(min_value=0.0, max_value=0.03, allow_nan=False, allow_infinity=False)


@dataclass(frozen=True)
class Case:
    """One randomly drawn but VALID backtest case (bars + spec knobs).

    Held as raw inputs so every test can rebuild fresh ``StrategySpec`` /
    ``Bars`` objects from the SAME draw (I9's two runs) or derive a
    comparison run with ``dataclasses.replace`` (I10/I11/I12) instead of
    drawing a second, unrelated case.
    """

    rows: tuple[tuple[float, float, float, float], ...]  # (open, high, low, close)
    family: str  # "relative" (indicator rules) | "absolute" (price-level rules)
    fast: int  # sma_fast period
    slow: int  # sma_slow period (always > fast)
    with_cross: bool  # entry/exit via sma_fast/sma_slow crossover vs close/sma_fast
    with_exit_rule: bool  # exit_long rule present (otherwise risk exits/end-of-data)
    rsi_filter: bool  # extra rsi14 < 70 condition on the entry rule
    abs_level: float  # absolute entry level (absolute family only)
    abs_exit_level: float  # absolute exit level (absolute family only)
    stop: float | None
    take_profit: float | None
    trailing: float | None
    max_holding: int | None
    method: str  # sizing method (§4.1)
    sizing_value: float  # valid for ``method``
    percent_value: float  # a ready-made valid percent-of-equity value (10..100)
    allow_fractional: bool
    fee_bps: float
    slippage_bps: float
    fixed_fee: float
    capital: float


@st.composite
def _cases(draw: Any) -> Case:
    """Draw one random case guaranteed to be spec-valid.

    Validity is enforced twice, deliberately: every numeric knob is drawn
    inside its model/semantic bound (§4.1: percent 0 < v <= 100, strict
    floats, integer-valued fixed_shares when not fractional,
    ``risk_per_trade`` ⇒ a stop exists), and ``_build`` re-asserts
    ``validate_spec`` returns no errors for every case.
    """
    n = draw(st.integers(min_value=40, max_value=90))
    opens = draw(st.lists(_PRICE, min_size=n, max_size=n))
    closes = draw(st.lists(_PRICE, min_size=n, max_size=n))
    ups = draw(st.lists(_WIG, min_size=n, max_size=n))
    downs = draw(st.lists(_WIG, min_size=n, max_size=n))

    # Valid OHLCV bars: low <= min(open, close) <= max(open, close) <= high,
    # every price > 0 (Bars validation contract, P1-T1).
    rows = tuple(
        (
            open_price,
            max(open_price, close) * (1.0 + up),
            min(open_price, close) * (1.0 - down),
            close,
        )
        for open_price, close, up, down in zip(opens, closes, ups, downs, strict=True)
    )

    family = draw(st.sampled_from(("relative", "absolute")))
    fast = draw(st.integers(min_value=2, max_value=12))
    slow = draw(st.integers(min_value=13, max_value=25))  # always > fast (2..12)
    with_cross = draw(st.booleans())
    with_exit_rule = draw(st.booleans())
    rsi_filter = draw(st.booleans())
    abs_level = draw(_PRICE)
    abs_exit_level = draw(_PRICE)

    stop = draw(st.one_of(st.none(), st.floats(min_value=0.5, max_value=50.0)))
    take_profit = draw(st.one_of(st.none(), st.floats(min_value=0.5, max_value=100.0)))
    trailing = draw(st.one_of(st.none(), st.floats(min_value=0.5, max_value=50.0)))
    max_holding = draw(st.one_of(st.none(), st.integers(min_value=1, max_value=25)))

    method = draw(
        st.sampled_from(("percent_of_equity", "fixed_cash", "fixed_shares", "risk_per_trade"))
    )
    allow_fractional = draw(st.booleans())

    # Draw one valid value for EVERY method (cheap) so tests that force a
    # different method still have a valid, varied value to substitute.
    percent_value = draw(st.floats(min_value=10.0, max_value=100.0))
    cash_value = draw(st.floats(min_value=10.0, max_value=50_000.0))
    shares_fractional = draw(st.floats(min_value=1.0, max_value=500.0))
    shares_integer = float(draw(st.integers(min_value=1, max_value=500)))
    risk_value = draw(st.floats(min_value=0.1, max_value=5.0))
    sizing_value = {
        "percent_of_equity": percent_value,
        "fixed_cash": cash_value,
        "fixed_shares": shares_integer if not allow_fractional else shares_fractional,
        "risk_per_trade": risk_value,
    }[method]

    if method == "risk_per_trade" and stop is None:
        # §4.1/P4-T6: risk_per_trade without a stop is a spec-validation error.
        stop = draw(st.floats(min_value=0.5, max_value=50.0))

    return Case(
        rows=rows,
        family=family,
        fast=fast,
        slow=slow,
        with_cross=with_cross,
        with_exit_rule=with_exit_rule,
        rsi_filter=rsi_filter,
        abs_level=abs_level,
        abs_exit_level=abs_exit_level,
        stop=stop,
        take_profit=take_profit,
        trailing=trailing,
        max_holding=max_holding,
        method=method,
        sizing_value=sizing_value,
        percent_value=percent_value,
        allow_fractional=allow_fractional,
        fee_bps=draw(st.floats(min_value=0.0, max_value=500.0)),
        slippage_bps=draw(st.floats(min_value=0.0, max_value=500.0)),
        fixed_fee=draw(st.floats(min_value=0.0, max_value=5.0)),
        capital=draw(st.floats(min_value=1_000.0, max_value=500_000.0)),
    )


_CASES = _cases()


# --------------------------------------------------------------------------- #
# Fixtures and helpers                                                          #
# --------------------------------------------------------------------------- #


def _bars(case: Case) -> Bars:
    """Fresh validated ``Bars`` from the case's raw rows (new object each
    call — I9 needs two independent constructions of the same data)."""
    idx = pd.date_range("2024-01-01", periods=len(case.rows), freq="D", tz="UTC")
    frame = pd.DataFrame(
        {
            "open": [row[0] for row in case.rows],
            "high": [row[1] for row in case.rows],
            "low": [row[2] for row in case.rows],
            "close": [row[3] for row in case.rows],
            "volume": [1000.0] * len(case.rows),
        },
        index=idx,
    )
    return Bars(frame)


def _rules(
    case: Case,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None]:
    """Build ``(indicators, entry_long, exit_long | None)`` for the case.

    ``relative`` family compares price to indicators (scale-invariant, the
    only family I12 may use); ``absolute`` family compares price to a drawn
    number (§4.2 allows both). Crossover mode uses sma_fast/sma_slow
    (fast < slow by construction); non-cross mode uses close vs sma_fast.
    """
    indicators: dict[str, Any] = {}
    if case.family == "relative":
        indicators["sma_f"] = {"type": "sma", "params": {"period": case.fast}, "source": "close"}
        if case.with_cross:
            indicators["sma_s"] = {
                "type": "sma",
                "params": {"period": case.slow},
                "source": "close",
            }
    if case.rsi_filter:
        indicators["rsi14"] = {"type": "rsi", "params": {"period": 14}, "source": "close"}

    if case.family == "relative" and case.with_cross:
        entry_condition: dict[str, Any] = {
            "left": "sma_f",
            "op": "crosses_above",
            "right": "sma_s",
        }
        exit_condition: dict[str, Any] = {
            "left": "sma_f",
            "op": "crosses_below",
            "right": "sma_s",
        }
    elif case.family == "relative":
        entry_condition = {"left": "close", "op": ">", "right": "sma_f"}
        exit_condition = {"left": "close", "op": "<", "right": "sma_f"}
    else:
        entry_condition = {"left": "close", "op": ">", "right": case.abs_level}
        exit_condition = {"left": "close", "op": "<", "right": case.abs_exit_level}

    entry_conditions = [entry_condition]
    if case.rsi_filter:
        entry_conditions.append({"left": "rsi14", "op": "<", "right": 70.0})
    entry: dict[str, Any] = {"all": entry_conditions}
    exit_rule: dict[str, Any] | None = {"all": [exit_condition]} if case.with_exit_rule else None
    return indicators, entry, exit_rule


def _build(case: Case) -> tuple[StrategySpec, Bars]:
    """Fresh ``StrategySpec`` + ``Bars`` for the case, asserted VALID.

    Both validation layers run on every draw: schema (pydantic
    ``model_validate``) and semantic (``validate_spec`` — indicator
    references, param bounds, warm-up vs window, sizing rules). A draw that
    fails either layer is a bug in THIS file's generator and fails the test
    loudly rather than silently narrowing the inputs.
    """
    indicators, entry, exit_rule = _rules(case)
    risk: dict[str, Any] = {}
    if case.stop is not None:
        risk["stop_loss_pct"] = case.stop
    if case.take_profit is not None:
        risk["take_profit_pct"] = case.take_profit
    if case.trailing is not None:
        risk["trailing_stop_pct"] = case.trailing
    if case.max_holding is not None:
        risk["max_holding_bars"] = case.max_holding

    rules: dict[str, Any] = {"entry_long": entry}
    if exit_rule is not None:
        rules["exit_long"] = exit_rule

    payload: dict[str, Any] = {
        "spec_version": "1.0",
        "name": "p4-t9-property",
        "universe": {"symbols": ["TEST"], "interval": "1d"},
        "period": {"start": "2024-01-01", "end": "2024-12-31"},
        "indicators": indicators,
        "rules": rules,
        "risk": risk,
        "sizing": {
            "method": case.method,
            "value": case.sizing_value,
            "allow_fractional": case.allow_fractional,
        },
        "execution": {
            "fill": "next_open",
            "fee_bps": case.fee_bps,
            "slippage_bps": case.slippage_bps,
            "fixed_fee": case.fixed_fee,
        },
        "capital": {"initial": case.capital},
    }
    spec = StrategySpec.model_validate(payload)
    errors = validate_spec(spec).errors
    assert not errors, f"generated spec must be semantically valid, got: {errors}"
    return spec, _bars(case)


def _referenced_indicators(rule: Any) -> set[str]:
    """Names of every indicator definition ``rule`` reads (§4.2 operands)."""
    names: set[str] = set()
    stack: list[Any] = [rule]
    while stack:
        node = stack.pop()
        if isinstance(node, AllRule | AnyRule):
            stack.extend(node.conditions)
        elif isinstance(node, NotRule):
            stack.append(node.condition)
        elif isinstance(node, Condition):
            for operand in (node.left, node.right):
                if isinstance(operand, IndicatorOperand):
                    names.add(operand.name)
    return names


def _entry_first_valid_index(spec: StrategySpec) -> int:
    """First bar index at which every indicator the ENTRY rule reads is valid.

    Registry warm-up is the single source of truth (C7): ``warmup_fn``
    returns the index of the first valid output (verified against the
    installed registry: ``sma(period=5).warmup_fn == 4``, ``rsi(14) == 14``).
    §4.2 makes any comparison/crossover involving NaN False, so no entry
    signal can fire before that index. Generated rules use ``lag=0``
    operands only, so no lag shift applies. Indicators read only by the EXIT
    rule are excluded deliberately: I4 is about ENTRY, and an exit rule
    still warming up merely evaluates False (hold), which is not an entry
    before warm-up.
    """
    first = 0
    for name in _referenced_indicators(spec.rules.entry_long):
        definition = spec.indicators[name]
        registry_spec = REGISTRY.get(name=definition.type)
        resolved = {param: pspec.default for param, pspec in registry_spec.params.items()}
        resolved.update(definition.params)
        first = max(first, registry_spec.warmup_fn(resolved))
    return first


def _times(trades: list[Trade]) -> list[tuple[Any, ...]]:
    """Trade timing only: (signal_time, entry_time, exit_time) per trade."""
    return [(t.signal_time, t.entry_time, t.exit_time) for t in trades]


def _sequence(trades: list[Trade]) -> list[tuple[Any, ...]]:
    """Trade sequence identity: timing + fill prices + exit reason.

    Share counts and P&L are deliberately NOT compared — sizing and fees are
    exactly what I10/I11 legitimately change (I10) or scale (I11). Fill
    prices ARE compared: they depend only on the bar data (§4.5), so a fee
    change (I10) or a capital change (I11) must leave them untouched.
    """
    return [
        (
            t.signal_time,
            t.entry_time,
            float(t.entry_price),
            t.exit_time,
            float(t.exit_price),
            t.exit_reason,
        )
        for t in trades
    ]


# --------------------------------------------------------------------------- #
# I1-I8: per-run structural invariants                                          #
# --------------------------------------------------------------------------- #


@PROFILE
@given(case=_CASES)
def test_i1_equity_identity_every_bar(case: Case) -> None:
    """I1 (§8.3): ``equity[t] == cash[t] + position_value[t]`` for every bar.

    Both sides are computed from the same operands (``ledger.equity(price)``
    is ``cash + shares * price`` and ``position_value`` is
    ``shares * close``), so the identity holds bit-for-bit; ``rtol=1e-12``
    only absorbs the (zero expected) possibility of a reassociated sum.
    """
    spec, bars = _build(case)
    curve = run(spec, bars).equity_curve
    observed = curve["equity"].to_numpy(dtype=float)
    parts = (curve["cash"] + curve["position_value"]).to_numpy(dtype=float)
    bad = ~np.isclose(observed, parts, rtol=1e-12, atol=1e-9)
    assert not bad.any(), (
        f"I1 broken: equity != cash + position_value at bars {np.flatnonzero(bad)}"
    )


@PROFILE
@given(case=_CASES)
def test_i2_cash_never_negative(case: Case) -> None:
    """I2 (§8.3): cash never negative for unlevered long-only.

    Draws deliberately include sizing/fee combinations that stress the
    affordability path (fixed_cash or fixed_shares larger than cash, 100 %
    sizing with fees, fixed_fee > 0), which is where a negative-cash bug
    would surface.
    """
    spec, bars = _build(case)
    cash = run(spec, bars).equity_curve["cash"].to_numpy(dtype=float)
    assert (cash >= 0.0).all(), f"I2 broken: negative cash at bars {np.flatnonzero(cash < 0.0)}"


@PROFILE
@given(case=_CASES)
def test_i3_entry_time_strictly_after_signal_time(case: Case) -> None:
    """I3 (§8.3): every ``entry_time`` is strictly after its ``signal_time``.

    §4.5 fills pending orders at the NEXT bar's open, so the gap is at
    least one bar (timestamps are unique daily bars).
    """
    spec, bars = _build(case)
    for trade in run(spec, bars).trades:
        assert trade.entry_time > trade.signal_time, (
            f"I3 broken: entry {trade.entry_time} not strictly after signal {trade.signal_time}"
        )


@PROFILE
@given(case=_CASES)
def test_i4_no_entry_before_indicator_warmup(case: Case) -> None:
    """I4 (§8.3): no entry before all indicators the entry rule uses are valid.

    The cutoff is recomputed OUTSIDE the engine from the registry warm-up
    contract (``_entry_first_valid_index``), not read from any engine
    output, so the engine cannot pass by agreeing with itself. Draws with
    no entry-rule indicator (absolute family without the RSI filter) yield
    cutoff = bar 0, where the invariant is vacuous by construction.
    """
    spec, bars = _build(case)
    cutoff = bars.index[_entry_first_valid_index(spec)]
    for trade in run(spec, bars).trades:
        assert trade.signal_time >= cutoff, (
            f"I4 broken: entry signalled at {trade.signal_time}, before the warm-up cutoff {cutoff}"
        )


@PROFILE
@given(case=_CASES)
def test_i5_trades_never_overlap(case: Case) -> None:
    """I5 (§8.3): trades never overlap for the same symbol (v1: one position).

    Trades are ordered by entry time (they are already generated in that
    order); each next entry must be at or after the previous exit.
    """
    spec, bars = _build(case)
    ordered = sorted(run(spec, bars).trades, key=lambda t: t.entry_time)
    for previous, nxt in itertools.pairwise(ordered):
        assert previous.exit_time <= nxt.entry_time, (
            f"I5 broken: trade {nxt.id} entered {nxt.entry_time} while trade "
            f"{previous.id} was still open (exited {previous.exit_time})"
        )


@PROFILE
@given(case=_CASES)
def test_i6_exit_not_before_entry_and_bars_held_non_negative(case: Case) -> None:
    """I6 (§8.3): ``exit_time >= entry_time`` and ``bars_held >= 0``.

    ``bars_held = exit_bar_index - entry_bar_index`` (§4.6 / SC12), so the
    two assertions are the timestamp and index readings of one fact.
    """
    spec, bars = _build(case)
    for trade in run(spec, bars).trades:
        assert trade.exit_time >= trade.entry_time, (
            f"I6 broken: exit {trade.exit_time} before entry {trade.entry_time}"
        )
        assert trade.bars_held >= 0, f"I6 broken: bars_held = {trade.bars_held} < 0"


@PROFILE
@given(case=_CASES)
def test_i7_fees_nonnegative_and_net_pnl_sums_to_equity_change(case: Case) -> None:
    """I7 (§8.3): fees >= 0, slippage cost >= 0, and sum(net_pnl) equals
    final_equity - initial_capital when flat at the end.

    The sum identity is a cash-flow partition, derived here: every ledger
    operation of a completed trade is ``-shares*fill_entry - fee_entry``
    then ``+shares*fill_exit - fee_exit``; ``net_pnl`` is
    ``(exit_price - entry_price)*shares - (fee_entry + fee_exit)`` with
    ``fill == recorded price`` (§4.6), so per trade
    ``net_pnl == cash_delta``, and cash changes ONLY through completed
    trades — therefore ``sum(net_pnl) == cash_final - initial`` whenever
    the final row is flat. Runs still holding a position at the last bar
    (whose end_of_data close settles AFTER the final row is recorded, §4.5)
    are excluded exactly by the ``position_value == 0`` precondition below.
    ``MONEY_TOL`` absorbs only IEEE accumulation, not a missing fee.
    """
    spec, bars = _build(case)
    result = run(spec, bars)
    for trade in result.trades:
        assert trade.fees >= 0.0, f"I7 broken: negative fees {trade.fees}"
        assert trade.slippage_cost >= 0.0, f"I7 broken: negative slippage {trade.slippage_cost}"

    curve = result.equity_curve
    if float(curve["position_value"].iloc[-1]) > 1e-9:
        return  # not flat: the sum identity does not apply (precondition)
    total = sum(t.net_pnl for t in result.trades)
    expected = float(curve["equity"].iloc[-1]) - case.capital
    assert total == pytest.approx(expected, rel=1e-9, abs=MONEY_TOL), (
        f"I7 broken: sum(net_pnl) = {total!r} != final - initial = {expected!r}"
    )


@PROFILE
@given(case=_CASES)
def test_i8_fill_price_within_bar_range(case: Case) -> None:
    """I8 (§8.3): the PRE-slippage fill lies within [low, high] of its bar.

    The recorded prices are slippage-adjusted (§4.5: buy up, sell down), so
    the pre-slippage level is reconstructed by dividing the exact bps
    factor back out — ``entry/(1+s)`` and ``exit/(1-s)`` — which recovers
    the level to within a few ulp (documented binary roundoff, hence
    ``PRICE_TOL``). Reconstruction matters because the recorded, slipped
    price legitimately sits outside the bar's range (a sell slips BELOW
    ``low``); asserting on it directly would be testing the wrong number.
    """
    spec, bars = _build(case)
    result = run(spec, bars)
    slip = case.slippage_bps / 10_000.0
    # Draw where the entry rule never fires (e.g. flat series with
    # close == sma, or an absolute level above every close): no fills
    # means no fill prices to range-check, so the draw is vacuous for
    # I8. Resample rather than pass vacuously - every COUNTED example
    # must exercise the invariant.
    assume(result.trades)
    for trade in result.trades:
        entry_bar = bars.loc[trade.entry_time]
        pre_entry = trade.entry_price / (1.0 + slip)
        assert (
            float(entry_bar["low"]) - PRICE_TOL <= pre_entry <= float(entry_bar["high"]) + PRICE_TOL
        ), (
            f"I8 broken: pre-slippage entry {pre_entry!r} outside "
            f"[{entry_bar['low']!r}, {entry_bar['high']!r}] at {trade.entry_time}"
        )
        exit_bar = bars.loc[trade.exit_time]
        pre_exit = trade.exit_price / (1.0 - slip)
        assert (
            float(exit_bar["low"]) - PRICE_TOL <= pre_exit <= float(exit_bar["high"]) + PRICE_TOL
        ), (
            f"I8 broken: pre-slippage exit {pre_exit!r} outside "
            f"[{exit_bar['low']!r}, {exit_bar['high']!r}] at {trade.exit_time}"
        )


# --------------------------------------------------------------------------- #
# I9-I12: run-twice / derived-case invariants                                   #
# --------------------------------------------------------------------------- #


@PROFILE
@given(case=_CASES)
def test_i9_determinism_two_runs_identical(case: Case) -> None:
    """I9 (§8.3): two runs of the same case are identical (C2 determinism).

    One random case is drawn; the second run rebuilds spec and bars from
    the SAME raw inputs through two independent ``model_validate`` /
    ``Bars`` constructions — exactly what a re-run of the same request
    does. ``Trade`` is an eq-dataclass, so list equality compares EVERY
    field (including floats) for exact equality: same spec + same data +
    same code ⇒ byte-identical results (§0.3 C2).
    """
    spec_a, bars_a = _build(case)
    spec_b, bars_b = _build(case)
    first = run(spec_a, bars_a)
    second = run(spec_b, bars_b)

    assert first.trades == second.trades, "I9 broken: trade lists differ between identical runs"
    pd.testing.assert_frame_equal(first.equity_curve, second.equity_curve)
    assert first.metrics == second.metrics, "I9 broken: metrics differ between identical runs"
    assert first.warnings == second.warnings, "I9 broken: warnings differ between identical runs"


@PROFILE
@given(case=_CASES, extra_fee=st.floats(min_value=10.0, max_value=50.0))
def test_i10_higher_fees_never_higher_final_equity(case: Case, extra_fee: float) -> None:
    """I10 (§8.3): identical trade sequence and zero slippage ⇒ higher fees
    never produce a higher final equity.

    The invariant's own preconditions are FORCED, not hoped for:
    ``slippage_bps = 0`` (as §8.3 states) and ``fixed_fee = 0``; percent
    sizing with FRACTIONAL shares removes the integer-floor artefact, where
    a higher fee can leave a cheaper share count and — on a losing trade —
    strictly more leftover cash, which is a rounding artefact of the
    affordability floor rather than the fee monotonicity I10 states (the
    integer-share path is pinned by hand-written ``test_i10``).
    Everything else — bars, rules, risk levels, capital, sizing percent,
    fee floor — is randomly drawn. The base fee is capped at 450 bps so
    ``base + extra_fee <= 500`` (§4.1 max fee_bps).

    Precondition check: the trade SEQUENCE (timing, fill prices, reason)
    must be identical between the runs — fees must not move fills — and
    only then is the equity comparison meaningful.
    """
    base = replace(
        case,
        method="percent_of_equity",
        sizing_value=case.percent_value,
        allow_fractional=True,
        fixed_fee=0.0,
        slippage_bps=0.0,
        fee_bps=min(case.fee_bps, 450.0),
    )
    richer = replace(base, fee_bps=base.fee_bps + extra_fee)

    spec_low, bars_low = _build(base)
    spec_high, bars_high = _build(richer)
    low = run(spec_low, bars_low)
    high = run(spec_high, bars_high)

    assert _sequence(low.trades) == _sequence(high.trades), (
        "I10 precondition broken: changing fees changed the trade sequence — "
        f"{_sequence(low.trades)!r} vs {_sequence(high.trades)!r}"
    )
    low_final = float(low.equity_curve["equity"].iloc[-1])
    high_final = float(high.equity_curve["equity"].iloc[-1])
    assert high_final <= low_final + 1e-6, (
        f"I10 broken: fee {richer.fee_bps:g} bps ended at {high_final!r} > "
        f"{low_final!r} with fee {base.fee_bps:g} bps"
    )


@PROFILE
@given(case=_CASES)
def test_i11_double_capital_same_timing_same_pct_returns(case: Case) -> None:
    """I11 (§8.3): doubling initial capital (fractional shares, percent
    sizing, ``fixed_fee = 0``) ⇒ identical trade timing and identical
    percentage returns.

    The second run is DERIVED from the drawn base case via
    ``replace(capital=2*capital)`` — one random case, two runs, exactly as
    §8.3 frames it. The forced knobs are the invariant's stated preconditions
    (fractional + percent + fixed_fee 0): all cost terms are then
    proportional to capital, so every quantity in the run doubles exactly
    in binary floating point (x2 introduces no rounding) and the two
    PERCENTAGE curves coincide; slippage/fees stay drawn because bps are
    proportional too, while absolute sizing methods (fixed_cash /
    fixed_shares) would rightly break proportionality and are therefore
    outside I11's stated scope.
    """
    base = replace(
        case,
        method="percent_of_equity",
        sizing_value=case.percent_value,
        allow_fractional=True,
        fixed_fee=0.0,
    )
    double = replace(base, capital=base.capital * 2.0)

    spec_a, bars_a = _build(base)
    spec_b, bars_b = _build(double)
    first = run(spec_a, bars_a)
    second = run(spec_b, bars_b)

    assert _sequence(first.trades) == _sequence(second.trades), (
        "I11 precondition broken: doubling capital changed the trade sequence — "
        f"{_sequence(first.trades)!r} vs {_sequence(second.trades)!r}"
    )
    pct_first = float(first.equity_curve["equity"].iloc[-1]) / base.capital - 1.0
    pct_second = float(second.equity_curve["equity"].iloc[-1]) / double.capital - 1.0
    assert pct_first == pytest.approx(pct_second, rel=1e-9, abs=1e-12), (
        f"I11 broken: percentage return {pct_first!r} vs {pct_second!r} after doubling capital"
    )
    assert [t.return_pct for t in first.trades] == pytest.approx(
        [t.return_pct for t in second.trades], rel=1e-9
    ), "I11 broken: per-trade percentage returns differ after doubling capital"


@PROFILE
@given(
    case=_CASES,
    k=st.sampled_from((0.25, 0.5, 2.0, 4.0, 8.0)),
)
def test_i12_price_scaling_leaves_timing_unchanged(case: Case, k: float) -> None:
    """I12 (§8.3): scaling all prices by k > 0 leaves trade timing unchanged
    for specs WITHOUT absolute price thresholds.

    Two constructions make this the mathematical statement, not a tolerance
    game:

    * ``family="relative"`` forces indicator-only rules, and the
      precondition is re-checked against the validator's own W5 warning
      (``Absolute price thresholds…``) below — the spec is proven threshold-
      free by the same code that flags thresholds elsewhere;
    * ``k`` is a power of two, so scaling is EXACT in binary floating point
      and every downstream quantity (SMA sums, risk levels from the entry
      fill, bps costs) commutes with the scaling without introducing
      rounding that could flip a near-tie comparison.

    Fractional percent sizing removes an unrelated artefact: with integer
    shares a k-scaled run can become unaffordable at k=8 and the order gets
    REJECTED by the affordability floor — a sizing-flooring artefact, not
    signal timing (§8.3 scopes I12 to timing).
    """
    base = replace(
        case,
        family="relative",
        method="percent_of_equity",
        sizing_value=case.percent_value,
        allow_fractional=True,
    )
    spec, bars = _build(base)
    warnings = validate_spec(spec).warnings
    assert not any(w.startswith("Absolute price thresholds") for w in warnings), (
        "I12 precondition broken: generated spec has an absolute price threshold"
    )

    frame = bars.copy()
    for column in ("open", "high", "low", "close"):
        frame[column] = frame[column] * k
    scaled = Bars(frame)

    first = run(spec, bars)
    second = run(spec, scaled)
    assert _times(first.trades) == _times(second.trades), (
        f"I12 broken: scaling prices by k={k} changed trade timing — "
        f"{_times(first.trades)!r} vs {_times(second.trades)!r}"
    )


# --------------------------------------------------------------------------- #
# I13-I14                                                                      #
# --------------------------------------------------------------------------- #


@PROFILE
@given(case=_CASES)
def test_i13_no_nan_or_inf_in_equity_or_metrics(case: Case) -> None:
    """I13 (§8.3): no NaN/inf in the equity curve or metrics.

    Undefined metrics are ``None`` (§4.7 null + warning), never NaN/inf —
    ``None`` is skipped exactly as the invariant words it, everything else
    must be finite. The equity-curve check covers every numeric column,
    drawdown included (division by a peak that could be zero is where a
    NaN would appear).
    """
    spec, bars = _build(case)
    result = run(spec, bars)
    numeric = result.equity_curve[["equity", "cash", "position_value", "drawdown"]].to_numpy(
        dtype=float
    )
    assert np.isfinite(numeric).all(), "I13 broken: NaN/inf in the equity curve"
    for name, value in result.metrics.items():
        if value is None:
            continue  # documented null + warning (§4.7)
        assert np.isfinite(float(value)), f"I13 broken: metric {name} is NaN/inf: {value!r}"


@PROFILE
@given(
    case=_CASES,
    stop=st.floats(min_value=0.5, max_value=50.0),
    take=st.floats(min_value=0.5, max_value=100.0),
)
def test_i14_stop_and_take_profit_fill_bounds(case: Case, stop: float, take: float) -> None:
    """I14 (§8.3): long stop-loss fill never ABOVE the stop level and
    take-profit fill never BELOW the target (pre-slippage); gap fills occur
    at the open.

    Both risk exits are FORCED non-None (drawn values replace ``None``) so
    the assertion is not vacuous by generator choice; everything else stays
    random. The levels are rebuilt from the spec alone (§4.5:
    ``entry*(1 - stop/100)``, ``entry*(1 + tp/100)``) and the pre-slippage
    fill is reconstructed from the recorded price by dividing out the exact
    bps factor (documented roundoff ⇒ ``PRICE_TOL``), so nothing is read
    back from engine internals. The gap branch is the §4.5 rule: when the
    bar's open already gapped beyond the level, the fill IS the open;
    otherwise it is exactly the level.

    ``trailing_stop`` fills are checked against a path-independent upper
    bound instead: the trail level is ``trail_high * (1 - pct/100)`` where
    ``trail_high`` only ever ratchets through entry price and PAST highs
    (§4.5 — a bar's own high can raise the stop only after that bar's
    check), so the fill can never exceed ``max(entry, highs of the trade's
    bars)``. The exact path-dependent level is pinned by the hand-written
    ``test_i7``-era trailing scenario in the unit suite (SC7), not
    re-derived here.
    """
    forced = replace(
        case,
        stop=stop if case.stop is None else case.stop,
        take_profit=take if case.take_profit is None else case.take_profit,
    )
    spec, bars = _build(forced)
    result = run(spec, bars)
    slip = forced.slippage_bps / 10_000.0
    assert forced.stop is not None and forced.take_profit is not None

    checked = 0
    for trade in result.trades:
        pre_exit = trade.exit_price / (1.0 - slip)
        exit_bar = bars.loc[trade.exit_time]
        open_price = float(exit_bar["open"])

        if trade.exit_reason == "stop_loss":
            level = trade.entry_price * (1.0 - forced.stop / 100.0)
            assert pre_exit <= level + PRICE_TOL, (
                f"I14 broken: stop fill {pre_exit!r} above stop level {level!r}"
            )
            if open_price < level:  # gap through the stop → fill at the open
                assert pre_exit == pytest.approx(open_price, abs=PRICE_TOL), (
                    f"I14 broken: gapped stop should fill at open {open_price!r}, got {pre_exit!r}"
                )
            else:
                assert pre_exit == pytest.approx(level, abs=PRICE_TOL), (
                    f"I14 broken: touched stop should fill at level {level!r}, got {pre_exit!r}"
                )
            checked += 1
        elif trade.exit_reason == "take_profit":
            level = trade.entry_price * (1.0 + forced.take_profit / 100.0)
            assert pre_exit >= level - PRICE_TOL, (
                f"I14 broken: take-profit fill {pre_exit!r} below target {level!r}"
            )
            if open_price > level:  # gap above the target → fill at the open
                assert pre_exit == pytest.approx(open_price, abs=PRICE_TOL), (
                    f"I14 broken: gapped take-profit should fill at open "
                    f"{open_price!r}, got {pre_exit!r}"
                )
            else:
                assert pre_exit == pytest.approx(level, abs=PRICE_TOL), (
                    f"I14 broken: touched take-profit should fill at level "
                    f"{level!r}, got {pre_exit!r}"
                )
            checked += 1
        elif trade.exit_reason == "trailing_stop":
            entry_idx = bars.index.get_loc(trade.entry_time)
            exit_idx = bars.index.get_loc(trade.exit_time)
            window_high = bars["high"].iloc[entry_idx : exit_idx + 1].max()
            ceiling = max(trade.entry_price, float(window_high))
            assert pre_exit <= ceiling + PRICE_TOL, (
                f"I14 broken: trailing fill {pre_exit!r} above the highest high "
                f"the trail can ratchet from ({ceiling!r})"
            )
            checked += 1

    # Not asserted as non-vacuous: a draw can legitimately produce no
    # completed trade (short series, entry only on the last bar). The pinned
    # hand-computed cases in tests/unit/test_engine_scenarios.py guarantee
    # the non-vacuous stop/take/trailing coverage; this test's job is the
    # 100 random draws where risk exits DO fire.
    del checked
