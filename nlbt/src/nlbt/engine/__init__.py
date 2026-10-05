"""Backtest engine (ROADMAP Phase 4): the deterministic core.

Module map (§3.4 / P4-T1..T8), imported lazily-by-submodule so this package
initialisation stays cycle-free:

* :mod:`nlbt.engine.ledger` — cash, position, fees, equity (P4-T1, L1-L10)
* :mod:`nlbt.engine.signals` — vectorised lookahead-free rules (P4-T2, S1-S12)
* :mod:`nlbt.engine.execution` — slippage, fees, gap fills (P4-T3, E1-E8)
* :mod:`nlbt.engine.sizing` — §4.5 position sizing (P4-T6, SZ1-SZ8)
* :mod:`nlbt.engine.risk` — stop/take-profit/trailing/time exits (P4-T5, R1-R11)
* :mod:`nlbt.engine.backtest` — the §4.5 bar loop: ``run(spec, bars)`` (P4-T4)

Import the submodules directly, e.g.
``from nlbt.engine.backtest import run``. The engine depends only on
``nlbt.spec``/``nlbt.data``/``nlbt.indicators``/``nlbt.errors`` and
pandas/numpy — never on the NL/LLM layer (§3.2 import boundary,
tests/unit/test_import_boundaries.py).
"""
