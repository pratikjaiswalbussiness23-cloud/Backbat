"""P5-T4a: result.json persistence round trip (tmp_path only — never runs/)."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from nlbt.data.models import Bars, BarsMeta
from nlbt.results import execute_run
from nlbt.spec.models import StrategySpec

NOW = datetime(2026, 10, 24, 12, 0, 0, tzinfo=UTC)
NOW_2 = datetime(2026, 10, 24, 13, 0, 0, tzinfo=UTC)
DATA_SOURCE = {"kind": "csv", "path": "fixtures/valid_daily.csv"}

PAYLOAD_KEYS = {
    "run_id",
    "manifest",
    "metrics",
    "benchmark_metrics",
    "warnings",
    "data_quality_report",
}


def _reject_constant(name: str) -> None:
    raise AssertionError(f"non-JSON constant in result.json: {name}")


def _bars() -> Bars:
    closes = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0]
    idx = pd.date_range("2024-01-01", periods=6, freq="D", tz="utc")
    return Bars(
        pd.DataFrame(
            {
                "open": closes,
                "high": [c + 1.0 for c in closes],
                "low": [c - 1.0 for c in closes],
                "close": closes,
                "volume": [1000.0] * 6,
            },
            index=idx,
        )
    )


def _spec() -> StrategySpec:
    return StrategySpec.model_validate(
        {
            "spec_version": "1.0",
            "name": "p5t4a-roundtrip",
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
                "fee_bps": 5.0,
                "slippage_bps": 5.0,
                "fixed_fee": 0.0,
            },
            "capital": {"initial": 10_000.0},
        }
    )


def _drop_volatile(payload: dict) -> dict:
    """Documented volatile keys (determinism comparison excludes them)."""
    cleaned = deepcopy(payload)
    cleaned.pop("run_id", None)
    manifest = cleaned.get("manifest", {})
    manifest.pop("run_started_at", None)
    data = manifest.get("data", {})
    data.pop("fetched_at", None)
    source = data.get("source")
    if isinstance(source, dict):
        source.pop("path", None)
    return cleaned


def test_result_json_written_with_section_46_keys_only(tmp_path: Path) -> None:
    result = execute_run(_spec(), _bars(), data_source=DATA_SOURCE, now=NOW, runs_dir=tmp_path)
    path = tmp_path / result.run_id / "result.json"
    assert path.is_file(), path

    text = path.read_text(encoding="utf-8")
    payload = json.loads(text, parse_constant=_reject_constant)  # no NaN/Infinity
    assert set(payload) == PAYLOAD_KEYS
    assert "equity_curve" not in payload  # parquet is P5-T4b
    assert "trades" not in payload
    assert payload["data_quality_report"] is None
    assert '"data_quality_report": null' in text
    assert '"prompt_version": null' in text  # None -> JSON null
    assert "NaN" not in text and "Infinity" not in text


def test_run_id_format_is_timestamp_plus_logic_hash_suffix(tmp_path: Path) -> None:
    result = execute_run(_spec(), _bars(), now=NOW, runs_dir=tmp_path)
    assert re.fullmatch(r"2026-10-24T12-00-00Z_[0-9a-f]{6}", result.run_id), result.run_id


def test_determinism_after_dropping_volatile_keys(tmp_path: Path) -> None:
    first = execute_run(_spec(), _bars(), data_source=DATA_SOURCE, now=NOW, runs_dir=tmp_path / "a")
    second = execute_run(
        _spec(), _bars(), data_source=DATA_SOURCE, now=NOW_2, runs_dir=tmp_path / "b"
    )
    assert first.run_id != second.run_id  # timestamps differ
    p1 = json.loads((tmp_path / "a" / first.run_id / "result.json").read_text(encoding="utf-8"))
    p2 = json.loads((tmp_path / "b" / second.run_id / "result.json").read_text(encoding="utf-8"))
    assert json.dumps(_drop_volatile(p1), sort_keys=True) == json.dumps(
        _drop_volatile(p2), sort_keys=True
    )


def test_run_id_collision_never_overwrites(tmp_path: Path) -> None:
    first = execute_run(_spec(), _bars(), now=NOW, runs_dir=tmp_path)
    first_path = tmp_path / first.run_id / "result.json"
    first_bytes = first_path.read_bytes()

    second = execute_run(_spec(), _bars(), now=NOW, runs_dir=tmp_path)  # same now, same spec
    second_path = tmp_path / second.run_id / "result.json"

    assert second.run_id != first.run_id  # numeric suffix
    assert second.run_id == f"{first.run_id}_2"
    assert second_path.is_file()
    assert first_path.read_bytes() == first_bytes  # first directory untouched


def test_persist_false_writes_nothing(tmp_path: Path) -> None:
    target = tmp_path / "never"
    result = execute_run(_spec(), _bars(), now=NOW, runs_dir=target, persist=False)
    assert result.run_id  # still gets an id
    assert not target.exists()
    assert list(tmp_path.iterdir()) == []


def test_quality_report_present_when_meta_supplied(tmp_path: Path) -> None:
    meta = BarsMeta(
        provider="csv",
        symbol="TEST",
        interval="1d",
        adjusted=False,
        timezone="UTC",
        fetched_at=datetime(2026, 10, 24, 11, 0, tzinfo=UTC),
    )
    result = execute_run(_spec(), _bars(), meta=meta, now=NOW, runs_dir=tmp_path)
    path = tmp_path / result.run_id / "result.json"
    payload = json.loads(path.read_text(encoding="utf-8"), parse_constant=_reject_constant)
    report = payload["data_quality_report"]
    assert isinstance(report, dict)
    assert report["bars"] == 6
    assert isinstance(report["passed_blocking"], bool)
