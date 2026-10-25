"""P6-T1: scripts/record_llm_fixture.py refuses to write a file with the key.

The recorder is dev tooling loaded from its file path (scripts/ is not a
package). Two behaviors under test:
1. ``write_fixture`` RAISES and writes NOTHING when the serialized record
   would contain the key (R13 / owner key rules).
2. A clean record is written and round-trips as JSON.

Never makes a network call: only the pure record-building/writing helpers are
exercised here (the live recording path ran once in Phase B step 5 with the
real endpoint, outside CI).
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

_HELPER_PATH = Path(__file__).resolve().parents[2] / "scripts" / "record_llm_fixture.py"

FAKE_KEY = "nvapi-FAKE-RECORDER-KEY-0123456789"


def _load_recorder() -> Any:
    spec = importlib.util.spec_from_file_location("nlbt_record_llm_fixture", _HELPER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def clean_record() -> dict[str, Any]:
    return {
        "name": "unit_clean",
        "request_hash": "a" * 64,
        "request": {
            "model": "test-model",
            "messages": [{"role": "user", "content": "hi"}],
            "schema_sha256": "b" * 64,
            "temperature": 0.0,
            "structured_mode": "json_schema",
        },
        "response": {"status": "ok"},
        "recorded_at": "2026-10-25T00:00:00+00:00",
        "host": "integrate.api.nvidia.com",
        "source": "recorded",
    }


def test_recorder_refuses_record_containing_the_key(tmp_path: Path) -> None:
    recorder = _load_recorder()
    record = clean_record()
    record["response"] = {"status": "ok", "leaked": FAKE_KEY}  # attacker/bot mistake

    target = tmp_path / "dirty.json"
    with pytest.raises(RuntimeError) as excinfo:
        recorder.write_fixture(target, record, key=FAKE_KEY)

    assert not target.exists(), "a refused record must leave NO file behind"
    assert FAKE_KEY not in str(excinfo.value), "the refusal message must not echo the key"


def test_recorder_writes_a_clean_record(tmp_path: Path) -> None:
    recorder = _load_recorder()
    target = tmp_path / "clean.json"

    recorder.write_fixture(target, clean_record(), key=FAKE_KEY)

    assert target.exists()
    loaded = json.loads(target.read_text(encoding="utf-8"))
    assert loaded["name"] == "unit_clean"
    assert FAKE_KEY not in target.read_text(encoding="utf-8")


def test_recorder_checks_even_the_request_side(tmp_path: Path) -> None:
    """Key hidden in a message would still be caught by the byte check."""
    recorder = _load_recorder()
    record = clean_record()
    record["request"]["messages"][0]["content"] = f"my key is {FAKE_KEY}"

    target = tmp_path / "dirty2.json"
    with pytest.raises(RuntimeError):
        recorder.write_fixture(target, record, key=FAKE_KEY)

    assert not target.exists()
