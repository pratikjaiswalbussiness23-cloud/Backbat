"""P6-T10 CLI integration: the `nlbt ask` confirmation gate (ROADMAP 8.1 style).

Zero network by construction:

* the LLM boundary is injected (``nlbt.cli._ask_llm_client`` swapped for a
  ``RecordedClient`` fixture written by the test, or a real
  ``OpenAICompatibleClient`` wired to an unreachable session);
* data comes from ``tests/fixtures/csv/cli_daily.csv`` or a fake provider;
* ``input()`` is patched everywhere an interactive answer is expected, and
  patched to RAISE where no prompt is ever allowed (Gate 7: an unconfirmed
  spec cannot run, and non-ok statuses never reach the prompt).

Expected values are derived: the spec payload is the committed golden
fixture READ from disk (never edited), exit codes are the owner ruling Q3,
the JSON key set is the owner ruling Q4, and prompt/cancel literals are the
task-mandated strings.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
import requests

from nlbt.cli import main
from nlbt.config import Config, get_config
from nlbt.errors import DataEmptyError
from nlbt.nl import service as service_module
from nlbt.nl.client import request_fingerprint
from nlbt.nl.envelope import envelope_schema
from nlbt.nl.openai_client import DEMO_WARNING, OpenAICompatibleClient
from nlbt.nl.parse import build_user_message
from nlbt.nl.prompt import build_system_prompt
from nlbt.nl.recorded import RecordedClient
from nlbt.results.store import render_result_json

ASK_TEXT = (
    "Buy ACME when close crosses above 80 and sell when close crosses below 75. "
    "From 2024-01-02 to 2024-01-17."
)
SPEC_GOLDEN = Path("tests/fixtures/spec/cli_golden.json")
CSV = "tests/fixtures/csv/cli_daily.csv"

#: Q4: the interpretation JSON object carries EXACTLY these keys.
INTERPRETATION_JSON_KEYS = {
    "status",
    "resolved_symbol",
    "questions",
    "unsupported",
    "assumptions",
    "warnings",
    "rendering",
    "data_summary",
}

#: Obviously-fake test credential (same literal as test_llm_demo_mode.py);
#: never a real key, never read from or written to any env file.
FAKE_KEY = "nvapi-FAKE-DEMO-KEY-0123456789"


# --------------------------------------------------------------------- helpers
def golden_spec() -> dict[str, Any]:
    """The committed golden spec, READ (the fixture itself is never edited)."""
    return json.loads(SPEC_GOLDEN.read_text(encoding="utf-8"))


def write_fixture(fixture_dir: Path, *, name: str, payload: dict[str, Any]) -> None:
    """Persist one recording exactly as scripts/record_llm_fixture.py would."""
    system = build_system_prompt()
    user = build_user_message(ASK_TEXT)
    model_id = get_config().llm_model
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    digest = request_fingerprint(
        model=model_id,
        messages=messages,
        schema=envelope_schema(),
        temperature=0.0,
        structured_mode="json_schema",
    )
    fixture_dir.mkdir(parents=True, exist_ok=True)
    (fixture_dir / f"{name}.json").write_text(
        json.dumps(
            {
                "name": name,
                "request_hash": digest,
                "request": {
                    "model": model_id,
                    "messages": messages,
                    "temperature": 0.0,
                    "structured_mode": "json_schema",
                },
                "response": payload,
                "recorded_at": "2026-10-28T00:00:00+00:00",
                "host": "written-by-test",
                "source": "recorded",
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )


class RaisingProvider:
    """A DataProvider that always raises (proves it was never asked for data)."""

    def __init__(self, exc: BaseException) -> None:
        self.exc = exc
        self.calls = 0

    def get_bars(
        self,
        symbol: str,
        start: Any,
        end: Any,
        interval: str,
        adjusted: bool = False,
    ) -> Any:
        self.calls += 1
        raise self.exc


class UnreachableSession:
    """Always refuses the connection (4 attempts' worth of outcomes)."""

    def __init__(self, exc: Exception) -> None:
        self.exc = exc
        self.calls: list[Any] = []

    def post(self, url: str, **kwargs: Any) -> Any:
        self.calls.append(url)
        raise self.exc


def fake_client(**kwargs: Any) -> OpenAICompatibleClient:
    """A real transport pointed at an unreachable endpoint (no network)."""
    return OpenAICompatibleClient(
        config=Config(
            nvidia_api_key=FAKE_KEY,
            llm_base_url="https://unit.test/v1",
            offline=False,
        ),
        session=UnreachableSession(requests.ConnectionError("refused")),
        sleep=lambda _seconds: None,
        **kwargs,
    )


def input_returning(answer: str) -> Any:
    def _fake(*args: Any, **kwargs: Any) -> str:
        return answer

    return _fake


def input_must_not_be_called(*args: Any, **kwargs: Any) -> str:
    raise AssertionError("input() must not be called for this path")


def input_eof(*args: Any, **kwargs: Any) -> str:
    raise EOFError


def execute_run_boom(*args: Any, **kwargs: Any) -> Any:
    raise AssertionError("execute_run must not be called after cancellation")


def inject_recorded(monkeypatch: pytest.MonkeyPatch, fixture_dir: Path) -> None:
    monkeypatch.setattr("nlbt.cli._ask_llm_client", lambda: RecordedClient(fixture_dir=fixture_dir))


def no_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "nlbt.cli._ask_data_provider",
        lambda _csv: RaisingProvider(AssertionError("provider must not be fetched")),
    )


