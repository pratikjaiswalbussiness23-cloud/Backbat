"""P6-T1: schema flattening equivalence (owner test list item).

The flattened envelope schema must accept exactly the same documents and
reject exactly the same documents as the original pydantic schema. Both are
checked with the INDEPENDENT ``jsonschema`` validator (a direct dev dependency
declared in pyproject.toml -- permitted by the ruling) so the oracle is not
pydantic judging its own output.

Live-probe context (step 2, 2026-10-25): the endpoint ACCEPTED pydantic's raw
``$defs``/``$ref`` shape (200), so flattening is not required for NVIDIA NIM
today -- it stays in the client for provider neutrality, and this test pins
that it changes nothing semantically.
"""

from __future__ import annotations

from typing import Any

import jsonschema
import pytest

from nlbt.nl import envelope_schema, flatten_schema

# Hand-built samples, each with the expected verdict under BOTH schemas.
SAMPLES: list[tuple[dict[str, Any], bool, str]] = [
    ({"status": "ok"}, True, "minimal valid envelope"),
    (
        {
            "status": "needs_clarification",
            "spec": None,
            "questions": [{"id": "q1", "question": "Which symbol?"}],
            "assumptions": [],
            "unsupported": [],
        },
        True,
        "full valid envelope",
    ),
    ({"status": "banana"}, False, "status outside the envelope enum"),
    ({"status": "ok", "surprise": 1}, False, "extra field: extra=forbid"),
    ({"spec": {}}, False, "required status missing"),
    ({"status": "ok", "assumptions": [{"oops": 1}]}, False, "assumption item shape"),
    ([{"status": "ok"}], False, "top level must be an object"),
]


@pytest.mark.parametrize(("sample", "expected_valid", "why"), SAMPLES)
def test_original_pydantic_schema_verdict(sample: Any, expected_valid: bool, why: str) -> None:
    validator = jsonschema.Draft202012Validator(envelope_schema())
    errors = sorted(validator.iter_errors(sample), key=lambda e: list(e.path))
    assert (not errors) is expected_valid, f"{why}: unexpected verdict on the RAW schema"


@pytest.mark.parametrize(("sample", "expected_valid", "why"), SAMPLES)
def test_flattened_schema_gives_the_same_verdict(
    sample: Any, expected_valid: bool, why: str
) -> None:
    flat = flatten_schema(envelope_schema())
    assert "$defs" not in flat, "flattening must inline every $defs entry"
    validator = jsonschema.Draft202012Validator(flat)
    errors = sorted(validator.iter_errors(sample), key=lambda e: list(e.path))
    assert (not errors) is expected_valid, f"{why}: flattened verdict diverged"


def test_flattened_is_semantically_identical_on_the_whole_sample_set() -> None:
    """One assertion over everything: the two verdict vectors must be identical."""
    raw_validator = jsonschema.Draft202012Validator(envelope_schema())
    flat_validator = jsonschema.Draft202012Validator(flatten_schema(envelope_schema()))
    raw_verdicts = [not list(raw_validator.iter_errors(s)) for s, _, _ in SAMPLES]
    flat_verdicts = [not list(flat_validator.iter_errors(s)) for s, _, _ in SAMPLES]
    assert raw_verdicts == flat_verdicts
    assert raw_verdicts == [ok for _, ok, _ in SAMPLES]
