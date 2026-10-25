"""P5-T5 CLI v0 integration tests (ROADMAP 8.1: CLI end-to-end on a fixture CSV).

Expected numbers are HAND-DERIVED from the documented contracts (ROADMAP
4.5 execution model, 4.7 metric definitions) against a fixture series
DESIGNED for hand arithmetic -- every derivation is shown in the constants
below and none of it is copied from CLI output. Risk metrics are checked
against an independent numpy oracle built from the hand-derived equity
series. The golden file (tests/golden/cli_run_result.json) is only written
AFTER these assertions pass; see tests/golden/README.md for its provenance
and the owner-approval rule (ROADMAP 8.4).
"""

from __future__ import annotations

import copy
import json
import math
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from nlbt.cli import main
from nlbt.spec.models import StrategySpec
from nlbt.spec.render import render_spec

ROOT = Path(__file__).resolve().parents[2]
SPEC = "tests/fixtures/spec/cli_golden.json"
SPEC_SCHEMA_BAD = "tests/fixtures/spec/cli_invalid_schema.json"
SPEC_SEMANTIC_BAD = "tests/fixtures/spec/cli_invalid_semantics.json"
SPEC_MALFORMED = "tests/fixtures/spec/cli_malformed.json"
SPEC_MISSING = "tests/fixtures/spec/does_not_exist.json"
CSV = "tests/fixtures/csv/cli_daily.csv"
CSV_BAD = "tests/fixtures/csv/missing_column.csv"
GOLDEN = ROOT / "tests" / "golden" / "cli_run_result.json"

# ---------------------------------------------------------------------------
# Hand-derived constants -- arithmetic shown, never copied from output.
#
# Fixture: 12 weekday bars 2024-01-02..2024-01-17, zero fees/slippage
# (fee_bps=0, slippage_bps=0, fixed_fee=0), percent_of_equity 100 % with
# fractional shares => shares = cash / fill_price exactly (ROADMAP 4.5
# "sizing is computed at fill time"; engine/sizing.py percent_of_equity).
#
# Signals (hand-evaluated on the close column):
#   entry  close crosses_above 80 -> true on 2024-01-04 (82 vs 72 before)
#          -> fills at the NEXT bar open, 2024-01-05 = 80.0        [trade 1]
#   exit   close crosses_below 75 -> true on 2024-01-10 (74 vs 86 before)
#          -> fills at the NEXT bar open, 2024-01-11 = 76.0        [trade 1]
#   entry  close crosses_above 80 -> true on 2024-01-15 (84 vs 78 before)
#          -> fills at the NEXT bar open, 2024-01-16 = 95.0        [trade 2]
#   no exit signal remains -> forced end_of_data close at the last bar
#          close, 2024-01-17 = 105.0                              [trade 2]
# ---------------------------------------------------------------------------
INITIAL_CAPITAL = 10000.0
ENTRY_1, EXIT_1 = 80.0, 76.0  # trade 1 fills
ENTRY_2, EXIT_2 = 95.0, 105.0  # trade 2 fills (exit = last close)

SHARES_1 = INITIAL_CAPITAL / ENTRY_1  # = 10000 / 80 = 125.0
NET_PNL_1 = (EXIT_1 - ENTRY_1) * SHARES_1  # = (76 - 80) * 125 = -500.0
CASH_AFTER_1 = INITIAL_CAPITAL + NET_PNL_1  # = 9500.0
SHARES_2 = CASH_AFTER_1 / ENTRY_2  # = 9500 / 95 = 100.0
NET_PNL_2 = (EXIT_2 - ENTRY_2) * SHARES_2  # = (105 - 95) * 100 = +1000.0
FINAL_EQUITY = CASH_AFTER_1 + NET_PNL_2  # = 10500.0
TOTAL_RETURN = FINAL_EQUITY / INITIAL_CAPITAL - 1.0  # = 0.05

