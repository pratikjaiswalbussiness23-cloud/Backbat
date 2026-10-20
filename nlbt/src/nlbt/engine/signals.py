"""Signal evaluation (ROADMAP P4-T2, §4.2 rules over boolean arrays).

Vectorised, lookahead-free rule evaluation: every element of an output
depends only on the SAME-or-earlier bar of its inputs (lag only ever shifts
BACKWARD; crossover looks at ``t-1`` and ``t``; indicators are computed
bar-causally by the registry's ``compute_fn``).

Pinned API (tests/unit/test_engine_signals.py, OQ-0049):

    compare(left, op, right)            # op: > >= < <= crosses_above crosses_below
    crosses_above(a, b) / crosses_below(a, b)
    lag(values, k)                      # value from bar t-k; NaN before bar k
    logical_and(*bool_series) / logical_or(*bool_series) / logical_not(bool_series)
    evaluate_rule(rule, bars, indicators) -> bool array

Semantics (§4.2):

* Operands are consumed POSITIONALLY as float arrays (lists, numpy arrays
  and pandas Series all convert); operands of equal length line up bar for
  bar — inside ``evaluate_rule`` every operand is built on ``bars.index``,
  so positional == aligned there.
* NaN comparisons are ALWAYS False (§4.2) — numpy/pandas comparison
  semantics, with the invalid-value floating-point flag silenced.
* ``crosses_above(a, b)`` at t: ``a[t-1] <= b[t-1] AND a[t] > b[t]``, all
  values non-NaN (NaN makes the relevant comparison False). Index 0 is
  always False (no previous bar). Equality at t-1 COUNTS (``<=`` half).
* ``lag(values, k)``: element t holds the value from bar t-k; bars before
  the window are NaN — a negative k is rejected outright (future data is
  forbidden, §4.2), and there is no Python negative-index wraparound.
* ``evaluate_rule`` resolves operands per §4.2: raw OHLCV columns, indicator
  outputs (computed via the registry on demand, optional ``lag`` applied)
  and literal numbers; the rule tree (Condition / all / any / not) reduces
  to one boolean array. Warm-up is an explicit GATE on that array (§4.5):
  the result is False wherever any indicator output the rule references is
  NaN at that bar (a lag-k reference counts as valid from ``first_valid +
  k``), so no signal can fire before all indicators used by the rule are
  valid — for every tree shape. A bare "NaN comparison is False" guard is
  not enough: ``not`` inverts it and literal ``any`` arms mask it (review
  finding H1).
"""

from __future__ import annotations

import operator
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import numpy as np
import pandas as pd

from nlbt.data.models import Bars
from nlbt.errors import SpecRefError
from nlbt.indicators.registry import REGISTRY, Registry, validate_indicator_params
from nlbt.spec.models import (
    AllRule,
    AnyRule,
    Condition,
    IndicatorDef,
    IndicatorOperand,
    Node,
    NotRule,
    NumberOperand,
    Operand,
    RawColumnOperand,
)

__all__ = [
    "compare",
    "crosses_above",
    "crosses_below",
    "evaluate_rule",
    "lag",
    "logical_and",
    "logical_not",
    "logical_or",
]

#: Anything that converts to a float array of bar values.
ArrayLike = np.ndarray | pd.Series | Sequence[float]

#: Anything that converts to a boolean array.
BoolArrayLike = np.ndarray | pd.Series | Sequence[bool]

#: §4.2 comparison operators → binary functions (NaN <op> x is False).
_COMPARISONS: dict[str, Callable[[Any, Any], Any]] = {
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
}


def _float_array(values: ArrayLike | float) -> np.ndarray:
    """Convert an operand to a float64 numpy array (scalars broadcast)."""
    return np.asarray(values, dtype=float)


