"""P6-T1 tests: RecordedClient (fixture replay, never silent).

Hit: the stored response is returned with source "recorded".
Miss: a LOUD E_NL_LLM error naming the request hash -- a miss must never fall
back to anything (the hash is printed so the operator can see exactly which
request had no fixture).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from nlbt.errors import NLLlmError
from nlbt.nl import RecordedClient, request_fingerprint

SYSTEM = "You translate English into the nlbt envelope JSON."
USER = "Translate: buy AAPL when RSI(14) is under 30"
SCHEMA = {
    "type": "object",
    "properties": {"status": {"type": "string"}},
    "required": ["status"],
    "additionalProperties": False,
}
STORED_PAYLOAD = {
    "status": "ok",
    "spec": None,
    "questions": [],
    "assumptions": [],
    "unsupported": [],
}


def write_fixture(
    fixture_dir: Path,
    *,
    name: str,
    model: str,
    structured_mode: str = "json_schema",
    temperature: float = 0.0,
    payload: dict[str, Any] = STORED_PAYLOAD,
) -> str:
    """Create a fixture whose request_hash matches a call with these inputs."""
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": USER},
    ]
    digest = request_fingerprint(
        model=model,
        messages=messages,
        schema=SCHEMA,
        temperature=temperature,
        structured_mode=structured_mode,
    )
    fixture_dir.mkdir(parents=True, exist_ok=True)
    (fixture_dir / f"{name}.json").write_text(
        json.dumps(
            {
                "name": name,
                "request_hash": digest,
                "request": {
                    "model": model,
                    "messages": messages,
                    "schema_sha256": "computed-by-helpers-not-asserted-here",
                    "temperature": temperature,
                    "structured_mode": structured_mode,
                },
                "response": payload,
                "recorded_at": "2026-10-25T00:00:00+00:00",
                "host": "integrate.api.nvidia.com",
                "source": "recorded",
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return digest


def test_hit_returns_stored_response_with_source_recorded(tmp_path: Path) -> None:
    write_fixture(tmp_path / "llm", name="envelope_ok", model="test-model")
    client = RecordedClient(fixture_dir=tmp_path / "llm")

    resp = client.complete_structured(SYSTEM, USER, SCHEMA, model="test-model")

    assert resp.source == "recorded"
    assert resp.payload == STORED_PAYLOAD


def test_hit_ignores_other_fixtures(tmp_path: Path) -> None:
    """A fixture recorded for a different model must NOT be served."""
    write_fixture(tmp_path / "llm", name="other_model", model="different-model")
    client = RecordedClient(fixture_dir=tmp_path / "llm")

    with pytest.raises(NLLlmError) as excinfo:
        client.complete_structured(SYSTEM, USER, SCHEMA, model="test-model")

    assert excinfo.value.details["request_hash"] in str(excinfo.value)


def test_miss_raises_loud_error_naming_the_request_hash(tmp_path: Path) -> None:
    client = RecordedClient(fixture_dir=tmp_path / "llm")  # empty dir

    # expected hash, computed INDEPENDENTLY of the client under test:
    expected = request_fingerprint(
        model="test-model",
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": USER},
        ],
        schema=SCHEMA,
        temperature=0.0,
        structured_mode="json_schema",
    )

    with pytest.raises(NLLlmError) as excinfo:
        client.complete_structured(SYSTEM, USER, SCHEMA, model="test-model")

    err = excinfo.value
    assert err.code == "E_NL_LLM"
    assert expected in str(err), "miss error must name the request hash"
    assert err.details["request_hash"] == expected
    assert "no recorded" in err.message.lower() or "recorded" in err.message.lower()


def test_miss_never_returns_a_payload(tmp_path: Path) -> None:
    """Loud, not silent: no fixture match means an exception, never a replay."""
    client = RecordedClient(fixture_dir=tmp_path / "does_not_exist")

    with pytest.raises(NLLlmError):
        client.complete_structured(SYSTEM, USER, SCHEMA, model="test-model")