# ------------------------------------------------------------- --yes (flag path)
def test_ask_yes_flag_runs_without_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    write_fixture(tmp_path, name="ok", payload={"status": "ok", "spec": golden_spec()})
    inject_recorded(monkeypatch, tmp_path)
    monkeypatch.setattr("builtins.input", input_must_not_be_called)

    code = main(["ask", ASK_TEXT, "--yes", "--data-csv", CSV, "--no-persist"])

    out = capsys.readouterr().out
    assert code == 0
    assert "confirmed: yes (--yes)" in out  # --yes is LOGGED (P6-T10 accept)
    assert f"=== STRATEGY: {golden_spec()['name']} ===" in out  # rendering shown
    assert "run_id:" in out  # run summary printed
    assert "result:  (not persisted)" in out


# ---------------------------------------------------------- interactive y / n / EOF
def test_ask_interactive_yes_runs_and_persists_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fixture_dir = tmp_path / "recordings"
    runs_dir = tmp_path / "runs"
    write_fixture(fixture_dir, name="ok", payload={"status": "ok", "spec": golden_spec()})
    inject_recorded(monkeypatch, fixture_dir)
    monkeypatch.setattr("builtins.input", input_returning("y"))

    code = main(["ask", ASK_TEXT, "--data-csv", CSV, "--runs-dir", str(runs_dir)])

    captured = capsys.readouterr()
    assert code == 0
    assert "Confirm run? [y/N]: " in captured.out
    assert "confirmed: yes (interactive)" in captured.out
    assert "run_id:" in captured.out
    results = sorted(runs_dir.glob("*/result.json"))
    assert len(results) == 1
    payload = json.loads(results[0].read_text(encoding="utf-8"))
    confirmed_at = payload["manifest"]["nl"]["user_confirmed_at"]
    assert confirmed_at is not None
    datetime.fromisoformat(confirmed_at)  # a real ISO timestamp was recorded
    assert payload["manifest"]["nl"]["llm_source"] == "recorded"
    assert payload["manifest"]["llm"]["user_confirmed_at"] is None


def test_ask_interactive_no_cancels_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fixture_dir = tmp_path / "recordings"
    runs_dir = tmp_path / "runs"
    write_fixture(fixture_dir, name="ok", payload={"status": "ok", "spec": golden_spec()})
    inject_recorded(monkeypatch, fixture_dir)
    monkeypatch.setattr("builtins.input", input_returning("n"))
    monkeypatch.setattr(service_module, "execute_run", execute_run_boom)

    code = main(["ask", ASK_TEXT, "--data-csv", CSV, "--runs-dir", str(runs_dir)])

    out = capsys.readouterr().out
    assert code == 0
    assert "Run cancelled." in out
    assert not runs_dir.exists() or list(runs_dir.iterdir()) == []  # nothing persisted


def test_ask_eof_cancels_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fixture_dir = tmp_path / "recordings"
    runs_dir = tmp_path / "runs"
    write_fixture(fixture_dir, name="ok", payload={"status": "ok", "spec": golden_spec()})
    inject_recorded(monkeypatch, fixture_dir)
    monkeypatch.setattr("builtins.input", input_eof)
    monkeypatch.setattr(service_module, "execute_run", execute_run_boom)

    code = main(["ask", ASK_TEXT, "--data-csv", CSV, "--runs-dir", str(runs_dir)])

    out = capsys.readouterr().out
    assert code == 0
    assert "Run cancelled." in out
    assert not runs_dir.exists() or list(runs_dir.iterdir()) == []


