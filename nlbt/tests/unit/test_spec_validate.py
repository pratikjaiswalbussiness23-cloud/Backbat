"""P3-T2 tests: the semantic validator (nlbt.spec.validate).

Layout mirrors the task's numbered tests:

* SECTION 1 (tests 1-3): Appendix C fixtures validate with ZERO errors
  (and zero warnings -- each fixture has an exit mechanism and no
  warning-triggering combination).
* SECTION 2 (tests 4-7): E_SPEC_REF -- unknown indicator type, source
  not allowed for that indicator, operand naming an undefined
  indicator, operand naming a nonexistent output. Paths locate the
  exact JSON fragment (e.g. ``rules.entry_long.conditions.0.right``).
* SECTION 3 (tests 8-9): E_SPEC_RANGE via the REGISTRY's own
  ``validate_indicator_params`` (sma bounds [2, 500], probed).
* SECTION 4 (tests 10-13): sizing per method. NOTE on test 11
  (percent value=0): the P3-T1 schema already rejects value<=0, so the
  semantic branch is reachable only through an UNVALIDATED instance
  (``Sizing.model_construct``) -- that is the point: validate_spec must
  defend its invariants even for specs that skipped pydantic.
* SECTION 5 (tests 14-15): warm-up heuristic with hand-computed
  arithmetic in the docstrings (registry warmup_fn is the oracle:
  sma(p) = p-1).
* SECTION 6 (tests 16-19): warnings W1/W3/W4/W5, exact strings.
* SECTION 7 (test 20): three simultaneous errors -- the validator
  collects ALL of them.
* CANARY (test 21): an operand referencing an undefined indicator
  passes PYDANTIC (schema knows nothing of cross-references) but fails
  SEMANTIC validation -- both layers are necessary.

The clock is frozen via the P3-T1 injection point
(``nlbt.spec.models._get_today``); ``validate_spec`` itself performs no
date checks (pydantic owns those) -- ``today`` is accepted only for
interface symmetry, per the task text ("use injected today or
date.today()... Already checked by pydantic. Skip here.").
"""

from __future__ import annotations

import copy
import json
from datetime import date
from typing import Any

import pytest

from nlbt.spec import models as spec_models
from nlbt.spec.models import IndicatorDef, Sizing, StrategySpec
from nlbt.spec.validate import SemanticValidationResult, validate_spec

FROZEN_TODAY = date(2025, 1, 1)


@pytest.fixture(autouse=True)
def _frozen_today(monkeypatch: pytest.MonkeyPatch) -> None:
    """Freeze the spec-model clock (P3-T1 injection point) for determinism."""
    monkeypatch.setattr(spec_models, "_get_today", lambda: FROZEN_TODAY)


# ---------------------------------------------------------------------------
# Appendix C fixtures -- verbatim from ROADMAP.md Appendix C (same literals
# as tests/unit/test_spec_models.py; kept in sync deliberately).
# ---------------------------------------------------------------------------

_C1_JSON = """
{"spec_version": "1.0", "name": "SMA 50/200 golden cross",
 "universe": {"symbols": ["SPY"], "interval": "1d"},
 "period": {"start": "2010-01-01", "end": "2024-12-31"},
 "indicators": {
   "fast": {"type": "sma", "params": {"period": 50},  "source": "close"},
   "slow": {"type": "sma", "params": {"period": 200}, "source": "close"}},
 "rules": {
   "entry_long": {"all": [{"left": "fast", "op": "crosses_above", "right": "slow"}]},
   "exit_long":  {"all": [{"left": "fast", "op": "crosses_below", "right": "slow"}]}},
 "risk": {}, "sizing": {"method": "percent_of_equity", "value": 100, "allow_fractional": true},
 "execution": {"fill": "next_open", "fee_bps": 5, "slippage_bps": 5, "fixed_fee": 0},
 "capital": {"initial": 100000, "currency": "USD"}}
"""