NUM_TRADES = 2.0
WIN_RATE = 1.0 / 2.0  # trade 1 loses, trade 2 wins
PROFIT_FACTOR = NET_PNL_2 / abs(NET_PNL_1)  # = 1000 / 500 = 2.0
RETURN_1 = NET_PNL_1 / (ENTRY_1 * SHARES_1)  # = -500 / 10000 = -0.05
RETURN_2 = NET_PNL_2 / (ENTRY_2 * SHARES_2)  # = 1000 / 9500
EXPECTANCY = (RETURN_1 + RETURN_2) / 2.0
AVG_WIN = RETURN_2
AVG_LOSS = RETURN_1
LONGEST_LOSING_STREAK = 1.0
# Bars with position_value > 0: Jan 05, 08, 09, 10 (trade 1) + Jan 16, 17
# (trade 2); the Jan 11 bar sold at the open, so it is flat at the close.
EXPOSURE = 6.0 / 12.0

# Hand-built settled equity series (bar-by-bar, mark to market at close):
#   bars 0-2 flat 10000 | bar 3: 125*84=10500 | bar 4: 125*88=11000
#   bar 5: 125*86=10750 | bar 6: 125*74=9250 | bars 7-9 flat 9500
#   bar 10: 100*102=10200 | bar 11: 100*105=10500 (settled last value =
#   final_equity 10500 after the forced end_of_data close -- same number)
EQUITY_SETTLED = np.array(
    [
        10000.0,
        10000.0,
        10000.0,
        10500.0,
        11000.0,
        10750.0,
        9250.0,
        9500.0,
        9500.0,
        9500.0,
        10200.0,
        10500.0,
    ],
    dtype=float,
)
# Max drawdown = min(E/cummax(E) - 1): peak 11000 (2024-01-08), trough 9250
# (2024-01-10) => 9250/11000 - 1 = -0.1590909...
HAND_MAX_DRAWDOWN = 9250.0 / 11000.0 - 1.0
# Drawdown < 0 on bars 5..11 inclusive (bar 11 still below the 11000 peak).
LONGEST_DRAWDOWN_BARS = 7.0

# ---------------------------------------------------------------------------
# Independent numpy oracle for the risk metrics (ROADMAP 4.7 formulas,
# coded here from the definitions -- not from the implementation):
#   years            = (last_date - first_date).days / 365.25 = 15 / 365.25
#   bar return r[t]  = E[t]/E[t-1] - 1
#   annualised vol   = std(r, ddof=1) * sqrt(bars_per_year)
#   sharpe           = (mean(r) - rf/bars_per_year) / std(r, ddof=1) * sqrt(bars_per_year)
#   CAGR             = (E_end/E_start)^(1/years) - 1
#   calmar           = CAGR / abs(max drawdown)
# bars_per_year = 252: the fixture is 12 weekday bars (median 4 bars per ISO
# week >= EQUITY_MIN_DAYS_PER_WEEK=4.0 => DAILY_EQUITY, frequency.py).
# ---------------------------------------------------------------------------
BARS_PER_YEAR = 252.0
RF = 0.0
_BAR_RETURNS = EQUITY_SETTLED[1:] / EQUITY_SETTLED[:-1] - 1.0
_STD = float(np.std(_BAR_RETURNS, ddof=1))
EXPECTED_VOLATILITY = _STD * math.sqrt(BARS_PER_YEAR)
EXPECTED_SHARPE = (
    (float(np.mean(_BAR_RETURNS)) - RF / BARS_PER_YEAR) / _STD * math.sqrt(BARS_PER_YEAR)
)
YEARS = 15 / 365.25  # 2024-01-17 minus 2024-01-02
EXPECTED_CAGR = (10500.0 / 10000.0) ** (1.0 / YEARS) - 1.0
EXPECTED_MAX_DRAWDOWN = float((EQUITY_SETTLED / np.maximum.accumulate(EQUITY_SETTLED) - 1.0).min())
EXPECTED_CALMAR = EXPECTED_CAGR / abs(EXPECTED_MAX_DRAWDOWN)

# Benchmark (engine/benchmark.py: buy-and-hold, enters the bar after the
# first signal). Entry rule is "close > 0" -> true on bar 0 -> fills at
# 2024-01-03 open = 70.0; settled at the last close 105.0:
#   total_return = 105/70 - 1 = 0.5
EXPECTED_BENCHMARK_TOTAL_RETURN = 105.0 / 70.0 - 1.0

