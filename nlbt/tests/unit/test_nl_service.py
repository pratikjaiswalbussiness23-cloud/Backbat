"""P6-T4/T5/T10 (minimal): ``nlbt.nl.service`` -- interpret + confirmation gate.

Every test runs on a ``RecordedClient`` fixture written by the test itself in
the P6-T1 request-hash format, plus a CSV/fake ``DataProvider``: zero network,
zero live LLM calls (AGENTS.md: mock only the LLM/data boundaries).

Expected values are DERIVED, never invented:

* hashes/timestamps come from the imported ``spec_hash_*`` functions and the
  injected clock;
* the fake-ticker question text is the owner ruling (Q1) verbatim;
* structural expectations come from the contracts themselves (the five
  ``manifest["nl"]`` keys are the owner-ruled ``_NL_META_KEYS`` list, the
  ``E_NL_UNCONFIRMED`` string is the owner ruling Q2);
* "fetched exactly once" style claims are counted by wrapping providers.

Deliberate design pin: ``source_text`` is EXCLUDED from ``spec_hash_logic``
(nlbt/src/nlbt/spec/canonical.py ``_LOGIC_EXCLUDED_FIELDS``), so a
confirmation must carry BOTH hashes -- ``test_source_text_edit_...`` proves
the logic hash alone would miss that edit.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from nlbt.config import get_config
from nlbt.data.csv_provider import CSVProvider
from nlbt.errors import (
    DataEmptyError,
    DataProviderError,
    DataQualityError,
    LimitExceededError,
    NLAmbiguousError,
    NLLlmError,
    NLUnsupportedError,
)
from nlbt.nl import service as service_module
from nlbt.nl.client import request_fingerprint
from nlbt.nl.envelope import envelope_schema
from nlbt.nl.parse import MAX_INPUT_CHARS, build_user_message
from nlbt.nl.prompt import build_system_prompt
from nlbt.nl.recorded import RecordedClient
from nlbt.nl.service import (
    Interpretation,
    UnconfirmedSpecError,
    confirm_spec,
    interpret,
    require_confirmation,
    run_confirmed,
)
from nlbt.spec.canonical import spec_hash_full, spec_hash_logic
from nlbt.spec.models import StrategySpec
from nlbt.spec.render import render_spec
from nlbt.spec.validate import validate_spec

FIXED_TODAY = date(2026, 6, 15)  # injected clock (S10); <= the real today
NOW = datetime(2026, 10, 28, 9, 30, 0, tzinfo=UTC)

TEXT = (
    "Buy SPY when close is above 100 and sell when close is below 90. "
    "From 2024-01-01 to 2024-12-31."
)
PERIOD = {"start": "2024-01-01", "end": "2024-12-31"}
RULES = {"entry_long": {"all": [{"left": "close", "op": ">", "right": 100.0}]}}

CSV = "tests/fixtures/csv/cli_daily.csv"

#: Owner ruling Q1, verbatim (no invented alternative ticker, ever).
CLARIFICATION_QUESTION = "I couldn't find data for ZZZQ. Which symbol did you mean?"


# --------------------------------------------------------------------- helpers
def ok_spec(symbol: str = "SPY", **overrides: Any) -> dict[str, Any]:
    """A complete, valid spec dict (parse-time defaults-shaped)."""
    spec: dict[str, Any] = {
        "spec_version": "1.0",
        "name": "nl service strategy",
        "universe": {"symbols": [symbol], "interval": "1d"},
        "period": dict(PERIOD),
        "indicators": {},
        "rules": json.loads(json.dumps(RULES)),
        "sizing": {"method": "percent_of_equity", "value": 100.0},
        "capital": {"initial": 100000.0},
    }
    spec.update(overrides)
    return spec


def write_fixture(fixture_dir: Path, *, name: str, payload: dict[str, Any]) -> None:
    """Persist one recording exactly as scripts/record_llm_fixture.py would."""
    system = build_system_prompt()
    user = build_user_message(TEXT)
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


class CountingProvider:
    """Wraps a DataProvider and counts ``get_bars`` calls (fetch-once proofs)."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.calls = 0

    def get_bars(
        self,
        symbol: str,
        start: date,
        end: date,
        interval: str,
        adjusted: bool = False,
    ) -> Any:
        self.calls += 1
        return self.inner.get_bars(symbol, start, end, interval=interval, adjusted=adjusted)


class RaisingProvider:
    """A DataProvider that always raises (never returns data)."""

    def __init__(self, exc: BaseException) -> None:
        self.exc = exc
        self.calls = 0

    def get_bars(
        self,
        symbol: str,
        start: date,
        end: date,
        interval: str,
        adjusted: bool = False,
    ) -> Any:
        self.calls += 1
        raise self.exc


