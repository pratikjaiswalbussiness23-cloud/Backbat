"""P5-T4a: manifest contents (§4.6 + Appendix E + owner rulings)."""

from __future__ import annotations

import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from nlbt.data.models import Bars
from nlbt.engine.benchmark import compute_benchmark
from nlbt.results import execute_run
from nlbt.spec.canonical import spec_hash_full, spec_hash_logic
from nlbt.spec.models import StrategySpec

DATA_SOURCE = {"kind": "csv", "path": "fixtures/valid_daily.csv"}
NOW = datetime(2026, 10, 24, 12, 0, 0, tzinfo=UTC)


def _bars(closes: list[float] | None = None) -> Bars:
    closes = closes or [100.0, 101.0, 102.0, 103.0, 104.0, 105.0]
    idx = pd.date_range("2024-01-01", periods=len(closes), freq="D", tz="utc")
    return Bars(
        pd.DataFrame(
            {
                "open": closes,
                "high": [c + 1.0 for c in closes],
                "low": [c - 1.0 for c in closes],
                "close": closes,
                "volume": [1000.0] * len(closes),
            },
            index=idx,
        )
    )


def _spec(fee_bps: float = 5.0) -> StrategySpec:
    return StrategySpec.model_validate(
        {
            "spec_version": "1.0",
            "name": "p5t4a-manifest",
            "universe": {"symbols": ["TEST"], "interval": "1d"},
            "period": {"start": "2024-01-01", "end": "2024-12-31"},
            "indicators": {},
            "rules": {"entry_long": {"all": [{"left": "close", "op": ">", "right": 10000}]}},
            "risk": {},
            "sizing": {
                "method": "percent_of_equity",
                "value": 50.0,
                "allow_fractional": True,
            },
            "execution": {
                "fill": "next_open",
                "fee_bps": fee_bps,
                "slippage_bps": 5.0,
                "fixed_fee": 0.0,
            },
            "capital": {"initial": 10_000.0},
        }
    )


def test_spec_hashes_match_canonical_functions() -> None:
    spec = _spec()
    result = execute_run(spec, _bars(), data_source=DATA_SOURCE, now=NOW, persist=False)
    assert result.manifest["spec_hash_logic"] == spec_hash_logic(spec)
    assert result.manifest["spec_hash_full"] == spec_hash_full(spec)
    assert result.manifest["spec_hash_logic"].startswith("sha256:")


def test_data_hash_prefix_stable_and_sensitive() -> None:
    bars = _bars()
    first = execute_run(_spec(), bars, now=NOW, persist=False)
    second = execute_run(_spec(), _bars(), now=NOW, persist=False)  # same data, new frame
    assert first.manifest["data_hash"].startswith("sha256:")
    assert first.manifest["data_hash"] == second.manifest["data_hash"]

    changed = _bars([100.0, 101.0, 102.5, 103.0, 104.0, 105.0])  # one price moved
    other = execute_run(_spec(), changed, now=NOW, persist=False)
    assert other.manifest["data_hash"] != first.manifest["data_hash"]


def test_python_and_package_versions_recorded() -> None:
    import platform

    result = execute_run(_spec(), _bars(), now=NOW, persist=False)
    code = result.manifest["code"]
    assert code["python"] == platform.python_version()
    for package in ("pandas", "numpy", "pydantic"):
        version = code["packages"][package]
        assert isinstance(version, str) and version != "", (package, version)


def test_llm_fields_are_null_until_phase_6() -> None:
    result = execute_run(_spec(), _bars(), now=NOW, persist=False)
    nl = result.manifest["llm"]
    assert nl["llm_model"] is None
    assert nl["prompt_version"] is None
    assert nl["user_confirmed_at"] is None


def test_code_version_is_git_sha_or_unknown() -> None:
    result = execute_run(_spec(), _bars(), now=NOW, persist=False)
    code_version = result.manifest["code"]["code_version"]
    assert code_version == "unknown" or re.fullmatch(r"[0-9a-f]{40}", code_version)
    # cross-check against git itself when available
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
            cwd=Path(__file__).resolve().parents[3],
        )
        assert code_version == out.stdout.strip()
    except OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired:
        assert code_version in {"unknown"} or re.fullmatch(r"[0-9a-f]{40}", code_version)


def test_data_source_recorded_under_data_section() -> None:
    result = execute_run(_spec(), _bars(), data_source=DATA_SOURCE, now=NOW, persist=False)
    assert result.manifest["data"]["source"] == DATA_SOURCE
    assert result.manifest["data"]["bars"] == 6
    assert result.manifest["data"]["symbol"] == "TEST"
    assert result.manifest["data"]["interval"] == "1d"


def test_run_started_at_reflects_injected_now() -> None:
    result = execute_run(_spec(), _bars(), now=NOW, persist=False)
    assert result.manifest["run_started_at"] == NOW.isoformat()


def test_benchmark_metrics_equals_compute_benchmark() -> None:
    spec, bars = _spec(), _bars()
    result = execute_run(spec, bars, rf=0.03, persist=False)
    expected, _ = compute_benchmark(spec, bars, rf=0.03)
    assert result.benchmark_metrics == expected  # exact, same inputs
    assert result.benchmark_metrics["risk_free_rate"] == 0.03
