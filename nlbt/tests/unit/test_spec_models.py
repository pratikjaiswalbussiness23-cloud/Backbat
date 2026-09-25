"""P3-T1 tests: StrategySpec v1 pydantic models (ROADMAP 4.1-4.2).

Five sections:

1. APPENDIX C PARSE (tests 1-3): the three ROADMAP fixtures, embedded
   verbatim, must parse under a FROZEN clock and yield the documented
   model types (discriminated unions) and values. The fixtures end
   2024-12-31, so they are valid relative to the frozen "today"
   (2025-01-01) and to the real clock alike.
2. FIELD VALIDATION (tests 4-23): every constraint from the 4.1 table,
   one test per row/boundary. Expected values come from the ROADMAP
   text, never invented (AGENTS.md R2). Strict typing: a string capital
   must be rejected (no silent coercion); int -> float widening is
   allowed (lossless, OQ-0014 precedent) and asserted in test 13.
3. RULE GRAMMAR (tests 24-35): 1..20 conditions per all/any, recursive
   not, nesting depth limit 4 (boundaries 4 ok / 5 fail), the op set
   without "==", raw_column membership, lag >= 0, and the 4.2 operand
   spellings (bare name, "name.output", {"name", "lag"}) plus a fully
   tagged document (what P6 emits).
4. DEFAULTS (tests 36-38): Execution / Risk / list defaults exactly as
   the 4.1 table states.
5. CANARY (test 39): extra="forbid" on EVERY model -- a sweep proving
   unknown fields are rejected at every level of the schema, not just
   the top level.

The clock is frozen via monkeypatching nlbt.spec.models._get_today (the
models never call date.today() directly -- task mandate), so
period-vs-today tests are deterministic forever.
"""

from __future__ import annotations

import copy
import json
from datetime import date
from typing import Any, ClassVar

import pytest
from pydantic import ValidationError

from nlbt.spec import models as spec_models
from nlbt.spec.models import (
    AllRule,
    AnyRule,
    Assumption,
    Capital,
    Condition,
    Execution,
    IndicatorDef,
    IndicatorOperand,
    NotRule,
    NumberOperand,
    Period,
    RawColumnOperand,
    Risk,
    Rules,
    Sizing,
    StrategySpec,
    Universe,
    rule_depth,
)

FROZEN_TODAY = date(2025, 1, 1)


@pytest.fixture(autouse=True)
def _frozen_today(monkeypatch: pytest.MonkeyPatch) -> None:
    """Freeze the spec clock so period.end tests never age out."""
    monkeypatch.setattr(spec_models, "_get_today", lambda: FROZEN_TODAY)


# ---------------------------------------------------------------------------
# Appendix C fixtures -- verbatim from ROADMAP.md Appendix C.
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


def _c1() -> dict[str, Any]:
    """A fresh C1 dict per call (tests mutate their copies)."""
    return json.loads(_C1_JSON)


def _c2() -> dict[str, Any]:
    return json.loads(_C2_JSON)


def _c3() -> dict[str, Any]:
    return json.loads(_C3_JSON)


def _patched_c1(**changes: Any) -> dict[str, Any]:
    """C1 with top-level keys replaced; nested structures are deep-copied."""
    spec = _c1()
    for key, value in changes.items():
        spec[key] = copy.deepcopy(value)
    return spec


_SIMPLE_CONDITION: dict[str, Any] = {"left": "close", "op": ">", "right": 1}


# ===========================================================================
# Section 1 -- Appendix C parses (acceptance: "every example in Appendix C
# parses and validates")
# ===========================================================================


