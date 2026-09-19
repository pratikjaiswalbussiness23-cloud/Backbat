"""P1-T4 tests for CachedProvider.

Oracle policy (AGENTS.md/R6): the underlying provider is the REAL
``CSVProvider`` reading ``valid_daily.csv`` — only wrapped in a counting spy
that delegates every call. Nothing inside ``CachedProvider`` is mocked.

Canary: a test-local subclass with the hash check bypassed proves corrupted
data WOULD be served without the check — i.e. the hash gate does real work.
"""

from __future__ import annotations

import io
import json
import logging
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from nlbt.config import reset_config
from nlbt.data.cache import CachedProvider, cache_key
from nlbt.data.csv_provider import CSVProvider
from nlbt.data.models import Bars, BarsMeta
from nlbt.errors import DataProviderError

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "csv"
SYMBOL = str(FIXTURES / "valid_daily.csv")
RANGE: tuple[date, date] = (date(2024, 1, 1), date(2024, 12, 31))
ARGS = (*RANGE, "1d", False)


class CountingCSVProvider(CSVProvider):
    """Spy around the REAL provider: counts calls, delegates everything."""

    def __init__(self) -> None:
        super().__init__()
        self.call_count = 0

    def get_bars(self, symbol: str, start: date, end: date, interval: str, adjusted: bool):
        self.call_count += 1
        return super().get_bars(symbol, start, end, interval, adjusted)


@pytest.fixture(autouse=True)
def _fresh_config() -> None:
    """Each test starts with a config rebuilt from the (monkeypatched) env."""
    reset_config()


@pytest.fixture
def provider() -> CountingCSVProvider:
    return CountingCSVProvider()


# --------------------------------------------------------------------------
# 1-3: basic hit/miss behaviour
# --------------------------------------------------------------------------


def test_first_call_fetches_second_is_cache_hit(
    tmp_path: Path, provider: CountingCSVProvider
) -> None:
    cached = CachedProvider(provider, str(tmp_path))
    cached.get_bars(SYMBOL, *ARGS)
    assert provider.call_count == 1
    cached.get_bars(SYMBOL, *ARGS)
    assert provider.call_count == 1  # NOT 2 — served from cache


def test_cache_hit_returns_identical_dataframe(
    tmp_path: Path, provider: CountingCSVProvider
) -> None:
    cached = CachedProvider(provider, str(tmp_path))
    bars_1, _ = cached.get_bars(SYMBOL, *ARGS)
    bars_2, _ = cached.get_bars(SYMBOL, *ARGS)
    pd.testing.assert_frame_equal(bars_1, bars_2)


def test_cache_hit_meta_identical_except_source_notes(
    tmp_path: Path, provider: CountingCSVProvider
) -> None:
    cached = CachedProvider(provider, str(tmp_path))
    _bars_1, meta_fresh = cached.get_bars(SYMBOL, *ARGS)
    _bars_2, meta_cached = cached.get_bars(SYMBOL, *ARGS)
    assert "[from cache]" in meta_cached.source_notes
    assert "[from cache]" not in meta_fresh.source_notes
    fresh_fields = meta_fresh.model_dump()
    cached_fields = meta_cached.model_dump()
    assert cached_fields.pop("source_notes") == fresh_fields.pop("source_notes") + " [from cache]"
    assert cached_fields == fresh_fields


# --------------------------------------------------------------------------
# 4: cache key sensitivity
# --------------------------------------------------------------------------


VARIED_ARGS: dict[str, tuple] = {
    # Every variation must be a LOADABLE request (unsorted_dates.csv is valid
    # after sorting; missing_column.csv would raise in the provider).
    "symbol": (str(FIXTURES / "unsorted_dates.csv"), *RANGE, "1d", False),
    "interval": (SYMBOL, *RANGE, "1h", False),
    "adjusted": (SYMBOL, *RANGE, "1d", True),
    "start": (SYMBOL, date(2024, 1, 2), RANGE[1], "1d", False),
    "end": (SYMBOL, RANGE[0], date(2024, 6, 30), "1d", False),
}


