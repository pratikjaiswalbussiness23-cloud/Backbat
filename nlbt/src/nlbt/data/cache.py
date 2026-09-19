"""Parquet cache wrapper around any DataProvider (P1-T4).

Layout: one folder per cache key under ``cache_dir`` containing
``bars.parquet`` (the Bars frame) and ``meta.json`` (BarsMeta fields plus a
``content_hash`` = sha256 of the exact parquet bytes stored).

The hash check is the corruption gate: if the parquet bytes on disk no longer
match the stored ``content_hash``, the folder is treated as corrupted, a
warning is logged, the folder is deleted and the data is refetched from the
underlying provider (see the canary test proving the check is load-bearing).
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import shutil
from datetime import date
from pathlib import Path

import pandas as pd

from nlbt.config import get_config
from nlbt.data.models import Bars, BarsMeta, DataProvider
from nlbt.errors import DataProviderError

__all__ = ["CachedProvider", "cache_key"]

_BARS_FILE = "bars.parquet"
_META_FILE = "meta.json"

logger = logging.getLogger(__name__)


def cache_key(
    provider_name: str,
    symbol: str,
    interval: str,
    adjusted: bool,
    start: date,
    end: date,
) -> str:
    """sha256 hex digest of the canonical P1-T4 key string.

    Format (exact, per task)::

        "{provider_name}|{symbol}|{interval}|{adjusted}|{start}|{end}"

    with ``start``/``end`` as ISO date strings, hashed as UTF-8.
    """
    canonical = (
        f"{provider_name}|{symbol}|{interval}|{adjusted}|{start.isoformat()}|{end.isoformat()}"
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class CachedProvider:
    """Transparent parquet cache in front of any :class:`DataProvider`."""

    def __init__(self, provider: DataProvider, cache_dir: str) -> None:
        self.provider = provider
        self.cache_dir = Path(cache_dir)

    def get_bars(
        self,
        symbol: str,
        start: date,
        end: date,
        interval: str,
        adjusted: bool,
    ) -> tuple[Bars, BarsMeta]:
        """Return bars for ``symbol`` via the cache (write-through on miss).

        Read path: miss → fetch + store; corrupt (hash mismatch or unreadable
        parquet) → warn + delete folder + refetch; hit → serve from cache.
        ``NLBT_OFFLINE`` blocks the underlying fetch on a miss (``E_DATA_PROVIDER``)
        but never blocks cache reads.
        """
        key = cache_key(
            type(self.provider).__name__,
            symbol,
            interval,
            adjusted,
            start,
            end,
        )
        key_dir = self.cache_dir / key

        if key_dir.exists():
            cached = self._read_cache(key_dir, key)
            if cached is not None:
                bars, meta = cached
                meta = meta.model_copy(update={"source_notes": f"{meta.source_notes} [from cache]"})
                return bars, meta
            # corrupted → fall through to a fresh fetch below

        if get_config().offline:
            raise DataProviderError(
                f"Offline mode: no cached data for {symbol}",
                details={
                    "symbol": symbol,
                    "start": str(start),
                    "end": str(end),
                    "interval": interval,
                    "cache_key": key,
                },
            )

        bars, meta = self.provider.get_bars(symbol, start, end, interval, adjusted)
        self._write_cache(key_dir, bars, meta)
        return bars, meta

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _read_cache(self, key_dir: Path, key: str) -> tuple[Bars, BarsMeta] | None:
        """Return cached data, or ``None`` when the folder is corrupted.

        Corruption = hash mismatch OR unreadable/missing files; either way the
        folder is deleted (best effort) so the caller refetches.
        """
        parquet_path = key_dir / _BARS_FILE
        meta_path = key_dir / _META_FILE
        try:
            parquet_bytes = parquet_path.read_bytes()
            computed_hash = hashlib.sha256(parquet_bytes).hexdigest()
            meta_payload = json.loads(meta_path.read_text(encoding="utf-8"))
            stored_hash = meta_payload.pop("content_hash")
            meta = BarsMeta.model_validate(meta_payload)
            if computed_hash != stored_hash:
                self._handle_corruption(
                    key_dir,
                    key,
                    f"content hash mismatch (stored {stored_hash[:12]}…, "
                    f"computed {computed_hash[:12]}…)",
                )
                return None
            frame = pd.read_parquet(io.BytesIO(parquet_bytes))
        except FileNotFoundError as exc:
            self._handle_corruption(key_dir, key, f"missing cache file: {exc.filename}")
            return None
        except (json.JSONDecodeError, ValueError, OSError) as exc:
            # unreadable json, unreadable parquet (pyarrow errors), unreadable bytes
            self._handle_corruption(key_dir, key, f"unreadable cache data: {type(exc).__name__}")
            return None
        if not isinstance(frame.index, pd.DatetimeIndex):
            self._handle_corruption(key_dir, key, "cached frame index is not a DatetimeIndex")
            return None
        return Bars(frame), meta

    def _handle_corruption(self, key_dir: Path, key: str, reason: str) -> None:
        """Log a warning and delete the corrupted folder (best effort)."""
        logger.warning(
            "Cache corrupted for key %s (%s); deleting folder and refetching",
            key[:12],
            reason,
        )
        shutil.rmtree(key_dir, ignore_errors=True)

    def _write_cache(self, key_dir: Path, bars: Bars, meta: BarsMeta) -> None:
        """Store parquet + meta with the content hash of the written bytes."""
        key_dir.mkdir(parents=True, exist_ok=True)
        # Stub overloads infer plain bytes when path is omitted (mypy-verified).
        parquet_bytes: bytes = bars.to_parquet()
        (key_dir / _BARS_FILE).write_bytes(parquet_bytes)
        payload = {
            **meta.model_dump(mode="json"),
            "content_hash": hashlib.sha256(parquet_bytes).hexdigest(),
        }
        (key_dir / _META_FILE).write_text(json.dumps(payload, indent=2), encoding="utf-8")
