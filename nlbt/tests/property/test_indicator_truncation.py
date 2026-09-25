"""P2-T7: truncation-invariance property tests (ROADMAP §P2-T7, marker `lookahead`).

For random OHLCV series and random VALID indicator params, every indicator's
output computed on ``bars[:n]`` must be IDENTICAL on the first ``n`` rows to
the output computed on ``bars[:n+k]`` (k >= 1) — NaN-aware (NaN == NaN). Any
difference means the indicator reads data beyond bar ``n``: lookahead bias
(§4.5 "Signals on data ≤ t"; defence table row → P2-T7).

Every hypothesis test here uses ``@pytest.mark.lookahead`` and
``@settings(max_examples=100)`` (PR-CI budget per the task text; nightly can
raise it via ``--hypothesis-profile`` or by editing the constant). Windows
overhead makes per-example runtimes jittery, so ``deadline=None`` replaces the
library's 200 ms default deadline (flakiness guard, NOT a reduced workload —
``max_examples`` still forces 100 distinct generated series per test).

No indicator logic lives in this file — only the canary (a deliberately leaky
SMA, defined in-test so a future kernel change can never silently fix it) and
the comparison harness. If hypothesis finds a counterexample it is a REAL bug
(AGENTS.md): stop, document in docs/OPEN_QUESTIONS.md, do not suppress.

Draw order matters for VALIDITY: params are drawn FIRST, then the bars length
is floored at ``max(task_floor, warmup + 4)`` so the split range
``[warmup + 2, len - 2]`` and the tail room ``k ∈ [1, len - n]`` are never
empty (an inverted range raises ``InvalidArgument`` and burns the example
budget — the first run of this file failed exactly that way on MACD, whose
warmup = slow + signal - 2 can exceed any fixed bar floor). ``k`` is drawn
AFTER ``n`` and capped by the remaining tail, so ``n + k <= len`` always.

The two-vector shared-Bars construction is pinned by ``test_bars_construction``
and the 12-way wiring table by ``test_registry_and_wiring_parity`` (two
structural tests beyond the task's 13 — both also marked ``lookahead``, since
EVERY test in this file carries the marker per the task text). The kernels
only read the five OHLCV columns, so one Bars instance per (prices, volumes)
draw is elementwise-equal to building Bars from the prefix — truncation then
exactly equals "compute on bars[:n]".

The canary's leak detection is proved POSITIVE and NEGATIVE under the exact
task fixture (prices 1..30, n=15, k=5, period=5): the leak is real numeric
divergence at positions 13/14 (``test_canary_divergence_is_real``) and
one-sided NaN masking cannot smuggle it past the comparison
(``test_canary_nan_masking_is_not_fooled``) — the comparison is sign-directed
(AGENTS.md: never weaken the test to pass).

Verified on hypothesis 6.168.1 (docs/verified_apis.md, 2026-09-25):
``st.data()`` with bounds derived from earlier draws; ``st.floats(lo, hi,
allow_nan=False)``; bounded ``st.floats`` does not emit NaN on this install
(probe ran NaN-free), the flag is defence-in-depth; ``deadline=None`` accepted
in ``@settings``; ``Bars.iloc[:n]`` keeps the subclass and UTC tz.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import datetime
from typing import Any

import hypothesis.strategies as st
import numpy as np
import pandas as pd
import pytest
from hypothesis import HealthCheck, given, settings

from nlbt.data.models import Bars
from nlbt.indicators.registry import REGISTRY, IndicatorSpec

#: Task-mandated budget for PR CI (nightly may raise; see module docstring).
MAX_EXAMPLES = 100

#: Tolerance for the truncation comparison (task text: 1e-10).
TOL = 1e-10

# ===========================================================================
# Bars construction (task helper 1) — TWO-VECTOR design.
#
# One Bars instance is built from the FULL vectors; truncation is `iloc[:n]`
# on that instance. Each column is an arithmetic expression of open/closes,
# so a column expression evaluated on the full vector is elementwise-equal to
# the same expression evaluated on the prefix — hence bars_full.iloc[:n] ==
# bars_short for every column (PROVEN for the actual frames by
# test_bars_construction below). The kernels only read these five columns, so
# "compute on the sliced frame" == "compute on the full frame's prefix".
# ===========================================================================

_COL_EXPR: dict[str, Callable[[list[float], list[float]], np.ndarray]] = {
    "open": lambda closes, _v: np.array([closes[0], *closes[:-1]], dtype=float),
    "high": lambda closes, _v: (
        np.maximum(closes, np.array([closes[0], *closes[:-1]])) * (1.0 + 0.01)
    ),
    "low": lambda closes, _v: (
        np.minimum(closes, np.array([closes[0], *closes[:-1]])) * (1.0 - 0.01)
    ),
    "close": lambda closes, _v: np.asarray(closes, dtype=float),
    "volume": lambda _closes, vols: np.asarray(vols, dtype=float),
}


def make_ohlcv_bars(n: int, seed_prices: list[float], seed_volumes: list[float]) -> Bars:
    """Build a validated-shape OHLCV frame from seed prices/volumes.

    Task structure (close = seed, open = close shifted by 1 with first open =
    close[0]; high/low = ±1% of the larger/smaller of close/prev-close;
    positive volumes; DatetimeIndex 2020-01-01, daily, UTC) expressed as
    per-column expressions over the two vectors, so column values depend only
    on the corresponding slice of the input vectors (prefix-stability).
    Returns a :class:`Bars` (validated shape: lowercase OHLCV columns, sorted
    unique tz-aware UTC DatetimeIndex, float64, high >= low > 0).
    """
    closes = [float(p) for p in seed_prices]
    volumes = [float(v) for v in seed_volumes]
    if len(closes) != n or len(volumes) != n:
        raise ValueError(f"seed vectors must both have length n={n}")

    idx = pd.date_range(datetime(2020, 1, 1), periods=n, freq="D", tz="UTC")
    data = {col: expr(closes, volumes) for col, expr in _COL_EXPR.items()}
    bars = Bars(data, index=idx)
    if not (bars["high"] >= bars["low"]).all():
        raise ValueError("make_ohlcv_bars produced high < low (internal logic error)")
    return bars


# ===========================================================================
# Hypothesis strategies (task helper 2) — one params strategy per indicator.
# Bounds are COPIES of the registration bounds in src/ (verified 2026-09-25,
# docs/verified_apis.md); the registry remains the single source of truth —
# if the two drift, _draw_params violates and the test fails at draw time.
# Upper bounds are tightened vs the registry ONLY where the registry maximum
# would force absurd bar counts (documented per strategy); every draw here is
# in-bounds for the registry, i.e. "random valid params" per the task.
# ===========================================================================

_volume = st.floats(1.0, 100_000.0, allow_nan=False, allow_infinity=False)

_period_2_30 = st.integers(2, 30)
_period_2_200 = st.integers(2, 200)
_period_1_500 = st.integers(1, 500)


@st.composite
def valid_prices(draw: st.DrawFn, min_bars: int = 50, max_bars: int = 150) -> list[float]:
    """Random positive-walk price vector of n in [min_bars, max_bars] bars.

    Task template: n random, start price random in [10, 1000], daily changes
    in ±5%. max(0.01, ·) floors the walk above zero; a floor reset biases
    upward steps slightly (a valid distributional quirk, not a bias the
    truncation property could exploit). NaN-free by construction
    (st.floats(..., allow_nan=False) — verified on 6.168.1).
    """
    n = draw(st.integers(min_bars, max_bars))
    start = draw(st.floats(10.0, 1000.0, allow_nan=False))
    changes = draw(
        st.lists(st.floats(-0.05, 0.05, allow_nan=False), min_size=n - 1, max_size=n - 1)
    )
    prices = [start]
    for change in changes:
        prices.append(max(0.01, prices[-1] * (1.0 + change)))
    return prices


@st.composite
def valid_sma_params(draw: st.DrawFn) -> dict[str, int]:
    """sma period ∈ [2, 30] (registry [2, 500]; 30 keeps runtimes sane)."""
    return {"period": draw(_period_2_30)}


@st.composite
def valid_ema_params(draw: st.DrawFn) -> dict[str, int]:
    """ema period ∈ [2, 30] (registry [2, 500])."""
    return {"period": draw(_period_2_30)}


@st.composite
def valid_rsi_params(draw: st.DrawFn) -> dict[str, int]:
    """rsi period ∈ [2, 30] (registry [2, 100]; warmup = period)."""
    return {"period": draw(_period_2_30)}


@st.composite
def valid_roc_params(draw: st.DrawFn) -> dict[str, int]:
    """roc period ∈ [1, 30] (registry [1, 500]; warmup = period)."""
    return {"period": draw(st.integers(1, 30))}


@st.composite
def valid_macd_params(draw: st.DrawFn) -> dict[str, int]:
    """macd fast/slow/signal — full registry bounds [2, 200] each.

    Includes fast >= slow draws (individual bounds only; OQ-0021 explicitly
    leaves cross-param constraints undecided) — a pure-recursion indicator
    stays truncation-safe for every in-bounds draw, which is exactly the
    property under test. Bars are sized from the drawn warmup (slow+signal-2
    can reach 398), so no bound tightening is needed here.
    """
    return {
        "fast": draw(_period_2_200),
        "slow": draw(_period_2_200),
        "signal": draw(_period_2_200),
    }


@st.composite
def valid_bbands_params(draw: st.DrawFn) -> dict[str, float | int]:
    """bbands period ∈ [2, 100] (registry [2, 500]), k ∈ [0.1, 10.0]."""
    return {
        "period": draw(st.integers(2, 100)),
        "k": draw(st.floats(0.1, 10.0, allow_nan=False, allow_infinity=False)),
    }


@st.composite
def valid_atr_params(draw: st.DrawFn) -> dict[str, int]:
    """atr period ∈ [2, 30] (registry [2, 100]; warmup = period)."""
    return {"period": draw(_period_2_30)}


@st.composite
def valid_stoch_params(draw: st.DrawFn) -> dict[str, int]:
    """stoch k_period/d_period ∈ [2, 30], smooth_period ∈ [1, 10]."""
    return {
        "k_period": draw(_period_2_30),
        "d_period": draw(_period_2_30),
        "smooth_period": draw(st.integers(1, 10)),
    }


@st.composite
def valid_adx_params(draw: st.DrawFn) -> dict[str, int]:
    """adx period ∈ [2, 30] (registry [2, 100]; warmup = 2·period - 1)."""
    return {"period": draw(_period_2_30)}


@st.composite
def valid_highest_params(draw: st.DrawFn) -> dict[str, int]:
    """highest period ∈ [2, 60] (registry [2, 500]; warmup = period)."""
    return {"period": draw(st.integers(2, 60))}


@st.composite
def valid_lowest_params(draw: st.DrawFn) -> dict[str, int]:
    """lowest period ∈ [2, 60] (registry [2, 500]; warmup = period)."""
    return {"period": draw(st.integers(2, 60))}


def valid_obv_params(_draw: st.DrawFn | None = None) -> dict[str, Any]:
    """obv takes NO parameters (registration has params={}).

    Plain function (nothing to draw) — returns the empty params dict
    DIRECTLY (not a strategy), which _draw_params uses as-is so the wiring
    interface stays uniform across all 12 indicators.
    """
    return {}


# ===========================================================================
# Per-indicator wiring: params strategy + bars-length floor + source column.
#
# Keys == exactly the 12 names in REGISTRY.list_indicators()
# (['adx','atr','bbands','ema','highest','lowest','macd','obv','roc','rsi',
#   'sma','stoch'] — recorded in docs/verified_apis.md). A future indicator
# registered without a wiring row fails test_registry_and_wiring_parity.
# The floors are the task's minimums (MACD 60, ADX 80, else 50); the ACTUAL
# bars length is max(floor, warmup + 4) per draw — see module docstring.
# ===========================================================================

_WIRING: dict[str, tuple[Callable[[st.DrawFn], dict[str, Any]], int, str]] = {
    "sma": (valid_sma_params, 50, "close"),
    "ema": (valid_ema_params, 50, "close"),
    "rsi": (valid_rsi_params, 50, "close"),
    "roc": (valid_roc_params, 50, "close"),
    "macd": (valid_macd_params, 60, "close"),
    "bbands": (valid_bbands_params, 50, "close"),
    "atr": (valid_atr_params, 50, "close"),
    "stoch": (valid_stoch_params, 50, "close"),
    "adx": (valid_adx_params, 80, "close"),
    "highest": (valid_highest_params, 50, "high"),
    "lowest": (valid_lowest_params, 50, "low"),
    "obv": (valid_obv_params, 50, "close"),
}


def _draw_params(name: str, data: st.data, strategy: Callable[[st.DrawFn], Any]) -> dict[str, Any]:
    """Draw params and gate them through the REAL registry gate.

    ``strategy`` is a ``@st.composite`` factory — CALLING it returns the
    SearchStrategy to draw (passing the function object itself to
    ``data.draw`` raises ``InvalidArgument``, caught by the first run of this
    file) — or, for the parameterless obv, a plain function returning the
    empty params dict, which is used directly.
    ``validate_indicator_params`` is the production parameter gate (§4.3): it
    fills defaults, rejects unknown params / non-numeric / non-finite / bool
    / out-of-bound values with E_SPEC_RANGE. Gating here proves the property
    test exercises only params the spec layer would accept.
    """
    from nlbt.indicators.registry import validate_indicator_params

    drawn = strategy()
    if isinstance(drawn, st.SearchStrategy):
        drawn = data.draw(drawn)
    return validate_indicator_params(name, drawn)


def _assert_truncation_equal(short_col: pd.Series, long_col: pd.Series, n: int, label: str) -> None:
    """NaN-aware equality of the first n rows (task helper, row-wise form).

    NaN at the same position counts as EQUAL (a truncated series legitimately
    has warmup NaN the long series may not have — those must not mask a real
    leak on other positions, which the canary's masking guard pins). Any
    finite difference beyond TOL fails with the exact position and values.
    """
    assert len(short_col) >= n and len(long_col) >= n, f"{label}: expected at least {n} rows"
    for i in range(n):
        s = short_col.iloc[i]
        long_i = long_col.iloc[i]
        both_nan = math.isnan(s) and math.isnan(long_i)
        if not both_nan:
            assert abs(s - long_i) < TOL, (
                f"Truncation mismatch in column {label!r} at index {i}: short={s}, long={long_i}"
            )


def _warmup_floor(name: str, params: dict[str, Any]) -> int:
    """The registry's warmup for this draw — the floor for the split point.

    Uses warmup_fn from the registry itself (no duplication of warmup logic).
    """
    return REGISTRY.get(name).warmup_fn(params)


def _hypothesis_settings() -> settings:
    """Shared hypothesis profile: max_examples=MAX_EXAMPLES, no deadline.

    deadline=None: pandas kernels can exceed the 200 ms default on slower
    machines → flaky failures that are NOT property violations. The workload
    is defined by max_examples (100 distinct series per test), not the clock.
    """
    return settings(
        max_examples=MAX_EXAMPLES,
        deadline=None,
        suppress_health_check=[HealthCheck.data_too_large, HealthCheck.filter_too_much],
    )


def _assert_truncation_invariance(
    bars: Bars, spec: IndicatorSpec, params: dict[str, Any], n: int, k: int, source: str
) -> None:
    """Run the P2-T7 truncation comparison for one (bars, params, n, k) draw.

    Exactly the task's steps 4-6: compute on bars[:n] and bars[:n+k] (k >= 1,
    random per draw) and require identical first-n rows on EVERY output
    column, NaN-aware.
    """
    bars_short = bars.iloc[:n]
    bars_long = bars.iloc[: n + k]
    assert len(bars_short) == n and len(bars_long) == n + k

    result_short = spec.compute_fn(bars_short, params, source)
    result_long = spec.compute_fn(bars_long, params, source)
    assert list(result_short.columns) == list(spec.outputs)
    assert list(result_long.columns) == list(spec.outputs)

    for col in spec.outputs:
        _assert_truncation_equal(result_short[col], result_long[col], n, col)


def _run_truncation_case(name: str, data: st.data) -> None:
    """Shared body of the 12 truncation tests (task structure, steps 1-6).

    Draw order (see module docstring): params → warmup → bars length floored
    at max(task floor, warmup + 4) → split n ∈ [warmup + 2, len - 2] →
    k ∈ [1, len - n] (so n + k <= len). Bars are built ONCE from the full
    vectors and sliced (prefix-stable construction, pinned by
    test_bars_construction).
    """
    strategy, bars_floor, source = _WIRING[name]
    params = _draw_params(name, data, strategy)
    warmup = _warmup_floor(name, params)

    floor = max(bars_floor, warmup + 4)  # warmup+2 for n, +2 more for k headroom
    prices = data.draw(valid_prices(min_bars=floor, max_bars=floor + 100))
    volumes = data.draw(_volume)

    n = data.draw(st.integers(warmup + 2, len(prices) - 2))
    k = data.draw(st.integers(1, len(prices) - n))

    bars = make_ohlcv_bars(len(prices), prices, [volumes] * len(prices))
    _assert_truncation_invariance(bars, REGISTRY.get(name), params, n, k, source)


# ===========================================================================
# Structural sanity (both marked lookahead: EVERY test here carries it).
# ===========================================================================


@pytest.mark.lookahead
def test_bars_construction() -> None:
    """One full-frame Bars == a per-slice Bars for every column, at any split.

    The kernels read only the five OHLCV columns; the helper builds each
    column as an expression of the full close/volume vectors, so slicing the
    frame must equal building the frame from the slice (a construction bug
    would fake truncation-invariance, hence this pinned sanity test — one of
    two structural tests beyond the task's 13; the other is wiring parity).
    """
    prices = [11.0, 12.0, 10.5, 13.0, 12.5, 14.0, 13.5, 15.0]
    volumes = [100.0, 200.0, 150.0, 300.0, 120.0, 80.0, 210.0, 90.0]
    for split in (1, 4, 7, len(prices)):
        bars_full = make_ohlcv_bars(len(prices), prices, volumes)
        bars_short = make_ohlcv_bars(split, prices[:split], volumes[:split])
        for col in ("open", "high", "low", "close", "volume"):
            assert np.array_equal(bars_full[col].to_numpy()[:split], bars_short[col].to_numpy()), (
                col,
                split,
            )


@pytest.mark.lookahead
def test_registry_and_wiring_parity() -> None:
    """The wiring table covers EXACTLY the registry's indicator names.

    Guards both directions: a newly registered indicator without a wiring row
    fails here (with its name), and a wiring row for a de-registered name
    fails too. Keeps the 12 truncation tests exhaustively mapped.
    """
    registered = set(REGISTRY.list_indicators())
    wired = set(_WIRING)
    assert registered == wired, (
        f"unwired indicators: {sorted(registered - wired)}; "
        f"stale wiring rows: {sorted(wired - registered)}"
    )


# ===========================================================================
# The 12 truncation property tests (task list, one per indicator).
# All marked @pytest.mark.lookahead; shared profile: 100 examples, no deadline.
# ===========================================================================


@pytest.mark.lookahead
@_hypothesis_settings()
@given(data=st.data())
def test_truncation_sma(data: st.data) -> None:
    """sma: warmup = period - 1 (registry); random split and k ≥ 1."""
    _run_truncation_case("sma", data)


@pytest.mark.lookahead
@_hypothesis_settings()
@given(data=st.data())
def test_truncation_ema(data: st.data) -> None:
    """ema: warmup = period - 1 (registry); ADR-0002 SMA-seeded recursion."""
    _run_truncation_case("ema", data)


@pytest.mark.lookahead
@_hypothesis_settings()
@given(data=st.data())
def test_truncation_rsi(data: st.data) -> None:
    """rsi: warmup = period (registry); Wilder gain/loss smoothing ADR-0003."""
    _run_truncation_case("rsi", data)


@pytest.mark.lookahead
@_hypothesis_settings()
@given(data=st.data())
def test_truncation_roc(data: st.data) -> None:
    """roc: warmup = period (registry); (p[t]/p[t-period] - 1)·100."""
    _run_truncation_case("roc", data)


@pytest.mark.lookahead
@_hypothesis_settings()
@given(data=st.data())
def test_truncation_macd(data: st.data) -> None:
    """macd: warmup = slow + signal - 2; task floor min_bars=60 (warmup may
    push the actual length higher — slow/signal span the full [2, 200])."""
    _run_truncation_case("macd", data)


@pytest.mark.lookahead
@_hypothesis_settings()
@given(data=st.data())
def test_truncation_bbands(data: st.data) -> None:
    """bbands: warmup = period - 1 (registry); ddof=1 per ADR-0004."""
    _run_truncation_case("bbands", data)


@pytest.mark.lookahead
@_hypothesis_settings()
@given(data=st.data())
def test_truncation_atr(data: st.data) -> None:
    """atr: warmup = period (registry); reads high/low/close directly."""
    _run_truncation_case("atr", data)


@pytest.mark.lookahead
@_hypothesis_settings()
@given(data=st.data())
def test_truncation_stoch(data: st.data) -> None:
    """stoch: warmup = k-1 + smooth-1 + d-1 (registry); reads high/low/close."""
    _run_truncation_case("stoch", data)


@pytest.mark.lookahead
@_hypothesis_settings()
@given(data=st.data())
def test_truncation_adx(data: st.data) -> None:
    """adx: warmup = 2·period - 1 (OQ-0022); task floor min_bars=80."""
    _run_truncation_case("adx", data)


@pytest.mark.lookahead
@_hypothesis_settings()
@given(data=st.data())
def test_truncation_highest(data: st.data) -> None:
    """highest: warmup = period (registry); max over PREVIOUS period bars."""
    _run_truncation_case("highest", data)


@pytest.mark.lookahead
@_hypothesis_settings()
@given(data=st.data())
def test_truncation_lowest(data: st.data) -> None:
    """lowest: warmup = period (registry); min over PREVIOUS period bars."""
    _run_truncation_case("lowest", data)


@pytest.mark.lookahead
@_hypothesis_settings()
@given(data=st.data())
def test_truncation_obv(data: st.data) -> None:
    """obv: warmup = 0 (registry); classic Wilder OBV, neutral on flats."""
    _run_truncation_case("obv", data)


# ===========================================================================
# CANARY (task test 13): a deliberately leaky indicator MUST be caught.
#
# NOT a hypothesis test — deterministic, on the exact task fixture
# (prices = 1..30, n = 15, k = 5, period = 5). The leak is a CENTERED window:
#   leaky[i] = mean(prices[i - period//2 : i + period//2 + 1])
# i.e. mean of prices i-2 .. i+2 for period=5. Causal-looking (it is an SMA),
# but each output reads TWO FUTURE prices. Divergence appears on the last
# full centered windows: at i = 13 and i = 14 the short frame has NO bars
# beyond index 14, so pandas' centered+min_periods=5 window yields NaN there,
# while the long frame (bars[:20]) has real values. NaN-aware equality must
# FAIL there — proved positive (divergence is real) and negative (one-sided
# NaN masking cannot sneak through the comparison) below.
# ===========================================================================


def _leaky_sma(bars: Bars, period: int) -> pd.Series:
    """CENTERED-window SMA — DELIBERATE LOOKAHEAD (canary only).

    result[i] = mean(prices[i - period//2 : i + period//2 + 1]) via pandas'
    center=True (min_periods=period keeps windows full, so positions whose
    window runs past the END of the frame are NaN — that NaN asymmetry is
    itself a symptom of the leak). This mirrors the kernel style of the real
    indicators (rolling on bars[source]) so the canary proves the HARNESS
    catches a realistic leak, not a strawman.
    """
    return bars["close"].rolling(window=period, center=True, min_periods=period).mean()


def _canary_frame() -> Bars:
    """Task's canary fixture: closes 1..30 over 2020-01-01, daily UTC."""
    return make_ohlcv_bars(30, [float(i) for i in range(1, 31)], [100.0] * 30)


@pytest.mark.lookahead
def test_canary_leaky_indicator_is_caught() -> None:
    """The truncation harness MUST fail on the centered-window SMA.

    Fixture: prices = 1..30, n = 15, k = 5, period = 5 (task-mandated exact).
    With close[j] = j + 1 (values 1..30), the centered window of position i
    covers INDICES [i-2, i+2], i.e. close VALUES i-1 .. i+3:
      - i <= 12: window fully inside both frames → identical.
      - i = 13: indices [11..15]; short frame ends at index 14 → index 15
        missing → NaN; long frame (bars[:20]) → mean(values 12..16) =
        70/5 = 14.0.
      - i = 14: indices [12..16] → short NaN; long mean(values 13..17) =
        75/5 = 15.0.
      - (i = 15, 16 exist only on the long frame and are outside the
        first-n comparison.)
    So positions 13 and 14 differ (NaN vs finite) → the NaN-aware comparison
    fails → the leak is CAUGHT.
    """
    n, k, period = 15, 5, 5
    bars = _canary_frame()
    result_short = _leaky_sma(bars.iloc[:n], period)
    result_long = _leaky_sma(bars.iloc[: n + k], period)

    # Positional access only: identical construction ⇒ identical index.
    short_col = result_short.reset_index(drop=True)
    long_col = result_long.reset_index(drop=True)

    # Premises (so the failure below is understood, not accidental):
    # centered windows at the tail of the short frame are NaN...
    assert math.isnan(short_col.iloc[13]) and math.isnan(short_col.iloc[14])
    # ...while the long frame has real values there (mean of 5 closes).
    assert long_col.iloc[13] == pytest.approx(14.0, abs=TOL)  # mean(values 12..16) = 70/5
    assert long_col.iloc[14] == pytest.approx(15.0, abs=TOL)  # mean(values 13..17) = 75/5
    # Inside both frames, centered windows agree (leak is only at the edge).
    for i in range(n - 3):
        s = short_col.iloc[i]
        long_i = long_col.iloc[i]
        if not (math.isnan(s) and math.isnan(long_i)):
            assert s == pytest.approx(long_i, abs=TOL)

    # THE CANARY: the NaN-aware first-n comparison MUST raise.
    with pytest.raises(AssertionError, match="Truncation mismatch"):
        _assert_truncation_equal(short_col, long_col, n, "leaky_sma")

    # AND the failure must point at the leaking positions, 13 or 14:
    with pytest.raises(AssertionError) as excinfo:
        _assert_truncation_equal(short_col, long_col, n, "leaky_sma")
    message = str(excinfo.value)
    assert "at index 13" in message or "at index 14" in message, message


@pytest.mark.lookahead
def test_canary_divergence_is_real() -> None:
    """Positive control on the task fixture: real numeric divergence exists.

    With close[j] = j + 1, position 12 reads close VALUES 11..15 (indices
    10..14 — fully inside bars[:15], so identical on both frames); positions
    13/14 read values reaching indices 15/16, which DO NOT EXIST on the short
    frame. This test pins that the canary's failure is a REAL data leak, not
    a NaN bookkeeping artifact: the long-frame values at the leaking
    positions are computed from closes absent from bars[:15].
    """
    n, k, period = 15, 5, 5
    bars = _canary_frame()
    long_col = _leaky_sma(bars.iloc[: n + k], period).reset_index(drop=True)

    # mean(values 11..15) = 65/5 = 13.0 — identical on both frames (window
    # indices 10..14 all fit inside bars[:15]).
    assert long_col.iloc[12] == pytest.approx(13.0, abs=TOL)
    # The two leaking windows READ data beyond the short frame:
    # long[13] = mean(values 12..16) = 70/5 = 14.0 — index 15 (value 16) does
    # not exist in bars[:15].
    assert long_col.iloc[13] == pytest.approx(14.0, abs=TOL)
    # long[14] = mean(values 13..17) = 75/5 = 15.0 — indices 15, 16 (values
    # 16, 17) do not exist in bars[:15].
    assert long_col.iloc[14] == pytest.approx(15.0, abs=TOL)


@pytest.mark.lookahead
def test_canary_nan_masking_is_not_fooled() -> None:
    """Negative control: one-sided NaN masking CANNOT pass the comparison.

    A sign-blind check (|s - l| > tol) evaluates to False whenever one side
    is NaN — it would silently SKIP the leaking positions and the canary
    would pass despite a real leak. Our helper is sign-directed: NaN on one
    side only → the ``both_nan`` gate is False → the finite difference is
    evaluated → AssertionError. This test pins that direction explicitly.
    """
    n, period = 15, 5
    bars = _canary_frame()
    short_col = _leaky_sma(bars.iloc[:n], period).reset_index(drop=True)
    long_col = _leaky_sma(bars.iloc[: n + 5], period).reset_index(drop=True)

    # Premise: exactly the leaking positions are one-sided NaN.
    assert math.isnan(short_col.iloc[13]) and not math.isnan(long_col.iloc[13])
    assert math.isnan(short_col.iloc[14]) and not math.isnan(long_col.iloc[14])

    # One-sided NaN is NOT treated as equality → must raise.
    with pytest.raises(AssertionError, match="Truncation mismatch"):
        _assert_truncation_equal(short_col, long_col, n, "leaky_sma")

    # Sanity: genuine NaN==NaN pairs at the same position DO pass (the
    # NaN-aware allowance works as mandated, e.g. warmup NaN on both sides).
    both_nan_short = short_col.copy()
    both_nan_long = long_col.copy()
    both_nan_short.iloc[13:15] = np.nan  # identical NaN on BOTH sides only
    both_nan_long.iloc[13:15] = np.nan
    _assert_truncation_equal(both_nan_short, both_nan_long, n, "leaky_sma_both_nan")
