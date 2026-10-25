"""RecordedClient — P6-T1: replay stored responses keyed by request hash.

A miss is LOUD: ``E_NL_LLM`` naming the exact request hash. There is no
silent fallback path anywhere in this class (R7/C4): an unmatched request can
never return somebody else's recording and can never quietly go live.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from nlbt.config import get_config
from nlbt.errors import NLLlmError
from nlbt.nl.client import LLMResponse, request_fingerprint

__all__ = ["RecordedClient"]


class RecordedClient:
    """Replays fixtures from ``tests/fixtures/llm/`` (unit-test transport)."""

    def __init__(self, *, fixture_dir: Path, structured_mode: str = "json_schema") -> None:
        self._fixture_dir = fixture_dir
        self._structured_mode = structured_mode

    @property
    def fixture_dir(self) -> Path:
        return self._fixture_dir

    def complete_structured(
        self,
        system: str,
        user: str,
        schema: dict[str, Any],
        *,
        temperature: float = 0.0,
        model: str | None = None,
    ) -> LLMResponse:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        model_id = model if model is not None else get_config().llm_model
        digest = request_fingerprint(
            model=model_id,
            messages=messages,
            schema=schema,
            temperature=temperature,
            structured_mode=self._structured_mode,
        )

        if self._fixture_dir.is_dir():
            for path in sorted(self._fixture_dir.glob("*.json")):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except OSError, json.JSONDecodeError:
                    continue  # unreadable file: not a match, never a crash
                if not isinstance(data, dict):
                    continue
                if data.get("request_hash") == digest:
                    payload = data.get("response")
                    if not isinstance(payload, dict):
                        raise NLLlmError(
                            f"Recorded fixture {path.name} has no object 'response'",
                            details={"fixture": path.name, "request_hash": digest},
                            hint="Re-record the fixture with scripts/record_llm_fixture.py.",
                        )
                    return LLMResponse(payload=payload, source="recorded")

        raise NLLlmError(
            f"No recorded response for request hash {digest}",
            details={"request_hash": digest, "fixture_dir": str(self._fixture_dir)},
            hint="Record this request with scripts/record_llm_fixture.py (dev-only).",
        )