_C2_JSON = """
{"spec_version": "1.0", "name": "RSI 2 dip buy above 200 SMA",
 "universe": {"symbols": ["QQQ"], "interval": "1d"},
 "period": {"start": "2015-01-01", "end": "2024-12-31"},
 "indicators": {
   "rsi2":  {"type": "rsi", "params": {"period": 2},   "source": "close"},
   "trend": {"type": "sma", "params": {"period": 200}, "source": "close"}},
 "rules": {
   "entry_long": {"all": [
     {"left": "close", "op": ">", "right": "trend"},
     {"left": "rsi2",  "op": "<", "right": 10}]},
   "exit_long": {"any": [{"left": "rsi2", "op": ">", "right": 70}]}},
 "risk": {"stop_loss_pct": 6, "max_holding_bars": 10},
 "sizing": {"method": "percent_of_equity", "value": 50, "allow_fractional": true},
 "execution": {"fill": "next_open", "fee_bps": 5, "slippage_bps": 5, "fixed_fee": 0},
 "capital": {"initial": 100000, "currency": "USD"}}
"""

_C3_JSON = """
{"spec_version": "1.0", "name": "20-day breakout, 8% trailing stop",
 "universe": {"symbols": ["BTC-USD"], "interval": "1d"},
 "period": {"start": "2018-01-01", "end": "2024-12-31"},
 "indicators": {"hh20": {"type": "highest", "params": {"period": 20}, "source": "high"}},
 "rules": {"entry_long": {"all": [{"left": "close", "op": ">", "right": "hh20"}]}},
 "risk": {"trailing_stop_pct": 8, "stop_loss_pct": 8},
 "sizing": {"method": "risk_per_trade", "value": 1, "allow_fractional": true},
 "execution": {"fill": "next_open", "fee_bps": 10, "slippage_bps": 10, "fixed_fee": 0},
 "capital": {"initial": 50000, "currency": "USD"}}
"""


def make_spec(**overrides: Any) -> StrategySpec:
    """A schema-valid C1 (SMA crossover) spec with top-level overrides.

    Overrides REPLACE the top-level key (deep-copied). For semantic-layer
    faults that pydantic cannot express (unknown indicator TYPE, bad
    source), tests mutate the returned model -- pydantic models are
    mutable by default (no ``validate_assignment`` in the P3-T1 config),
    which is exactly the surface ``validate_spec`` must police.
    """
    spec_dict = json.loads(_C1_JSON)
    for key, value in overrides.items():
        spec_dict[key] = copy.deepcopy(value)
    return StrategySpec.model_validate(spec_dict)


def make_spec_from(fixture: str) -> StrategySpec:
    """Parse one of the verbatim Appendix C fixtures."""
    return StrategySpec.model_validate(json.loads(fixture))


def _paths(result: SemanticValidationResult) -> set[str]:
    return {error.path for error in result.errors}


def _codes(result: SemanticValidationResult) -> set[str]:
    return {error.code for error in result.errors}


# ===========================================================================
# SECTION 1 -- valid specs pass (task tests 1-3)
# ===========================================================================


class TestValidSpecsPass:
    def test_01_c1_validates_with_zero_errors(self) -> None:
        result = validate_spec(make_spec())
        assert result.is_valid
        assert result.errors == []
        # C1 has an exit rule, 100% sizing WITHOUT a stop, fractional
        # shares allowed, no bare price thresholds -> no warnings either.
        assert result.warnings == []

    def test_02_c2_validates_with_zero_errors(self) -> None:
        result = validate_spec(make_spec_from(_C2_JSON))
        assert result.is_valid
        assert result.errors == []
        assert result.warnings == []

    def test_03_c3_validates_with_zero_errors(self) -> None:
        result = validate_spec(make_spec_from(_C3_JSON))
        assert result.is_valid
        assert result.errors == []
        assert result.warnings == []


# ===========================================================================
# SECTION 2 -- indicator reference errors, E_SPEC_REF (task tests 4-7)
# ===========================================================================


