"""P6-T1: recorded-demo mode -- reachable-vs-unreachable gating, loud labels.

Owner ruling: demo replay happens ONLY when (a) the endpoint is UNREACHABLE
(connection/timeout after retries), AND (b) ``NLBT_LLM_DEMO=1``, AND (c) a
recording matches the request hash. Every other outcome is the normal
``E_NL_LLM``. The served response is labelled three ways: source
``"recorded-demo"``, a ``[nlbt][DEMO]`` warning on stderr, and nothing else
(the manifest wiring is deferred to P6-T3, OQ-logged by this task).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import requests

from nlbt.config import Config
from nlbt.errors import NLLlmError
from nlbt.nl import OpenAICompatibleClient, request_fingerprint

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


def make_config(**overrides: Any) -> Config:
    base: dict[str, Any] = {
        "nvidia_api_key": "nvapi-FAKE-DEMO-KEY-0123456789",
        "llm_model": "test-model",
        "llm_base_url": "https://unit.test/v1",
        "offline": False,
    }
    base.update(overrides)
    return Config(**base)


class UnreachableSession:
    """Always refuses the connection (4 attempts' worth of outcomes)."""

    def __init__(self, exc: Exception) -> None:
        self.exc = exc
        self.calls: list[Any] = []

    def post(self, url: str, **kwargs: Any) -> Any:
        self.calls.append(url)
        raise self.exc


class RateLimitedSession:
    """Endpoint IS reachable: every attempt comes back 429."""

    def __init__(self) -> None:
        self.calls: list[Any] = []

    def post(self, url: str, **kwargs: Any) -> Any:
        self.calls.append(url)
        return _Resp(429, {"error": "rate limited"})


class _Resp:
    def __init__(
        self, status_code: int, payload: Any, headers: dict[str, str] | None = None
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)
        self.headers = headers or {}

    def json(self) -> Any:
        return self._payload


def write_matching_fixture(fixture_dir: Path, *, model: str = "test-model") -> None:
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": USER},
    ]
    digest = request_fingerprint(
        model=model,
        messages=messages,
        schema=SCHEMA,
        temperature=0.0,
        structured_mode="json_schema",
    )
    fixture_dir.mkdir(parents=True, exist_ok=True)
    (fixture_dir / "demo_ok.json").write_text(
        json.dumps(
            {
                "name": "demo_ok",
                "request_hash": digest,
                "request": {
                    "model": model,
                    "messages": messages,
                    "schema_sha256": "n/a-in-fixture",
                    "temperature": 0.0,
                    "structured_mode": "json_schema",
                },
                "response": STORED_PAYLOAD,
                "recorded_at": "2026-10-25T00:00:00+00:00",
                "host": "integrate.api.nvidia.com",
                "source": "recorded",
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def make_client(
    session: Any,
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


def test_unreachable_with_demo_flag_and_matching_recording_serves_demo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("NLBT_LLM_DEMO", "1")
    write_matching_fixture(tmp_path / "llm")
    client = make_client(
        UnreachableSession(requests.ConnectionError("refused")), [], recordings_dir=tmp_path / "llm"
    )

    resp = client.complete_structured(SYSTEM, USER, SCHEMA)

    assert resp.source == "recorded-demo"
    assert resp.payload == STORED_PAYLOAD
    err = capsys.readouterr().err
    assert "[nlbt][DEMO]" in err, "demo serving must be announced on stderr"
    assert "RECORDED" in err


def test_demo_flag_without_recording_is_normal_enl_llm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("NLBT_LLM_DEMO", "1")
    client = make_client(
        UnreachableSession(requests.ConnectionError("refused")),
        [],
        recordings_dir=tmp_path / "empty",
    )

    with pytest.raises(NLLlmError):
        client.complete_structured(SYSTEM, USER, SCHEMA)

    assert "[nlbt][DEMO]" not in capsys.readouterr().err


def test_unreachable_without_demo_flag_is_normal_enl_llm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("NLBT_LLM_DEMO", raising=False)
    write_matching_fixture(tmp_path / "llm")
    client = make_client(
        UnreachableSession(requests.Timeout("timed out")), [], recordings_dir=tmp_path / "llm"
    )

    with pytest.raises(NLLlmError):
        client.complete_structured(SYSTEM, USER, SCHEMA)

    assert "[nlbt][DEMO]" not in capsys.readouterr().err


def test_reachable_but_rate_limited_never_serves_demo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """429 means REACHABLE: demo replay is only for an unreachable endpoint."""
    monkeypatch.setenv("NLBT_LLM_DEMO", "1")
    write_matching_fixture(tmp_path / "llm")
    client = make_client(RateLimitedSession(), [], recordings_dir=tmp_path / "llm")

    with pytest.raises(NLLlmError) as excinfo:
        client.complete_structured(SYSTEM, USER, SCHEMA)

    assert excinfo.value.details["status"] == 429
    assert "[nlbt][DEMO]" not in capsys.readouterr().err
