"""P3-T4 tests: canonicalisation and hashing (nlbt.spec.canonical).

Five sections + canary, per the task's numbered tests:

1. NUMBER NORMALISATION (tests 1-5): whole floats -> int, everything
   else (str, bool, fractional floats) unchanged; recursion through
   dicts and lists.
2. CANONICAL DICT (tests 6-10): keys sorted at every nesting level;
   ``5`` vs ``5.0`` produce IDENTICAL canonical dicts; source_text /
   assumptions / unsupported are included in ``canonicalise`` but
   excluded from ``canonical_logic_dict``.
3. HASH PROPERTIES (tests 11-18): determinism, format
   ``sha256:`` + 64 hex chars = 71 chars, provenance changes move only
   the FULL hash, logic changes move BOTH hashes, distinct specs have
   distinct logic hashes.
4. JSON STRING PROPERTIES (tests 19-22): valid JSON, deterministic,
   structurally whitespace-free, keys already sorted.
5. SEMANTIC EQUIVALENCE (tests 23-24): key order in the SOURCE dict is
   irrelevant; ``5`` vs ``5.0`` spellings hash identically.
CANARY (test 25): raw ``json.dumps`` treats 5 and 5.0 differently
(mandated probe, recorded in verified_apis.md); canonicalisation makes
the two spellings hash identically.

The fee_bps int-vs-float pair is built with
``Execution.model_construct(fee_bps=...)`` (task instruction: bypass
coercion). Probed behaviour (verified_apis.md): model_dump serialises
float-typed fields as floats even when the attribute holds an int, so
for the SCHEMA-typed fee_bps the two dumps are ALREADY identical and
normalisation is belt-and-braces; for Any-typed values (indicator
``params``, ``Assumption.value``) the dump passes ints/floats through
verbatim, so the recursive normalisation is load-bearing exactly there
-- test_24 covers the params path explicitly (OQ-0045).

The clock is frozen via the P3-T1 injection point
(``nlbt.spec.models._get_today``) so the fixtures never age out.
"""

from __future__ import annotations

import copy
import json
from datetime import date
from typing import Any

import pytest

from nlbt.spec import models as spec_models
from nlbt.spec.canonical import (
    canonical_json,
    canonical_logic_dict,
    canonicalise,
    normalise_number,
    spec_hash_full,
    spec_hash_logic,
)
from nlbt.spec.models import Assumption, Execution, StrategySpec

FROZEN_TODAY = date(2025, 1, 1)