def interpret_ok(tmp_path: Path) -> tuple[Interpretation, CountingProvider]:
    """status=ok interpretation against the CSV fixture (one counted fetch)."""
    write_fixture(tmp_path, name="ok", payload={"status": "ok", "spec": ok_spec()})
    provider = CountingProvider(CSVProvider())
    interp = interpret(
        TEXT,
        client=RecordedClient(fixture_dir=tmp_path),
        provider=provider,
        today=FIXED_TODAY,
        data_symbol_override=CSV,
    )
    return interp, provider


def _execute_run_boom(*args: Any, **kwargs: Any) -> Any:
    raise AssertionError("execute_run must not be called for a refused interpretation")


def assert_refused(
    interp: Interpretation,
    monkeypatch: pytest.MonkeyPatch,
    expected: type[BaseException],
) -> None:
    """``run_confirmed`` refuses BEFORE ``execute_run`` (Gate 7)."""
    monkeypatch.setattr(service_module, "execute_run", _execute_run_boom)
    with pytest.raises(expected):
        run_confirmed(interp, None, persist=False)


def spec_for_gate(**overrides: Any) -> StrategySpec:
    return StrategySpec.model_validate(ok_spec(**overrides))


# --------------------------------------------------------------- interpret(): ok
def test_interpret_ok_returns_spec_rendering_bars_and_nl_meta(tmp_path: Path) -> None:
    interp, provider = interpret_ok(tmp_path)

    assert interp.status == "ok"
    assert interp.error is None
    assert isinstance(interp.spec, StrategySpec)
    spec = interp.spec
    assert interp.rendering == render_spec(spec)
    assert interp.assumptions  # registry defaults were disclosed (S6)
    for item in interp.assumptions:
        assert set(item) == {"field", "value", "reason"}
    assert interp.warnings == validate_spec(spec, today=FIXED_TODAY).warnings
    assert interp.questions == []
    assert interp.unsupported == []
    # S9: the symbol is shown back to the user, resolved against the spec.
    assert interp.resolved_symbol == spec.universe.symbols[0]

    # the verification fetch happened EXACTLY once and is reused downstream
    assert provider.calls == 1
    assert interp.bars is not None
    assert interp.bars_meta is not None
    assert interp.bars_meta.provider == "csv"
    summary = interp.data_summary
    assert summary is not None
    assert summary["provider"] == "csv"
    assert summary["symbol"] == interp.resolved_symbol
    assert summary["bars"] == len(interp.bars)
    assert summary["start"] == interp.bars.index.min().date().isoformat()
    assert summary["end"] == interp.bars.index.max().date().isoformat()

    meta = interp.nl_meta
    assert meta is not None
    assert meta["user_confirmed_at"] is None
    assert set(meta) == {
        "llm_model",
        "prompt_version",
        "llm_source",
        "assumptions",
        "user_confirmed_at",
    }
    assert meta["assumptions"] == interp.assumptions


# --------------------------------------------------- interpret(): non-ok statuses
def test_interpret_needs_clarification_from_model_never_fetches(tmp_path: Path) -> None:
    payload = {
        "status": "needs_clarification",
        "questions": [{"id": "entry_logic_missing", "question": "What should trigger a buy?"}],
        "unsupported": [],
    }
    write_fixture(tmp_path, name="clarify", payload=payload)
    provider = RaisingProvider(AssertionError("provider must not be fetched"))

    interp = interpret(
        TEXT,
        client=RecordedClient(fixture_dir=tmp_path),
        provider=provider,
        today=FIXED_TODAY,
    )

    assert interp.status == "needs_clarification"
    assert interp.spec is None
    assert interp.rendering == ""
    assert interp.questions == payload["questions"]
    assert interp.bars is None
    assert interp.nl_meta is None
    assert provider.calls == 0


def test_interpret_unsupported_from_model_refuses_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = {"status": "unsupported", "unsupported": ["options trading"], "questions": []}
    write_fixture(tmp_path, name="unsupported", payload=payload)
    provider = RaisingProvider(AssertionError("provider must not be fetched"))

    interp = interpret(
        TEXT,
        client=RecordedClient(fixture_dir=tmp_path),
        provider=provider,
        today=FIXED_TODAY,
    )

    assert interp.status == "unsupported"
    assert interp.unsupported == payload["unsupported"]
    assert interp.spec is None
    assert provider.calls == 0
    assert_refused(interp, monkeypatch, NLUnsupportedError)


