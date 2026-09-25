"""StrategySpec v1 pydantic models (ROADMAP P3-T1, §4.1-§4.2).

Strict-typed schema: ``extra="forbid"`` on EVERY model (unknown fields are
rejected, per P3-T1 acceptance), scalar types strict (no ``"5"`` → ``5.0``
coercion; ``int`` → ``float`` widening IS allowed — lossless, the OQ-0014
precedent), no ``==`` operator (float equality is a footgun — §4.2), and no
negative lags (future data — §4.2).

Two deliberate normalisation layers (both recorded in OQ-0033) so that the
ROADMAP's OWN Appendix C fixtures parse verbatim while the model layer stays
discriminated and explicit (§4.2's Node grammar):

1. ``_lift_operand`` lifts ``{"left": "fast", "op": "<", "right": 70}``
   operands: bare ``str`` left/right become indicator refs, bare numbers
   become ``NumberOperand``; ``"open"/"high"/"low"/"close"/"volume"`` become
   ``RawColumnOperand`` (raw columns are more specific than an indicator ref
   and the §4.2 grammar allows both spellings).
2. ``_lift_rule`` lifts ``{"all": [...]}`` / ``{"any": [...]}`` /
   ``{"not": {...}}`` into the ``kind``-tagged AllRule/AnyRule/NotRule form,
   RECURSIVELY: condition dicts inside a lifted body that lack a ``kind``
   tag (every Appendix C rule condition is written shorthand) are tagged
   ``{"kind": "condition", ...}`` here too — a discriminated union needs the
   tag on each item of the ``conditions`` list, and nested shorthand rules
   are lifted the same way.

Both run as ``mode="before"`` FIELD validators on the union-typed fields —
a discriminated union's tag lookup happens on the RAW input (probed:
pydantic 2.13.5 rejects an untagged dict before any class validator could
run), so the lift MUST happen before union discrimination. Full tagged
documents (what P6 emits) are accepted unchanged; shorthand is accepted so
Appendix C — the task's mandated fixtures — parses as written.

Nesting depth: ``rule_depth`` counts Condition=1, each rule wrapper =+1;
v1 limit is 4 (§4.2), enforced in AllRule/AnyRule/NotRule's after-validator.

Deterministic clock: the period-vs-today check calls the module-level
``_get_today()`` (default ``date.today``) — tests monkeypatch it (task
mandate: never ``date.today()`` directly in a validator).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date
from typing import Annotated, Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

__all__ = [
    "ALL_RULE_MAX_CONDITIONS",
    "ALL_RULE_MIN_CONDITIONS",
    "INDICATOR_NAME_MAX_LENGTH",
    "INDICATOR_NAME_PATTERN",
    "MAX_RULE_DEPTH",
    "RAW_COLUMNS",
    "RESERVED_INDICATOR_NAMES",
    "RULE_KINDS",
    "SYMBOL_PATTERN",
    "AllRule",
    "AnyRule",
    "Assumption",
    "Capital",
    "Condition",
    "Execution",
    "IndicatorDef",
    "IndicatorOperand",
    "Node",
    "NotRule",
    "NumberOperand",
    "Op",
    "Operand",
    "OperandUnion",
    "Period",
    "RawColumnOperand",
    "Risk",
    "RuleUnion",
    "Rules",
    "Sizing",
    "SizingMethod",
    "StrategySpec",
    "Universe",
    "rule_depth",
]

#: Patchable clock (task mandate) — validators call _get_today(), never
#: date.today() directly, so tests can freeze time deterministically.
_get_today: Callable[[], date] = date.today

#: ---------------------------------------------------------------- patterns
INDICATOR_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
INDICATOR_NAME_MAX_LENGTH = 32
SYMBOL_PATTERN = re.compile(r"^[A-Za-z0-9.\-=^]{1,20}$")  # task-literal class
RAW_COLUMNS: frozenset[str] = frozenset({"open", "high", "low", "close", "volume"})
RESERVED_INDICATOR_NAMES: frozenset[str] = frozenset(
    {
        "open",
        "high",
        "low",
        "close",
        "volume",
        "entry_long",
        "exit_long",
        "entry_short",
        "exit_short",
    }
)

#: ------------------------------------------------------------------ limits
MAX_RULE_DEPTH = 4
ALL_RULE_MIN_CONDITIONS = 1
ALL_RULE_MAX_CONDITIONS = 20

#: Rule ``kind`` tags (shorthand lifting dispatches on these).
RULE_KINDS: frozenset[str] = frozenset({"all", "any", "not"})


class _StrictModel(BaseModel):
    """Base: unknown fields are REJECTED, strict scalars, strict Pydantic.

    ``strict=True`` makes number/bool literals strict (no ``"5"`` → 5.0);
    per the probe on 2.13.5 it does NOT block int → float widening, and
    ``date`` fields remain lax enough to parse ISO strings — both deliberate
    (Appendix C fixtures; lossless widening per OQ-0014).
    """

    model_config = ConfigDict(extra="forbid", strict=True)


# ===========================================================================
# Operands (§4.2)
# ===========================================================================


class NumberOperand(_StrictModel):
    """A literal number operand: ``{"kind": "number", "value": 3.5}``."""

    kind: Literal["number"]
    value: float


class IndicatorOperand(_StrictModel):
    """A reference to one indicator output: name (registry identifier) and
    the output column (e.g. ``value``, ``line``), read ``lag`` bars back.

    ``output`` defaults to ``"value"`` because the §4.2 grammar allows a bare
    indicator name and a ``{"name": ..., "lag": ...}`` dict — both meaning
    the indicator's primary output (§4.3 lists ``value`` first for every
    single-output indicator). Whether the referenced indicator actually HAS
    that output is reference resolution — the P3-T2 semantic validator's
    job against the live registry, not a schema-level check (OQ-0034)."""

    kind: Literal["indicator"]
    name: Annotated[
        str, Field(pattern=INDICATOR_NAME_PATTERN.pattern, max_length=INDICATOR_NAME_MAX_LENGTH)
    ]
    output: str = "value"
    lag: Annotated[int, Field(strict=True, ge=0)] = 0


class RawColumnOperand(_StrictModel):
    """A raw OHLCV column reference (one of open/high/low/close/volume)."""

    kind: Literal["raw_column"]
    name: str

    @field_validator("name")
    @classmethod
    def _name_is_a_raw_column(cls, value: str) -> str:
        if value not in RAW_COLUMNS:
            raise ValueError(f"raw_column name must be one of {sorted(RAW_COLUMNS)}, got {value!r}")
        return value


#: The operand union (discriminated on ``kind``). Alias kept simple for
#: readability at use sites; ``Node``'s Condition embeds it on left/right.
OperandUnion = Annotated[
    NumberOperand | IndicatorOperand | RawColumnOperand,
    Field(discriminator="kind"),
]
Operand = OperandUnion


def _lift_operand(value: Any) -> Any:
    """Lift every §4.2 ``Operand`` spelling into the tagged form (OQ-0033).

    The §4.2 grammar is ``Operand := number | indicator_name | raw_column |
    "indicator.output" | { "name": <ref>, "lag": int >= 0 }``, so:

    * ``str`` in RAW_COLUMNS → ``{"kind": "raw_column", "name": ...}``
    * ``"macd.signal"`` → ``{"kind": "indicator", "name": "macd",
      "output": "signal"}`` (indicator names cannot contain a dot, so the
      LAST dot separates name from output)
    * other ``str`` → ``{"kind": "indicator", "name": ...}`` (primary output)
    * ``int``/``float`` (not bool) → ``{"kind": "number", "value": ...}``
    * untagged dict with a ``name`` key → ``{"kind": "indicator", ...}``
    * already-tagged dicts and model instances pass through unchanged.
    """
    if isinstance(value, bool):
        return value  # bools are never operands; let validation reject them
    if isinstance(value, str):
        if value in RAW_COLUMNS:
            return {"kind": "raw_column", "name": value}
        if "." in value:
            name, _, output = value.rpartition(".")
            return {"kind": "indicator", "name": name, "output": output}
        return {"kind": "indicator", "name": value}
    if isinstance(value, (int, float)):
        return {"kind": "number", "value": value}
    if isinstance(value, dict) and "kind" not in value and "name" in value:
        return {"kind": "indicator", **value}
    return value


class Condition(_StrictModel):
    """``left <op> right`` — operands discriminated on ``kind``.

    ``mode="before"`` field validators lift the §4.2 shorthand operands
    (bare strings/numbers — see module docstring / OQ-0033) BEFORE the
    discriminated union extracts its tag.
    """

    kind: Literal["condition"]
    left: OperandUnion
    op: Op
    right: OperandUnion

    @model_validator(mode="before")
    @classmethod
    def _default_kind(cls, value: Any) -> Any:
        # The §4.2 grammar spells a condition WITHOUT a tag
        # (``Condition := { "left", "op", "right" }``); the ``kind`` tag is
        # only our discriminated-union implementation detail, so validating
        # a Condition directly accepts the grammar spelling too (OQ-0033).
        # Inside unions the tag is injected earlier, by _lift_condition /
        # _normalize_node (the union reads the tag before validators run).
        if isinstance(value, dict) and "kind" not in value:
            return {"kind": "condition", **value}
        return value

    @field_validator("left", "right", mode="before")
    @classmethod
    def _lift_shorthand_operand(cls, value: Any) -> Any:
        return _lift_operand(value)


# ===========================================================================
# Rule nodes (recursive, depth ≤ 4, §4.2)
# ===========================================================================

#: Comparison operators. ``==`` is intentionally ABSENT in v1 (float
#: equality is a footgun — §4.2 "Precise semantics").
Op = Literal[">", ">=", "<", "<=", "crosses_above", "crosses_below"]


def _lift_rule(value: Any) -> Any:
    """Lift the §4.2 rule shorthand ``{"all": [...]}`` (etc.) into the
    tagged form ``{"kind": "all", "conditions": [...]}`` (OQ-0033).

    Recursively (shorthand rules nest freely in §4.2):

    * a dict with exactly one rule key and no ``kind`` tag is rewritten to
      the tagged form;
    * inside a lifted ``all``/``any`` body, condition dicts that lack a
      ``kind`` tag but have the ``left``/``op``/``right`` keys are tagged
      ``{"kind": "condition", ...}`` — the Appendix C fixtures write
      conditions shorthand, and the discriminated union reads each item's
      tag off the raw input before any class validator could run;
    * already-tagged dicts and model instances pass through unchanged.

    A dict that has NEITHER a ``kind`` tag NOR exactly one rule key is left
    for the union to reject with pydantic's own error.
    """
    if isinstance(value, dict) and "kind" not in value:
        present = [kind for kind in RULE_KINDS if kind in value]
        if len(present) == 1:
            kind = present[0]
            body = value[kind]
            if kind == "not":
                return {"kind": "not", "condition": _normalize_node(body)}
            return {
                "kind": kind,
                "conditions": [_normalize_node(item) for item in body],
            }
    return value


def _lift_condition(value: Any) -> Any:
    """Tag an untagged shorthand condition dict ``{"left", "op", "right"}``
    as ``{"kind": "condition", ...}`` (OQ-0033). Already-tagged dicts and
    anything else pass through unchanged (the union rejects those itself).
    """
    if isinstance(value, dict) and "kind" not in value and {"left", "op", "right"} <= value.keys():
        return {"kind": "condition", **value}
    return value


def _normalize_node(value: Any) -> Any:
    """Normalize one raw rule-tree node: lift a shorthand rule OR tag a
    shorthand condition, recursing into rule bodies (OQ-0033)."""
    if not isinstance(value, dict) or "kind" in value:
        return value
    if RULE_KINDS & value.keys():
        return _lift_rule(value)
    return _lift_condition(value)


def rule_depth(node: Node, current: int = 1) -> int:
    """Depth of a rule tree: Condition = 1; each rule wrapper adds 1.

    Implemented as a standalone recursive function (task mandate) over the
    parsed model tree. ``current`` tracks the depth AT this node.
    """
    if isinstance(node, Condition):
        return current
    if isinstance(node, AllRule | AnyRule):
        return max((rule_depth(child, current + 1) for child in node.conditions), default=current)
    if isinstance(node, NotRule):
        return rule_depth(node.condition, current + 1)
    raise TypeError(f"Unknown rule node type: {type(node)!r}")


def _node_depth(node: Condition | AllRule | AnyRule | NotRule, current: int = 1) -> int:
    """rule_depth for callers holding the static union type.

    Model validators receive ``self`` typed as the concrete class' shared
    base (mypy cannot see that it IS a union member), so they route through
    this thin wrapper after a cast — one traversal definition (rule_depth).
    """
    return rule_depth(node, current=current)


class _ConditionsRule(_StrictModel):
    """Shared body of AllRule/AnyRule: 1..20 conditions, depth ≤ 4."""

    conditions: list[Node] = Field(
        min_length=ALL_RULE_MIN_CONDITIONS, max_length=ALL_RULE_MAX_CONDITIONS
    )

    @field_validator("conditions", mode="before")
    @classmethod
    def _normalize_items(cls, value: Any) -> Any:
        # Tag shorthand items even when THIS rule arrived already tagged
        # (mixed documents): the discriminated union reads each item's tag
        # off the raw input before any validator could run (OQ-0033).
        if isinstance(value, list):
            return [_normalize_node(item) for item in value]
        return value

    @model_validator(mode="after")
    def _depth_limit(self) -> _ConditionsRule:
        # NOTE: runs inside the recursive parse, so by construction children
        # are already depth-valid; the check re-derives depth from the root
        # of each parse, giving one consistent definition (root = 1). mypy
        # only sees the _ConditionsRule type, so route through the union.
        depth = _node_depth(cast("Condition | AllRule | AnyRule | NotRule", self), current=1)
        if depth > MAX_RULE_DEPTH:
            raise ValueError(
                f"Rule nesting depth {depth} exceeds the v1 maximum of {MAX_RULE_DEPTH}"
            )
        return self


class AllRule(_ConditionsRule):
    """Logical AND over ``conditions`` (tagged ``kind: "all"``)."""

    kind: Literal["all"]


class AnyRule(_ConditionsRule):
    """Logical OR over ``conditions`` (tagged ``kind: "any"``)."""

    kind: Literal["any"]


class NotRule(_StrictModel):
    """Logical NOT over exactly one node (tagged ``kind: "not"``)."""

    kind: Literal["not"]
    condition: Node

    @field_validator("condition", mode="before")
    @classmethod
    def _normalize_inner(cls, value: Any) -> Any:
        # Same rationale as _ConditionsRule._normalize_items (OQ-0033).
        return _normalize_node(value)

    @model_validator(mode="after")
    def _depth_limit(self) -> NotRule:
        depth = _node_depth(cast("Condition | AllRule | AnyRule | NotRule", self), current=1)
        if depth > MAX_RULE_DEPTH:
            raise ValueError(
                f"Rule nesting depth {depth} exceeds the v1 maximum of {MAX_RULE_DEPTH}"
            )
        return self


#: Forward references (resolved by the model_rebuild calls below).
Node = Annotated[
    Condition | AllRule | AnyRule | NotRule,
    Field(discriminator="kind"),
]
RuleUnion = Node

# Depth counting above uses these names before their definition — rebuild the
# recursive models now that ``Node`` exists (task-mandated pattern).
for _model in (AllRule, AnyRule, NotRule):
    _model.model_rebuild()
del _model


# ===========================================================================
# Rule sets, risk, sizing, execution, universe, period, capital
# ===========================================================================


class Rules(_StrictModel):
    """Entry/exit rule sets (exit optional — §4.1 row ``rules.exit_long``).

    ``mode="before"`` field validators lift the §4.2 shorthand rule dicts
    (``{"all": [...]}`` → ``{"kind": "all", "conditions": [...]}``)
    BEFORE the discriminated union extracts its tag — a discriminated union
    reads the tag off the raw input (probed: pydantic 2.13.5 raises
    ``union_tag_not_found`` before any class-level validator could run), so
    class validators cannot do this lifting (OQ-0033).
    """

    entry_long: Node
    exit_long: Node | None = None

    @field_validator("entry_long", "exit_long", mode="before")
    @classmethod
    def _lift_shorthand_rule(cls, value: Any) -> Any:
        # _normalize_node (not _lift_rule) because a bare condition dict is
        # itself a valid Node in the §4.2 grammar: Node := Condition | Rule.
        return _normalize_node(value)


class Risk(_StrictModel):
    """Risk exits; every field optional with §4.1's open-interval bounds.

    The bounds ride on the fields (strict + gt/lt through ``X | None``,
    probed): ``0 < stop_loss_pct < 100``, ``take_profit_pct > 0``,
    ``0 < trailing_stop_pct < 100``, ``max_holding_bars >= 1``.
    """

    stop_loss_pct: Annotated[float, Field(strict=True, gt=0, lt=100)] | None = None
    take_profit_pct: Annotated[float, Field(strict=True, gt=0)] | None = None
    trailing_stop_pct: Annotated[float, Field(strict=True, gt=0, lt=100)] | None = None
    max_holding_bars: Annotated[int, Field(strict=True, ge=1)] | None = None


SizingMethod = Literal["percent_of_equity", "fixed_cash", "fixed_shares", "risk_per_trade"]


class Sizing(_StrictModel):
    """Position sizing. v1 bounds ``value > 0`` (method-specific ranges —
    e.g. percent ≤ 100 — are the P3-T2 semantic validator's business)."""

    method: SizingMethod
    value: Annotated[float, Field(strict=True, gt=0)]
    allow_fractional: bool = True


class Execution(_StrictModel):
    """Fill convention and costs; only ``next_open`` exists in v1 (§4.1)."""

    fill: Literal["next_open"] = "next_open"
    fee_bps: Annotated[float, Field(strict=True, ge=0)] = 5.0
    slippage_bps: Annotated[float, Field(strict=True, ge=0)] = 5.0
    fixed_fee: Annotated[float, Field(strict=True, ge=0)] = 0.0


class Universe(_StrictModel):
    """Tradable symbols; v1: exactly ONE symbol, interval ``1d`` only."""

    symbols: Annotated[list[str], Field(min_length=1, max_length=1)]
    interval: Literal["1d"] = "1d"

    @field_validator("symbols")
    @classmethod
    def _symbols_match_pattern(cls, value: list[str]) -> list[str]:
        # Field(pattern=...) cannot apply to list[str] (probed TypeError);
        # per-item check with the task-literal regex instead.
        for symbol in value:
            if SYMBOL_PATTERN.match(symbol) is None:
                raise ValueError(f"Symbol {symbol!r} does not match {SYMBOL_PATTERN.pattern!r}")
        return value


class Period(_StrictModel):
    """Backtest window: ``start < end <= today`` (clock via ``_get_today``).

    The date fields override the class-level ``strict=True`` with
    ``Field(strict=False)`` (probed on 2.13.5): Appendix C fixtures are JSON
    with ISO date strings, which STRICT dates reject. This is parsing of an
    explicitly-formatted date literal, not silent coercion of a wrong scalar
    type (no number/bool ever becomes a date).
    """

    start: Annotated[date, Field(strict=False)]
    end: Annotated[date, Field(strict=False)]

    @model_validator(mode="after")
    def _sane_window(self) -> Period:
        if self.start >= self.end:
            raise ValueError(f"period.start ({self.start}) must be before period.end ({self.end})")
        if self.end > _get_today():
            raise ValueError(f"period.end ({self.end}) is in the future (today is {_get_today()})")
        return self


class Capital(_StrictModel):
    """Starting capital; must be positive (§4.1 ``capital.initial > 0``)."""

    initial: Annotated[float, Field(strict=True, gt=0)]
    currency: str = "USD"


class Assumption(_StrictModel):
    """One disclosed assumption (parser-populated, §4.4): what field was
    defaulted, to what value, and why."""

    field: str
    value: Any
    reason: str


class IndicatorDef(_StrictModel):
    """One indicator usage: ``type`` names a registry indicator (the P3-T2
    validator checks existence/bounds against the registry), ``params`` are
    forwarded, ``source`` is the input OHLCV column."""

    type: str
    params: dict[str, Any] = {}
    source: str = "close"

    @field_validator("type")
    @classmethod
    def _type_is_registry_shaped(cls, value: str) -> str:
        # Shape-level check only; existence + param bounds are the semantic
        # validator's job (P3-T2, against the live registry).
        if INDICATOR_NAME_PATTERN.match(value) is None:
            raise ValueError(
                f"Indicator type {value!r} does not match {INDICATOR_NAME_PATTERN.pattern!r}"
            )
        return value

    @field_validator("source")
    @classmethod
    def _source_is_a_raw_column(cls, value: str) -> str:
        if value not in RAW_COLUMNS:
            raise ValueError(f"source must be one of {sorted(RAW_COLUMNS)}, got {value!r}")
        return value


# ===========================================================================
# StrategySpec (top level)
# ===========================================================================


class StrategySpec(_StrictModel):
    """The complete, validated strategy specification (§4.1).

    Cross-field checks (model_validator mode="after"):
    * spec_version == "1.0", name length, v1 single symbol,
    * indicator-name collisions/reserved words,
    * positive capital/sizing, non-negative execution costs.
    Field-level checks live on the component models (Universe/Period/…);
    they run automatically because StrategySpec embeds them.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    spec_version: Literal["1.0"]
    name: Annotated[str, Field(max_length=120)]
    source_text: str | None = None
    universe: Universe
    period: Period
    indicators: dict[str, IndicatorDef] = {}
    rules: Rules
    risk: Risk = Risk()
    sizing: Sizing
    execution: Execution = Execution()
    capital: Capital
    assumptions: list[Assumption] = []
    unsupported: list[str] = []

    @field_validator("indicators", mode="before")
    @classmethod
    def _indicator_names_are_well_formed(cls, value: Any) -> Any:
        """Name-shape + reserved-word checks on the MAP KEYS.

        Runs before per-value IndicatorDef parsing so a reserved name fails
        with a targeted message even if the definition itself is also bad.
        The regex here mirrors IndicatorOperand's Field(pattern=...) — one
        identifier grammar, enforced on both definition and reference sites.
        """
        if isinstance(value, dict):
            for key in value:
                if not isinstance(key, str) or INDICATOR_NAME_PATTERN.match(key) is None:
                    raise ValueError(
                        f"Indicator name {key!r} does not match {INDICATOR_NAME_PATTERN.pattern!r}"
                    )
                if key in RESERVED_INDICATOR_NAMES:
                    raise ValueError(
                        f"Indicator name {key!r} is reserved (raw columns and rule slots)"
                    )
        return value

    @model_validator(mode="after")
    def _v1_semantics(self) -> StrategySpec:
        if len(self.universe.symbols) != 1:
            raise ValueError(f"v1 supports exactly one symbol, got {len(self.universe.symbols)}")
        if self.capital.initial <= 0:
            raise ValueError("capital.initial must be > 0")
        if self.sizing.value <= 0:
            raise ValueError("sizing.value must be > 0")
        if (
            self.execution.fee_bps < 0
            or self.execution.slippage_bps < 0
            or self.execution.fixed_fee < 0
        ):
            raise ValueError("execution costs (fee_bps, slippage_bps, fixed_fee) must be >= 0")
        if self.unsupported:
            raise ValueError(
                f"unsupported must be empty in strict mode (§4.1); got {self.unsupported!r}"
            )
        return self


# Node needs Condition/AllRule/AnyRule/NotRule fully defined — final rebuild
# (idempotent) so the module is import-order-safe.
StrategySpec.model_rebuild()
