"""Semantic validation of a schema-valid StrategySpec (ROADMAP P3-T2).

P3-T1's pydantic models prove the spec is WELL-FORMED (types, bounds, extra
fields). This module proves it is MEANINGFUL against the indicator registry:
every referenced indicator exists, sources/outputs are real, params are in
bounds, sizing matches its method, and the indicator warm-up fits the
backtest window.

Contract (task mandate):

* ``validate_spec`` NEVER raises -- it always returns a
  ``SemanticValidationResult`` (errors collected, never raised);
* ALL errors are collected before returning (no stop at the first);
* error codes come from the §4.8 taxonomy already used by the registry:
  ``E_SPEC_REF`` (unknown indicator / source / output / operand reference)
  and ``E_SPEC_RANGE`` (param bounds, warm-up, sizing);
* pydantic already enforces the schema-level facts (period ordering,
  symbol regex, reserved names, raw-column membership, risk bounds) --
  they are deliberately NOT duplicated here.

Paths follow the task examples (``indicators.fast.params.period``) and
locate operands inside the rule tree (``rules.entry_long.conditions.0.left``)
so P6 repair loops can point at the offending JSON fragment.

Warm-up arithmetic is NOT reimplemented: each indicator's ``warmup_fn`` from
the P2-T1 registry is the single source of truth (probes recorded in
docs/verified_apis.md, e.g. sma(p) = p-1, highest(p) = p, adx = 2p-1).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from nlbt.errors import SpecRangeError, SpecRefError
from nlbt.indicators.registry import Registry, validate_indicator_params
from nlbt.spec.models import (
    AllRule,
    AnyRule,
    Condition,
    IndicatorOperand,
    NotRule,
    NumberOperand,
    RawColumnOperand,
    StrategySpec,
)

__all__ = [
    "SemanticError",
    "SemanticValidationResult",
    "validate_spec",
]

#: Sizing bounds per §4.1 / task items 10-13 (method-specific ranges).
_PERCENT_METHODS: frozenset[str] = frozenset({"percent_of_equity", "risk_per_trade"})
_MAX_PERCENT = 100.0

#: W5 threshold: a bare number compared to a raw price column is usually an
#: absolute price level, which split/dividend adjustment distorts.
_ABSOLUTE_PRICE_THRESHOLD = 10.0


@dataclass(frozen=True)
class SemanticError:
    """One semantic violation, located by §4.8 code + dotted path."""

    code: str  # E_SPEC_REF or E_SPEC_RANGE
    path: str  # e.g. "indicators.ema_fast.params.period"
    message: str
    hint: str = ""


@dataclass
class SemanticValidationResult:
    """Everything the validator found: errors (blocking) and warnings."""

    errors: list[SemanticError] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0


# ===========================================================================
# Indicator checks (task items 1-3)
# ===========================================================================


def _check_indicators(
    spec: StrategySpec,
    registry: Registry,
    errors: list[SemanticError],
) -> None:
    """Existence (E_SPEC_REF), allowed source (E_SPEC_REF), param bounds
    (E_SPEC_RANGE, via the registry's own validate_indicator_params)."""
    for name, indicator_def in sorted(spec.indicators.items()):
        try:
            indicator_spec = registry.get(name=indicator_def.type)
        except KeyError:
            errors.append(
                SemanticError(
                    code="E_SPEC_REF",
                    path=f"indicators.{name}.type",
                    message=f"Unknown indicator type {indicator_def.type!r} for {name!r}",
                    hint=f"Available indicators: {registry.list_indicators()}",
                )
            )
            continue  # source/param checks need the registry spec

        if indicator_def.source not in indicator_spec.allowed_sources:
            errors.append(
                SemanticError(
                    code="E_SPEC_REF",
                    path=f"indicators.{name}.source",
                    message=(
                        f"Indicator {name!r} ({indicator_def.type!r}) does not accept "
                        f"source {indicator_def.source!r}"
                    ),
                    hint=f"Allowed sources: {list(indicator_spec.allowed_sources)}",
                )
            )

        try:
            validate_indicator_params(indicator_def.type, indicator_def.params, registry)
        except SpecRefError as exc:  # defensive: type existence checked above
            errors.append(
                SemanticError(
                    code=exc.code,
                    path=f"indicators.{name}.type",
                    message=exc.message,
                    hint=exc.hint,
                )
            )
        except SpecRangeError as exc:
            violations = exc.details.get("violations", [])
            bad_params = sorted({str(v.get("param", "?")) for v in violations}) or ["?"]
            for param_name in bad_params:
                errors.append(
                    SemanticError(
                        code=exc.code,
                        path=f"indicators.{name}.params.{param_name}",
                        message=exc.message,
                        hint=exc.hint,
                    )
                )


# ===========================================================================
# Operand reference checks (task items 4-6): walk the whole rule tree
# ===========================================================================


def _walk_operands(
    node: Any,
    path: str,
) -> list[tuple[IndicatorOperand | RawColumnOperand, str]]:
    """Depth-first walk of a parsed rule tree; returns (operand, path) pairs.

    Paths mirror the parsed model structure (``rules.<side>.conditions.0.left``
    / ``rules.<side>.condition``) so an error points at the JSON fragment.
    """
    found: list[tuple[IndicatorOperand | RawColumnOperand, str]] = []
    if isinstance(node, Condition):
        for side in ("left", "right"):
            operand = getattr(node, side)
            if isinstance(operand, IndicatorOperand | RawColumnOperand):
                found.append((operand, f"{path}.{side}"))
        return found
    if isinstance(node, AllRule | AnyRule):
        for index, child in enumerate(node.conditions):
            found.extend(_walk_operands(child, f"{path}.conditions.{index}"))
        return found
    if isinstance(node, NotRule):
        found.extend(_walk_operands(node.condition, f"{path}.condition"))
    return found


def _check_operands(
    spec: StrategySpec,
    registry: Registry,
    errors: list[SemanticError],
) -> None:
    """Every IndicatorOperand must name a defined indicator (E_SPEC_REF) and
    a real output of it (E_SPEC_REF). RawColumnOperand names are already
    constrained to the OHLCV set by pydantic (task item 6)."""
    rules = spec.rules
    sides: list[tuple[str, Any]] = [("entry_long", rules.entry_long)]
    if rules.exit_long is not None:
        sides.append(("exit_long", rules.exit_long))

    for ruleside, root in sides:
        for operand, path in _walk_operands(root, f"rules.{ruleside}"):
            if not isinstance(operand, IndicatorOperand):
                continue
            defined = spec.indicators.get(operand.name)
            if defined is None:
                errors.append(
                    SemanticError(
                        code="E_SPEC_REF",
                        path=path,
                        message=(
                            f"Operand references {operand.name!r} "
                            f"({operand.output!r}@lag{operand.lag}), which is not defined"
                        ),
                        hint=f"Defined indicators: {list(spec.indicators.keys())}",
                    )
                )
                continue
            try:
                indicator_spec = registry.get(name=defined.type)
            except KeyError:
                # The unknown TYPE is already reported by _check_indicators;
                # the output check needs the registry spec, so skip here.
                continue
            if operand.output not in indicator_spec.outputs:
                errors.append(
                    SemanticError(
                        code="E_SPEC_REF",
                        path=path,
                        message=(
                            f"Indicator {operand.name!r} ({defined.type!r}) has no output "
                            f"{operand.output!r}"
                        ),
                        hint=f"Available outputs: {list(indicator_spec.outputs)}",
                    )
                )


# ===========================================================================
# Warm-up vs available bars (task item 9)
# ===========================================================================


def _indicator_warmup(
    indicator_def_type: str,
    params: dict[str, Any],
    registry: Registry,
) -> int:
    """Warm-up bars for one indicator definition, via the registry's own
    ``warmup_fn`` with omitted params resolved to their defaults (never
    recomputed here -- the registry is the single source of truth)."""
    indicator_spec = registry.get(name=indicator_def_type)
    resolved = {p: pspec.default for p, pspec in indicator_spec.params.items()}
    resolved.update(params)
    return indicator_spec.warmup_fn(resolved)


def _check_warmup(
    spec: StrategySpec,
    registry: Registry,
    errors: list[SemanticError],
) -> None:
    """Max warm-up across all DEFINED indicators vs the estimated bar count
    of the backtest window (task heuristic: trading days = calendar days *
    252/365 for interval "1d")."""
    if not spec.indicators:
        return
    warmups: dict[str, int] = {}
    for name, indicator_def in spec.indicators.items():
        try:
            warmups[name] = _indicator_warmup(indicator_def.type, indicator_def.params, registry)
        except KeyError:
            # Unknown TYPE (already reported by _check_indicators) -- its
            # warm-up is unknowable, so exclude it from the max.
            continue
    if not warmups:
        return
    total_warmup = max(warmups.values())

    days = (spec.period.end - spec.period.start).days
    estimated_bars = int(days * 252 / 365) if spec.universe.interval == "1d" else days

    if total_warmup >= estimated_bars:
        errors.append(
            SemanticError(
                code="E_SPEC_RANGE",
                path="period",
                message=(
                    f"Warm-up ({total_warmup} bars) exceeds estimated available bars "
                    f"({estimated_bars})"
                ),
                hint=(
                    f"Window {spec.period.start}..{spec.period.end} is {days} calendar days "
                    f"(~{estimated_bars} trading bars at interval {spec.universe.interval!r}); "
                    f"longest warm-up: {max(warmups, key=lambda k: warmups[k])!r}"
                ),
            )
        )


# ===========================================================================
# Sizing checks (task items 10-13)
# ===========================================================================


def _check_sizing(spec: StrategySpec, errors: list[SemanticError]) -> None:
    method = spec.sizing.method
    value = spec.sizing.value

    if method in _PERCENT_METHODS and not 0 < value <= _MAX_PERCENT:
        errors.append(
            SemanticError(
                code="E_SPEC_RANGE",
                path="sizing.value",
                message=(
                    f"{method} sizing value must satisfy 0 < value <= {_MAX_PERCENT:g}, got {value}"
                ),
            )
        )

    if method == "fixed_cash" and value <= 0:
        errors.append(
            SemanticError(
                code="E_SPEC_RANGE",
                path="sizing.value",
                message=f"fixed_cash sizing value must be > 0, got {value}",
            )
        )

    if method == "fixed_shares" and value <= 0:
        errors.append(
            SemanticError(
                code="E_SPEC_RANGE",
                path="sizing.value",
                message=f"fixed_shares sizing value must be > 0, got {value}",
            )
        )
    elif (
        method == "fixed_shares"
        and not spec.sizing.allow_fractional
        and not float(value).is_integer()
    ):
        errors.append(
            SemanticError(
                code="E_SPEC_RANGE",
                path="sizing.value",
                message=(
                    "fixed_shares sizing requires an integer value "
                    f"when allow_fractional=False, got {value}"
                ),
            )
        )

    if method == "risk_per_trade" and spec.risk.stop_loss_pct is None:
        # Risk-based sizing is meaningless without a stop: no risk to scale.
        errors.append(
            SemanticError(
                code="E_SPEC_RANGE",
                path="sizing.method",
                message="risk_per_trade sizing requires stop_loss_pct",
                hint="Set risk.stop_loss_pct (0 < pct < 100) or choose another sizing method",
            )
        )


# ===========================================================================
# Warnings (task W1, W3, W4, W5 -- W2 deferred to the engine per task)
# ===========================================================================


def _has_any_exit(spec: StrategySpec) -> bool:
    """True when at least one exit mechanism exists (rule OR any risk exit)."""
    risk = spec.risk
    has_risk_exit = (
        risk.stop_loss_pct is not None
        or risk.take_profit_pct is not None
        or risk.trailing_stop_pct is not None
        or risk.max_holding_bars is not None
    )
    return spec.rules.exit_long is not None or has_risk_exit


def _check_warnings(spec: StrategySpec, warnings: list[str]) -> None:
    # W1: no exit mechanism at all.
    if not _has_any_exit(spec):
        warnings.append("No exit mechanism defined. Position will be held until end of data.")

    # W3: 100% of equity AND a stop loss (§4.1 warnings list).
    if (
        spec.sizing.method == "percent_of_equity"
        and spec.sizing.value == _MAX_PERCENT
        and (spec.risk.stop_loss_pct is not None)
    ):
        warnings.append("100% equity sizing with a stop loss may result in large drawdowns.")

    # W4: integer shares with percent sizing.
    if spec.sizing.method == "percent_of_equity" and not spec.sizing.allow_fractional:
        warnings.append(
            "Integer shares with percent sizing may result in "
            "significant cash unused at low prices."
        )

    # W5: absolute price threshold (bare number > 10 vs a price column).
    if _has_absolute_price_threshold(spec):
        warnings.append("Absolute price thresholds are distorted by split/dividend adjustment.")


def _has_absolute_price_threshold(spec: StrategySpec) -> bool:
    """W5: any condition where a NumberOperand > 10 is compared directly
    against a RawColumnOperand named close or open (a bare price level,
    which split/dividend adjustment moves)."""
    price_columns = ("close", "open")
    rules = spec.rules
    roots = [rules.entry_long] + ([] if rules.exit_long is None else [rules.exit_long])
    for root in roots:
        for condition in _iter_conditions(root):
            sides = (condition.left, condition.right)
            for side_a, side_b in (sides, reversed(sides)):
                if (
                    isinstance(side_a, NumberOperand)
                    and side_a.value > _ABSOLUTE_PRICE_THRESHOLD
                    and isinstance(side_b, RawColumnOperand)
                    and side_b.name in price_columns
                ):
                    return True
    return False


def _iter_conditions(node: Any) -> Iterator[Condition]:
    """Yield every Condition in a parsed rule tree (depth-first)."""
    if isinstance(node, Condition):
        yield node
    elif isinstance(node, AllRule | AnyRule):
        for child in node.conditions:
            yield from _iter_conditions(child)
    elif isinstance(node, NotRule):
        yield from _iter_conditions(node.condition)


# ===========================================================================
# Main entry point
# ===========================================================================


def validate_spec(
    spec: StrategySpec,
    registry: Registry | None = None,
    today: date | None = None,
) -> SemanticValidationResult:
    """Semantically validate a SCHEMA-valid spec; never raises.

    ``registry`` defaults to the global built-in registry; ``today`` is
    accepted for interface symmetry with the spec models' injected clock
    (the period-vs-today check itself lives in pydantic, so the validator
    performs no date check of its own).
    """
    if registry is None:
        from nlbt.indicators.registry import REGISTRY

        registry = REGISTRY

    errors: list[SemanticError] = []
    warnings: list[str] = []

    _check_indicators(spec, registry, errors)
    _check_operands(spec, registry, errors)
    _check_warmup(spec, registry, errors)
    _check_sizing(spec, errors)
    _check_warnings(spec, warnings)

    return SemanticValidationResult(errors=errors, warnings=warnings)
