"""JSON Schema export for StrategySpec (ROADMAP P3-T3, C7, S1).

Generates ``docs/spec_schema.json`` FROM the pydantic models plus the
indicator registry, so schema, docs, validator and the future LLM prompt
can never drift apart (C7). The registry's indicator names become a CLOSED
VOCABULARY ``enum`` inside the schema (S1): a JSON-Schema validator, not
pydantic, rejects hallucinated indicator types before anything else runs.

What the exported schema validates is the WIRE FORMAT -- the fully TAGGED
document (P6's emission target, task choice A): every operand and rule
node carries its ``kind`` tag, operands spell ``output`` explicitly, and
the §4.2 shorthand (bare strings/numbers, ``{"all": [...]}``) is NOT
accepted here. The pydantic models accept both spellings (OQ-0033
lifting); the schema deliberately pins the canonical tagged form only --
the shorthand is an INPUT convenience for Appendix C fixtures, not an
emission contract.

Independent validation (ROADMAP acceptance: "using an independent
JSON-Schema validator (not pydantic)") is provided by
:func:`validate_with_jsonschema` on the ``jsonschema`` library
(dev-only dependency, DEPENDENCIES.md; probed behaviour in
verified_apis.md).

Freshness contract: ``x-nlbt-generated-at`` changes every run, so the
staleness test compares documents with that ONE key stripped (P2-T8
precedent). CI fails if the committed file drifts from a fresh
generation -- hand-edits or model/registry changes without a regen.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nlbt.indicators.registry import REGISTRY, Registry
from nlbt.spec.models import StrategySpec

__all__ = [
    "GENERATED_AT_KEY",
    "VERSION_KEY",
    "generate_spec_schema",
    "validate_with_jsonschema",
    "write_spec_schema",
]

#: Extension keys added to the exported schema (kept in ONE place so the
#: staleness test strips exactly the volatile one).
VERSION_KEY = "x-nlbt-version"
GENERATED_AT_KEY = "x-nlbt-generated-at"

#: Draft of the exported document. Probed: pydantic 2.13.5 emits ``$defs`` +
#: ``$ref``/``const`` (2020-12 style) and jsonschema 4.26 enforces them
#: natively under Draft202012Validator (verified_apis.md).
SCHEMA_DRAFT = "https://json-schema.org/draft/2020-12/schema"

#: docs/spec_schema.json anchor, independent of the CWD (OQ-0030 precedent
#: from P2-T8): derived from this file's location, nlbt/ = parents[3].
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "docs" / "spec_schema.json"


def _utc_now_iso() -> str:
    """Timezone-aware UTC timestamp (probed P2-T8: datetime.now(tz=UTC).isoformat())."""
    return datetime.now(tz=UTC).isoformat()


def generate_spec_schema(registry: Registry | None = None) -> dict[str, Any]:
    """Generate the full JSON Schema document for StrategySpec.

    Steps (task mandate):

    a. ``StrategySpec.model_json_schema()`` -- the base pydantic schema;
    b. inject the registry's indicator names as an ``enum`` into
       ``#/$defs/IndicatorDef/properties/type`` (probed: pydantic emits a
       plain ``{"type": "string"}`` there) -- the schema then REJECTS
       unknown indicator types at the JSON-Schema level (S1 closed
       vocabulary);
    c. add ``x-nlbt-version`` ("1.0") and ``x-nlbt-generated-at`` (UTC
       ISO timestamp) plus a ``$schema`` draft declaration;
    d. return the complete schema dict.

    The returned dict is freshly built every call (pydantic builds a new
    schema per call) -- mutating it has no effect on the models.
    """
    if registry is None:
        registry = REGISTRY

    schema: dict[str, Any] = StrategySpec.model_json_schema()

    indicator_def = schema.get("$defs", {}).get("IndicatorDef")
    if indicator_def is None:  # pragma: no cover - would mean models changed shape
        raise RuntimeError("StrategySpec schema has no $defs.IndicatorDef; cannot inject enum")
    indicator_def["properties"]["type"] = {
        "enum": sorted(registry.list_indicators()),
        "title": "Type",
        "type": "string",
    }

    schema["$schema"] = SCHEMA_DRAFT
    schema[VERSION_KEY] = "1.0"
    schema[GENERATED_AT_KEY] = _utc_now_iso()
    return schema


def write_spec_schema(
    output_path: str | Path = DEFAULT_OUTPUT_PATH,
    registry: Registry | None = None,
) -> dict[str, Any]:
    """Generate the schema and write it as ``indent=2`` JSON.

    Returns the generated dict (the ON-DISK document is byte-identical to
    ``json.dumps(result, indent=2)`` modulo the timestamp, which the
    staleness test strips). UTF-8 explicitly: descriptions contain
    non-ASCII characters (arrows, dashes) that must survive round-trips.
    """
    schema = generate_spec_schema(registry)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(schema, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return schema


def validate_with_jsonschema(instance: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    """Validate ``instance`` against ``schema`` with the INDEPENDENT
    jsonschema library (never pydantic) and return error messages.

    Empty list = valid. Uses Draft202012Validator (probed: native ``$defs``/
    ``const``/``oneOf`` support) with a FormatChecker so the emitted
    ``format: "date"`` constraints are enforced, not annotation-only.
    Imported lazily so the src/ layer keeps working without the dev-only
    dependency installed.
    """
    from jsonschema import Draft202012Validator, FormatChecker

    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    return [error.message for error in validator.iter_errors(instance)]


def main() -> None:
    """CLI entry: regenerate docs/spec_schema.json from the live models."""
    schema = write_spec_schema()
    print(f"Generated: {DEFAULT_OUTPUT_PATH}")
    enum = schema["$defs"]["IndicatorDef"]["properties"]["type"]["enum"]
    print(f"Indicators in enum: {len(enum)}")


if __name__ == "__main__":
    main()
