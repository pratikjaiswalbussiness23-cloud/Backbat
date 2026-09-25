"""P2-T8 tests: generated indicator docs are fresh and complete.

The registry is the single source of truth (ROADMAP C7); these tests enforce
it three ways:

1. STALENESS (tests 1-2): the committed docs/indicators.{md,json} are
   regenerated in memory on every PR and compared modulo the timestamp —
   hand-edits or registry changes without a regen fail the suite. The failure
   message tells the developer the exact regeneration command.
2. COMPLETENESS/CONSISTENCY (tests 3-8): the committed catalog covers exactly
   the registry's indicators with the required fields, and warmup_default
   matches an INDEPENDENT recomputation through the registry's warmup_fn
   (no invented values — AGENTS.md R2; the registry is the oracle here).
3. CANARY (test 11): a temporary indicator registered in a FRESH registry
   (global REGISTRY untouched) changes the generated markdown — proving the
   staleness comparison does real work.

Order-independence: the reference artifacts are generated from an IMPORT-TIME
snapshot of the registry specs (BUILTIN_SPECS) — an unrelated test mutates the
global REGISTRY mid-suite (OQ-0032), and run-time reads of the live registry
would make these tests flaky on file order. Snapshot ≠ weakened check: the
artifacts are still generated from the real built-in specs.

These run on every PR (no special marker — task text). docs/indicators.md
and docs/indicators.json are GENERATED artifacts (do not edit by hand).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from nlbt.indicators.generate_docs import (
    generate_catalog_json,
    generate_indicators_markdown,
)
from nlbt.indicators.registry import REGISTRY, IndicatorSpec, ParamSpec, Registry

#: tests/unit/test_indicators_docs.py -> parents[2] = nlbt/ (project root).
PROJECT_ROOT = Path(__file__).resolve().parents[2]
COMMITTED_MD_PATH = PROJECT_ROOT / "docs" / "indicators.md"
COMMITTED_JSON_PATH = PROJECT_ROOT / "docs" / "indicators.json"

#: Snapshot at MODULE-IMPORT time (= collection time, before ANY test runs):
#: the global REGISTRY then holds exactly the built-in indicators.
#: NEEDED because tests/unit/test_indicator_registry.py registers a dummy
#: spec ("dummy_global_path") into the GLOBAL registry mid-suite with no
#: cleanup (pre-existing hygiene flaw, OQ-0032 — that file is outside this
#: task's allowed list). Generating the reference artifacts from the live
#: REGISTRY at RUN time would make every staleness comparison depend on
#: alphabetical test-file order (reproduced: 6 docs failures in the full
#: suite, 12/12 green standalone). The artifacts stay fully GENERATED from
#: real registry specs (C7 intact) — only the view is purified.
BUILTIN_SPECS: dict[str, IndicatorSpec] = {
    name: REGISTRY.get(name) for name in REGISTRY.list_indicators()
}
BUILTIN_NAMES: list[str] = sorted(BUILTIN_SPECS)


def _builtin_registry() -> Registry:
    """A FRESH Registry holding exactly the built-in specs (snapshot above).

    The global REGISTRY is never mutated (the P2-T1 registry contract is
    exercised by its own tests; the canary below adds its temp indicator to
    this fresh instance only).
    """
    reg = Registry()
    for spec in BUILTIN_SPECS.values():
        reg.register(spec)
    return reg


#: Must stay in sync with generate_docs._GENERATED_AT_PREFIX (asserted in
#: test_strip_prefix_matches_generator_constant below — drift fails loudly).
GENERATED_AT_PREFIX = "*Generated at:"

#: Required keys of one catalog indicator entry (task test 4).
REQUIRED_ENTRY_KEYS = {"description", "outputs", "allowed_sources", "warmup_default", "params"}


def _strip_md_timestamp(text: str) -> str:
    """Drop the '*Generated at: ...' line(s) — the only volatile md content."""
    return "\n".join(line for line in text.splitlines() if not line.startswith(GENERATED_AT_PREFIX))


def _md_sections(md: str) -> dict[str, str]:
    """Split the catalog markdown into {indicator_name: section_body}.

    A section starts at the '## {name}' heading and runs to the next
    '## ' heading (or end of document).
    """
    sections: dict[str, str] = {}
    current: str | None = None
    body: list[str] = []
    for line in md.splitlines():
        if line.startswith("## "):
            if current is not None:
                sections[current] = "\n".join(body)
            current = line[len("## ") :].strip()
            body = []
        elif current is not None:
            body.append(line)
    if current is not None:
        sections[current] = "\n".join(body)
    return sections


def _committed_md() -> str:
    return COMMITTED_MD_PATH.read_text(encoding="utf-8")


def _committed_catalog() -> dict[str, Any]:
    raw = json.loads(COMMITTED_JSON_PATH.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)  # narrow Any for mypy-clean tests
    return raw


# ===========================================================================
# Staleness (the CI gate — task tests 1-2)
# ===========================================================================


def test_indicators_md_is_not_stale() -> None:
    """Freshly generated markdown == committed file, ignoring the timestamp line.

    Generated from the import-time registry snapshot (see BUILTIN_SPECS for
    why the live global REGISTRY cannot be used at run time).
    """
    fresh = _strip_md_timestamp(generate_indicators_markdown(_builtin_registry()))
    committed = _strip_md_timestamp(_committed_md())
    assert fresh == committed, (
        "docs/indicators.md is stale. Run:\nuv run python -m nlbt.indicators.generate_docs"
    )


def test_catalog_json_is_not_stale() -> None:
    """Freshly generated catalog == committed file, ignoring generated_at."""
    fresh = generate_catalog_json(_builtin_registry())
    committed = _committed_catalog()
    fresh.pop("generated_at")
    committed.pop("generated_at")
    assert fresh == committed, (
        "docs/indicators.json is stale. Run:\nuv run python -m nlbt.indicators.generate_docs"
    )


def test_strip_prefix_matches_generator_constant() -> None:
    """The strip helper targets exactly the generator's timestamp-line prefix.

    If the generator's header format ever changes, the staleness tests above
    must not silently start comparing timestamps (which would flake) — this
    pins the contract from the other side: the committed file contains exactly
    one such line.
    """
    from nlbt.indicators.generate_docs import _GENERATED_AT_PREFIX

    assert GENERATED_AT_PREFIX == _GENERATED_AT_PREFIX
    committed_lines = _committed_md().splitlines()
    matches = [line for line in committed_lines if line.startswith(GENERATED_AT_PREFIX)]
    assert len(matches) == 1
    assert matches[0].endswith("*")


# ===========================================================================
# Completeness / consistency vs the registry (task tests 3-8)
# ===========================================================================


def test_catalog_contains_all_registry_indicators() -> None:
    """Catalog indicator names == the registry's names (import-time snapshot).

    ``BUILTIN_NAMES`` IS ``REGISTRY.list_indicators()`` captured at module
    import (before any test can mutate the global registry — OQ-0032); at
    collection time the two are identical, which the guard test below pins.
    """
    catalog = _committed_catalog()
    assert sorted(catalog["indicators"]) == BUILTIN_NAMES


def test_registry_still_contains_all_builtins() -> None:
    """Guard for the snapshot contract: every builtin is still registered.

    If the LIVE global registry ever LOSES a builtin (or a builtin spec is
    swapped after import), this fails — the snapshot may only ever be a
    subset-equal view, never a stale copy of changed specs.
    """
    live = set(REGISTRY.list_indicators())
    assert set(BUILTIN_NAMES) <= live
    for name, spec in BUILTIN_SPECS.items():
        assert REGISTRY.get(name) is spec, name


def test_catalog_indicator_has_required_fields() -> None:
    """Every catalog entry carries description/outputs/allowed_sources/
    warmup_default/params; params carry type/default/minimum/maximum/description."""
    catalog = _committed_catalog()
    for name, entry in catalog["indicators"].items():
        assert set(entry) >= REQUIRED_ENTRY_KEYS, (name, sorted(entry))
        for param_name, param in entry["params"].items():
            assert {"type", "default", "minimum", "maximum", "description"} <= set(param), (
                name,
                param_name,
                sorted(param),
            )


def test_markdown_contains_all_indicator_names() -> None:
    """Every registry indicator appears as a '## {name}' heading in the md."""
    sections = _md_sections(_committed_md())
    for name in BUILTIN_NAMES:
        assert f"## {name}" in _committed_md(), name
        assert name in sections, name


def test_markdown_has_parameter_tables() -> None:
    """Every indicator WITH params (all except obv) has a parameter table."""
    sections = _md_sections(_committed_md())
    for name in BUILTIN_NAMES:
        if name == "obv":
            continue  # task: OBV has no params section (see next test)
        assert "| Parameter |" in sections[name], name


def test_obv_has_no_params_section() -> None:
    """OBV takes no params: its section says 'No parameters.', no table."""
    sections = _md_sections(_committed_md())
    obv = sections["obv"]
    assert "No parameters." in obv
    assert "| Parameter |" not in obv


def test_warmup_default_matches_registry() -> None:
    """warmup_default == warmup_fn recomputed from the catalog's own defaults.

    ``BUILTIN_SPECS[name]`` is ``REGISTRY.get(name)`` captured at import
    (same object — pinned by test_registry_still_contains_all_builtins).
    """
    catalog = _committed_catalog()
    for name, entry in catalog["indicators"].items():
        defaults = {k: v["default"] for k, v in entry["params"].items()}
        expected = BUILTIN_SPECS[name].warmup_fn(defaults)
        assert entry["warmup_default"] == expected, name


# ===========================================================================
# Determinism / well-formedness (task tests 9-10)
# ===========================================================================


def test_generate_docs_is_idempotent() -> None:
    """Two generations are identical modulo the timestamp (no randomness).

    Both artifacts: the markdown (timestamp line stripped) and the JSON dict
    (generated_at popped) — ordering is fixed by list_indicators' sort.
    """
    md_1 = _strip_md_timestamp(generate_indicators_markdown(_builtin_registry()))
    md_2 = _strip_md_timestamp(generate_indicators_markdown(_builtin_registry()))
    assert md_1 == md_2

    json_1 = generate_catalog_json(_builtin_registry())
    json_2 = generate_catalog_json(_builtin_registry())
    json_1.pop("generated_at")
    json_2.pop("generated_at")
    assert json_1 == json_2


def test_catalog_json_is_valid_json() -> None:
    """The committed file parses with stdlib json (raw-text round-trip)."""
    raw = COMMITTED_JSON_PATH.read_text(encoding="utf-8")
    parsed = json.loads(raw)  # must not raise
    assert isinstance(parsed, dict)
    assert set(parsed) == {"version", "generated_at", "indicators"}


# ===========================================================================
# CANARY (task test 11): the staleness check must do real work
# ===========================================================================


def test_canary_adding_indicator_breaks_staleness() -> None:
    """A NEWLY REGISTERED indicator changes the generated markdown.

    A FRESH Registry is populated with the built-in specs via the public API
    (Registry.register — the global REGISTRY is never mutated), then one
    temporary indicator is added. The freshly generated markdown must then
    DIFFER from the committed file — and the difference must be exactly the
    new section (precise attribution, not luck).
    """
    fresh = _builtin_registry()

    temp_spec = IndicatorSpec(
        name="zzz_temp_canary",
        outputs=("value",),
        params={
            "period": ParamSpec(
                type="int",
                minimum=2,
                maximum=10,
                default=5,
                description="Temporary canary parameter (never computed).",
            )
        },
        allowed_sources=("close",),
        warmup_fn=lambda params: int(params["period"]) - 1,
        # Never called by json_schema()/markdown rendering; a valid kernel
        # shape regardless (compute_fn contract: DataFrame, index=bars.index).
        compute_fn=lambda bars, params, source: pd.DataFrame(
            {"value": [0.0] * len(bars)}, index=bars.index
        ),
        description="Temporary canary indicator for the P2-T8 staleness test.",
    )
    fresh.register(temp_spec)

    committed = _strip_md_timestamp(_committed_md())
    fresh_md = _strip_md_timestamp(generate_indicators_markdown(fresh))

    assert fresh_md != committed, (
        "Canary failed: adding an indicator did NOT change the generated "
        "markdown - the staleness check would never fire."
    )
    # Precise attribution: the temp section exists only in the fresh output.
    assert "## zzz_temp_canary" in fresh_md
    assert "## zzz_temp_canary" not in committed
    # Hygiene: the global registry is untouched by this test.
    assert "zzz_temp_canary" not in REGISTRY.list_indicators()
    assert set(BUILTIN_NAMES) <= set(REGISTRY.list_indicators())
