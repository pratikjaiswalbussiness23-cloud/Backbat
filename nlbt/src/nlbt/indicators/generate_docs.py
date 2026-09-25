"""Generate the indicator catalog docs from the registry (ROADMAP P2-T8, C7).

C7: "The indicator registry generates the schema, the LLM prompt, the docs
and the validator, so they can never drift apart." This module is the docs
leg of that promise: `docs/indicators.md` (human) and `docs/indicators.json`
(machine-readable, the Phase 6 LLM-prompt fragment) are RENDERED from
`Registry.json_schema()` (P2-T1) - never hand-written. Two staleness tests
(tests/unit/test_indicators_docs.py) regenerate both in memory on every PR
and fail if the committed files drifted.

Structure (task-mandated):

* `generate_indicators_markdown(registry)` - the markdown document; indicators
  in ALPHABETICAL order (Registry.list_indicators is already sorted), each
  with outputs / allowed sources / warmup-at-default-params / parameter table
  ("No parameters." when the indicator takes none, e.g. obv).
* `generate_catalog_json(registry)` - {"version": "1.0", "generated_at",
  "indicators": {name: {description, outputs, allowed_sources,
  warmup_default, params}}} - a dict, written as pretty-printed JSON.
* `write_indicators_md` / `write_catalog_json` - thin writers (REGISTRY when
  `registry=None`); the JSON writer returns the dict it wrote.
* `__main__` - writes both to their standard locations and prints
  "Generated: <path>" per file.

Both functions embed a generation timestamp (the "*Generated at: ..." line /
the "generated_at" field). The staleness tests strip exactly that line/field
before comparing - everything else must match byte-for-byte.

Default output paths are anchored to the PROJECT ROOT derived from
__file__ (nlbt/src/nlbt/indicators/generate_docs.py -> parents[3] = nlbt/),
NOT to the CWD - `python -m nlbt.indicators.generate_docs` therefore writes
nlbt/docs/ from any working directory (OQ-0030). The Makefile runs it from
nlbt/, where both anchoring choices coincide.

Verified APIs (docs/verified_apis.md, 2026-09-25): stdlib json.dumps
(indent=2, ensure_ascii=False - non-ASCII descriptions round-trip),
datetime.now(timezone.utc).isoformat(), Path.write_text; and the P2-T1
Registry.json_schema() shape (indicators.{name}.{description, outputs,
allowed_sources, params, warmup} with warmup evaluated at DEFAULT params).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nlbt.indicators.registry import REGISTRY, Registry

__all__ = [
    "generate_catalog_json",
    "generate_indicators_markdown",
    "write_catalog_json",
    "write_indicators_md",
]

#: Project root = the directory containing src/ and docs/
#: (nlbt/src/nlbt/indicators/generate_docs.py -> parents[3] = nlbt/).
_PROJECT_ROOT = Path(__file__).resolve().parents[3]

#: Standard output locations (task text; OQ-0030 for the anchoring choice).
DEFAULT_MD_PATH = _PROJECT_ROOT / "docs" / "indicators.md"
DEFAULT_JSON_PATH = _PROJECT_ROOT / "docs" / "indicators.json"

#: Prefix of the markdown timestamp line; the staleness tests strip every
#: line starting with this prefix before comparing.
_GENERATED_AT_PREFIX = "*Generated at:"

#: Catalog schema version (task text mandates the literal "1.0").
CATALOG_VERSION = "1.0"


def _utc_now_iso() -> str:
    """UTC ISO-8601 timestamp (timezone-aware, e.g. 2026-09-25T09:03:03+00:00)."""
    return datetime.now(tz=UTC).isoformat()


def _md_cell(text: str) -> str:
    """Escape a string for a markdown table cell (a raw | would split it)."""
    return str(text).replace("|", "\\|")


def _render_param_table(params: dict[str, dict[str, Any]]) -> str:
    """Render the parameter table, or "No parameters." when params == {}.

    Format per the task's example: the header row is the FIXED literal
    ``| Parameter | Type | Default | Min | Max | Description |`` (unpadded -
    the staleness test greps exactly that substring), while data cells and
    the dash separator are padded to the per-column maximum (header included),
    so the table is aligned wherever data fits the header (all current
    indicators except stoch, whose ``smooth_period`` exceeds "Parameter").
    A missing bound renders as "-" (no current indicator has one, but
    ParamSpec.minimum/maximum are Optional - deterministic either way).
    Bounds render VERBATIM from the ParamSpec dumps - they are floats
    (``2.0``), not the task example's ``2``; reformatting would misstate
    what the validator enforces (OQ-0031).
    """
    if not params:
        return "No parameters."

    header = ["Parameter", "Type", "Default", "Min", "Max", "Description"]
    rows: list[list[str]] = []
    for name, spec in params.items():
        rows.append(
            [
                _md_cell(name),
                _md_cell(spec["type"]),
                _md_cell(spec["default"]),
                _md_cell("-" if spec["minimum"] is None else spec["minimum"]),
                _md_cell("-" if spec["maximum"] is None else spec["maximum"]),
                _md_cell(spec["description"]),
            ]
        )

    widths = [max(len(header[i]), *(len(row[i]) for row in rows)) for i in range(len(header))]

    def _fmt_row(cells: list[str]) -> str:
        padded = (cell.ljust(widths[i]) for i, cell in enumerate(cells))
        return "| " + " | ".join(padded) + " |"

    separator = "|" + "|".join("-" * (w + 2) for w in widths) + "|"
    # Header row FIXED (unpadded) per the task's example format; data rows
    # and separator padded to the column maxima.
    header_row = "| " + " | ".join(header) + " |"
    lines = [header_row, separator, *(_fmt_row(row) for row in rows)]
    return "\n".join(lines)


def generate_indicators_markdown(registry: Registry) -> str:
    """Render the full indicator catalog as a markdown document.

    Everything is read from ``registry.json_schema()`` (single source of
    truth per C7): outputs, allowed sources, param bounds and the warmup
    evaluated at each indicator's DEFAULT params. Indicators appear in
    alphabetical order (``list_indicators`` contract).
    """
    schema = registry.json_schema()
    lines: list[str] = [
        "# nlbt Indicator Catalog",
        "",
        "*Generated from the indicator registry.",
        "Do not edit manually \u2014 run `make generate-docs`.*",
        "",
        f"{_GENERATED_AT_PREFIX} {_utc_now_iso()}*",
        "",
    ]
    for name in sorted(schema["indicators"]):
        entry = schema["indicators"][name]
        lines += [
            f"## {name}",
            "",
            entry["description"],
            "",
            f"**Outputs:** {', '.join(entry['outputs'])}",
            "",
            f"**Allowed sources:** {', '.join(entry['allowed_sources'])}",
            "",
            f"**Warmup:** {entry['warmup']} bars",
            "",
            "**Parameters:**",
            "",
            _render_param_table(entry["params"]),
            "",
            "---",
            "",
        ]
    return "\n".join(lines)


def generate_catalog_json(registry: Registry) -> dict[str, Any]:
    """Render the machine-readable catalog dict (Phase 6 LLM-prompt fragment).

    Same source as the markdown (``json_schema()``) with the registry's
    ``warmup`` field renamed to the task-mandated ``warmup_default``; the
    per-param dicts are the ParamSpec dumps (type/default/minimum/maximum/
    description). ``generated_at`` is the only volatile field.
    """
    schema = registry.json_schema()
    indicators: dict[str, dict[str, Any]] = {}
    for name in sorted(schema["indicators"]):
        entry = schema["indicators"][name]
        indicators[name] = {
            "description": entry["description"],
            "outputs": list(entry["outputs"]),
            "allowed_sources": list(entry["allowed_sources"]),
            "warmup_default": entry["warmup"],
            "params": entry["params"],
        }
    return {
        "version": CATALOG_VERSION,
        "generated_at": _utc_now_iso(),
        "indicators": indicators,
    }


def write_indicators_md(output_path: Path, registry: Registry | None = None) -> None:
    """Write the markdown catalog to ``output_path`` (REGISTRY if None)."""
    text = generate_indicators_markdown(REGISTRY if registry is None else registry)
    output_path.write_text(text, encoding="utf-8")


def write_catalog_json(output_path: Path, registry: Registry | None = None) -> dict[str, Any]:
    """Write the JSON catalog to ``output_path`` (REGISTRY if None); return it."""
    catalog = generate_catalog_json(REGISTRY if registry is None else registry)
    output_path.write_text(
        json.dumps(catalog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return catalog


if __name__ == "__main__":
    write_indicators_md(DEFAULT_MD_PATH)
    print(f"Generated: {DEFAULT_MD_PATH}")
    write_catalog_json(DEFAULT_JSON_PATH)
    print(f"Generated: {DEFAULT_JSON_PATH}")