@pytest.fixture(autouse=True)
def _frozen_today(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(spec_models, "_get_today", lambda: FROZEN_TODAY)


# ---------------------------------------------------------------------------
# Appendix C1 -- verbatim from ROADMAP.md Appendix C (same literals as the
# other spec test files; kept in sync deliberately).
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


def make_c1_spec(**overrides: Any) -> StrategySpec:
    """The Appendix C1 spec as a validated StrategySpec (top-level overrides)."""
    spec_dict = json.loads(_C1_JSON)
    for key, value in overrides.items():
        spec_dict[key] = copy.deepcopy(value)
    return StrategySpec.model_validate(spec_dict)


def _with_int_fee(spec: StrategySpec) -> StrategySpec:
    """Same spec but execution.fee_bps stored as the INT 5.

    model_construct bypasses validation/coercion entirely (probed:
    Execution.model_construct(fee_bps=5) holds a Python int; a validated
    model would hold 5.0). The task mandates this construction path.
    """
    execution = Execution.model_construct(
        fill="next_open", fee_bps=5, slippage_bps=5.0, fixed_fee=0.0
    )
    clone = spec.model_copy(deep=True)
    clone.execution = execution
    return clone


# ===========================================================================
# SECTION 1 -- number normalisation (task tests 1-5)
# ===========================================================================


class TestNumberNormalisation:
    def test_01_whole_float_becomes_int(self) -> None:
        result = normalise_number(5.0)
        assert result == 5
        assert isinstance(result, int)

    def test_02_int_unchanged(self) -> None:
        result = normalise_number(5)
        assert result == 5
        assert isinstance(result, int)

    def test_03_fractional_float_unchanged(self) -> None:
        result = normalise_number(2.5)
        assert result == 2.5
        assert isinstance(result, float)

    def test_04_string_unchanged(self) -> None:
        assert normalise_number("hello") == "hello"

    def test_05_recursive_through_dicts_and_lists(self) -> None:
        result = normalise_number({"a": 5.0, "b": [1.0, 2.5, 3.0]})
        assert result == {"a": 5, "b": [1, 2.5, 3]}
        assert isinstance(result["a"], int)
        assert isinstance(result["b"][0], int)
        assert isinstance(result["b"][1], float)
        assert isinstance(result["b"][2], int)

    def test_05b_bool_is_never_normalised(self) -> None:
        # allow_fractional=True must not collapse to 1.
        result = normalise_number({"allow_fractional": True})
        assert result == {"allow_fractional": True}
        assert isinstance(result["allow_fractional"], bool)


# ===========================================================================
# SECTION 2 -- canonical dict (task tests 6-10)
# ===========================================================================


class TestCanonicalDict:
    def test_06_keys_sorted_at_all_nesting_levels(self) -> None:
        canonical = canonicalise(make_c1_spec())

        def assert_sorted(v: Any) -> None:
            if isinstance(v, dict):
                keys = list(v.keys())
                assert keys == sorted(keys), f"unsorted keys: {keys}"
                for item in v.values():
                    assert_sorted(item)
            elif isinstance(v, list):
                for item in v:
                    assert_sorted(item)

        assert_sorted(canonical)

    def test_07_fee_bps_5_and_5_0_identical_canonical_dicts(self) -> None:
        float_spec = make_c1_spec()  # validated: fee_bps stored as 5.0
        int_spec = _with_int_fee(float_spec)  # fee_bps stored as int 5
        assert int_spec.execution.fee_bps == 5
        assert not isinstance(int_spec.execution.fee_bps, float)
        assert canonicalise(float_spec) == canonicalise(int_spec)

    def test_08_source_text_included_in_full_excluded_from_logic(self) -> None:
        spec = make_c1_spec()
        spec.source_text = "Buy AAPL when the 20 EMA crosses above the 50 EMA..."
        full = canonicalise(spec)
        logic = canonical_logic_dict(spec)
        assert "source_text" in full
        assert full["source_text"] == spec.source_text
        assert "source_text" not in logic

    def test_09_assumptions_included_in_full_excluded_from_logic(self) -> None:
        spec = make_c1_spec()
        spec.assumptions = [
            Assumption(field="execution.fee_bps", value=5, reason="not specified; registry default")
        ]
        full = canonicalise(spec)
        logic = canonical_logic_dict(spec)
        assert len(full["assumptions"]) == 1
        assert "assumptions" not in logic

    def test_10_unsupported_included_in_full_excluded_from_logic(self) -> None:
        # unsupported must be empty for a VALIDATED spec (OQ-0035), so the
        # exclusion is checked on the dump level via model_construct.
        spec = make_c1_spec()
        assert spec.unsupported == []
        full = canonicalise(spec)
        logic = canonical_logic_dict(spec)
        assert "unsupported" in full
        assert full["unsupported"] == []
        assert "unsupported" not in logic

    def test_10b_defaults_are_filled_in_the_canonical_form(self) -> None:
        # model_dump always emits optional fields (probed): risk all-None,
        # execution defaults, empty lists -- part of the canonical form.
        canonical = canonicalise(make_c1_spec())
        assert canonical["risk"] == {
            "stop_loss_pct": None,
            "take_profit_pct": None,
            "trailing_stop_pct": None,
            "max_holding_bars": None,
        }
        assert canonical["execution"] == {
            "fill": "next_open",
            "fee_bps": 5,
            "slippage_bps": 5,
            "fixed_fee": 0,
        }
        assert canonical["source_text"] is None


# ===========================================================================
# SECTION 3 -- hash properties (task tests 11-18)
# ===========================================================================


class TestHashProperties:
    def test_11_logic_hash_deterministic(self) -> None:
        spec = make_c1_spec()
        assert spec_hash_logic(spec) == spec_hash_logic(spec)

    def test_12_full_hash_deterministic(self) -> None:
        spec = make_c1_spec()
        assert spec_hash_full(spec) == spec_hash_full(spec)

    def test_13_changing_fee_bps_changes_both_hashes(self) -> None:
        spec = make_c1_spec()
        changed = spec.model_copy(deep=True)
        changed.execution.fee_bps = 7.5
        assert spec_hash_logic(changed) != spec_hash_logic(spec)
        assert spec_hash_full(changed) != spec_hash_full(spec)

    def test_14_source_text_changes_full_not_logic(self) -> None:
        spec1 = make_c1_spec()
        spec1.source_text = None
        spec2 = make_c1_spec()
        spec2.source_text = (
            "Buy AAPL when the 20 EMA crosses above the 50 EMA and RSI is under 70..."
        )
        assert spec_hash_logic(spec1) == spec_hash_logic(spec2)
        assert spec_hash_full(spec1) != spec_hash_full(spec2)

    def test_15_changing_assumptions_changes_full_not_logic(self) -> None:
        spec1 = make_c1_spec()
        spec2 = make_c1_spec()
        spec2.assumptions = [
            Assumption(field="execution.fee_bps", value=5, reason="not specified; registry default")
        ]
        assert spec_hash_logic(spec1) == spec_hash_logic(spec2)
        assert spec_hash_full(spec1) != spec_hash_full(spec2)

    def test_16_hash_format_prefix(self) -> None:
        assert spec_hash_logic(make_c1_spec()).startswith("sha256:")
        assert spec_hash_full(make_c1_spec()).startswith("sha256:")

    def test_17_hash_length_is_71_chars(self) -> None:
        # Arithmetic (task mandate): sha256 hexdigest = 256 bits / 4 = 64
        # hex chars (probe: len(hashlib.sha256(b'test').hexdigest()) == 64);
        # prefix "sha256:" = 7 chars; 7 + 64 = 71.
        logic_hash = spec_hash_logic(make_c1_spec())
        full_hash = spec_hash_full(make_c1_spec())
        assert len(logic_hash) == 71
        assert len(full_hash) == 71

    def test_18_distinct_specs_distinct_logic_hashes(self) -> None:
        c1 = make_c1_spec()
        c2_dict = json.loads(_C2_JSON)
        c2 = StrategySpec.model_validate(c2_dict)
        assert spec_hash_logic(c1) != spec_hash_logic(c2)


# ===========================================================================
# SECTION 4 -- JSON string properties (task tests 19-22)
# ===========================================================================


class TestCanonicalJsonProperties:
    def test_19_canonical_json_is_valid_json(self) -> None:
        parsed = json.loads(canonical_json(make_c1_spec()))  # must not raise
        assert isinstance(parsed, dict)

    def test_20_canonical_json_deterministic(self) -> None:
        spec = make_c1_spec()
        assert canonical_json(spec) == canonical_json(spec)

    def test_21_no_whitespace_before_first_quote(self) -> None:
        spec = make_c1_spec()
        canonical = canonical_json(spec)
        # Task's literal check: nothing but '{' before the first quote...
        assert " " not in canonical.split('"')[0]
        assert canonical.startswith('{"')
        # ...plus a stronger structural check: removing ALL whitespace that
        # sits OUTSIDE string values must not change anything, i.e. the
        # only spaces are inside string values ("SMA 50/200 golden cross").
        assert canonical == _strip_whitespace_outside_strings(canonical)

    def test_22_key_order_already_sorted(self) -> None:
        canonical = canonical_json(make_c1_spec())
        re_dumped = json.dumps(json.loads(canonical), sort_keys=True, separators=(",", ":"))
        assert canonical == re_dumped


def _strip_whitespace_outside_strings(text: str) -> str:
    """Remove every space that is outside a JSON string literal."""
    out: list[str] = []
    in_string = False
    escaped = False
    for char in text:
        if in_string:
            out.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
            out.append(char)
        elif char != " ":
            out.append(char)
    return "".join(out)


# ===========================================================================
# SECTION 5 -- semantic equivalence (task tests 23-24)
# ===========================================================================


class TestSemanticEquivalence:
    def test_23_source_key_order_irrelevant(self) -> None:
        normal = make_c1_spec()
        shuffled_dict = _reverse_key_order(json.loads(_C1_JSON))
        shuffled = StrategySpec.model_validate(shuffled_dict)
        assert spec_hash_logic(normal) == spec_hash_logic(shuffled)
        assert spec_hash_full(normal) == spec_hash_full(shuffled)

    def test_24_params_5_vs_5_0_identical_logic_hashes(self) -> None:
        # The load-bearing normalisation path: indicator params are
        # Any-typed, so the dump passes 50 and 50.0 through VERBATIM
        # (probed) -- without normalise_number these two specs would hash
        # differently. fee_bps (a float-TYPED field) dumps as 5.0 either
        # way; params is where int-vs-float can actually diverge.
        p50 = make_c1_spec()
        p50_float = make_c1_spec()
        p50_float.indicators["fast"].params = {"period": 50.0}
        assert spec_hash_logic(p50) == spec_hash_logic(p50_float)
        assert canonical_json(p50) == canonical_json(p50_float)


def _reverse_key_order(value: Any) -> Any:
    """Deeply reverse dict key insertion order (semantics unchanged)."""
    if isinstance(value, dict):
        return {k: _reverse_key_order(value[k]) for k in reversed(list(value.keys()))}
    if isinstance(value, list):
        return [_reverse_key_order(item) for item in value]
    return value


# ===========================================================================
# CANARY (task test 25)
# ===========================================================================


class TestNormalisationCanary:
    def test_25_five_vs_five_point_zero(self) -> None:
        """json.dumps treats 5 and 5.0 differently. Our normalisation step
        fixes this so specs that are semantically identical hash
        identically.
        """
        # Premise, probed on this interpreter (verified_apis.md): raw
        # json.dumps renders the two spellings differently.
        assert json.dumps({"v": 5}) != json.dumps({"v": 5.0})
        # Through our canonicalisation: identical output for both.
        float_spec = make_c1_spec()
        int_spec = _with_int_fee(float_spec)
        assert canonical_json(float_spec) == canonical_json(int_spec)
        assert spec_hash_logic(float_spec) == spec_hash_logic(int_spec)
        assert spec_hash_full(float_spec) == spec_hash_full(int_spec)
