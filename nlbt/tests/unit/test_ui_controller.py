"""P7-T4/P7-T6 UI controller and offline-demo acceptance tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nlbt.data.csv_provider import CSVProvider
from nlbt.errors import NLAmbiguousError, NLUnsupportedError
from nlbt.nl.recorded import RecordedClient
from nlbt.nl.service import UnconfirmedSpecError
from nlbt.spec.models import StrategySpec
from nlbt.ui import controller as controller_module
from nlbt.ui.controller import DISCLAIMER_TEXT, UIController
from nlbt.ui.demo_cases import DEMO_CASES

ROOT = Path(__file__).resolve().parents[2]
CSV_PATH = ROOT / "tests" / "fixtures" / "csv" / "demo_spy_daily.csv"
RECORDINGS = ROOT / "tests" / "fixtures" / "llm"


def controller_for_demo() -> UIController:
    return UIController(
        client=RecordedClient(fixture_dir=RECORDINGS),
        provider=CSVProvider(),
        data_csv=CSV_PATH,
    )


@pytest.mark.parametrize("index", range(3))
def test_successful_demo_prompts_replay_and_run_offline(index: int) -> None:
    case = DEMO_CASES[index]
    controller = controller_for_demo()

    interpretation = controller.interpret_request(case.prompt)

    assert interpretation.status == "ok"
    assert interpretation.spec is not None
    assert interpretation.bars is not None
    assert controller.is_recorded_demo is True
    confirmation = controller.confirm()
    assert confirmation is not None
    result = controller.run()

    assert result.trades
    assert result.metrics
    assert result.manifest["nl"]["llm_source"] == "recorded"


@pytest.mark.parametrize(
    ("index", "status"),
    [(3, "needs_clarification"), (4, "unsupported")],
)
def test_non_run_demo_prompts_replay_offline(index: int, status: str) -> None:
    controller = controller_for_demo()

    interpretation = controller.interpret_request(DEMO_CASES[index].prompt)

    assert interpretation.status == status
    assert (
        interpretation.questions if status == "needs_clarification" else interpretation.unsupported
    )
    assert controller.confirm() is None
    error = NLAmbiguousError if status == "needs_clarification" else NLUnsupportedError
    with pytest.raises(error):
        controller.run()


def test_unconfirmed_run_is_rejected() -> None:
    controller = controller_for_demo()
    controller.interpret_request(DEMO_CASES[0].prompt)

    with pytest.raises(UnconfirmedSpecError) as exc_info:
        controller.run()

    assert exc_info.value.code == "E_NL_UNCONFIRMED"


def test_edit_invalidates_confirmation_rerenders_and_requires_reconfirmation() -> None:
    controller = controller_for_demo()
    controller.interpret_request(DEMO_CASES[0].prompt)
    assert controller.confirm() is not None
    original_rendering = controller.state.rendering
    assert controller.state.spec is not None
    payload = controller.state.spec.model_dump(mode="json")
    payload["name"] = "Edited crossover"

    edited = controller.edit_spec_json(json.dumps(payload))

    assert edited is True
    assert controller.state.spec is not None
    assert controller.state.spec.name == "Edited crossover"
    assert controller.state.rendering != original_rendering
    assert controller.state.confirmation is None
    with pytest.raises(UnconfirmedSpecError):
        controller.run()
    assert controller.confirm() is not None
    assert controller.run().trades


def test_invalid_json_and_semantic_edit_surface_errors_and_block_confirmation() -> None:
    controller = controller_for_demo()
    controller.interpret_request(DEMO_CASES[0].prompt)
    assert controller.confirm() is not None

    assert controller.edit_spec_json("{") is False
    assert controller.state.edit_error
    assert controller.state.confirmation is None
    assert controller.confirm() is None

    assert controller.state.spec is not None
    payload = controller.state.spec.model_dump(mode="json")
    payload["sizing"]["value"] = 0.0
    assert controller.edit_spec_json(json.dumps(payload)) is False
    assert controller.state.edit_error
    assert controller.state.confirmation is None
    assert controller.confirm() is None


def test_weak_sample_warning_threshold() -> None:
    controller = controller_for_demo()
    controller.state.run_result = type("Run", (), {"metrics": {"num_trades": 29}})()
    assert controller.weak_sample_warning == (
        "Warning: only 29 trades — statistically weak sample (< 30 trades)"
    )
    controller.state.run_result = type("Run", (), {"metrics": {"num_trades": 30}})()
    assert controller.weak_sample_warning is None


@pytest.mark.parametrize("source", ["recorded", "recorded-demo"])
def test_recorded_llm_sources_show_demo_badge(source: str) -> None:
    controller = UIController(client=object(), provider=CSVProvider(), data_csv=CSV_PATH)
    controller.state.llm_source = source
    assert controller.is_recorded_demo is True


def test_live_source_does_not_show_demo_badge(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NLBT_LLM_DEMO", raising=False)
    controller = UIController(client=object(), provider=CSVProvider(), data_csv=CSV_PATH)
    controller.state.llm_source = "live"
    assert controller.is_recorded_demo is False


def test_honesty_bar_has_provenance_costs_trade_count_and_disclaimer() -> None:
    controller = controller_for_demo()
    controller.interpret_request(DEMO_CASES[0].prompt)
    controller.confirm()
    controller.run()

    bar = controller.honesty_bar

    assert {
        "data_source",
        "adjusted",
        "start",
        "end",
        "bars",
        "fee_bps",
        "slippage_bps",
        "num_trades",
    } <= bar.keys()
    assert DISCLAIMER_TEXT == (
        "Historical simulation only; not investment advice. LLM translation uses NVIDIA NIM "
        "under the NVIDIA API Trial Terms of Service (evaluation/development only)."
    )


def test_demo_fixtures_have_unique_matching_cases() -> None:
    assert len(DEMO_CASES) == 5
    assert len({case.prompt for case in DEMO_CASES}) == 5
    assert CSV_PATH.is_file()


def test_ui_app_module_imports_without_starting_server() -> None:
    import nlbt.ui.app as app

    assert callable(app.main)


def test_edit_invalidates_confirmation_deliberate_break_canary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pin the Gate-7 state transition independently of the complete edit path."""
    controller = controller_for_demo()
    controller.interpret_request(DEMO_CASES[0].prompt)
    controller.confirm()
    assert controller.state.confirmation is not None
    monkeypatch.setattr(controller_module, "render_spec", lambda spec: "edited")
    payload = controller.state.spec.model_dump(mode="json")  # type: ignore[union-attr]
    payload["name"] = "Canary edit"

    controller.edit_spec_json(json.dumps(payload))

    assert controller.state.confirmation is None


def test_edited_payload_is_a_valid_strategy_spec() -> None:
    """A small schema smoke assertion for the JSON editor's model contract."""
    spec = StrategySpec.model_validate_json(json.dumps(DEMO_CASES[0].spec))
    assert spec.universe.symbols == ["SPY"]