PAYLOAD_KEYS = {
    "run_id",
    "manifest",
    "metrics",
    "benchmark_metrics",
    "warnings",
    "data_quality_report",
}


@pytest.fixture(autouse=True)
def _cwd_root(monkeypatch: pytest.MonkeyPatch) -> None:
    """Literal fixture paths are relative to the nlbt root and must stay
    stable inside the manifest (and therefore inside the golden file)."""
    monkeypatch.chdir(ROOT)


def _invoke(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    """Call the real entry point in-process; return (exit code, out, err)."""
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _run_argv(runs_dir: Path, *extra: str) -> list[str]:
    return ["run", SPEC, "--data-csv", CSV, "--rf", "0.0", "--runs-dir", str(runs_dir), *extra]


def _strip_volatile(payload: dict[str, Any]) -> dict[str, Any]:
    """Drop exactly the volatile fields approved in Phase B rulings Q2/Q5:
    run_id, manifest.run_started_at, manifest.data.fetched_at,
    manifest.data.source.path, the WHOLE manifest.code section, and
    data_quality_report warnings with code STALE_LAST_BAR (the 2024 fixture
    ages past the 5-business-day threshold -- see tests/golden/README.md)."""
    stripped = copy.deepcopy(payload)
    stripped.pop("run_id", None)
    manifest = stripped["manifest"]
    manifest.pop("run_started_at", None)
    data = manifest["data"]
    data.pop("fetched_at", None)
    source = data.get("source")
    if isinstance(source, dict):
        source.pop("path", None)
    manifest.pop("code", None)
    report = stripped.get("data_quality_report")
    if isinstance(report, dict):
        report["warnings"] = [
            warning for warning in report["warnings"] if warning.get("code") != "STALE_LAST_BAR"
        ]
    return stripped


def _load_stored(runs_dir: Path) -> dict[str, Any]:
    matches = sorted(runs_dir.glob("*/result.json"))
    assert len(matches) == 1, f"expected exactly one result.json under {runs_dir}, got {matches}"
    return json.loads(matches[0].read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# run: exit 0, summary output, no NaN/inf, ASCII only
# ---------------------------------------------------------------------------


def test_run_exit0_summary_output_and_ascii(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    runs = tmp_path / "runs"
    code, out, err = _invoke(_run_argv(runs), capsys)
    assert code == 0, err
    assert err == ""
    # run_id line + result path line of the compact human summary
    assert re.search(r"(?m)^run_id:  \S", out)
    assert re.search(r"(?m)^result:  .+[/\\]result\.json", out)
    assert str(runs) in out
    assert "CLI golden crossover" in out
    assert "warnings: none" in out
    # no NaN/inf ever reaches stdout/stderr (values render as "n/a")
    assert re.search(r"(?<![A-Za-z0-9])(nan|inf|-inf)(?![A-Za-z0-9])", out + err) is None
    # ASCII-only output
    assert all(ord(char) < 128 for char in out + err)


# ---------------------------------------------------------------------------
# run: hand-derived constants + independent numpy oracle
# ---------------------------------------------------------------------------


def test_run_metrics_match_hand_derived_constants(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    runs = tmp_path / "runs"
    code, _, err = _invoke(_run_argv(runs), capsys)
    assert code == 0, err
    metrics = _load_stored(runs)["metrics"]

    assert metrics["initial_capital"] == INITIAL_CAPITAL
    assert metrics["final_equity"] == pytest.approx(FINAL_EQUITY, rel=1e-12)
    assert metrics["total_return"] == pytest.approx(TOTAL_RETURN, rel=1e-12)
    assert metrics["num_trades"] == NUM_TRADES
    assert metrics["win_rate"] == pytest.approx(WIN_RATE, rel=1e-12)
    assert metrics["profit_factor"] == pytest.approx(PROFIT_FACTOR, rel=1e-12)
    assert metrics["expectancy"] == pytest.approx(EXPECTANCY, rel=1e-12)
    assert metrics["avg_win"] == pytest.approx(AVG_WIN, rel=1e-12)
    assert metrics["avg_loss"] == pytest.approx(AVG_LOSS, rel=1e-12)
    assert metrics["longest_losing_streak"] == LONGEST_LOSING_STREAK
    assert metrics["exposure"] == pytest.approx(EXPOSURE, rel=1e-12)
    assert metrics["max_drawdown"] == pytest.approx(HAND_MAX_DRAWDOWN, rel=1e-12)
    assert metrics["longest_drawdown_bars"] == LONGEST_DRAWDOWN_BARS
    assert metrics["risk_free_rate"] == RF


def test_run_metrics_match_independent_numpy_oracle(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    runs = tmp_path / "runs"
    code, _, err = _invoke(_run_argv(runs), capsys)
    assert code == 0, err
    payload = _load_stored(runs)
    metrics = payload["metrics"]

    assert metrics["annualised_volatility"] == pytest.approx(EXPECTED_VOLATILITY, rel=1e-9)
    assert metrics["sharpe"] == pytest.approx(EXPECTED_SHARPE, rel=1e-9)
    assert metrics["cagr"] == pytest.approx(EXPECTED_CAGR, rel=1e-9)
    assert metrics["calmar"] == pytest.approx(EXPECTED_CALMAR, rel=1e-9)

    benchmark = payload["benchmark_metrics"]
    assert benchmark["total_return"] == pytest.approx(EXPECTED_BENCHMARK_TOTAL_RETURN, rel=1e-12)

    # Engine/benchmark produced every warning-free value: the payload
    # carries no warnings at all (all metrics defined; frequency classified
    # DAILY_EQUITY without a warning).
    assert payload["warnings"] == []


# ---------------------------------------------------------------------------
# run: golden comparison after dropping volatile fields
# ---------------------------------------------------------------------------


def test_run_result_json_matches_golden(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    runs = tmp_path / "runs"
    code, _, err = _invoke(_run_argv(runs), capsys)
    assert code == 0, err
    assert GOLDEN.is_file(), (
        "tests/golden/cli_run_result.json does not exist yet -- see tests/golden/README.md "
        "(it may only be written after the hand-derived assertions pass)"
    )
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    actual = _strip_volatile(_load_stored(runs))
    assert actual == expected


def test_manifest_code_section_keys_and_types(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    runs = tmp_path / "runs"
    code, _, err = _invoke(_run_argv(runs), capsys)
    assert code == 0, err
    code_section = _load_stored(runs)["manifest"]["code"]
    # Q5 ruling: manifest.code is dropped from the golden comparison and
    # asserted HERE instead (keys/types per execute.py _manifest/_PACKAGES).
    assert set(code_section) == {"code_version", "python", "packages"}
    assert isinstance(code_section["code_version"], str)
    assert code_section["code_version"] == "unknown" or re.fullmatch(
        r"[0-9a-f]{40}", code_section["code_version"]
    )
    assert isinstance(code_section["python"], str)
    assert re.fullmatch(r"\d+\.\d+\.\d+", code_section["python"])
    assert isinstance(code_section["packages"], dict)
    assert set(code_section["packages"]) == {"pandas", "numpy", "pydantic", "pyarrow"}
    assert all(isinstance(version, str) for version in code_section["packages"].values())


# ---------------------------------------------------------------------------
# run: --json and --no-persist
# ---------------------------------------------------------------------------


def test_run_json_prints_exactly_the_stored_payload(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    runs = tmp_path / "runs"
    code, out, err = _invoke(_run_argv(runs, "--json"), capsys)
    assert code == 0, err
    assert err == ""
    printed = json.loads(out)  # stdout must be pure JSON
    stored = _load_stored(runs)
    assert printed == stored


def test_run_no_persist_creates_no_directory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    runs = tmp_path / "never"
    code, out, err = _invoke(_run_argv(runs, "--no-persist", "--json"), capsys)
    assert code == 0, err
    assert not runs.exists()
    payload = json.loads(out)  # in-memory payload printed as pure JSON
    assert set(payload) == PAYLOAD_KEYS
    assert payload["run_id"]


def test_run_no_persist_human_summary(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    runs = tmp_path / "never"
    code, out, err = _invoke(_run_argv(runs, "--no-persist"), capsys)
    assert code == 0, err
    assert not runs.exists()
    assert re.search(r"(?m)^result:  \(not persisted\)$", out)


# ---------------------------------------------------------------------------
# run: through the real module entry point in a subprocess
# ---------------------------------------------------------------------------


def test_run_subprocess_module_entry(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "nlbt",
            "run",
            SPEC,
            "--data-csv",
            CSV,
            "--rf",
            "0.0",
            "--runs-dir",
            str(runs),
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == 0, proc.stderr
    assert "run_id:" in proc.stdout
    assert len(list(runs.glob("*/result.json"))) == 1


# ---------------------------------------------------------------------------
# validate-spec
# ---------------------------------------------------------------------------


def test_validate_spec_valid_exit0(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = _invoke(["validate-spec", SPEC], capsys)
    assert code == 0, err
    assert f"valid: {SPEC}" in out
    assert "[E_" not in out + err


def test_validate_spec_schema_invalid_exit1(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = _invoke(["validate-spec", SPEC_SCHEMA_BAD], capsys)
    assert code == 1
    assert "[E_SPEC_SCHEMA]" in err
    assert "valid:" not in out


def test_validate_spec_semantically_invalid_exit1(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = _invoke(["validate-spec", SPEC_SEMANTIC_BAD], capsys)
    assert code == 1
    assert "[E_SPEC_REF]" in err or "[E_SPEC_RANGE]" in err
    assert "valid:" not in out


# ---------------------------------------------------------------------------
# render-spec
# ---------------------------------------------------------------------------


def test_render_spec_prints_renderer_output(capsys: pytest.CaptureFixture[str]) -> None:
    spec = StrategySpec.model_validate(json.loads(Path(SPEC).read_text(encoding="utf-8")))
    code, out, err = _invoke(["render-spec", SPEC], capsys)
    assert code == 0, err
    assert out == render_spec(spec) + "\n"


# ---------------------------------------------------------------------------
# error mapping: exit codes 1 and 2
# ---------------------------------------------------------------------------


def test_missing_spec_file_exit2_plain_message(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = _invoke(["validate-spec", SPEC_MISSING], capsys)
    assert code == 2
    assert "cannot read spec file" in err
    assert out == ""  # plain message on stderr only
    assert "[E_" not in err  # Q1: plain message, no invented code


def test_malformed_json_exit1_spec_schema(capsys: pytest.CaptureFixture[str]) -> None:
    code, _, err = _invoke(["validate-spec", SPEC_MALFORMED], capsys)
    assert code == 1
    assert "[E_SPEC_SCHEMA]" in err


def test_bad_csv_exit1_data_quality(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    runs = tmp_path / "runs"
    argv = [
        "run",
        SPEC,
        "--data-csv",
        CSV_BAD,
        "--runs-dir",
        str(runs),
    ]
    code, _, err = _invoke(argv, capsys)
    assert code == 1
    assert "[E_DATA_QUALITY]" in err
    assert not runs.exists()  # failed before any persistence


def test_no_args_exit2(capsys: pytest.CaptureFixture[str]) -> None:
    code, _, err = _invoke([], capsys)
    assert code == 2
    assert "error:" in err


def test_unknown_flag_exit2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, _, err = _invoke(
        ["run", SPEC, "--data-csv", CSV, "--runs-dir", str(tmp_path / "runs"), "--bogus"], capsys
    )
    assert code == 2
    assert "error:" in err


def test_help_carries_disclaimer_and_is_ascii(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = _invoke(["--help"], capsys)
    assert code == 0, err
    assert "Historical simulation only; not investment advice." in out
    assert all(ord(char) < 128 for char in out)


def test_unexpected_error_reported_with_debug_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("boom")

    monkeypatch.setattr("nlbt.cli.CSVProvider.get_bars", _boom)
    monkeypatch.setenv("NLBT_DEBUG", "1")
    code, _, err = _invoke(_run_argv(tmp_path / "runs"), capsys)
    assert code == 1
    assert "unexpected error: RuntimeError: boom" in err
    assert "Traceback (most recent call last)" in err
