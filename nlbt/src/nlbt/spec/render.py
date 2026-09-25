"""Deterministic spec -> English renderer (ROADMAP P3-T5, S8).

The user's CONFIRMATION GATE: a pure-template rendering of a StrategySpec
so the user can read exactly what will run before any backtest happens.
NO LLM, NO randomness -- the same spec always renders byte-identically
(snapshot + mutation tests enforce this).

Coverage contract (S8: "Every spec field appears in the rendering"):
every field of StrategySpec is rendered, and the mutation test suite
(plus the test 50 canary sweeping all 23 fields) fails loudly the day a
field stops being rendered.

Sections follow the task's exact layout; rule rendering is recursive with
English operators (``>`` -> "is strictly above", ...). Numbers are
normalised through the P3-T4 helper (``5.0`` -> ``"5"``, ``2.5`` ->
``"2.5"``) -- one int/float normalisation implementation in the project.

The renderer also runs the P3-T2 semantic validator: its warnings go into
the WARNINGS section, and any ERRORS get a VALIDATION ERRORS section
before WARNINGS so a user can never confirm a spec that the semantic
layer already rejects (the rendering still proceeds -- never raises).
"""

from __future__ import annotations

from typing import Any

from nlbt.spec.canonical import normalise_number
from nlbt.spec.models import (
    AllRule,
    AnyRule,
    Condition,
    NotRule,
    StrategySpec,
)
from nlbt.spec.validate import validate_spec

__all__ = ["render_rule", "render_spec"]

#: English operator phrases (task-mandated mapping; complete over the Op
#: Literal, so a new operator is a compile-time mypy error until mapped).
_OP_PHRASES: dict[str, str] = {
    ">": "is strictly above",
    ">=": "is at or above",
    "<": "is strictly below",
    "<=": "is at or below",
    "crosses_above": "crosses above",
    "crosses_below": "crosses below",
}

_INDENT = "  "


def _render_operand(operand: Any) -> str:
    """One operand as display text.

    IndicatorOperand: ``name.output`` (or ``name`` for the primary
    "value" output), ``[t-lag]`` suffix when lag > 0.
    NumberOperand: normalised number (5.0 -> "5", 2.5 -> "2.5").
    RawColumnOperand: the column name ("close").
    """
    kind = getattr(operand, "kind", None)
    if kind == "indicator":
        text = operand.name if operand.output == "value" else f"{operand.name}.{operand.output}"
        if operand.lag > 0:
            text = f"{text}[t-{operand.lag}]"
        return str(text)
    if kind == "number":
        return str(normalise_number(operand.value))
    if kind == "raw_column":
        return str(operand.name)
    return repr(operand)  # defensive: unknown operand kind (never in practice)


def render_rule(node: Any, indent: int = 0) -> str:
    """Render a rule tree (Condition | AllRule | AnyRule | NotRule) as
    indented English. Recursion mirrors the P3-T1 Node grammar."""
    pad = _INDENT * indent
    if isinstance(node, Condition):
        phrase = _OP_PHRASES[node.op]
        return f"{pad}{_render_operand(node.left)} {phrase} {_render_operand(node.right)}"
    if isinstance(node, AllRule | AnyRule):
        header = (
            "ALL of the following are true:"
            if isinstance(node, AllRule)
            else "ANY of the following are true:"
        )
        lines = [f"{pad}{header}"]
        lines.extend(render_rule(child, indent + 1) for child in node.conditions)
        return "\n".join(lines)
    if isinstance(node, NotRule):
        lines = [f"{pad}NOT ("]
        lines.append(render_rule(node.condition, indent + 1))
        lines.append(f"{pad})")
        return "\n".join(lines)
    return f"{pad}(unrenderable rule node: {type(node).__name__})"  # defensive


def _or_none(section_body: list[str]) -> list[str]:
    """Empty section body -> the task's "(none)" placeholder."""
    return section_body if section_body else [_INDENT + "(none)"]


def _render_indicators(spec: StrategySpec) -> list[str]:
    lines = [
        f"{_INDENT}{name}: {definition.type}({_format_params(definition.params)}) "
        f"on {definition.source}"
        for name, definition in sorted(spec.indicators.items())
    ]
    return _or_none(lines)