class TestIndicatorReferenceErrors:
    def test_04_unknown_indicator_type(self) -> None:
        spec = make_spec()
        spec.indicators["ghost"] = IndicatorDef(type="nope", params={})
        result = validate_spec(spec)
        assert not result.is_valid
        assert "indicators.ghost.type" in _paths(result)
        assert "E_SPEC_REF" in _codes(result)
        error = next(e for e in result.errors if e.path == "indicators.ghost.type")
        assert "Available indicators:" in error.hint

    def test_05_source_not_allowed_for_indicator(self) -> None:
        # Probed (verified_apis.md): obv allowed_sources == ('close',) --
        # an 'open' source must be rejected semantically. The schema layer
        # cannot know this (source is any raw column there).
        spec = make_spec()
        spec.indicators["ov1"] = IndicatorDef(type="obv", params={}, source="open")
        result = validate_spec(spec)
        assert "indicators.ov1.source" in _paths(result)
        assert "E_SPEC_REF" in _codes(result)

    def test_06_operand_references_undefined_indicator(self) -> None:
        spec = make_spec()
        del spec.indicators["slow"]  # C1 rules still reference it
        result = validate_spec(spec)
        assert "rules.entry_long.conditions.0.right" in _paths(result)
        assert "rules.exit_long.conditions.0.right" in _paths(result)
        error = next(e for e in result.errors if e.path == "rules.entry_long.conditions.0.right")
        assert "Defined indicators:" in error.hint
        assert "E_SPEC_REF" in _codes(result)

    def test_07_operand_references_wrong_output(self) -> None:
        # macd HAS outputs line/signal/hist (probed) -- 'close_price' is
        # not one of them. A dotted reference to a real output must pass
        # (covered by test_06's sibling assert below), a fake one must not.
        spec = make_spec()
        spec.indicators["m"] = IndicatorDef(
            type="macd", params={"fast": 12, "slow": 26, "signal": 9}, source="close"
        )
        cond = spec.rules.entry_long.conditions[0]
        cond.left = _retype_indicator_operand(cond.left, name="m", output="close_price")
        result = validate_spec(spec)
        assert "rules.entry_long.conditions.0.left" in _paths(result)
        assert "E_SPEC_REF" in _codes(result)

        # Same setup but a REAL macd output -> no output error.
        spec2 = make_spec()
        spec2.indicators["m"] = IndicatorDef(
            type="macd", params={"fast": 12, "slow": 26, "signal": 9}, source="close"
        )
        cond2 = spec2.rules.entry_long.conditions[0]
        cond2.left = _retype_indicator_operand(cond2.left, name="m", output="line")
        assert validate_spec(spec2).is_valid


def _retype_indicator_operand(operand: Any, *, name: str, output: str) -> Any:
    """Rewrite an operand's name/output (plain attribute mutation; the
    operand classes are mutable pydantic models)."""
    operand.name = name
    operand.output = output
    return operand


# ===========================================================================
# SECTION 3 -- param range errors, E_SPEC_RANGE (task tests 8-9)
# ===========================================================================


class TestParamRangeErrors:
    def test_08_sma_period_below_minimum(self) -> None:
        # Registry bound (probed): sma period minimum = 2.
        spec = make_spec(
            indicators={
                "fast": {"type": "sma", "params": {"period": 1}, "source": "close"},
                "slow": {"type": "sma", "params": {"period": 200}, "source": "close"},
            }
        )
        result = validate_spec(spec)
        assert "indicators.fast.params.period" in _paths(result)
        assert "E_SPEC_RANGE" in _codes(result)

    def test_09_sma_period_above_maximum(self) -> None:
        # Registry bound (probed): sma period maximum = 500.
        spec = make_spec(
            indicators={
                "fast": {"type": "sma", "params": {"period": 501}, "source": "close"},
                "slow": {"type": "sma", "params": {"period": 200}, "source": "close"},
            }
        )
        result = validate_spec(spec)
        assert "indicators.fast.params.period" in _paths(result)
        assert "E_SPEC_RANGE" in _codes(result)


# ===========================================================================
# SECTION 4 -- sizing errors, E_SPEC_RANGE (task tests 10-13)
# ===========================================================================


