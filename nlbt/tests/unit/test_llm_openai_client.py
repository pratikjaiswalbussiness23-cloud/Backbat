"""P6-T1 tests: OpenAICompatibleClient on a STUBBED transport (no network).

Every test in this file drives the client through a scripted fake session:
outcomes (responses or exceptions) are consumed one per HTTP attempt, and an
injected ``sleep`` records the delay sequence instead of waiting. R6: only the
network boundary is stubbed -- retry/backoff/parsing/validation logic is the
real production code.

Hand-derived expectations (no copied outputs):
- retry schedule for plain 429s: attempt 1 fails -> sleep 1.0, attempt 2 fails
  -> sleep 2.0, attempt 3 fails -> sleep 4.0, attempt 4 fails -> E_NL_LLM, so
  sleeps == [1.0, 2.0, 4.0] and details["attempts"] == 4 (3 retries after the
  initial request).
- ``Retry-After: 7`` replaces the scheduled delay for that one wait only.
- 400/422 are terminal (no retry): exactly ONE session call.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
import requests

from nlbt.config import Config
from nlbt.errors import NLLlmError
from nlbt.nl import OpenAICompatibleClient

FAKE_KEY = "nvapi-FAKE-UNIT-KEY-0123456789"
SYSTEM = "You translate English into the nlbt envelope JSON."
USER = "Translate: buy AAPL when RSI(14) is under 30"
VALID_PAYLOAD = {
    "status": "ok",
    "spec": None,
    "questions": [],
    "assumptions": [],
    "unsupported": [],
}
MINI_SCHEMA = {
    "type": "object",
    "properties": {"status": {"type": "string"}},
    "required": ["status"],
    "additionalProperties": False,
}


def make_config(**overrides: Any) -> Config:
    base: dict[str, Any] = {
        "nvidia_api_key": FAKE_KEY,
        "llm_model": "test-model",
        "llm_base_url": "https://unit.test/v1",
        "offline": False,
    }
    base.update(overrides)
    return Config(**base)


class StubResponse:
    def __init__(
        self,
        status_code: int,
        payload: Any = None,
        *,
        text: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = (
            text if text is not None else (json.dumps(payload) if payload is not None else "")
        )
        self.headers = headers or {}

    def json(self) -> Any:
        if self._payload is None:
            raise ValueError("stub body is not JSON")
        return self._payload


def chat(content: str | None) -> StubResponse:
    return StubResponse(200, {"choices": [{"message": {"content": content}}]})


class StubSession:
    """Scripted transport: pops one outcome per attempt and records calls."""

    def __init__(self, outcomes: list[Any]) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []

    def post(self, url: str, *, headers: Any = None, json: Any = None, timeout: Any = None) -> Any:
        self.calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        if not self.outcomes:
            raise AssertionError(f"stub session exhausted after {len(self.calls)} call(s)")
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def make_client(
    session: StubSession,
    sleeps: list[float],
    config: Config | None = None,
    **kwargs: Any,
) -> OpenAICompatibleClient:
    return OpenAICompatibleClient(
        config=config or make_config(),
        session=session,
        sleep=sleeps.append,
        **kwargs,
    )


# --------------------------------------------------------------------- success


def test_success_returns_live_response_and_builds_json_schema_body() -> None:
    session = StubSession([chat(json.dumps(VALID_PAYLOAD))])
    sleeps: list[float] = []
    client = make_client(session, sleeps)

    resp = client.complete_structured(SYSTEM, USER, MINI_SCHEMA)

    assert resp.source == "live"
    assert resp.payload == VALID_PAYLOAD
    assert sleeps == []
    call = session.calls[0]
    assert call["url"] == "https://unit.test/v1/chat/completions"
    assert call["headers"]["Authorization"].startswith("Bearer ")
    body = call["json"]
    assert body["model"] == "test-model"
    assert body["messages"] == [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": USER},
    ]
    assert body["temperature"] == 0.0
    fmt = body["response_format"]
    assert fmt["type"] == "json_schema"
    assert fmt["json_schema"]["schema"] == MINI_SCHEMA
    assert fmt["json_schema"]["strict"] is True


def test_nvext_mode_sends_guided_json_instead_of_response_format() -> None:
    session = StubSession([chat(json.dumps(VALID_PAYLOAD))])
    client = make_client(session, [], structured_mode="nvext_guided_json")

    resp = client.complete_structured(SYSTEM, USER, MINI_SCHEMA)

    assert resp.source == "live"
    body = session.calls[0]["json"]
    assert "response_format" not in body
    assert body["nvext"] == {"guided_json": MINI_SCHEMA}


# --------------------------------------------------------------------- 429 flow


def test_429_then_success_sleeps_exact_schedule() -> None:
    session = StubSession(
        [
            StubResponse(429, {"error": "rate limited"}),
            StubResponse(429, {"error": "rate limited"}),
            StubResponse(429, {"error": "rate limited"}),
            chat(json.dumps(VALID_PAYLOAD)),
        ]
    )
    sleeps: list[float] = []
    client = make_client(session, sleeps)

    resp = client.complete_structured(SYSTEM, USER, MINI_SCHEMA)

    assert resp.source == "live"
    assert sleeps == [1.0, 2.0, 4.0], "hand-derived backoff schedule drifted"
    assert len(session.calls) == 4


def test_retry_after_header_replaces_scheduled_delay() -> None:
    session = StubSession(
        [
            StubResponse(429, {"error": "rate limited"}, headers={"Retry-After": "7"}),
            chat(json.dumps(VALID_PAYLOAD)),
        ]
    )
    sleeps: list[float] = []
    client = make_client(session, sleeps)

    client.complete_structured(SYSTEM, USER, MINI_SCHEMA)

    assert sleeps == [7.0], "Retry-After must be honoured verbatim (seconds)"


def test_unparsable_retry_after_falls_back_to_schedule() -> None:
    session = StubSession(
        [
            StubResponse(429, {"error": "rate limited"}, headers={"Retry-After": "soon-ish"}),
            chat(json.dumps(VALID_PAYLOAD)),
        ]
    )
    sleeps: list[float] = []
    client = make_client(session, sleeps)

    client.complete_structured(SYSTEM, USER, MINI_SCHEMA)

    assert sleeps == [1.0], "non-numeric Retry-After falls back to the schedule"


def test_429_exhausted_raises_enl_llm_with_exact_details_and_no_key() -> None:
    session = StubSession([StubResponse(429, {"error": "rate limited"})] * 4)
    sleeps: list[float] = []
    client = make_client(session, sleeps)

    with pytest.raises(NLLlmError) as excinfo:
        client.complete_structured(SYSTEM, USER, MINI_SCHEMA)

    err = excinfo.value
    assert err.code == "E_NL_LLM"
    assert err.details == {"status": 429, "attempts": 4, "retry_after": None}
    assert sleeps == [1.0, 2.0, 4.0]
    assert FAKE_KEY not in str(err)
    assert FAKE_KEY not in repr(err)
    assert FAKE_KEY not in json.dumps(err.details)


def test_429_exhausted_records_last_retry_after_value() -> None:
    session = StubSession(
        [StubResponse(429, {"error": "rate limited"}, headers={"Retry-After": "3"})] * 4
    )
    sleeps: list[float] = []
    client = make_client(session, sleeps)

    with pytest.raises(NLLlmError) as excinfo:
        client.complete_structured(SYSTEM, USER, MINI_SCHEMA)

    assert excinfo.value.details == {"status": 429, "attempts": 4, "retry_after": 3.0}
    assert sleeps == [3.0, 3.0, 3.0]


# ------------------------------------------------------ transport-level errors


def test_timeouts_are_retried_then_enl_llm() -> None:
    session = StubSession([requests.Timeout("unit timeout") for _ in range(4)])
    sleeps: list[float] = []
    client = make_client(session, sleeps)

    with pytest.raises(NLLlmError) as excinfo:
        client.complete_structured(SYSTEM, USER, MINI_SCHEMA)

    err = excinfo.value
    assert err.code == "E_NL_LLM"
    assert err.details["status"] is None
    assert err.details["attempts"] == 4
    assert sleeps == [1.0, 2.0, 4.0]
    assert FAKE_KEY not in str(err)


def test_connection_errors_are_retried_then_enl_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NLBT_LLM_DEMO", raising=False)
    session = StubSession([requests.ConnectionError("refused") for _ in range(4)])
    sleeps: list[float] = []
    client = make_client(session, sleeps)

    with pytest.raises(NLLlmError) as excinfo:
        client.complete_structured(SYSTEM, USER, MINI_SCHEMA)

    assert excinfo.value.details == {"status": None, "attempts": 4, "retry_after": None}
    assert sleeps == [1.0, 2.0, 4.0]
    assert len(session.calls) == 4


# ------------------------------------------------------- terminal HTTP failures


@pytest.mark.parametrize("status", [400, 422])
def test_client_errors_are_terminal_enl_llm(status: int) -> None:
    session = StubSession([StubResponse(status, {"error": "bad request"})])
    sleeps: list[float] = []
    client = make_client(session, sleeps)

    with pytest.raises(NLLlmError) as excinfo:
        client.complete_structured(SYSTEM, USER, MINI_SCHEMA)

    assert excinfo.value.details == {"status": status, "attempts": 1, "retry_after": None}
    assert sleeps == [], "400/422 must not be retried"
    assert len(session.calls) == 1
    assert FAKE_KEY not in str(excinfo.value)


# ----------------------------------------------------- unparseable / invalid


def test_non_json_content_is_enl_llm() -> None:
    session = StubSession([chat("this is not JSON {")])
    client = make_client(session, [])

    with pytest.raises(NLLlmError) as excinfo:
        client.complete_structured(SYSTEM, USER, MINI_SCHEMA)

    assert excinfo.value.code == "E_NL_LLM"
    assert FAKE_KEY not in str(excinfo.value)


def test_null_content_is_enl_llm() -> None:
    session = StubSession([chat(None)])
    client = make_client(session, [])

    with pytest.raises(NLLlmError):
        client.complete_structured(SYSTEM, USER, MINI_SCHEMA)


def test_body_that_is_not_json_is_enl_llm() -> None:
    session = StubSession([StubResponse(200, None, text="<html>gateway</html>")])
    client = make_client(session, [])

    with pytest.raises(NLLlmError):
        client.complete_structured(SYSTEM, USER, MINI_SCHEMA)


def test_payload_failing_the_envelope_schema_is_enl_llm() -> None:
    # schema-forced shape is violated: status outside the envelope enum
    session = StubSession([chat('{"status": "banana"}')])
    client = make_client(session, [])

    with pytest.raises(NLLlmError) as excinfo:
        client.complete_structured(SYSTEM, USER, MINI_SCHEMA)

    assert excinfo.value.code == "E_NL_LLM"


def test_unknown_extra_field_fails_the_envelope_too() -> None:
    session = StubSession([chat('{"status": "ok", "surprise": 1}')])
    client = make_client(session, [])

    with pytest.raises(NLLlmError):
        client.complete_structured(SYSTEM, USER, MINI_SCHEMA)


# ------------------------------------------------------------------- hard gates


def test_offline_mode_makes_no_call_at_all() -> None:
    # outcome is an AssertionError: if the transport were touched, the stub
    # would raise it instead of the client's own typed error.
    session = StubSession([AssertionError("network touched while offline")])
    client = make_client(session, [], config=make_config(offline=True))

    with pytest.raises(NLLlmError) as excinfo:
        client.complete_structured(SYSTEM, USER, MINI_SCHEMA)

    assert excinfo.value.code == "E_NL_LLM"
    assert session.calls == [], "offline mode must never touch the transport"


def test_missing_key_is_enl_llm_before_any_call() -> None:
    session = StubSession([AssertionError("transport touched without a key")])
    client = make_client(session, [], config=make_config(nvidia_api_key=None))

    with pytest.raises(NLLlmError) as excinfo:
        client.complete_structured(SYSTEM, USER, MINI_SCHEMA)

    assert session.calls == []
    assert "NVIDIA_API_KEY" in (excinfo.value.hint + str(excinfo.value))
