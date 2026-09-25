"""P3-T5 tests: deterministic spec -> English renderer (nlbt.spec.render).

Sections per the task's numbered tests:

1. SNAPSHOT (tests 1-12): substrings of the C1/C2/C3 renderings,
   including the task's worked examples ("ALL of the following are
   true:", "fast crosses above slow", "rsi2 is strictly below 10").
2. MUTATION (tests 13-35 + canary 50): the ROADMAP's S8 gate -- every
   field of StrategySpec must affect the rendered text. Mutations are
   DEFINED ONCE (``MUTATIONS``) and shared by the individual parametrised
   tests and the canary loop, so the canary sweeps exactly what the
   numbered tests exercise. Deep model_copy + attribute writes are the
   mutation surface (probed: the spec models have no validate_assignment).
3. RULE RENDERING (tests 36-44): operand spellings (primary output
   suppressed, dotted outputs, lag suffix), number normalisation
   (5.0 -> "5", 2.5 -> "2.5"), all/any/not headers, nested rules.
4. EDGE CASES (tests 45-49): "(none — position held to end of data)",
   empty sections, determinism.
CANARY (test 50): runs ALL mutations against C1 and fails naming any
field whose mutation left the rendering unchanged.

Literal-only fields (spec_version, execution.fill) cannot be mutated to
a second valid value; they are documented exceptions (OQ-0047) --
``fill`` IS rendered and asserted, ``spec_version`` is a schema-pinned
constant.

Determinism: the renderer is pure templates -- no LLM, no randomness,
no clock. C1/C2/C3 fixtures are verbatim ROADMAP Appendix C (in sync
with the other spec test files). The clock is frozen via the P3-T1
injection point so the fixtures never age out.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import pytest

from nlbt.spec import models as spec_models
from nlbt.spec.models import AllRule, AnyRule, Assumption, NotRule, StrategySpec
from nlbt.spec.render import render_rule, render_spec

FROZEN_TODAY = date(2025, 1, 1)


@pytest.fixture(autouse=True)
def _frozen_today(monkeypatch: pytest.MonkeyPatch) -> None:
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


def make_c1_spec() -> StrategySpec:
    return StrategySpec.model_validate(json.loads(_C1_JSON))


def make_c2_spec() -> StrategySpec:
    return StrategySpec.model_validate(json.loads(_C2_JSON))


def make_c3_spec() -> StrategySpec:
    return StrategySpec.model_validate(json.loads(_C3_JSON))


def _new_entry_rule() -> AllRule:
    return AllRule.model_validate(
        {"kind": "all", "conditions": [{"left": "fast", "op": ">", "right": "slow"}]}
    )


def _add_ghost_indicator(s: StrategySpec) -> None:
    """Add an indicator whose TYPE is not in the registry (E_SPEC_REF)."""
    ghost = s.indicators["fast"].model_copy(deep=True)
    ghost.type = "nope"
    s.indicators["ghost"] = ghost


#: The mutation table: (field_path, mutator). Shared by Section 2's
#: parametrised tests AND the canary, so coverage is one source of truth.
MUTATIONS: list[tuple[str, Any]] = [
    ("name", lambda s: setattr(s, "name", "Different Name")),
    ("universe.symbols", lambda s: setattr(s.universe, "symbols", ["GOOG"])),
    ("universe.interval", lambda s: setattr(s.universe, "interval", "1h")),
    ("period.start", lambda s: setattr(s.period, "start", date(2011, 6, 1))),
    ("period.end", lambda s: setattr(s.period, "end", date(2024, 6, 30))),
    ("indicators.<n>.type", lambda s: setattr(s.indicators["fast"], "type", "ema")),
    ("indicators.<n>.params", lambda s: s.indicators["fast"].params.update({"period": 60})),
    ("indicators.<n>.source", lambda s: setattr(s.indicators["fast"], "source", "open")),
    ("rules.entry_long", lambda s: setattr(s.rules, "entry_long", _new_entry_rule())),
    ("rules.exit_long", lambda s: setattr(s.rules, "exit_long", None)),
    ("risk.stop_loss_pct", lambda s: setattr(s.risk, "stop_loss_pct", 5)),
    ("risk.take_profit_pct", lambda s: setattr(s.risk, "take_profit_pct", 15)),
    ("risk.trailing_stop_pct", lambda s: setattr(s.risk, "trailing_stop_pct", 8)),
    ("risk.max_holding_bars", lambda s: setattr(s.risk, "max_holding_bars", 20)),
    ("sizing.method", lambda s: setattr(s.sizing, "method", "fixed_cash")),
    ("sizing.value", lambda s: setattr(s.sizing, "value", 75)),
    ("sizing.allow_fractional", lambda s: setattr(s.sizing, "allow_fractional", False)),
    ("execution.fee_bps", lambda s: setattr(s.execution, "fee_bps", 9)),
    ("execution.slippage_bps", lambda s: setattr(s.execution, "slippage_bps", 3)),
    ("execution.fixed_fee", lambda s: setattr(s.execution, "fixed_fee", 1)),
    ("capital.initial", lambda s: setattr(s.capital, "initial", 123456)),
    ("capital.currency", lambda s: setattr(s.capital, "currency", "EUR")),
    (
        "assumptions",
        lambda s: setattr(
            s,
            "assumptions",
            [Assumption(field="execution.fee_bps", value=5, reason="default")],
        ),
    ),
    ("unsupported", lambda s: setattr(s, "unsupported", ["short selling"])),
]


def _mutated(base: StrategySpec, mutator: Any) -> StrategySpec:
    mutant = base.model_copy(deep=True)
    mutator(mutant)
    return mutant


# ===========================================================================
# SECTION 1 -- snapshot tests (task tests 1-12)
# ===========================================================================


class TestSnapshots:
    def test_01_name_rendered(self) -> None:
        assert "SMA 50/200 golden cross" in render_spec(make_c1_spec())

    def test_02_symbol_rendered(self) -> None:
        assert "SPY" in render_spec(make_c1_spec())

    def test_03_period_start_rendered(self) -> None:
        assert "2010-01-01" in render_spec(make_c1_spec())

    def test_04_period_end_rendered(self) -> None:
        assert "2024-12-31" in render_spec(make_c1_spec())

    def test_05_indicator_type_rendered(self) -> None:
        assert "sma" in render_spec(make_c1_spec())

    def test_06_entry_op_rendered_as_english(self) -> None:
        text = render_spec(make_c1_spec())
        assert "crosses above" in text
        assert "fast crosses above slow" in text  # task's worked example
        assert "ALL of the following are true:" in text

    def test_07_exit_op_rendered_as_english(self) -> None:
        assert "crosses below" in render_spec(make_c1_spec())

    def test_08_c2_rsi_condition_rendered(self) -> None:
        # Task's worked example: "rsi2 is strictly below 10".
        assert "rsi2 is strictly below 10" in render_spec(make_c2_spec())

    def test_09_c2_stop_loss_label_rendered(self) -> None:
        assert "Stop loss" in render_spec(make_c2_spec())

    def test_10_c2_stop_loss_value_rendered(self) -> None:
        assert "6%" in render_spec(make_c2_spec())

    def test_11_c3_trailing_stop_rendered(self) -> None:
        assert "trailing" in render_spec(make_c3_spec())

    def test_12_c3_sizing_method_rendered(self) -> None:
        assert "risk_per_trade" in render_spec(make_c3_spec())


# ===========================================================================
# SECTION 2 -- mutation tests (task tests 13-35)
# ===========================================================================


@pytest.mark.parametrize(
    ("field_path", "mutator"),
    MUTATIONS,
    ids=[field_path for field_path, _ in MUTATIONS],
)
class TestFieldMutations:
    def test_mutation_changes_output(self, field_path: str, mutator: Any) -> None:
        base_spec = make_c1_spec()
        base = render_spec(base_spec)
        assert render_spec(_mutated(base_spec, mutator)) != base, (
            f"Field {field_path} not rendered - mutation had no effect"
        )

    def test_mutation_is_visible_as_substring(self, field_path: str, mutator: Any) -> None:
        """Stronger than test_mutation_changes_output for scalar fields:
        the NEW value (or its normalised form) must actually appear in the
        mutated rendering, not merely differ somewhere."""
        base_spec = make_c1_spec()
        mutant = _mutated(base_spec, mutator)
        rendered = render_spec(mutant)
        assert rendered != render_spec(base_spec)
        # For the swaps the task names, the new value shows up verbatim.
        visible: dict[str, str] = {
            "name": "Different Name",
            "universe.symbols": "GOOG",
            "universe.interval": "1h",
            "period.start": "2011-06-01",
            "period.end": "2024-06-30",
            "indicators.<n>.type": "ema",
            "indicators.<n>.params": "period=60",
            "indicators.<n>.source": "open",
            "sizing.method": "fixed_cash",
            "sizing.value": "75",
            "sizing.allow_fractional": "no",
            "execution.fee_bps": "9 bps",
            "execution.slippage_bps": "3 bps",
            "execution.fixed_fee": "1 per trade",
            "capital.initial": "123456",
            "capital.currency": "EUR",
        }
        if field_path in visible:
            assert visible[field_path] in rendered, (
                f"mutation of {field_path} changed the text but the new "
                f"value {visible[field_path]!r} is not visible"
            )


# ===========================================================================
# SECTION 3 -- rule rendering (task tests 36-44)
# ===========================================================================


class TestRuleRendering:
    def _condition(self, raw: dict[str, Any]) -> Any:
        from nlbt.spec.models import Condition

        return Condition.model_validate(raw)

    def test_36_primary_output_suppressed(self) -> None:
        text = render_rule(self._condition({"left": "ema_fast", "op": ">", "right": 100}))
        assert "ema_fast is strictly above 100" in text
        assert "ema_fast.value" not in text

    def test_37_dotted_output_rendered(self) -> None:
        text = render_rule(self._condition({"left": "macd.signal", "op": ">", "right": 0}))
        assert "macd.signal is strictly above 0" in text

    def test_38_lag_suffix_rendered(self) -> None:
        raw: dict[str, Any] = {"left": {"name": "ema_fast", "lag": 2}, "op": ">", "right": 100}
        text = render_rule(self._condition(raw))
        assert "ema_fast[t-2] is strictly above 100" in text

    def test_39_whole_number_renders_without_decimal(self) -> None:
        text = render_rule(self._condition({"left": "x", "op": ">", "right": 5.0}))
        assert "5" in text
        assert "5.0" not in text

    def test_40_fractional_number_renders_with_decimal(self) -> None:
        text = render_rule(self._condition({"left": "x", "op": ">", "right": 2.5}))
        assert "2.5" in text

    def test_41_all_rule_renders_every_condition(self) -> None:
        rule = AllRule.model_validate(
            {
                "kind": "all",
                "conditions": [
                    {"left": "a", "op": ">", "right": 1},
                    {"left": "b", "op": "<", "right": 2},
                ],
            }
        )
        text = render_rule(rule)
        assert "ALL of the following are true:" in text
        assert "a is strictly above 1" in text
        assert "b is strictly below 2" in text

    def test_42_any_rule_renders_any_header(self) -> None:
        rule = AnyRule.model_validate(
            {
                "kind": "any",
                "conditions": [
                    {"left": "a", "op": ">", "right": 1},
                    {"left": "b", "op": "<", "right": 2},
                ],
            }
        )
        assert "ANY of the following are true:" in render_rule(rule)

    def test_43_not_rule_renders_not_wrapper(self) -> None:
        rule = NotRule.model_validate(
            {"kind": "not", "condition": {"left": "a", "op": ">", "right": 1}}
        )
        text = render_rule(rule)
        assert "NOT (" in text
        assert "a is strictly above 1" in text
        assert ")" in text

    def test_44_nested_rule_renders_both_levels(self) -> None:
        # Attribute assignment bypasses validation (probed), so the new
        # entry rule must be a CONSTRUCTED model, not a raw dict.
        new_entry = AllRule.model_validate(
            {
                "kind": "all",
                "conditions": [{"any": [{"left": "fast", "op": ">", "right": "slow"}]}],
            }
        )

        def swap(s: StrategySpec) -> None:
            s.rules.entry_long = new_entry

        text = render_spec(_mutated(make_c1_spec(), swap))
        assert "ALL of the following are true:" in text
        assert "ANY of the following are true:" in text
        assert "fast is strictly above slow" in text


# ===========================================================================
# SECTION 4 -- edge cases (task tests 45-49)
# ===========================================================================


class TestEdgeCases:
    def test_45_no_exit_rule_placeholder(self) -> None:
        spec = _mutated(make_c1_spec(), lambda s: setattr(s.rules, "exit_long", None))
        assert "(none — position held to end of data)" in render_spec(spec)

    def test_46_all_risk_none_renders_none(self) -> None:
        text = render_spec(make_c1_spec())  # C1 risk = {}
        assert "RISK EXITS\n  (none)" in text

    def test_47_no_indicators_renders_none(self) -> None:
        spec = _mutated(make_c1_spec(), lambda s: setattr(s, "indicators", {}))
        assert "INDICATORS\n  (none)" in render_spec(spec)

    def test_48_no_assumptions_renders_none(self) -> None:
        assert "ASSUMPTIONS\n  (none)" in render_spec(make_c1_spec())

    def test_49_render_is_deterministic(self) -> None:
        spec = make_c1_spec()
        assert render_spec(spec) == render_spec(spec)


# ===========================================================================
# CANARY (task test 50): every field's mutation changes the output
# ===========================================================================


class TestMutationCanary:
    def test_all_mutations_change_output(self) -> None:
        """Coverage canary: every StrategySpec field must be rendered.

        Runs all 24 mutations (23 numbered fields + universe.interval);
        if ANY produces output identical to the base rendering, that
        field is not rendered and this fails loudly naming it.
        """
        base_spec = make_c1_spec()
        base = render_spec(base_spec)
        for field_path, mutator in MUTATIONS:
            rendered = render_spec(_mutated(base_spec, mutator))
            assert rendered != base, (
                f"Field {field_path} not rendered — mutation had no effect on output"
            )

    def test_50b_literal_only_fields_documented(self) -> None:
        """Two fields cannot participate in the mutation sweep and are
        documented exceptions (OQ-0047; S8's intent is that every field a
        USER can vary must be rendered):

        * ``execution.fill``: Literal["next_open"] in v1 -- no second
          value exists to mutate to (the fill line IS rendered);
        * ``spec_version``: Literal["1.0"] -- a constant pinned by the
          schema (P3-T1); printing a constant adds noise.
        """
        assert "Fill:      next_open (next bar open)" in render_spec(make_c1_spec())
        # Attribute writes skip validation, so a mutated copy must not
        # crash the renderer and must stay deterministic.
        spec = _mutated(make_c1_spec(), lambda s: setattr(s, "spec_version", "9.9"))
        assert render_spec(spec) == render_spec(spec)


# ===========================================================================
# VALIDATION integration (warnings/errors sections)
# ===========================================================================


class TestValidationIntegration:
    def test_warnings_section_renders_validate_spec_warnings(self) -> None:
        # W1: no exit mechanism at all (rule + risk both empty).
        spec = _mutated(make_c1_spec(), lambda s: setattr(s.rules, "exit_long", None))
        spec.risk = spec.risk.__class__()  # all-None defaults
        text = render_spec(spec)
        assert "- No exit mechanism defined. Position will be held until end of data." in text

    def test_errors_section_renders_semantic_errors(self) -> None:
        text = render_spec(_mutated(make_c1_spec(), _add_ghost_indicator))
        assert "VALIDATION ERRORS" in text
        assert "[E_SPEC_REF] indicators.ghost.type" in text