def _format_params(params: dict[str, Any]) -> str:
    """``{"period": 20, "k": 2.0}`` -> ``"period=20, k=2.0"`` (sorted, so
    the rendering is independent of dict insertion order)."""
    return ", ".join(f"{key}={normalise_number(params[key])}" for key in sorted(params))


def _render_risk(spec: StrategySpec) -> list[str]:
    risk = spec.risk

    def fmt(value: float | int | None, unit: str) -> str:
        # Values arrive as floats from the schema (6 -> 6.0); normalise for
        # display ("6%", not "6.0%") like every other number here.
        if value is None:
            return "none"
        return f"{normalise_number(value)}{unit}"

    lines = [
        f"{_INDENT}Stop loss:      {fmt(risk.stop_loss_pct, '%')}",
        f"{_INDENT}Take profit:    {fmt(risk.take_profit_pct, '%')}",
        f"{_INDENT}Trailing stop:  {fmt(risk.trailing_stop_pct, '%')}",
        f"{_INDENT}Max holding:    {fmt(risk.max_holding_bars, ' bars')}",
    ]
    if all(
        value is None
        for value in (
            risk.stop_loss_pct,
            risk.take_profit_pct,
            risk.trailing_stop_pct,
            risk.max_holding_bars,
        )
    ):
        return [_INDENT + "(none)"]
    return lines


def render_spec(spec: StrategySpec) -> str:
    """Render the complete spec as deterministic English (see module doc)."""
    validation = validate_spec(spec)

    lines: list[str] = [f"=== STRATEGY: {spec.name} ==="]

    lines.append("SYMBOL AND PERIOD")
    lines.append(f"{_INDENT}Symbol:   {spec.universe.symbols[0]}")
    lines.append(f"{_INDENT}Interval: {spec.universe.interval}")
    lines.append(f"{_INDENT}From:     {spec.period.start}")
    lines.append(f"{_INDENT}To:       {spec.period.end}")

    lines.append("INDICATORS")
    lines.extend(_render_indicators(spec))

    lines.append("ENTRY RULE (long)")
    lines.append(render_rule(spec.rules.entry_long, indent=1))

    lines.append("EXIT RULE (long)")
    if spec.rules.exit_long is None:
        # Task-mandated literal (em dash inside a string literal is fine:
        # RUF002 only fires in comments/docstrings — probed P2-T8).
        lines.append(f"{_INDENT}(none — position held to end of data)")
    else:
        lines.append(render_rule(spec.rules.exit_long, indent=1))

    lines.append("RISK EXITS")
    lines.extend(_render_risk(spec))

    lines.append("POSITION SIZING")
    lines.append(f"{_INDENT}Method: {spec.sizing.method}")
    lines.append(f"{_INDENT}Value:  {normalise_number(spec.sizing.value)}")
    lines.append(f"{_INDENT}Fractional shares: {'yes' if spec.sizing.allow_fractional else 'no'}")

    lines.append("EXECUTION")
    fee = normalise_number(spec.execution.fee_bps)
    slippage = normalise_number(spec.execution.slippage_bps)
    lines.append(f"{_INDENT}Fill:      {spec.execution.fill} (next bar open)")
    lines.append(f"{_INDENT}Fee:       {fee} bps per side")
    lines.append(f"{_INDENT}Slippage:  {slippage} bps per side")
    lines.append(f"{_INDENT}Fixed fee: {normalise_number(spec.execution.fixed_fee)} per trade")

    lines.append("CAPITAL")
    initial = normalise_number(spec.capital.initial)
    lines.append(f"{_INDENT}Initial:  {initial} {spec.capital.currency}")

    lines.append("ASSUMPTIONS")
    lines.extend(
        _or_none(
            [
                f"{_INDENT}- {a.field}: {normalise_number(a.value)} ({a.reason})"
                for a in spec.assumptions
            ]
        )
    )

    if validation.errors:
        lines.append("VALIDATION ERRORS")
        lines.extend(f"{_INDENT}- [{e.code}] {e.path}: {e.message}" for e in validation.errors)

    lines.append("WARNINGS")
    lines.extend(_or_none([f"{_INDENT}- {warning}" for warning in validation.warnings]))

    lines.append("UNSUPPORTED REQUESTS")
    lines.extend(_or_none([f"{_INDENT}- {item}" for item in spec.unsupported]))

    lines.append("===")
    return "\n".join(lines)