class TestAppendixCFixtures:
    def test_01_c1_sma_crossover_parses(self) -> None:
        spec = StrategySpec.model_validate(_c1())
        assert spec.name == "SMA 50/200 golden cross"
        assert spec.universe.symbols == ["SPY"]
        assert set(spec.indicators) == {"fast", "slow"}
        entry = spec.rules.entry_long
        assert isinstance(entry, AllRule)
        assert rule_depth(entry) == 2  # all(1) -> condition(2)
        cond = entry.conditions[0]
        assert isinstance(cond.left, IndicatorOperand)
        assert cond.left.name == "fast"
        assert cond.left.output == "value"  # bare name = primary output
        assert cond.op == "crosses_above"
        assert isinstance(cond.right, IndicatorOperand)
        assert cond.right.name == "slow"
        assert isinstance(spec.rules.exit_long, AllRule)
        assert spec.risk.stop_loss_pct is None  # "risk": {} -> all defaults
        assert spec.capital.initial == 100000.0

    def test_02_c2_rsi_mean_reversion_parses(self) -> None:
        spec = StrategySpec.model_validate(_c2())
        entry = spec.rules.entry_long
        assert isinstance(entry, AllRule)
        first, second = entry.conditions
        # "close" is a raw column, NOT an indicator reference.
        assert isinstance(first.left, RawColumnOperand)
        assert first.left.name == "close"
        assert isinstance(first.right, IndicatorOperand)
        assert first.right.name == "trend"
        # Bare number 10 becomes a NumberOperand (strict float, widened).
        assert isinstance(second.right, NumberOperand)
        assert second.right.value == 10.0
        assert isinstance(spec.rules.exit_long, AnyRule)
        assert spec.risk.stop_loss_pct == 6.0
        assert spec.risk.max_holding_bars == 10
        assert spec.risk.take_profit_pct is None
        assert spec.sizing.value == 50.0
        assert spec.assumptions == []

    def test_03_c3_donchian_breakout_parses(self) -> None:
        spec = StrategySpec.model_validate(_c3())
        assert spec.universe.symbols == ["BTC-USD"]
        assert spec.indicators["hh20"].source == "high"
        assert isinstance(spec.rules.entry_long.conditions[0].left, RawColumnOperand)
        assert spec.risk.trailing_stop_pct == 8.0
        assert spec.risk.stop_loss_pct == 8.0
        assert spec.sizing.method == "risk_per_trade"
        assert spec.sizing.value == 1.0
        assert spec.execution.fee_bps == 10.0
        assert spec.capital.initial == 50000.0
        assert spec.rules.exit_long is None  # C3 has no exit rule


# ===========================================================================
# Section 2 -- field validation (ROADMAP 4.1 constraint table)
# ===========================================================================