class TestSizingErrors:
    def test_10_percent_of_equity_above_100(self) -> None:
        # The schema layer has NO upper bound on sizing.value (deliberate,
        # OQ-0036: "range depends on method" is semantic); 101 passes
        # pydantic and must fail here.
        spec = make_spec(
            sizing={"method": "percent_of_equity", "value": 101, "allow_fractional": True}
        )
        result = validate_spec(spec)
        assert "sizing.value" in _paths(result)
        assert "E_SPEC_RANGE" in _codes(result)

    def test_11_percent_of_equity_zero(self) -> None:
        # Pydantic already rejects value<=0 (gt=0), so the semantic branch
        # is only reachable through an UNVALIDATED instance -- which the
        # validator must still police (defence in depth, task item 11).
        unvalidated_sizing = Sizing.model_construct(
            method="percent_of_equity", value=0.0, allow_fractional=True
        )
        spec = make_spec()
        spec.sizing = unvalidated_sizing
        result = validate_spec(spec)
        assert "sizing.value" in _paths(result)
        assert "E_SPEC_RANGE" in _codes(result)

    def test_12_fixed_shares_non_integer_without_fractional(self) -> None:
        spec = make_spec(
            sizing={"method": "fixed_shares", "value": 10.5, "allow_fractional": False}
        )
        result = validate_spec(spec)
        assert "sizing.value" in _paths(result)
        assert "E_SPEC_RANGE" in _codes(result)

        # Boundary: the SAME value with allow_fractional=True is fine.
        fractional = make_spec(
            sizing={"method": "fixed_shares", "value": 10.5, "allow_fractional": True}
        )
        sizing_errors = [e for e in validate_spec(fractional).errors if e.path == "sizing.value"]
        assert sizing_errors == []

    def test_13_risk_per_trade_requires_stop_loss(self) -> None:
        # C1 has risk={} -> stop_loss_pct None -> E_SPEC_RANGE on
        # sizing.method with the task's exact message.
        spec = make_spec(sizing={"method": "risk_per_trade", "value": 2})
        result = validate_spec(spec)
        assert "sizing.method" in _paths(result)
        error = next(e for e in result.errors if e.path == "sizing.method")
        assert error.message == "risk_per_trade sizing requires stop_loss_pct"
        assert "E_SPEC_RANGE" in _codes(result)

        # With a stop: no sizing error (C3 exercises the same path).
        with_stop = make_spec(
            sizing={"method": "risk_per_trade", "value": 2},
            risk={"stop_loss_pct": 5},
        )
        assert validate_spec(with_stop).errors == []


# ===========================================================================
# SECTION 5 -- warm-up vs available bars, E_SPEC_RANGE (task tests 14-15)
# ===========================================================================


class TestWarmupCheck:
    def test_14_sma300_on_six_months_is_an_error(self) -> None:
        # Hand arithmetic (registry warmup_fn: sma(p) = p-1 -> 299):
        #   2024-01-01..2024-07-01 = 182 calendar days (2024 is a leap
        #   year: 31+29+31+30+31+30), estimated = int(182*252/365)
        #   = int(125.65...) = 125 bars. 299 >= 125 -> error.
        spec = make_spec(
            indicators={"trend": {"type": "sma", "params": {"period": 300}, "source": "close"}},
            rules={
                "entry_long": {"all": [{"left": "trend", "op": "crosses_above", "right": "trend"}]}
            },
            period={"start": "2024-01-01", "end": "2024-07-01"},
        )
        result = validate_spec(spec)
        assert "period" in _paths(result)
        assert "E_SPEC_RANGE" in _codes(result)
        error = next(e for e in result.errors if e.path == "period")
        assert error.message == ("Warm-up (299 bars) exceeds estimated available bars (125)")

    def test_15_warmup_boundary_is_inclusive(self) -> None:
        # Hand arithmetic (both windows end 2025-01-01; 2024 is a leap
        # year): start 2023-10-25 -> 434 days -> int(434*252/365) =
        # int(299.81) = 299 bars -> warmup 299 >= 299 -> ERROR (the task
        # mandates ">="); start 2023-10-24 -> 435 days ->
        # int(300.36) = 300 bars -> 299 < 300 -> VALID.
        base: dict[str, Any] = {
            "indicators": {"trend": {"type": "sma", "params": {"period": 300}, "source": "close"}},
            "rules": {
                "entry_long": {"all": [{"left": "trend", "op": "crosses_above", "right": "trend"}]}
            },
        }
        exact = make_spec(**base, period={"start": "2023-10-25", "end": "2025-01-01"})
        assert "period" in _paths(validate_spec(exact))  # 434 days -> 299 bars

        one_more = make_spec(**base, period={"start": "2023-10-24", "end": "2025-01-01"})
        assert [e for e in validate_spec(one_more).errors if e.path == "period"] == []  # 435 -> 300


# ===========================================================================
# SECTION 6 -- warnings (task tests 16-19; W4 covered as the task
# defines it even though the numbered list skips it)
# ===========================================================================


