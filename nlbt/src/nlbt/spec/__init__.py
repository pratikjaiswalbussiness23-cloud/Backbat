"""StrategySpec schema models (ROADMAP P3-T1) and semantic validator (P3-T2).

Importing this package exposes the validated spec models and
``validate_spec``, the semantic layer that cross-references the indicator
registry (P3-T2). Phase 3 continues with JSON Schema export (P3-T3),
canonicalisation (P3-T4) and the deterministic renderer (P3-T5) on top of
these.
"""

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
from nlbt.spec.validate import (
    SemanticError,
    SemanticValidationResult,
    validate_spec,
)

__all__ = [
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
    "Period",
    "RawColumnOperand",
    "Risk",
    "Rules",
    "SemanticError",
    "SemanticValidationResult",
    "Sizing",
    "SizingMethod",
    "StrategySpec",
    "Universe",
    "rule_depth",
    "validate_spec",
]
