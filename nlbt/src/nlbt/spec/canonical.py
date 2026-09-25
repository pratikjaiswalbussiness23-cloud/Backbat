"""Canonicalisation and hashing of StrategySpec (ROADMAP P3-T4, §4.6, App. E).

A *canonical* form is a single deterministic representation for a whole
equivalence class of specs: two specs that differ only in dict key order or
in ``5`` vs ``5.0`` spellings must produce byte-identical canonical JSON and
therefore identical hashes (P3-T4 acceptance: "semantically identical specs
(different key order, ``5`` vs ``5.0``) hash equal; any logic change alters
the hash").

Two hashes per ROADMAP §4.6 / Appendix E (``"sha256:..."`` prefixed, 64 hex
chars -> 71 total):

* ``spec_hash_logic``  -- over the strategy LOGIC only: ``source_text``
  (provenance), ``assumptions`` (parser disclosures) and ``unsupported``
  (parser bookkeeping) are EXCLUDED; re-parsing the same sentence with
  richer assumptions must not change the logic hash;
* ``spec_hash_full``   -- over everything, provenance included.

Determinism contract (task mandate: "no randomness"):

* keys sorted recursively (and ``json.dumps(sort_keys=True)`` as belt);
* numbers normalised recursively: whole floats -> int (``5.0`` -> ``5``),
  with bool / NaN / inf guards (bool is NOT a number here; NaN/inf are
  never whole and are rejected by the spec layer anyway);
* defaults filled via ``model_dump(mode="json")`` (probed: pydantic ALWAYS
  emits optional fields with their defaults -- risk all-None,
  ``execution`` 5.0/5.0/0.0, ``assumptions: []``, ``unsupported: []``,
  ``source_text: null``) and dates as ISO strings;
* ``model_dump(mode="json")`` alone is NOT sufficient for int/float
  equality: float-TYPED fields serialise as floats even when the stored
  attribute is an int, while ``Any``-typed values (indicator ``params``,
  ``Assumption.value``) pass through verbatim -- so the recursive
  normalisation is load-bearing exactly there (OQ-0045).

Nothing here mutates the input spec; every call rebuilds the dicts from
scratch.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any, cast

from nlbt.spec.models import StrategySpec

__all__ = [
    "HASH_PREFIX",
    "canonical_json",
    "canonical_logic_dict",
    "canonical_logic_json",
    "canonicalise",
    "normalise_number",
    "spec_hash_full",
    "spec_hash_logic",
]

#: ROADMAP Appendix E manifest format: "sha256:<64 hex chars>".
HASH_PREFIX = "sha256:"

#: Provenance fields excluded from the LOGIC hash (task item 2; the ROADMAP
#: names source_text/assumptions, unsupported added as parser bookkeeping).
_LOGIC_EXCLUDED_FIELDS: tuple[str, ...] = ("source_text", "assumptions", "unsupported")


def normalise_number(v: Any) -> Any:
    """Normalise a value, RECURSIVELY through dicts and lists (task item 7).

    Scalars: whole floats -> int (``5.0 -> 5``), ``2.5`` stays ``2.5``.
    ``True``/``False`` are returned as-is: bool is not a number for
    canonicalisation (probed: ``isinstance(True, float)`` is False on this
    interpreter, so the explicit guard below is intent-documenting
    defence, not a live fix). NaN/inf are returned as-is (never whole,
    and the spec layer already rejects them in params).
    """
    if isinstance(v, dict):
        return {k: normalise_number(item) for k, item in v.items()}
    if isinstance(v, list):
        return [normalise_number(item) for item in v]
    if isinstance(v, bool):
        return v
    if isinstance(v, float) and not math.isinf(v) and not math.isnan(v) and v == int(v):
        return int(v)
    return v


def canonicalise(spec: StrategySpec) -> dict[str, Any]:
    """Canonical dict of the FULL spec (provenance included).

    Keys are sorted recursively so the dict ITSELF is deterministic, not
    just its JSON rendering (lists keep their order -- conditions are
    ordered semantics, sorting them would change meaning).
    """
    return cast(dict[str, Any], _sort_deep(normalise_number(_dump_json(spec))))


def _dump_json(spec: StrategySpec) -> dict[str, Any]:
    dump: dict[str, Any] = spec.model_dump(mode="json")
    return dump


def canonical_logic_dict(spec: StrategySpec) -> dict[str, Any]:
    """Canonical dict EXCLUDING provenance (source_text/assumptions/unsupported).

    Two specs differing only in those fields get identical logic hashes.
    Exclusion happens on the DUMP (before normalisation), so the removed
    keys can never influence anything downstream.
    """
    dump = _dump_json(spec)
    for field_name in _LOGIC_EXCLUDED_FIELDS:
        dump.pop(field_name, None)
    return cast(dict[str, Any], _sort_deep(normalise_number(dump)))


def _sort_deep(v: Any) -> Any:
    """Recursively rebuild dicts with sorted keys (lists keep their order --
    conditions are ordered semantics, sorting them would change meaning)."""
    if isinstance(v, dict):
        return {k: _sort_deep(v[k]) for k in sorted(v)}
    if isinstance(v, list):
        return [_sort_deep(item) for item in v]
    return v


def canonical_json(spec: StrategySpec) -> str:
    """Deterministic, whitespace-free canonical JSON of the FULL spec."""
    return json.dumps(canonicalise(spec), sort_keys=True, separators=(",", ":"))


def canonical_logic_json(spec: StrategySpec) -> str:
    """Deterministic, whitespace-free canonical JSON of the LOGIC spec."""
    return json.dumps(canonical_logic_dict(spec), sort_keys=True, separators=(",", ":"))


def spec_hash_full(spec: StrategySpec) -> str:
    """``"sha256:" + sha256(canonical_json(spec).encode("utf-8")).hexdigest()``."""
    return HASH_PREFIX + hashlib.sha256(canonical_json(spec).encode("utf-8")).hexdigest()


def spec_hash_logic(spec: StrategySpec) -> str:
    """``"sha256:" + sha256(canonical_logic_json(spec).encode("utf-8")).hexdigest()``."""
    return HASH_PREFIX + hashlib.sha256(canonical_logic_json(spec).encode("utf-8")).hexdigest()