def compare(left: ArrayLike | float, op: str, right: ArrayLike | float) -> np.ndarray:
    """Elementwise ``left <op> right`` as a bool array; NaN compares False.

    ``op`` is a §4.2 operator string: one of ``>``, ``>=``, ``<``, ``<=``,
    ``crosses_above``, ``crosses_below`` (the crossover forms are the same
    definitions as :func:`crosses_above` / :func:`crosses_below`).
    """
    if op in ("crosses_above", "crosses_below"):
        fn = crosses_above if op == "crosses_above" else crosses_below
        return fn(_float_array(left), _float_array(right))
    comparison = _COMPARISONS.get(op)
    if comparison is None:
        raise ValueError(f"Unknown comparison operator {op!r} (§4.2 operators only)")
    a = _float_array(left)
    b = _float_array(right)
    with np.errstate(invalid="ignore"):
        return np.asarray(comparison(a, b), dtype=bool)


def crosses_above(a: ArrayLike, b: ArrayLike) -> np.ndarray:
    """True where ``a`` crosses ABOVE ``b`` (§4.2): ``a[t-1] <= b[t-1] AND
    a[t] > b[t]``, all four values non-NaN. Index 0 is always False."""
    return _crosses(a, b, above=True)


def crosses_below(a: ArrayLike, b: ArrayLike) -> np.ndarray:
    """True where ``a`` crosses BELOW ``b`` (§4.2): ``a[t-1] >= b[t-1] AND
    a[t] < b[t]``, all four values non-NaN. Index 0 is always False."""
    return _crosses(a, b, above=False)


def _crosses(a: ArrayLike, b: ArrayLike, *, above: bool) -> np.ndarray:
    """Shared §4.2 crossover kernel (positional, NaN-safe, no lookahead)."""
    x = np.atleast_1d(_float_array(a))
    y = np.atleast_1d(_float_array(b))
    out = np.zeros(max(x.shape[0], y.shape[0]), dtype=bool)
    length = out.shape[0]
    if length < 2:
        return out
    x = x[:length]
    y = y[:length]
    with np.errstate(invalid="ignore"):
        if above:
            previous = x[:-1] <= y[:-1]  # equality at t-1 counts
            current = x[1:] > y[1:]  # strict: touching is not a cross
        else:
            previous = x[:-1] >= y[:-1]
            current = x[1:] < y[1:]
    out[1:] = previous & current  # NaN anywhere makes that half False
    return out


def lag(values: ArrayLike, k: int) -> np.ndarray:
    """Value from bar ``t-k`` (§4.2); bars before the window are NaN.

    ``k = 0`` is the identity. A negative ``k`` would read the FUTURE and is
    rejected; index 0 of ``lag(values, 1)`` is NaN — never the wrap-around
    element Python would return for ``values[-1]``.
    """
    if k < 0:
        raise ValueError(f"Negative lag {k} would read future data (§4.2 forbids it)")
    arr = np.atleast_1d(_float_array(values))
    if k == 0:
        return arr.copy()
    out = np.full(arr.shape, np.nan, dtype=float)
    if k < arr.shape[0]:
        out[k:] = arr[: arr.shape[0] - k]
    return out


def logical_and(*bool_series: BoolArrayLike) -> np.ndarray:
    """Elementwise AND of one or more boolean array-likes."""
    if not bool_series:
        raise ValueError("logical_and requires at least one operand")
    result = np.asarray(bool_series[0], dtype=bool)
    for series in bool_series[1:]:
        result = np.logical_and(result, np.asarray(series, dtype=bool))
    return np.asarray(result, dtype=bool)


def logical_or(*bool_series: BoolArrayLike) -> np.ndarray:
    """Elementwise OR of one or more boolean array-likes."""
    if not bool_series:
        raise ValueError("logical_or requires at least one operand")
    result = np.asarray(bool_series[0], dtype=bool)
    for series in bool_series[1:]:
        result = np.logical_or(result, np.asarray(series, dtype=bool))
    return np.asarray(result, dtype=bool)