# ------------------------------------------------------------- non-ok statuses
def test_ask_needs_clarification_exits_0_without_prompting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = {
        "status": "needs_clarification",
        "questions": [{"id": "entry_logic_missing", "question": "What should trigger a buy?"}],
        "unsupported": [],
    }
    write_fixture(tmp_path, name="clarify", payload=payload)
    inject_recorded(monkeypatch, tmp_path)
    no_provider(monkeypatch)
    monkeypatch.setattr("builtins.input", input_must_not_be_called)

    code = main(["ask", ASK_TEXT, "--data-csv", CSV, "--runs-dir", str(tmp_path)])

    out = capsys.readouterr().out
    assert code == 0
    assert "status:  needs_clarification" in out
    assert "What should trigger a buy?" in out
    assert not list(tmp_path.rglob("result.json"))


# ------------------------------------------------------------- non-ok statuses


def test_ask_fake_ticker_needs_clarification_without_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    spec = golden_spec()
    spec["universe"]["symbols"] = ["ZZZQ"]
    write_fixture(tmp_path, name="fake-ticker", payload={"status": "ok", "spec": spec})
    inject_recorded(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "nlbt.cli._ask_data_provider",
        lambda _csv: RaisingProvider(DataEmptyError("no rows for ZZZQ")),
    )
    monkeypatch.setattr("builtins.input", input_must_not_be_called)

    code = main(["ask", ASK_TEXT, "--data-csv", CSV, "--runs-dir", str(tmp_path)])

    out = capsys.readouterr().out
    assert code == 0
    assert "status:  needs_clarification" in out
    assert "symbol_not_identifiable" in out
    assert "I couldn't find data for ZZZQ. Which symbol did you mean?" in out
    assert not list(tmp_path.rglob("result.json"))


def test_ask_unsupported_exits_0_without_prompting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = {"status": "unsupported", "unsupported": ["options trading"], "questions": []}
    write_fixture(tmp_path, name="unsupported", payload=payload)
    inject_recorded(monkeypatch, tmp_path)
    no_provider(monkeypatch)
    monkeypatch.setattr("builtins.input", input_must_not_be_called)

    code = main(["ask", ASK_TEXT, "--data-csv", CSV, "--runs-dir", str(tmp_path)])

    out = capsys.readouterr().out
    assert code == 0
    assert "status:  unsupported" in out
    assert "options trading" in out
    assert not list(tmp_path.rglob("result.json"))


# ------------------------------------------------------------------- --json mode
def test_ask_json_yes_prints_result_payload_on_stdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fixture_dir = tmp_path / "recordings"
    runs_dir = tmp_path / "runs"
    write_fixture(fixture_dir, name="ok", payload={"status": "ok", "spec": golden_spec()})
    inject_recorded(monkeypatch, fixture_dir)
    monkeypatch.setattr("builtins.input", input_must_not_be_called)

    code = main(
        ["ask", ASK_TEXT, "--yes", "--data-csv", CSV, "--json", "--runs-dir", str(runs_dir)]
    )

    captured = capsys.readouterr()
    assert code == 0
    payload = json.loads(captured.out)  # stdout is ONE valid JSON document
    assert payload["run_id"]
    assert payload["manifest"]["nl"]["user_confirmed_at"] is not None
    assert set(payload) == {
        "run_id",
        "manifest",
        "metrics",
        "benchmark_metrics",
        "warnings",
        "data_quality_report",
    }
    result_file = next(runs_dir.glob("*/result.json"))
    stored_json = result_file.read_text(encoding="utf-8")
    assert captured.out == stored_json
    assert captured.out == render_result_json(payload) + "\n"
    assert "confirmed: yes (--yes)" in captured.err  # logged, but off stdout