class TestFieldValidation:
    @pytest.mark.parametrize("version", ["1.1", "2.0", ""])
    def test_04_spec_version_must_be_exactly_1_0(self, version: str) -> None:
        with pytest.raises(ValidationError):
            StrategySpec.model_validate(_patched_c1(spec_version=version))

    def test_05_name_over_120_chars_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StrategySpec.model_validate(_patched_c1(name="x" * 121))

    def test_06_name_exactly_120_chars_accepted(self) -> None:
        spec = StrategySpec.model_validate(_patched_c1(name="x" * 120))
        assert len(spec.name) == 120

    def test_07_two_symbols_rejected_in_v1(self) -> None:
        # Enforced at the Universe list bound (v1: exactly 1 symbol, 4.1).
        universe = {"symbols": ["SPY", "QQQ"], "interval": "1d"}
        with pytest.raises(ValidationError, match="at most 1 item"):
            StrategySpec.model_validate(_patched_c1(universe=universe))

    @pytest.mark.parametrize("symbol", ["SPY!", "A B", "", "A" * 21])
    def test_08_symbols_outside_the_task_regex_rejected(self, symbol: str) -> None:
        universe = {"symbols": [symbol], "interval": "1d"}
        with pytest.raises(ValidationError, match="does not match"):
            StrategySpec.model_validate(_patched_c1(universe=universe))

    def test_09_start_equal_to_end_rejected(self) -> None:
        period = {"start": "2024-12-31", "end": "2024-12-31"}
        with pytest.raises(ValidationError, match="must be before"):
            StrategySpec.model_validate(_patched_c1(period=period))

    def test_10_start_after_end_rejected(self) -> None:
        period = {"start": "2024-06-01", "end": "2024-01-01"}
        with pytest.raises(ValidationError, match="must be before"):
            StrategySpec.model_validate(_patched_c1(period=period))

    def test_11_end_in_future_rejected(self) -> None:
        # Frozen today is 2025-01-01; 2025-06-01 is beyond it even though a
        # real wall clock might differ -- proves the injected clock is used.
        period = {"start": "2024-01-01", "end": "2025-06-01"}
        with pytest.raises(ValidationError, match="in the future"):
            StrategySpec.model_validate(_patched_c1(period=period))

    def test_12_end_equal_to_today_accepted(self) -> None:
        period = {"start": "2024-01-01", "end": "2025-01-01"}
        spec = StrategySpec.model_validate(_patched_c1(period=period))
        assert spec.period.end == date(2025, 1, 1)

    @pytest.mark.parametrize("initial", [0, -1000])
    def test_13_nonpositive_capital_rejected(self, initial: float) -> None:
        with pytest.raises(ValidationError):
            StrategySpec.model_validate(_patched_c1(capital={"initial": initial}))

    def test_14_capital_int_widens_but_string_rejected(self) -> None:
        # int -> float widening is lossless and allowed (OQ-0014 precedent);
        # the string "100000" is NOT coerced (strict types, P3-T1 task text).
        spec = StrategySpec.model_validate(_patched_c1(capital={"initial": 100000}))
        assert spec.capital.initial == 100000.0
        with pytest.raises(ValidationError):
            StrategySpec.model_validate(_patched_c1(capital={"initial": "100000"}))

    @pytest.mark.parametrize("value", [0, -5])
    def test_15_nonpositive_sizing_value_rejected(self, value: float) -> None:
        sizing = {"method": "percent_of_equity", "value": value}
        with pytest.raises(ValidationError):
            StrategySpec.model_validate(_patched_c1(sizing=sizing))

    @pytest.mark.parametrize(
        ("field", "value"),
        [("fee_bps", -1), ("slippage_bps", -0.5), ("fixed_fee", -1)],
    )
    def test_16_negative_execution_costs_rejected(self, field: str, value: float) -> None:
        execution = {"fill": "next_open", field: value}
        with pytest.raises(ValidationError):
            StrategySpec.model_validate(_patched_c1(execution=execution))

    @pytest.mark.parametrize("stop", [0, 100, 150])
    def test_17_stop_loss_outside_open_interval_rejected(self, stop: float) -> None:
        # 4.1: 0 < stop_loss_pct < 100 -- the endpoints themselves fail.
        with pytest.raises(ValidationError):
            StrategySpec.model_validate(_patched_c1(risk={"stop_loss_pct": stop}))

    def test_18_take_profit_zero_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StrategySpec.model_validate(_patched_c1(risk={"take_profit_pct": 0}))

    def test_19_trailing_stop_zero_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StrategySpec.model_validate(_patched_c1(risk={"trailing_stop_pct": 0}))

    @pytest.mark.parametrize("bars", [0, -1])
    def test_20_max_holding_below_one_rejected(self, bars: int) -> None:
        with pytest.raises(ValidationError):
            StrategySpec.model_validate(_patched_c1(risk={"max_holding_bars": bars}))

    def test_21_unknown_top_level_field_rejected(self) -> None:
        spec = _c1()
        spec["nope"] = 1
        with pytest.raises(ValidationError, match=r"extra_forbidden|nope"):
            StrategySpec.model_validate(spec)

    def test_22_reserved_indicator_name_rejected(self) -> None:
        # 4.1: indicator names must not shadow open/high/low/close/volume
        # or reserved words (entry_long, exit_long, ...).
        spec = _c1()
        spec["indicators"]["close"] = {"type": "sma", "params": {"period": 5}}
        with pytest.raises(ValidationError, match="reserved"):
            StrategySpec.model_validate(spec)

    def test_23_indicator_name_outside_the_grammar_rejected(self) -> None:
        # ^[a-z][a-z0-9_]{0,31}$: must start with a lowercase letter.
        spec = _c1()
        spec["indicators"]["123bad"] = {"type": "sma", "params": {"period": 5}}
        with pytest.raises(ValidationError, match="does not match"):
            StrategySpec.model_validate(spec)


# ===========================================================================
# Section 3 -- rule grammar (ROADMAP 4.2)
# ===========================================================================


