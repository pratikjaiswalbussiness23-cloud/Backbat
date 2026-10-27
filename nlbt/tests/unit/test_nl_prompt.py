"""P6-T2: prompt version hash + prompt-vs-registry (ROADMAP C7/S1, accept items).

Two acceptance criteria from ROADMAP.md:618:
* "a test fails if the prompt's indicator list differs from the registry"
* "a test fails if the prompt version isn't bumped when prompt text changes
  (hash check)"

The hash covers ONLY the literal text in ``nl/prompt.py`` (role, envelope
protocol, must-ask guidance, worked examples). The generated blocks
(indicators, operators, phrases, defaults, spec schema) are rebuilt from the
registry/defaults/models at call time, so they cannot drift by construction —
``test_prompt_indicator_catalog_matches_registry`` pins exactly that.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict
from typing import Any, get_args

from nlbt.indicators.registry import REGISTRY
from nlbt.nl.prompt import (
    MUST_ASK_GUIDANCE,
    PROMPT_TEXT_SHA256_BY_VERSION,
    PROMPT_VERSION,
    STATIC_SECTION_SEPARATOR,
    build_system_prompt,
    static_prompt_text,
)
from nlbt.spec.defaults import MUST_ASK, PHRASE_TABLE
from nlbt.spec.models import RAW_COLUMNS, Op

# Block markers the parser/test can rely on (prompt.py documents them).
BLOCK_RE = re.compile(
    r"<<<NLBT_BLOCK:(?P<name>[a-z_]+)>>>\n(?P<body>.*?)\n<<<END_NLBT_BLOCK>>>",
    re.DOTALL,
)


def _blocks(prompt: str) -> dict[str, str]:
    return {m.group("name"): m.group("body") for m in BLOCK_RE.finditer(prompt)}


def _json_block(prompt: str, name: str) -> Any:
    body = _blocks(prompt).get(name)
    assert body is not None, f"prompt is missing the <<<NLBT_BLOCK:{name}>>> block"
    return json.loads(body)


def test_prompt_version_is_a_nonempty_string() -> None:
    assert isinstance(PROMPT_VERSION, str) and PROMPT_VERSION == "2"


def test_prompt_text_hash_matches_the_recorded_version_hash() -> None:
    """FAILS when static prompt text changes without bumping PROMPT_VERSION,
    and when PROMPT_VERSION is bumped without recording the new hash."""
    recorded = PROMPT_TEXT_SHA256_BY_VERSION[PROMPT_VERSION]  # KeyError if unrecorded
    digest = hashlib.sha256(static_prompt_text().encode("utf-8")).hexdigest()
    assert digest == recorded, (
        "static prompt text changed without a PROMPT_VERSION bump: "
        f"recorded={recorded} actual={digest}"
    )


def test_prompt_indicator_catalog_matches_registry_exactly() -> None:
    """The catalog block IS Registry.json_schema()['indicators'] — same names,
    params, bounds and defaults (closed vocabulary, S1/C7)."""
    prompt = build_system_prompt()
    catalog = _json_block(prompt, "indicators")
    assert catalog == REGISTRY.json_schema()["indicators"]
    assert set(catalog) == set(REGISTRY.list_indicators())


def test_prompt_spec_schema_carries_the_registry_indicator_enum() -> None:
    schema = _json_block(build_system_prompt(), "spec_schema")
    enum = schema["$defs"]["IndicatorDef"]["properties"]["type"]["enum"]
    assert enum == sorted(REGISTRY.list_indicators())
    assert schema["x-nlbt-version"] == "1.0"
    assert "$schema" not in schema  # deterministic prompt: no timestamp/keys that vary
    assert "x-nlbt-generated-at" not in schema


def test_prompt_operators_and_columns_come_from_the_models() -> None:
    prompt = build_system_prompt()
    for op in get_args(Op):
        assert f'"{op}"' in prompt, f"operator {op} missing from the prompt"
    for column in sorted(RAW_COLUMNS):
        assert re.search(rf"\b{column}\b", prompt), f"column {column} missing from the prompt"


def test_prompt_phrase_table_rows_are_all_present() -> None:
    prompt = build_system_prompt()
    for entry in PHRASE_TABLE:
        assert f'"{entry.phrase}"' in prompt, f"phrase {entry.phrase!r} missing from the prompt"


def test_prompt_must_ask_block_lists_every_id_with_guidance() -> None:
    prompt = build_system_prompt()
    assert set(MUST_ASK_GUIDANCE) == set(MUST_ASK)
    for ask_id in MUST_ASK:
        assert f'"{ask_id}"' in prompt, f"must-ask id {ask_id} missing from the prompt"


def test_prompt_defaults_block_is_the_defaults_registry() -> None:
    from nlbt.spec.defaults import DEFAULTS

    prompt = build_system_prompt()
    assert _json_block(prompt, "defaults") == asdict(DEFAULTS)


def test_static_text_is_a_strict_subset_of_the_prompt() -> None:
    """Every hashed literal must actually reach the model."""
    prompt = build_system_prompt()
    for section in static_prompt_text().split(STATIC_SECTION_SEPARATOR):
        assert section, "empty section in static_prompt_text"
        assert section in prompt, "a hashed static section is not in the built prompt"


def test_worked_examples_are_valid_envelopes() -> None:
    """Every ENVELOPE example parses as an envelope; ok-examples with a period
    also carry a semantically valid StrategySpec (no lying examples)."""
    from nlbt.nl.envelope import Envelope
    from nlbt.spec.models import StrategySpec
    from nlbt.spec.validate import validate_spec

    prompt = build_system_prompt()
    examples = {
        name: json.loads(body)
        for name, body in _blocks(prompt).items()
        if name.startswith("example_")
    }
    assert len(examples) == 8, sorted(examples)
    for name, payload in sorted(examples.items()):
        Envelope.model_validate(payload)  # raises on a bad example
        spec_dict = payload.get("spec")
        if spec_dict is None:
            assert payload["status"] != "ok", name
            continue
        if "period" not in spec_dict:
            # relative-date example: nlbt fills period in code (P6-T6)
            assert payload["period_expression"], name
            continue
        spec = StrategySpec.model_validate(spec_dict)
        result = validate_spec(spec)
        assert result.errors == [], (name, result.errors)