def test_ask_json_needs_clarification_prints_interpretation_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = {
        "status": "needs_clarification",
        "questions": [{"id": "entry_logic_missing", "question": "What should trigger a buy?"}],
        "unsupported": [],
    }
    write_fixture(tmp_path, name="clarify", payload=payload)
    inject_recorded(monkeypatch, tmp_path)
    no_provider(monkeypatch)
    monkeypatch.setattr("builtins.input", input_must_not_be_called)

    code = main(["ask", ASK_TEXT, "--data-csv", CSV, "--json", "--runs-dir", str(tmp_path)])

    out = capsys.readouterr().out
    assert code == 0
    obj = json.loads(out)
    assert set(obj) == INTERPRETATION_JSON_KEYS  # Q4 key set, no cancelled key
    assert obj["status"] == "needs_clarification"
    assert obj["questions"] == payload["questions"]
    assert not list(tmp_path.rglob("result.json"))


def test_ask_json_unsupported_prints_interpretation_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = {"status": "unsupported", "unsupported": ["options trading"], "questions": []}
    write_fixture(tmp_path, name="unsupported", payload=payload)
    inject_recorded(monkeypatch, tmp_path)
    no_provider(monkeypatch)
    monkeypatch.setattr("builtins.input", input_must_not_be_called)

    code = main(["ask", ASK_TEXT, "--data-csv", CSV, "--json", "--runs-dir", str(tmp_path)])

    out = capsys.readouterr().out
    assert code == 0
    obj = json.loads(out)
    assert set(obj) == INTERPRETATION_JSON_KEYS
    assert obj["status"] == "unsupported"
    assert obj["unsupported"] == payload["unsupported"]
    assert not list(tmp_path.rglob("result.json"))


def test_ask_json_without_yes_writes_prompt_to_stderr_then_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Q4: prompt goes to stderr so stdout stays ONE valid JSON document."""
    write_fixture(tmp_path, name="ok", payload={"status": "ok", "spec": golden_spec()})
    inject_recorded(monkeypatch, tmp_path)
    monkeypatch.setattr("builtins.input", input_returning("y"))

    code = main(["ask", ASK_TEXT, "--data-csv", CSV, "--json", "--no-persist"])

    captured = capsys.readouterr()
    assert code == 0
    assert "Confirm run? [y/N]: " in captured.err
    payload = json.loads(captured.out)
    assert payload["manifest"]["nl"]["user_confirmed_at"] is not None


def test_ask_json_cancelled_prints_cancelled_interpretation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    write_fixture(tmp_path, name="ok", payload={"status": "ok", "spec": golden_spec()})
    inject_recorded(monkeypatch, tmp_path)
    monkeypatch.setattr("builtins.input", input_returning("n"))
    monkeypatch.setattr(service_module, "execute_run", execute_run_boom)

    code = main(["ask", ASK_TEXT, "--data-csv", CSV, "--json", "--no-persist"])

    captured = capsys.readouterr()
    assert code == 0
    assert "Confirm run? [y/N]: " in captured.err
    obj = json.loads(captured.out)
    assert set(obj) == INTERPRETATION_JSON_KEYS | {"cancelled"}
    assert obj["status"] == "ok"
    assert obj["cancelled"] is True


# --------------------------------------------------------- LLM unreachable / demo
def test_ask_unreachable_llm_exits_1_with_e_nl_llm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("NLBT_LLM_DEMO", raising=False)
    client = fake_client(recordings_dir=tmp_path / "empty-recordings")
    monkeypatch.setattr("nlbt.cli._ask_llm_client", lambda: client)
    monkeypatch.setattr("builtins.input", input_must_not_be_called)

    code = main(["ask", ASK_TEXT, "--yes", "--data-csv", CSV, "--no-persist"])

    captured = capsys.readouterr()
    assert code == 1
    assert "[E_NL_LLM]" in captured.err
    assert "run_id:" not in captured.out


def test_ask_demo_mode_serves_recorded_response_and_labels_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("NLBT_LLM_DEMO", "1")
    write_fixture(tmp_path, name="ok", payload={"status": "ok", "spec": golden_spec()})
    client = fake_client(recordings_dir=tmp_path)
    monkeypatch.setattr("nlbt.cli._ask_llm_client", lambda: client)
    monkeypatch.setattr("builtins.input", input_must_not_be_called)

    code = main(["ask", ASK_TEXT, "--yes", "--data-csv", CSV, "--json", "--no-persist"])

    captured = capsys.readouterr()
    assert code == 0
    assert DEMO_WARNING in captured.err  # clearly labelled on stderr
    payload = json.loads(captured.out)
    assert payload["manifest"]["nl"]["llm_source"] == "recorded-demo"