@pytest.mark.parametrize("changed", ["symbol", "interval", "adjusted", "start", "end"])
def test_cache_key_changes_when_any_parameter_changes(
    tmp_path: Path,
    provider: CountingCSVProvider,
    changed: str,
) -> None:
    cached = CachedProvider(provider, str(tmp_path))
    cached.get_bars(SYMBOL, *ARGS)  # prime the baseline folder
    assert len(list(tmp_path.iterdir())) == 1
    baseline_key = cache_key("CountingCSVProvider", SYMBOL, ARGS[2], ARGS[3], ARGS[0], ARGS[1])

    specific = VARIED_ARGS[changed]
    cached.get_bars(*specific)  # must create a NEW folder and refetch
    assert provider.call_count == 2  # param change ⇒ cache miss
    assert len(list(tmp_path.iterdir())) == 2  # distinct folder per param set
    # specific layout: (symbol, start, end, interval, adjusted)
    varied_key = cache_key(
        "CountingCSVProvider", specific[0], specific[3], specific[4], specific[1], specific[2]
    )
    assert varied_key != baseline_key


def test_cache_key_format_is_sha256_of_canonical_string() -> None:
    import hashlib

    expected = hashlib.sha256(
        f"CSVProvider|{SYMBOL}|1d|False|2024-01-01|2024-12-31".encode()
    ).hexdigest()
    assert (
        cache_key("CSVProvider", SYMBOL, "1d", False, date(2024, 1, 1), date(2024, 12, 31))
        == expected
    )


# --------------------------------------------------------------------------
# 5-6: corruption detection and refetch
# --------------------------------------------------------------------------


def test_corrupted_parquet_detected_and_refetched(
    tmp_path: Path, provider: CountingCSVProvider, caplog: pytest.LogCaptureFixture
) -> None:
    cached = CachedProvider(provider, str(tmp_path))
    cached.get_bars(SYMBOL, *ARGS)
    key_dir = next(tmp_path.iterdir())
    (key_dir / "bars.parquet").write_bytes(b"garbage")

    with caplog.at_level(logging.WARNING, logger="nlbt.data.cache"):
        bars, _meta = cached.get_bars(SYMBOL, *ARGS)  # must NOT raise
    assert isinstance(bars, Bars)
    assert bars.shape == (10, 5)
    assert provider.call_count == 2  # refetched from provider
    assert any("corrupted" in record.message.lower() for record in caplog.records)
    # folder was rebuilt with a fresh valid cache
    assert (key_dir / "bars.parquet").read_bytes() != b"garbage"


def test_tampered_content_hash_triggers_refetch(
    tmp_path: Path, provider: CountingCSVProvider
) -> None:
    cached = CachedProvider(provider, str(tmp_path))
    cached.get_bars(SYMBOL, *ARGS)
    key_dir = next(tmp_path.iterdir())
    meta_path = key_dir / "meta.json"
    payload = json.loads(meta_path.read_text(encoding="utf-8"))
    payload["content_hash"] = "deadbeef"
    meta_path.write_text(json.dumps(payload), encoding="utf-8")

    bars, _meta = cached.get_bars(SYMBOL, *ARGS)  # must NOT raise
    assert isinstance(bars, Bars)
    assert provider.call_count == 2


# --------------------------------------------------------------------------
# 7-8: NLBT_OFFLINE mode
# --------------------------------------------------------------------------