class TestWarnings:
    def test_16_no_exit_mechanism_warning(self) -> None:
        spec = make_spec(
            rules={"entry_long": {"all": [{"left": "fast", "op": ">", "right": "slow"}]}}
        )
        result = validate_spec(spec)
        assert (
            "No exit mechanism defined. Position will be held until end of data." in result.warnings
        )

    def test_17_hundred_percent_with_stop_warning(self) -> None:
        # C1 is already 100% of equity; adding a stop arms W3.
        spec = make_spec(risk={"stop_loss_pct": 5})
        result = validate_spec(spec)
        assert (
            "100% equity sizing with a stop loss may result in large drawdowns." in result.warnings
        )

    def test_18_exit_present_means_no_w1(self) -> None:
        result = validate_spec(make_spec())
        assert not any("No exit mechanism" in w for w in result.warnings)

    def test_19_absolute_price_threshold_warning(self) -> None:
        # NumberOperand 150 vs RawColumnOperand close (entry AND exit side
        # both exercise the reversed-sides case).
        spec = make_spec(
            indicators={},
            rules={
                "entry_long": {"all": [{"left": "close", "op": ">", "right": 150}]},
                "exit_long": {"all": [{"left": 200, "op": "<", "right": "close"}]},
            },
        )
        result = validate_spec(spec)
        assert (
            "Absolute price thresholds are distorted by split/dividend adjustment."
            in result.warnings
        )

        # NOT triggered: a big number against an INDICATOR operand is a
        # threshold on the indicator, not on the raw price.
        indicator_case = make_spec(
            rules={"entry_long": {"all": [{"left": "fast", "op": ">", "right": 150}]}}
        )
        assert not any("Absolute price" in w for w in validate_spec(indicator_case).warnings)
        # NOT triggered at the boundary: 10 is not > 10.
        boundary = make_spec(
            indicators={},
            rules={"entry_long": {"all": [{"left": "close", "op": ">", "right": 10}]}},
        )
        assert not any("Absolute price" in w for w in validate_spec(boundary).warnings)

    def test_19b_integer_shares_with_percent_sizing_warning(self) -> None:
        spec = make_spec(
            sizing={"method": "percent_of_equity", "value": 50, "allow_fractional": False}
        )
        result = validate_spec(spec)
        w4 = (
            "Integer shares with percent sizing may result in "
            "significant cash unused at low prices."
        )
        assert w4 in result.warnings


# ===========================================================================
# SECTION 7 -- multiple errors collected (task test 20)
# ===========================================================================


class TestMultipleErrors:
    def test_20_three_simultaneous_errors_all_reported(self) -> None:
        spec = make_spec(
            indicators={
                "fast": {"type": "sma", "params": {"period": 50}, "source": "close"},
                "ghost": {"type": "nope", "params": {}, "source": "close"},
                "ov1": {"type": "obv", "params": {}, "source": "open"},
            },
            rules={"entry_long": {"all": [{"left": "phantom", "op": ">", "right": "fast"}]}},
        )
        result = validate_spec(spec)
        # Exactly the three planted faults, none dropped, none short-circuited:
        #   1. unknown TYPE          -> indicators.ghost.type      (E_SPEC_REF)
        #   2. source not allowed    -> indicators.ov1.source      (E_SPEC_REF)
        #   3. undefined operand ref -> rules.entry_long...0.left  (E_SPEC_REF)
        assert _paths(result) == {
            "indicators.ghost.type",
            "indicators.ov1.source",
            "rules.entry_long.conditions.0.left",
        }
        assert _codes(result) == {"E_SPEC_REF"}


# ===========================================================================
# CANARY -- the two validation layers are BOTH necessary (task test 21)
# ===========================================================================


class TestTwoLayerCanary:
    def test_21_pydantic_accepts_what_semantic_rejects(self) -> None:
        raw = json.loads(_C1_JSON)
        raw["rules"] = {
            "entry_long": {"all": [{"left": "ghost_macd", "op": ">", "right": "fast"}]},
            "exit_long": raw["rules"]["exit_long"],
        }
        # Layer 1 (schema): PASSES -- pydantic cannot know 'ghost_macd'
        # is undefined; IndicatorOperand only checks the NAME SHAPE.
        spec = StrategySpec.model_validate(raw)
        assert isinstance(spec, StrategySpec)
        # Layer 2 (semantic): FAILS with a located E_SPEC_REF.
        result = validate_spec(spec)
        assert not result.is_valid
        assert "rules.entry_long.conditions.0.left" in _paths(result)
        assert "E_SPEC_REF" in _codes(result)
        assert any("ghost_macd" in e.message for e in result.errors)