def logical_not(bool_series: BoolArrayLike) -> np.ndarray:
    """Elementwise NOT of a boolean array-like."""
    return np.asarray(np.logical_not(np.asarray(bool_series, dtype=bool)), dtype=bool)


def evaluate_rule(
    rule: Node,
    bars: Bars,
    indicators: Mapping[str, IndicatorDef],
    *,
    registry: Registry | None = None,
) -> np.ndarray:
    """Evaluate a §4.2 rule tree against ``bars`` → one bool array.

    ``indicators`` is the spec's indicator map (usage name →
    :class:`~nlbt.spec.models.IndicatorDef`); referenced indicators are
    computed once per call through ``registry`` (default: the global
    :data:`~nlbt.indicators.registry.REGISTRY`) with
    ``validate_indicator_params`` filling defaults, then read per operand
    (``output`` column, ``lag`` shifted back). The reduced rule array is
    then gated (§4.5 warm-up): every bar where any indicator output the
    rule references (post-``lag``) is NaN is forced False, whatever the
    tree shape — so ``not`` rules and literal ``any`` arms cannot signal
    during warm-up (review finding H1; pinned by tests W1-W11).

    Unknown indicator references and unknown output columns raise
    ``E_SPEC_REF`` (§4.8) rather than leaking a KeyError.
    """
    reg = REGISTRY if registry is None else registry
    n = len(bars)
    cache: dict[str, pd.DataFrame] = {}
    warmup_masks: list[np.ndarray] = []

    def resolve_operand(operand: Operand) -> np.ndarray:
        if isinstance(operand, NumberOperand):
            return np.full(n, float(operand.value), dtype=float)
        if isinstance(operand, RawColumnOperand):
            return bars[operand.name].to_numpy(dtype=float)
        if isinstance(operand, IndicatorOperand):
            if operand.name not in indicators:
                raise SpecRefError(
                    f"Rule references undefined indicator {operand.name!r}",
                    details={
                        "indicator": operand.name,
                        "defined_indicators": sorted(indicators),
                    },
                    hint="Declare the indicator in spec.indicators before referencing it.",
                )
            frame = cache.get(operand.name)
            if frame is None:
                definition = indicators[operand.name]
                params = validate_indicator_params(definition.type, definition.params, registry=reg)
                spec = reg.get(definition.type)
                frame = spec.compute_fn(bars, params, definition.source)
                cache[operand.name] = frame
            if operand.output not in frame.columns:
                raise SpecRefError(
                    f"Indicator {operand.name!r} has no output {operand.output!r}",
                    details={
                        "indicator": operand.name,
                        "output": operand.output,
                        "available_outputs": [str(c) for c in frame.columns],
                    },
                    hint=f"Available outputs: {[str(c) for c in frame.columns]}",
                )
            series = frame[operand.output].to_numpy(dtype=float)
            if operand.lag > 0:
                series = lag(series, operand.lag)
            # §4.5 warm-up gate: this reference is usable only where its
            # (post-lag) output exists; collected here, applied to the
            # reduced rule array below (finding H1).
            warmup_masks.append(~np.isnan(series))
            return series
        raise TypeError(f"Unknown operand type: {type(operand)!r}")

    def eval_node(node: Node) -> np.ndarray:
        if isinstance(node, Condition):
            return compare(resolve_operand(node.left), node.op, resolve_operand(node.right))
        if isinstance(node, AllRule):
            return logical_and(*(eval_node(child) for child in node.conditions))
        if isinstance(node, AnyRule):
            return logical_or(*(eval_node(child) for child in node.conditions))
        if isinstance(node, NotRule):
            return logical_not(eval_node(node.condition))
        raise TypeError(f"Unknown rule node type: {type(node)!r}")

    result = eval_node(rule)
    if not warmup_masks:
        return result
    warm = np.ones(n, dtype=bool)
    for mask in warmup_masks:
        warm &= mask
    return np.asarray(np.logical_and(result, warm), dtype=bool)