class TestRuleGrammar:
    def test_24_all_rule_with_zero_conditions_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Rules.model_validate({"entry_long": {"all": []}})

    def test_25_all_rule_with_21_conditions_rejected(self) -> None:
        flooded = [_SIMPLE_CONDITION] * 21
        with pytest.raises(ValidationError):
            Rules.model_validate({"entry_long": {"all": flooded}})

    def test_26_not_rule_parses_and_counts_depth(self) -> None:
        rules = Rules.model_validate({"entry_long": {"not": {"not": _SIMPLE_CONDITION}}})
        entry = rules.entry_long
        assert isinstance(entry, NotRule)
        assert isinstance(entry.condition, NotRule)
        assert isinstance(entry.condition.condition, Condition)
        assert rule_depth(entry) == 3  # not(1) -> not(2) -> condition(3)

    def test_27_depth_four_accepted(self) -> None:
        # all(1) > all(2) > all(3) > condition(4): at the limit, allowed.
        nested: dict[str, Any] = _SIMPLE_CONDITION
        for _ in range(3):
            nested = {"all": [nested]}
        rules = Rules.model_validate({"entry_long": nested})
        assert rule_depth(rules.entry_long) == 4

    def test_28_depth_five_rejected(self) -> None:
        nested: dict[str, Any] = _SIMPLE_CONDITION
        for _ in range(4):
            nested = {"all": [nested]}
        with pytest.raises(ValidationError, match="depth 5 exceeds"):
            Rules.model_validate({"entry_long": nested})

    def test_29_crosses_above_with_number_operand_accepted(self) -> None:
        # 4.2 puts no restriction on operand kinds per op; semantic sanity
        # (a constant crossing a series) is P3-T2's business.
        rules = Rules.model_validate(
            {"entry_long": {"all": [{"left": 3, "op": "crosses_above", "right": "fast"}]}}
        )
        cond = rules.entry_long.conditions[0]
        assert isinstance(cond.left, NumberOperand)
        assert cond.left.value == 3.0

    @pytest.mark.parametrize("op", ["==", "!=", "~"])
    def test_30_equality_and_unknown_ops_rejected(self, op: str) -> None:
        # "==" is intentionally absent in v1 (float equality is a footgun).
        with pytest.raises(ValidationError):
            Rules.model_validate({"entry_long": {"all": [{"left": "close", "op": op, "right": 1}]}})

    def test_31_raw_column_name_must_be_ohlcv(self) -> None:
        with pytest.raises(ValidationError, match="raw_column name must be one of"):
            Rules.model_validate(
                {
                    "entry_long": {
                        "all": [
                            {"left": {"kind": "raw_column", "name": "vwap"}, "op": ">", "right": 1}
                        ]
                    }
                }
            )

    @pytest.mark.parametrize("lag", [-1])
    def test_32_negative_lag_rejected(self, lag: int) -> None:
        # Negative lag = future data; forbidden by 4.2.
        with pytest.raises(ValidationError):
            Rules.model_validate(
                {
                    "entry_long": {
                        "all": [{"left": {"name": "fast", "lag": lag}, "op": ">", "right": 1}]
                    }
                }
            )

    def test_33_fully_tagged_document_parses_unchanged(self) -> None:
        # What P6 (parser) emits: explicit kind tags everywhere.
        tagged = {
            "entry_long": {
                "kind": "all",
                "conditions": [
                    {
                        "kind": "condition",
                        "left": {"kind": "indicator", "name": "fast", "output": "value", "lag": 0},
                        "op": ">",
                        "right": {"kind": "number", "value": 70},
                    }
                ],
            }
        }
        rules = Rules.model_validate(tagged)
        entry = rules.entry_long
        assert isinstance(entry, AllRule)
        cond = entry.conditions[0]
        assert isinstance(cond.left, IndicatorOperand)
        assert cond.left.output == "value"
        assert isinstance(cond.right, NumberOperand)
        assert rule_depth(entry) == 2

    def test_34_dotted_indicator_reference_parses(self) -> None:
        # 4.2: "Multi-output indicators are referenced as name.output".
        cond = Condition.model_validate({"left": "macd.line", "op": ">", "right": 0})
        left = cond.left
        assert isinstance(left, IndicatorOperand)
        assert left.name == "macd"
        assert left.output == "line"

    def test_35_lagged_dict_operand_parses(self) -> None:
        # 4.2: {"name": <ref>, "lag": int >= 0} is an Operand spelling.
        cond = Condition.model_validate(
            {"left": {"name": "rsi14", "lag": 2}, "op": "<", "right": 30}
        )
        left = cond.left
        assert isinstance(left, IndicatorOperand)
        assert left.name == "rsi14"
        assert left.lag == 2