def test_interpret_nonempty_unsupported_strict_blocks_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S5/P6-T4: strict mode (default) refuses to run while unsupported is non-empty."""
    payload = {"status": "ok", "spec": ok_spec(), "unsupported": ["sentiment scoring"]}
    write_fixture(tmp_path, name="strict-unsupported", payload=payload)
    provider = RaisingProvider(AssertionError("provider must not be fetched"))

    interp = interpret(
        TEXT,
        client=RecordedClient(fixture_dir=tmp_path),
        provider=provider,
        today=FIXED_TODAY,  # strict defaults to True
    )

    assert interp.status == "unsupported"
    assert interp.unsupported == payload["unsupported"]
    assert interp.spec is None
    assert provider.calls == 0  # blocked before any data fetch
    assert_refused(interp, monkeypatch, NLUnsupportedError)


def test_fake_ticker_needs_clarification_without_fallback(tmp_path: Path) -> None:
    """P6-T5/S9: E_DATA_EMPTY -> clarification, NEVER an invented alternative."""
    write_fixture(tmp_path, name="fake-ticker", payload={"status": "ok", "spec": ok_spec("ZZZQ")})
    provider = RaisingProvider(DataEmptyError("no rows for ZZZQ"))

    interp = interpret(
        TEXT,
        client=RecordedClient(fixture_dir=tmp_path),
        provider=provider,
        today=FIXED_TODAY,
    )

    assert interp.status == "needs_clarification"
    assert provider.calls == 1  # the verification fetch DID happen
    assert interp.spec is None
    assert interp.bars is None
    assert interp.resolved_symbol == "ZZZQ"
    assert interp.questions == [
        {"id": "symbol_not_identifiable", "question": CLARIFICATION_QUESTION}
    ]


# -------------------------------------------------- interpret(): status == error
def test_interpret_data_quality_error_is_status_error(tmp_path: Path) -> None:
    write_fixture(tmp_path, name="ok", payload={"status": "ok", "spec": ok_spec()})
    provider = RaisingProvider(DataQualityError("broken csv"))

    interp = interpret(
        TEXT,
        client=RecordedClient(fixture_dir=tmp_path),
        provider=provider,
        today=FIXED_TODAY,
    )

    assert interp.status == "error"
    assert isinstance(interp.error, DataQualityError)
    assert interp.error is not None
    assert interp.error.code == DataQualityError.code
    assert provider.calls == 1


def test_interpret_data_provider_error_is_status_error(tmp_path: Path) -> None:
    write_fixture(tmp_path, name="ok", payload={"status": "ok", "spec": ok_spec()})
    provider = RaisingProvider(DataProviderError("network down"))

    interp = interpret(
        TEXT,
        client=RecordedClient(fixture_dir=tmp_path),
        provider=provider,
        today=FIXED_TODAY,
    )

    assert interp.status == "error"
    assert isinstance(interp.error, DataProviderError)
    assert provider.calls == 1


def test_interpret_input_over_limit_is_status_error(tmp_path: Path) -> None:
    """E_LIMIT_EXCEEDED fires BEFORE any LLM call (MAX_INPUT_CHARS contract)."""
    too_long = "x" * (MAX_INPUT_CHARS + 1)
    provider = RaisingProvider(AssertionError("provider must not be fetched"))

    interp = interpret(
        too_long,
        client=RecordedClient(fixture_dir=tmp_path),  # empty: no fixture could match anyway
        provider=provider,
        today=FIXED_TODAY,
    )

    assert interp.status == "error"
    assert isinstance(interp.error, LimitExceededError)
    assert provider.calls == 0


def test_interpret_llm_failure_is_status_error(tmp_path: Path) -> None:
    """No matching recording -> the client's loud E_NL_LLM, surfaced as status=error."""
    provider = RaisingProvider(AssertionError("provider must not be fetched"))

    interp = interpret(
        TEXT,
        client=RecordedClient(fixture_dir=tmp_path / "no-recordings"),
        provider=provider,
        today=FIXED_TODAY,
    )

    assert interp.status == "error"
    assert isinstance(interp.error, NLLlmError)
    assert provider.calls == 0


# --------------------------------------------------------- confirmation gate
def test_require_confirmation_without_confirmation_raises() -> None:
    spec = spec_for_gate()

    with pytest.raises(UnconfirmedSpecError) as excinfo:
        require_confirmation(spec, None)

    assert excinfo.value.code == "E_NL_UNCONFIRMED"


def test_confirm_spec_records_hashes_timestamp_and_via() -> None:
    spec = spec_for_gate()

    confirmation = confirm_spec(spec, confirmed_via="interactive", now=NOW)

    assert confirmation.confirmed_via == "interactive"
    assert confirmation.spec_hash_logic == spec_hash_logic(spec)
    assert confirmation.spec_hash_full == spec_hash_full(spec)
    assert confirmation.user_confirmed_at == NOW.isoformat()
    # an untouched spec keeps its confirmation
    assert require_confirmation(spec, confirmation) is confirmation


