"""P6-T1: the key must NEVER appear in logs, exceptions, recordings, output.

Phase A design (owner-approved), scoped to this task: the manifest is NOT
touched by P6-T1 (wiring deferred to P6-T3), so this test covers the surfaces
that exist now -- the structured log stream, exception str/repr/details, and
the request body -- plus the structural guarantee that the key travels ONLY in
the Authorization header.

Fake key by design: ``nvapi-FAKE-DO-NOT-LEAK-1234567890``. The real key (if
any) never enters this file. The proof that the test bites is produced by the
deliberate break in the Phase B step-7 run (temporarily logging the
Authorization header -> this file goes red), pasted in the task log.

Log capture mirrors tests/unit/test_logging_config.py exactly: production
handler first (its filter mutates the record), then a capture handler, so the
assertion covers filter + formatter + production pipeline.
"""

from __future__ import annotations

import io
import json
import logging
from typing import Any

import pytest

from nlbt.config import Config
from nlbt.errors import NLLlmError
from nlbt.logging_config import JsonFormatter, setup_logging
from nlbt.nl import OpenAICompatibleClient

FAKE_KEY = "nvapi-FAKE-DO-NOT-LEAK-1234567890"
SYSTEM = "You translate English into the nlbt envelope JSON."
USER = "Translate: buy AAPL when RSI(14) is under 30"
SCHEMA = {
    "type": "object",
    "properties": {"status": {"type": "string"}},
    "required": ["status"],
    "additionalProperties": False,
}
VALID_PAYLOAD = {
    "status": "ok",
    "spec": None,
    "questions": [],
    "assumptions": [],
    "unsupported": [],
}


@pytest.fixture()
def captured_root_log() -> io.StringIO:
    """Root pipeline (production handler + capture), as in test_logging_config."""
    stream = io.StringIO()
    setup_logging("DEBUG")
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.addHandler(handler)
    yield stream
    root.removeHandler(handler)
    for h in list(root.handlers):
        if getattr(h, "_nlbt_handler", False):
            root.removeHandler(h)
    root.setLevel("WARNING")


class StubResponse:
    def __init__(
        self, status_code: int, payload: Any, headers: dict[str, str] | None = None
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)
        self.headers = headers or {}

    def json(self) -> Any:
        return self._payload


class StubSession:
    def __init__(self, outcomes: list[Any]) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []

    def post(self, url: str, *, headers: Any = None, json: Any = None, timeout: Any = None) -> Any:
        self.calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def make_client(session: StubSession) -> OpenAICompatibleClient:
    config = Config(
        nvidia_api_key=FAKE_KEY,
        llm_model="test-model",
        llm_base_url="https://unit.test/v1",
        offline=False,
    )
    return OpenAICompatibleClient(config=config, session=session, sleep=lambda _s: None)


def test_key_travels_only_in_the_authorization_header() -> None:
    """Structural: body/URL are key-free; header carries exactly Bearer + key."""
    session = StubSession(
        [StubResponse(200, {"choices": [{"message": {"content": '{"status": "ok"}'}}]})]
    )
    make_client(session).complete_structured(SYSTEM, USER, SCHEMA)

    call = session.calls[0]
    assert call["headers"]["Authorization"] == f"Bearer {FAKE_KEY}"
    assert FAKE_KEY not in json.dumps(call["json"])
    assert FAKE_KEY not in call["url"]


def test_success_path_never_logs_the_key(captured_root_log: io.StringIO) -> None:
    session = StubSession(
        [StubResponse(200, {"choices": [{"message": {"content": '{"status": "ok"}'}}]})]
    )
    make_client(session).complete_structured(SYSTEM, USER, SCHEMA)

    out = captured_root_log.getvalue()
    assert out.strip(), "client must log something on success (vacuous leak test is worthless)"
    assert "test-model" in out, "expected the model id in the client's log line"
    assert FAKE_KEY not in out, "key leaked into log output"
    assert "authorization" not in out.lower()


def test_failure_path_exception_and_logs_are_key_free(
    captured_root_log: io.StringIO,
) -> None:
    session = StubSession([StubResponse(400, {"error": "bad request"})])
    client = make_client(session)

    with pytest.raises(NLLlmError) as excinfo:
        client.complete_structured(SYSTEM, USER, SCHEMA)

    err = excinfo.value
    assert FAKE_KEY not in str(err)
    assert FAKE_KEY not in repr(err)
    assert FAKE_KEY not in json.dumps(err.details)
    out = captured_root_log.getvalue()
    assert FAKE_KEY not in out, "key leaked into log output on the failure path"
    assert "authorization" not in out.lower()


def test_429_failure_exception_is_key_free() -> None:
    session = StubSession([StubResponse(429, {"error": "rate limited"})] * 4)
    client = make_client(session)

    with pytest.raises(NLLlmError) as excinfo:
        client.complete_structured(SYSTEM, USER, SCHEMA)

    err = excinfo.value
    assert FAKE_KEY not in str(err)
    assert FAKE_KEY not in repr(err)
    assert FAKE_KEY not in json.dumps(err.details)


def test_network_failure_exception_is_key_free() -> None:
    import requests as _requests

    session = StubSession([_requests.ConnectionError("refused") for _ in range(4)])
    client = make_client(session)

    with pytest.raises(NLLlmError) as excinfo:
        client.complete_structured(SYSTEM, USER, SCHEMA)

    assert FAKE_KEY not in str(excinfo.value)
    assert FAKE_KEY not in repr(excinfo.value)