# ===========================================================================
# Section 4 -- defaults (ROADMAP 4.1 table)
# ===========================================================================


class TestDefaults:
    def test_36_execution_defaults_match_the_table(self) -> None:
        # "fee_bps / slippage_bps | number | no | 5 / 5", fixed_fee 0,
        # fill next_open (Appendix C fixtures confirm all three).
        execution = Execution()
        assert execution.fill == "next_open"
        assert execution.fee_bps == 5.0
        assert execution.slippage_bps == 5.0
        assert execution.fixed_fee == 0.0

    def test_37_risk_defaults_are_all_none(self) -> None:
        risk = Risk()
        assert risk.stop_loss_pct is None
        assert risk.take_profit_pct is None
        assert risk.trailing_stop_pct is None
        assert risk.max_holding_bars is None

    def test_38_list_defaults_are_empty_and_spec_defaults_apply(self) -> None:
        # C1 without the explicit risk/execution blocks: component defaults
        # must fill in, and parser-populated lists default to [].
        spec_dict = _c1()
        del spec_dict["risk"]
        del spec_dict["execution"]
        spec = StrategySpec.model_validate(spec_dict)
        assert spec.assumptions == []
        assert spec.unsupported == []
        assert spec.risk == Risk()
        assert spec.execution == Execution()
        assert spec.execution.fee_bps == 5.0


# ===========================================================================
# Section 5 -- canary: extra="forbid" on EVERY model
# ===========================================================================


class TestExtraForbidCanary:
    CANARY_CASES: ClassVar[list[tuple[str, dict[str, Any]]]] = [
        ("NumberOperand", {"kind": "number", "value": 1}),
        ("IndicatorOperand", {"kind": "indicator", "name": "fast"}),
        ("RawColumnOperand", {"kind": "raw_column", "name": "close"}),
        ("Condition", {"left": "fast", "op": ">", "right": 1}),
        ("AllRule", {"kind": "all", "conditions": [_SIMPLE_CONDITION]}),
        ("AnyRule", {"kind": "any", "conditions": [_SIMPLE_CONDITION]}),
        ("NotRule", {"kind": "not", "condition": _SIMPLE_CONDITION}),
        ("Rules", {"entry_long": _SIMPLE_CONDITION}),
        ("Universe", {"symbols": ["SPY"], "interval": "1d"}),
        ("Period", {"start": "2024-01-01", "end": "2024-12-31"}),
        ("Capital", {"initial": 100000}),
        ("Sizing", {"method": "percent_of_equity", "value": 50}),
        ("Execution", {}),
        ("Risk", {}),
        ("IndicatorDef", {"type": "sma", "params": {"period": 5}}),
        ("Assumption", {"field": "x", "value": 1, "reason": "y"}),
    ]

    @staticmethod
    def _model_for(name: str) -> Any:
        return {
            "NumberOperand": NumberOperand,
            "IndicatorOperand": IndicatorOperand,
            "RawColumnOperand": RawColumnOperand,
            "Condition": Condition,
            "AllRule": AllRule,
            "AnyRule": AnyRule,
            "NotRule": NotRule,
            "Rules": Rules,
            "Universe": Universe,
            "Period": Period,
            "Capital": Capital,
            "Sizing": Sizing,
            "Execution": Execution,
            "Risk": Risk,
            "IndicatorDef": IndicatorDef,
            "Assumption": Assumption,
        }[name]

    @pytest.mark.parametrize(("model_name", "valid_input"), CANARY_CASES)
    def test_39_extra_field_rejected_on_every_model(
        self, model_name: str, valid_input: dict[str, Any]
    ) -> None:
        poisoned = dict(valid_input)
        poisoned["totally_unknown"] = 1
        with pytest.raises(ValidationError, match="totally_unknown"):
            self._model_for(model_name).model_validate(poisoned)

    def test_40_extra_field_rejected_on_strategy_spec(self) -> None:
        spec = _c1()
        spec["totally_unknown"] = 1
        with pytest.raises(ValidationError, match="totally_unknown"):
            StrategySpec.model_validate(spec)
