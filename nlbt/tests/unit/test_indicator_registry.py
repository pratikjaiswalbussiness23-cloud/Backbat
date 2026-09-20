"""P2-T1 tests: indicator registry and base API.

Only the DUMMY indicator defined here is used — no real indicators exist yet
(P2-T2+ must not be pre-registered). Expected values are hand-computed with
the arithmetic shown in each docstring (AGENTS.md R2).

Registry-behavior tests use FRESH ``Registry()`` instances so they cannot
pollute the module-level ``REGISTRY`` singleton; the singleton's identity and
the default-registry path of ``validate_indicator_params`` are covered by the
last two tests, which register into ``REGISTRY`` under a name unique to this
file (no other test module reads the singleton's contents today).
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import pytest

from nlbt.data.models import Bars
from nlbt.errors import NlbtError, SpecRangeError, SpecRefError
from nlbt.indicators import REGISTRY as REGISTRY_VIA_PACKAGE
from nlbt.indicators import IndicatorSpec, ParamSpec, Registry
from nlbt.indicators.registry import (
    REGISTRY as REGISTRY_VIA_MODULE,
)
from nlbt.indicators.registry import (
    register_indicator,
    validate_indicator_params,
)

#: The task-mandated dummy spec (a real SMA/EMA would violate "register no
#: real indicators yet"). warmup_fn: first valid SMA(20) output sits at index
#: period-1 = 19 → warmup = period - 1.
dummy_spec = IndicatorSpec(
    name="dummy",
    outputs=("value",),
    params={
        "period": ParamSpec(
            type="int",
            minimum=2,
            maximum=500,
            default=20,
            description="test param",
        )
    },
    allowed_sources=("close",),
    warmup_fn=lambda p: p["period"] - 1,
    compute_fn=lambda bars, params, source: pd.DataFrame(
        {"value": bars[source]},
        index=bars.index,
    ),
    description="Dummy indicator for tests",
)


def _fresh_registry_with_dummy() -> Registry:
    reg = Registry()
    reg.register(dummy_spec)
    return reg


def _mini_bars(n: int = 5) -> Bars:
    """``n`` daily UTC bars, 2024-01-01..2024-01-0n, close = 1.0, 2.0, ..., n.0.

    Hand-known values: close[i] = i + 1 (float), index = consecutive days.
    """
    idx = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    return Bars({"close": [float(i + 1) for i in range(n)]}, index=idx)


# 1 ---------------------------------------------------------------------------
def test_register_makes_indicator_listable() -> None:
    """Registering an indicator makes it appear in list_indicators()."""
    reg = Registry()
    assert reg.list_indicators() == []
    reg.register(dummy_spec)
    assert reg.list_indicators() == ["dummy"]


# 2 ---------------------------------------------------------------------------
def test_duplicate_name_raises_valueerror() -> None:
    """Registering the same name twice raises ValueError.

    Both registers use the identical dummy_spec, so ONLY the name collides —
    the error cannot be caused by anything else.
    """
    reg = _fresh_registry_with_dummy()
    with pytest.raises(ValueError, match="already registered"):
        reg.register(dummy_spec)


# 3 ---------------------------------------------------------------------------
def test_get_unknown_raises_keyerror() -> None:
    """get() of an unregistered name raises KeyError (task-mandated type)."""
    reg = _fresh_registry_with_dummy()
    with pytest.raises(KeyError, match="nope"):
        reg.get("nope")


# 4 ---------------------------------------------------------------------------
def test_list_indicators_sorted() -> None:
    """list_indicators() returns names sorted, whatever the register order."""
    reg = Registry()
    reg.register(dummy_spec)
    zulu = IndicatorSpec(
        name="aardvark",  # sorts before "dummy"
        outputs=("value",),
        params={},
        allowed_sources=("close",),
        warmup_fn=lambda p: 0,
        compute_fn=lambda bars, params, source: pd.DataFrame(index=bars.index),
        description="second dummy",
    )
    reg.register(zulu)
    # Registered order was [dummy, aardvark]; listing must invert it.
    assert reg.list_indicators() == ["aardvark", "dummy"]


# 5 ---------------------------------------------------------------------------
def test_json_schema_contains_all_registered() -> None:
    """json_schema()["indicators"] lists exactly the registered indicators."""
    reg = Registry()
    reg.register(dummy_spec)
    reg.register(
        IndicatorSpec(
            name="dummy2",
            outputs=("line", "signal"),  # multi-output shape
            params={},
            allowed_sources=("close",),
            warmup_fn=lambda p: 0,
            compute_fn=lambda bars, params, source: pd.DataFrame(index=bars.index),
            description="second dummy",
        )
    )
    schema = reg.json_schema()
    assert set(schema["indicators"]) == {"dummy", "dummy2"}
    assert schema["indicators"]["dummy"]["outputs"] == ["value"]
    assert schema["indicators"]["dummy2"]["outputs"] == ["line", "signal"]


# 6 ---------------------------------------------------------------------------
def test_json_schema_warmup_uses_default_params() -> None:
    """json_schema() evaluates warmup at DEFAULT params.

    Arithmetic: dummy warmup_fn = period - 1, default period = 20
    → schema warmup = 20 - 1 = 19.
    """
    reg = _fresh_registry_with_dummy()
    assert reg.json_schema()["indicators"]["dummy"]["warmup"] == 19


# 7 ---------------------------------------------------------------------------
def test_validate_fills_missing_params_with_defaults() -> None:
    """Missing params get their default; supplied params pass through.

    Arithmetic: dummy has one param, period, default 20 → {} resolves to
    {"period": 20}; {"period": 50} resolves to {"period": 50} (unchanged).
    """
    reg = _fresh_registry_with_dummy()
    assert validate_indicator_params("dummy", {}, registry=reg) == {"period": 20}
    assert validate_indicator_params("dummy", {"period": 50}, registry=reg) == {"period": 50}


# 8 ---------------------------------------------------------------------------
def test_validate_below_minimum_raises_spec_range() -> None:
    """period=1 is below minimum=2 → SpecRangeError carrying E_SPEC_RANGE.

    Arithmetic: violation iff value < minimum → 1 < 2 → violated.
    """
    reg = _fresh_registry_with_dummy()
    with pytest.raises(SpecRangeError) as excinfo:
        validate_indicator_params("dummy", {"period": 1}, registry=reg)
    assert excinfo.value.code == "E_SPEC_RANGE"
    assert excinfo.value.details["violations"][0]["problem"] == "below_minimum"


# 9 ---------------------------------------------------------------------------
def test_validate_above_maximum_raises_spec_range() -> None:
    """period=501 is above maximum=500 → E_SPEC_RANGE.

    Arithmetic: violation iff value > maximum → 501 > 500 → violated.
    """
    reg = _fresh_registry_with_dummy()
    with pytest.raises(SpecRangeError) as excinfo:
        validate_indicator_params("dummy", {"period": 501}, registry=reg)
    assert excinfo.value.code == "E_SPEC_RANGE"
    assert excinfo.value.details["violations"][0]["problem"] == "above_maximum"


# 10 --------------------------------------------------------------------------
def test_validate_unknown_param_raises_spec_range() -> None:
    """An unknown param name is a violation, never silently dropped."""
    reg = _fresh_registry_with_dummy()
    with pytest.raises(SpecRangeError) as excinfo:
        validate_indicator_params("dummy", {"lookback": 10}, registry=reg)
    assert excinfo.value.code == "E_SPEC_RANGE"
    assert excinfo.value.details["unknown_params"] == ["lookback"]


# 11 --------------------------------------------------------------------------
def test_describe_contains_name_and_is_nonempty() -> None:
    """describe() returns a non-empty human-readable string naming the indicator."""
    reg = _fresh_registry_with_dummy()
    text = reg.describe("dummy")
    assert text
    assert "dummy" in text
    # The rendered description includes the param's bounds and default.
    assert "2" in text and "500" in text and "20" in text


# 12 --------------------------------------------------------------------------
def test_duplicate_output_names_raise_valueerror() -> None:
    """outputs=("value", "value") is ambiguous → rejected at registration."""
    reg = Registry()
    bad = IndicatorSpec(
        name="dupout",
        outputs=("value", "value"),
        params={},
        allowed_sources=("close",),
        warmup_fn=lambda p: 0,
        compute_fn=lambda bars, params, source: pd.DataFrame(index=bars.index),
        description="duplicate-output spec",
    )
    with pytest.raises(ValueError, match="duplicate output"):
        reg.register(bad)


# 12b (extra: the two remaining register guards) ------------------------------
def test_empty_name_rejected() -> None:
    """An indicator with an empty name can never be referenced → ValueError."""
    reg = Registry()
    bad = IndicatorSpec(
        name="",
        outputs=("value",),
        params={},
        allowed_sources=("close",),
        warmup_fn=lambda p: 0,
        compute_fn=lambda bars, params, source: pd.DataFrame(index=bars.index),
        description="empty-name spec",
    )
    with pytest.raises(ValueError, match="non-empty string"):
        reg.register(bad)


def test_empty_outputs_rejected() -> None:
    """A spec with no outputs produces nothing readable → ValueError."""
    reg = Registry()
    bad = IndicatorSpec(
        name="noout",
        outputs=(),
        params={},
        allowed_sources=("close",),
        warmup_fn=lambda p: 0,
        compute_fn=lambda bars, params, source: pd.DataFrame(index=bars.index),
        description="empty-outputs spec",
    )
    with pytest.raises(ValueError, match="at least one output"):
        reg.register(bad)


# 13 --------------------------------------------------------------------------
def test_compute_fn_output_index_matches_input() -> None:
    """compute_fn must return a frame with the SAME index as its input.

    Arithmetic: _mini_bars(5) close = [1.0, 2.0, 3.0, 4.0, 5.0] over
    2024-01-01..2024-01-05; the dummy copies the source column, so value ==
    close elementwise and the index is identical (5 rows, same timestamps).
    """
    bars = _mini_bars(5)
    out = dummy_spec.compute_fn(bars, {"period": 20}, "close")
    assert list(out.index) == list(bars.index)
    assert list(out.columns) == ["value"]  # == spec.outputs
    assert out["value"].tolist() == [1.0, 2.0, 3.0, 4.0, 5.0]


# 14 --------------------------------------------------------------------------
def test_registry_is_singleton_across_import_paths() -> None:
    """Importing REGISTRY from two places yields the SAME object.

    Two import paths are exercised: the package root (nlbt.indicators) and the
    defining module (nlbt.indicators.registry). Python's module cache makes
    them identical — asserted, not assumed.
    """
    assert REGISTRY_VIA_PACKAGE is REGISTRY_VIA_MODULE


# 15 (extra: the task-mandated helper + default-registry path) ----------------
def test_register_indicator_helper_targets_global_singleton() -> None:
    """register_indicator() adds to the global REGISTRY, and
    validate_indicator_params() consults that same REGISTRY when no registry
    is passed (the path P2-T2+ indicator users will hit).

    Uses a name unique to this file so it cannot collide with anything else.
    """
    helper_spec = IndicatorSpec(
        name="dummy_global_path",
        outputs=("value",),
        params={
            "period": ParamSpec(
                type="int",
                minimum=2,
                maximum=500,
                default=20,
                description="test param",
            )
        },
        allowed_sources=("close",),
        warmup_fn=lambda p: p["period"] - 1,
        compute_fn=lambda bars, params, source: pd.DataFrame(
            {"value": bars[source]}, index=bars.index
        ),
        description="Registered only to exercise the global path",
    )
    register_indicator(helper_spec)
    assert "dummy_global_path" in REGISTRY_VIA_MODULE.list_indicators()
    # Default-registry path (registry=None): 3 is within [2, 500] → accepted.
    assert validate_indicator_params("dummy_global_path", {"period": 3}) == {"period": 3}


# 16 (extra: bounds are inclusive) --------------------------------------------
def test_validate_bounds_are_inclusive() -> None:
    """Boundary values equal to min/max are ACCEPTED.

    Arithmetic: minimum=2, maximum=500 → period=2 and period=500 both satisfy
    minimum <= value <= maximum → no violation, resolved unchanged.
    """
    reg = _fresh_registry_with_dummy()
    assert validate_indicator_params("dummy", {"period": 2}, registry=reg) == {"period": 2}
    assert validate_indicator_params("dummy", {"period": 500}, registry=reg) == {"period": 500}


# 17 (extra: strict typing of param values) -----------------------------------
@pytest.mark.parametrize(
    ("bad_value", "problem"),
    [
        pytest.param("20", "not_numeric", id="string-not-coerced"),
        pytest.param(True, "not_numeric", id="bool-excluded"),
        pytest.param(20.5, "expected_int", id="float-rejected-for-int"),
        pytest.param(float("nan"), "not_finite", id="nan-rejected"),
        pytest.param(float("inf"), "not_finite", id="inf-rejected"),
    ],
)
def test_validate_rejects_non_strict_param_values(bad_value: Any, problem: str) -> None:
    """Type/non-finite violations also raise E_SPEC_RANGE (see OQ-0014).

    Case arithmetic: "20" is str (not numeric); True is a bool (explicitly
    excluded even though bool subclasses int); 20.5 is float where type="int";
    NaN/inf violate §4.3's "never inf" spirit for parameters.
    """
    reg = _fresh_registry_with_dummy()
    with pytest.raises(SpecRangeError) as excinfo:
        validate_indicator_params("dummy", {"period": bad_value}, registry=reg)
    assert excinfo.value.code == "E_SPEC_RANGE"
    assert excinfo.value.details["violations"][0]["problem"] == problem


# 18 (extra: unknown indicator error surface) ---------------------------------
def test_validate_unknown_indicator_raises_spec_ref() -> None:
    """Unknown indicator name → SpecRefError (E_SPEC_REF), not a raw KeyError.

    The spec/LLM layers catch NlbtError; a bare KeyError would escape the
    §4.8 taxonomy. details carries the known names for a repair loop.
    """
    reg = _fresh_registry_with_dummy()
    with pytest.raises(SpecRefError) as excinfo:
        validate_indicator_params("nope", {"period": 20}, registry=reg)
    assert excinfo.value.code == "E_SPEC_REF"
    assert excinfo.value.details["known_indicators"] == ["dummy"]


def test_spec_errors_share_nlbt_error_base() -> None:
    """Both validation error types are within the §4.8 taxonomy (catchable)."""
    assert issubclass(SpecRangeError, NlbtError)
    assert issubclass(SpecRefError, NlbtError)
