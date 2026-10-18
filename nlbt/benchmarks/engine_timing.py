"""P4-T12 engine performance benchmark (ROADMAP P4-T12).

Runs ``nlbt.engine.backtest.run`` on SYNTHETIC daily OHLCV at two sizes:
~2,500 bars (~10 years) and ~100,000 bars (stress test), using a simple
SMA-crossover spec. Wall-clock time via ``time.perf_counter``; trade count
and final equity printed as proof the run did real work. Fixed seed,
no network calls.

ROADMAP P4-T12 target (quoted verbatim): "benchmark script prints timings
for e.g. 10 years and 100,000 daily-equivalent bars (initial target:
single-symbol daily backtest completes in well under a second; owner may
adjust)."

Usage (from nlbt/):
    uv run python benchmarks/engine_timing.py
"""

from __future__ import annotations

import platform
import time
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from nlbt.data.models import Bars
from nlbt.engine.backtest import run
from nlbt.spec.models import StrategySpec

SEED = 42
SIZES: tuple[int, ...] = (2_500, 100_000)
FAST_PERIOD = 10
SLOW_PERIOD = 30
CAPITAL = 100_000.0


def make_bars(n: int, seed: int = SEED) -> Bars:
    """Seeded synthetic daily bars: random-walk closes, valid OHLC by construction.

    Validity (asserted below, so a bad generator fails loudly):
        low <= min(open, close) <= max(open, close) <= high, every price > 0.
    open[0] = close[0]; open[t] = close[t-1] (gap-free opens).
    """
    rng = np.random.default_rng(seed)
    close = 100.0 * np.cumprod(1.0 + rng.normal(0.0003, 0.012, size=n))
    open_ = np.empty(n)
    open_[0] = close[0]
    open_[1:] = close[:-1]
    wiggle = rng.uniform(0.0005, 0.006, size=n)
    high = np.maximum(open_, close) * (1.0 + wiggle)
    low = np.minimum(open_, close) * (1.0 - wiggle)
    volume = rng.integers(1_000, 100_000, size=n).astype(float)

    min_oc = np.minimum(open_, close)
    max_oc = np.maximum(open_, close)
    assert (low > 0).all(), "every price must be > 0"
    assert (low <= min_oc).all(), "low must be <= min(open, close)"
    assert (max_oc <= high).all(), "max(open, close) must be <= high"

    idx = pd.date_range("2000-01-01", periods=n, freq="D", tz="UTC")
    frame = pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=idx,
    )
    return Bars(frame)


def make_spec() -> StrategySpec:
    """Simple SMA-crossover spec in the §4.1 shape (no risk exits)."""
    return StrategySpec.model_validate(
        {
            "spec_version": "1.0",
            "name": "benchmark sma cross",
            "universe": {"symbols": ["BENCH"], "interval": "1d"},
            "period": {"start": "2000-01-01", "end": "2026-10-18"},
            "indicators": {
                "fast": {"type": "sma", "params": {"period": FAST_PERIOD}, "source": "close"},
                "slow": {"type": "sma", "params": {"period": SLOW_PERIOD}, "source": "close"},
            },
            "rules": {
                "entry_long": {"all": [{"left": "fast", "op": "crosses_above", "right": "slow"}]},
                "exit_long": {"all": [{"left": "fast", "op": "crosses_below", "right": "slow"}]},
            },
            "risk": {},
            "sizing": {"method": "percent_of_equity", "value": 100, "allow_fractional": True},
            "execution": {"fill": "next_open", "fee_bps": 5, "slippage_bps": 5, "fixed_fee": 0},
            "capital": {"initial": CAPITAL},
        }
    )


def bench(n: int) -> None:
    """Time one ``run()`` of n bars; print duration, throughput, trades, equity."""
    bars = make_bars(n)
    spec = make_spec()
    t0 = time.perf_counter()
    result = run(spec, bars)
    dt = time.perf_counter() - t0
    final_equity = float(result.equity_curve["equity"].iloc[-1])
    print(
        f"bars={n:<7d} time={dt:.3f} s  ({n / dt:,.0f} bars/s)  "
        f"trades={len(result.trades):<5d} final_equity={final_equity:.2f}  "
        f"warnings={len(result.warnings)}"
    )


def main() -> None:
    print("nlbt engine benchmark - ROADMAP P4-T12")
    print(f"date (UTC): {datetime.now(UTC).isoformat(timespec='seconds')}")
    print(f"Python:     {platform.python_version()}")
    print(f"platform:   {platform.platform()}")
    print(
        f"seed: {SEED}  spec: SMA cross {FAST_PERIOD}/{SLOW_PERIOD}  "
        f"capital: {CAPITAL:.0f}  costs: 5bps fee / 5bps slippage"
    )
    print("OHLC validity: asserted in make_bars (low<=min(o,c)<=max(o,c)<=high, all > 0)")
    for n in SIZES:
        bench(n)


if __name__ == "__main__":
    main()
