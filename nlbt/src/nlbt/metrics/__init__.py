"""Return-based metrics for the backtest result (ROADMAP §4.7, P5-T1).

Pure functions on a settled equity series; must never import
``nlbt.engine`` — the dependency runs engine -> metrics only.
"""

from __future__ import annotations

from nlbt.metrics.returns import compute_return_metrics

__all__ = ["compute_return_metrics"]