def test_logic_edit_after_confirmation_invalidates() -> None:
    spec = spec_for_gate()
    confirmation = confirm_spec(spec, confirmed_via="flag", now=NOW)

    payload = json.loads(spec.model_dump_json())
    payload["rules"]["entry_long"]["conditions"][0]["right"]["value"] = 90.0
    edited = StrategySpec.model_validate(payload)

    assert spec_hash_logic(edited) != confirmation.spec_hash_logic  # the edit IS visible
    with pytest.raises(UnconfirmedSpecError):
        require_confirmation(edited, confirmation)


def test_risk_edit_after_confirmation_invalidates() -> None:
    spec = spec_for_gate()
    confirmation = confirm_spec(spec, confirmed_via="ui", now=NOW)

    payload = json.loads(spec.model_dump_json())
    payload["risk"]["stop_loss_pct"] = 5.0
    edited = StrategySpec.model_validate(payload)

    assert spec_hash_logic(edited) != confirmation.spec_hash_logic
    with pytest.raises(UnconfirmedSpecError):
        require_confirmation(edited, confirmation)


def test_source_text_edit_invalidates_via_full_hash_only() -> None:
    """Provenance edits are invisible to the LOGIC hash -- so the confirmation
    must carry ``spec_hash_full`` too (canonical.py _LOGIC_EXCLUDED_FIELDS)."""
    spec = spec_for_gate(source_text=TEXT)
    confirmation = confirm_spec(spec, confirmed_via="interactive", now=NOW)

    payload = json.loads(spec.model_dump_json())
    payload["source_text"] = f"{TEXT} (edited)"
    edited = StrategySpec.model_validate(payload)

    assert spec_hash_logic(edited) == confirmation.spec_hash_logic  # logic hash ALONE misses it
    assert spec_hash_full(edited) != confirmation.spec_hash_full
    with pytest.raises(UnconfirmedSpecError):
        require_confirmation(edited, confirmation)


# --------------------------------------------------------------- run_confirmed
def test_run_confirmed_reuses_fetch_and_records_confirmation(tmp_path: Path) -> None:
    interp, provider = interpret_ok(tmp_path)
    assert interp.spec is not None
    assert interp.nl_meta is not None
    confirmation = confirm_spec(interp.spec, confirmed_via="flag", now=NOW)

    result = run_confirmed(interp, confirmation, persist=False, now=NOW)

    assert provider.calls == 1  # NO second fetch: interpret()'s bars are reused
    nl = result.manifest["nl"]
    assert nl["user_confirmed_at"] == NOW.isoformat()
    assert nl["llm_source"] == "recorded"
    assert nl["assumptions"] == interp.nl_meta["assumptions"]
    legacy = result.manifest["llm"]
    assert legacy["llm_model"] is None
    assert legacy["prompt_version"] is None
    assert legacy["user_confirmed_at"] is None


def test_run_confirmed_without_confirmation_never_executes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    interp, _provider = interpret_ok(tmp_path)
    monkeypatch.setattr(service_module, "execute_run", _execute_run_boom)

    with pytest.raises(UnconfirmedSpecError):
        run_confirmed(interp, None, persist=False)


def test_run_confirmed_reraises_typed_status_error(tmp_path: Path) -> None:
    write_fixture(tmp_path, name="ok", payload={"status": "ok", "spec": ok_spec()})
    interp = interpret(
        TEXT,
        client=RecordedClient(fixture_dir=tmp_path),
        provider=RaisingProvider(DataQualityError("broken csv")),
        today=FIXED_TODAY,
    )
    assert interp.status == "error"

    with pytest.raises(DataQualityError) as excinfo:
        run_confirmed(interp, None, persist=False)

    assert excinfo.value is interp.error  # the exact typed error, re-raised


def test_run_confirmed_refuses_needs_clarification(tmp_path: Path) -> None:
    payload = {
        "status": "needs_clarification",
        "questions": [{"id": "entry_logic_missing", "question": "What should trigger a buy?"}],
        "unsupported": [],
    }
    write_fixture(tmp_path, name="clarify", payload=payload)
    interp = interpret(
        TEXT,
        client=RecordedClient(fixture_dir=tmp_path),
        provider=RaisingProvider(AssertionError("provider must not be fetched")),
        today=FIXED_TODAY,
    )
    assert interp.status == "needs_clarification"

    with pytest.raises(NLAmbiguousError) as excinfo:
        run_confirmed(interp, None, persist=False)

    assert excinfo.value.details["questions"] == interp.questions