def test_offline_cache_miss_raises_and_never_calls_provider(
    tmp_path: Path,
    provider: CountingCSVProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NLBT_OFFLINE", "true")
    reset_config()
    cached = CachedProvider(provider, str(tmp_path))
    with pytest.raises(DataProviderError) as excinfo:
        cached.get_bars(SYMBOL, *ARGS)
    assert "Offline" in excinfo.value.message
    assert excinfo.value.code == "E_DATA_PROVIDER"
    assert provider.call_count == 0  # never touched the provider


def test_offline_cache_hit_returns_normally(
    tmp_path: Path,
    provider: CountingCSVProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cached = CachedProvider(provider, str(tmp_path))
    cached.get_bars(SYMBOL, *ARGS)  # prime while online
    assert provider.call_count == 1

    monkeypatch.setenv("NLBT_OFFLINE", "true")
    reset_config()
    bars, _meta = cached.get_bars(SYMBOL, *ARGS)  # offline must not block reads
    assert isinstance(bars, Bars)
    assert provider.call_count == 1


# --------------------------------------------------------------------------
# 9-10: determinism and folder creation
# --------------------------------------------------------------------------


def test_two_independent_instances_write_byte_identical_parquet(tmp_path: Path) -> None:
    cache_a, cache_b = tmp_path / "a", tmp_path / "b"
    provider_a = CountingCSVProvider()
    provider_b = CountingCSVProvider()
    bars_a, _ = CachedProvider(provider_a, str(cache_a)).get_bars(SYMBOL, *ARGS)
    bars_b, _ = CachedProvider(provider_b, str(cache_b)).get_bars(SYMBOL, *ARGS)
    pd.testing.assert_frame_equal(bars_a, bars_b)
    blob_a = next(cache_a.glob("*/bars.parquet"))  # file lives inside the key folder
    blob_b = next(cache_b.glob("*/bars.parquet"))
    assert blob_a.read_bytes() == blob_b.read_bytes()
    # Same cache_dir: the second instance reuses the first one's file (1 folder, 1 fetch)
    shared = tmp_path / "shared"
    CachedProvider(CountingCSVProvider(), str(shared)).get_bars(SYMBOL, *ARGS)
    CachedProvider(CountingCSVProvider(), str(shared)).get_bars(SYMBOL, *ARGS)
    assert len(list(shared.iterdir())) == 1


def test_cache_dir_created_automatically(tmp_path: Path, provider: CountingCSVProvider) -> None:
    nested = tmp_path / "does" / "not" / "exist"
    assert not nested.exists()
    cached = CachedProvider(provider, str(nested))
    cached.get_bars(SYMBOL, *ARGS)
    assert nested.is_dir()
    assert len(list(nested.iterdir())) == 1  # one folder per cache key


# --------------------------------------------------------------------------
# CANARY: without the hash check, corruption comes straight back
# --------------------------------------------------------------------------


def test_canary_without_hash_check_corruption_is_served(
    tmp_path: Path, provider: CountingCSVProvider
) -> None:
    class NoHashCheckProvider(CachedProvider):
        """Test-local mutant: hash verification bypassed (the thing the canary exists for)."""

        def _read_cache(self, key_dir: Path, key: str) -> tuple[Bars, BarsMeta] | None:
            parquet_bytes = (key_dir / "bars.parquet").read_bytes()
            payload = json.loads((key_dir / "meta.json").read_text(encoding="utf-8"))
            payload.pop("content_hash")
            meta = BarsMeta.model_validate(payload)
            frame = pd.read_parquet(io.BytesIO(parquet_bytes))
            return Bars(frame), meta

    cache_dir = tmp_path / "canary"
    victim = NoHashCheckProvider(provider, str(cache_dir))
    victim.get_bars(SYMBOL, *ARGS)
    assert provider.call_count == 1

    # Tamper with VALID parquet (garbage would fail both paths equally):
    # double every close price inside the cached file.
    key_dir = next(cache_dir.iterdir())
    frame = pd.read_parquet(io.BytesIO((key_dir / "bars.parquet").read_bytes()))
    honest_close = float(frame["close"].iloc[0])
    frame["close"] = frame["close"] * 2
    (key_dir / "bars.parquet").write_bytes(frame.to_parquet())  # type: ignore[arg-type] # to_parquet() returns bytes here

    mutant_bars, _meta = victim.get_bars(SYMBOL, *ARGS)  # hash check bypassed
    assert provider.call_count == 1  # served from the corrupted cache
    assert float(mutant_bars["close"].iloc[0]) == pytest.approx(honest_close * 2)  # TAMPERED DATA

    guard = CachedProvider(provider, str(cache_dir))  # real implementation
    real_bars, _meta = guard.get_bars(SYMBOL, *ARGS)  # detects, refetches
    assert provider.call_count == 2
    assert float(real_bars["close"].iloc[0]) == pytest.approx(honest_close)  # honest data
