"""StrategySpec schema models (P3-T1), semantic validator (P3-T2), JSON
Schema export (P3-T3), canonicalisation/hashing (P3-T4), the
deterministic English renderer (P3-T5) and the defaults registry +
phrase table (P3-T6).

Importing this package exposes the validated spec models, ``validate_spec``
(the semantic layer that cross-references the indicator registry), the
schema generation/validation helpers, the canonical-form/hash functions
used by the §4.6 run manifest, ``render_spec`` (the user's
confirmation gate) and the §4.4 defaults registry (``DEFAULTS``,
``MUST_ASK``, ``PHRASE_TABLE``) -- the single source of truth for every
defaultable value.
"""

from typing import Any

from nlbt.spec.canonical import (
    canonical_json,
    canonical_logic_dict,
    canonical_logic_json,
    canonicalise,
    normalise_number,
    spec_hash_full,
    spec_hash_logic,
)
from nlbt.spec.defaults import (
    DEFAULTS,
    MUST_ASK,
    PHRASE_TABLE,
    NlbtDefaults,
    PhraseEntry,
    get_phrase,
    resolve_date_range,
)
from nlbt.spec.models import (
    AllRule,
    AnyRule,
    Assumption,
    Capital,
    Condition,
    Execution,
    IndicatorDef,
    IndicatorOperand,
    Node,
    NotRule,
    NumberOperand,
    Op,
    Operand,
    Period,
    RawColumnOperand,
    Risk,
    Rules,
    Sizing,
    SizingMethod,
    StrategySpec,
    Universe,
    rule_depth,
)
from nlbt.spec.render import render_rule, render_spec
from nlbt.spec.validate import (
    SemanticError,
    SemanticValidationResult,
    validate_spec,
)

# P3-T3 schema helpers are resolved LAZILY (PEP 562) so that
# ``python -m nlbt.spec.schema`` does not import nlbt.spec.schema from
# THIS package first -- runpy would otherwise emit a benign but noisy
# RuntimeWarning ("found in sys.modules after import of package").
_LAZY_SCHEMA_EXPORTS = {
    "GENERATED_AT_KEY": "GENERATED_AT_KEY",
    "VERSION_KEY": "VERSION_KEY",
    "generate_spec_schema": "generate_spec_schema",
    "validate_with_jsonschema": "validate_with_jsonschema",
    "write_spec_schema": "write_spec_schema",
}


def __getattr__(name: str) -> Any:
    if name in _LAZY_SCHEMA_EXPORTS:
        from nlbt.spec import schema as _schema_module

        return getattr(_schema_module, _LAZY_SCHEMA_EXPORTS[name])
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "DEFAULTS",
    "GENERATED_AT_KEY",
    "MUST_ASK",
    "PHRASE_TABLE",
    "VERSION_KEY",
    "AllRule",
    "AnyRule",
    "Assumption",
    "Capital",
    "Condition",
    "Execution",
    "IndicatorDef",
    "IndicatorOperand",
    "NlbtDefaults",
    "Node",
    "NotRule",
    "NumberOperand",
    "Op",
    "Operand",
    "Period",
    "PhraseEntry",
    "RawColumnOperand",
    "Risk",
    "Rules",
    "SemanticError",
    "SemanticValidationResult",
    "Sizing",
    "SizingMethod",
    "StrategySpec",
    "Universe",
    "canonical_json",
    "canonical_logic_dict",
    "canonical_logic_json",
    "canonicalise",
    "generate_spec_schema",
    "get_phrase",
    "normalise_number",
    "render_rule",
    "render_spec",
    "resolve_date_range",
    "rule_depth",
    "spec_hash_full",
    "spec_hash_logic",
    "validate_spec",
    "validate_with_jsonschema",
    "write_spec_schema",
]
