"""The LLM response envelope — P6-T1 wire shape (P6-T3 adopts and extends it).

ROADMAP P6-T3: ``status`` ∈ ``ok | needs_clarification | unsupported |
error``, plus ``spec``, ``questions[]``, ``assumptions[]``, ``unsupported[]``.
``extra="forbid"`` like every other nlbt model (§3): an unknown field from
the model is a validation failure, never a silent pass-through.

:func:`flatten_schema` inlines ``$defs``/``$ref`` for endpoints whose strict
``json_schema`` mode rejects references (provider neutrality). The live probe
(step 2, 2026-10-25) showed NVIDIA NIM ACCEPTS pydantic's raw ``$defs`` shape
— flattening therefore changes nothing today, and
``tests/unit/test_llm_envelope_flatten.py`` proves both shapes accept/reject
the same documents.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from nlbt.errors import NLLlmError

__all__ = [
    "Envelope",
    "EnvelopeAssumption",
    "EnvelopeQuestion",
    "envelope_schema",
    "flatten_schema",
]


class EnvelopeQuestion(BaseModel):
    """A clarification question (§4.8 ``details['questions']`` shape)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    question: str


class EnvelopeAssumption(BaseModel):
    """A disclosed default — §4.1 ``assumptions[]`` item shape, verbatim."""

    model_config = ConfigDict(extra="forbid")

    field: str
    value: Any
    reason: str


class Envelope(BaseModel):
    """Schema-forced LLM response envelope (S2; P6-T3 contract)."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "needs_clarification", "unsupported", "error"]
    spec: dict[str, Any] | None = None
    questions: list[EnvelopeQuestion] = []
    assumptions: list[EnvelopeAssumption] = []
    unsupported: list[str] = []
    #: Raw relative-date phrase ("last 3 years") passed through untouched;
    #: nlbt resolves it in code with an injected clock (S10, P6-T6) — the
    #: model never computes dates. P6-T3: optional, defaults to null.
    period_expression: str | None = None


def envelope_schema() -> dict[str, Any]:
    """The JSON Schema handed to the transport (single source: the model)."""
    return Envelope.model_json_schema()


def flatten_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Return ``schema`` with every local ``#/$defs/...`` reference inlined.

    Guards loudly: an unknown or cyclic reference cannot be flattened, and
    guessing would produce a schema that silently means something else — so it
    raises ``E_NL_LLM`` instead (C4).
    """
    defs = schema.get("$defs", {})

    def resolve(node: Any, seen: tuple[str, ...]) -> Any:
        if isinstance(node, list):
            return [resolve(item, seen) for item in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            target = node["$ref"]
            if not isinstance(target, str) or not target.startswith("#/$defs/"):
                raise NLLlmError(
                    "schema contains a non-local $ref that cannot be flattened",
                    details={"ref": str(target)},
                    hint="Export the schema with only local $defs references.",
                )
            name = target.rsplit("/", 1)[-1]
            if name in seen:
                raise NLLlmError(
                    "schema contains a cyclic $ref that cannot be flattened",
                    details={"ref": target},
                    hint="Break the cycle in the model definition.",
                )
            if name not in defs:
                raise NLLlmError(
                    "schema $ref points at an unknown $defs entry",
                    details={"ref": target},
                    hint="The schema is inconsistent; re-export it from the model.",
                )
            return resolve(defs[name], (*seen, name))
        return {key: resolve(value, seen) for key, value in node.items()}

    root = {key: value for key, value in schema.items() if key != "$defs"}
    flattened: dict[str, Any] = resolve(root, ())
    return flattened
