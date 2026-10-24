"""P5-T2 trade-based metrics (§4.7 + owner rulings OQ-0073/OQ-0074).

Trade-like objects are built directly (SimpleNamespace) — no engine import.
Every expected value is HAND-DERIVED with the arithmetic shown in each
docstring and cross-checked against an independent numpy oracle.
"""

from __future__ import annotations

import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from nlbt.metrics import compute_trade_metrics

# --------------------------------------------------------------- 6-trade example
# net_pnl    = [+120, -60, +80, -30, -10, +40]      (zero costs: gross == net)
# return_pct = [+0.12, -0.06, +0.08, -0.03, -0.01, +0.04]
#   win_rate           = 3 wins / 6 trades = 0.5
#   profit factor      = (120+80+40) / |(-60-30-10)| = 240 / 100 = 2.4   [NET basis]
#   expectancy         = (0.12-0.06+0.08-0.03-0.01+0.04) / 6 = 0.14/6
#   avg_win            = (0.12+0.08+0.04) / 3 = 0.24/3 = 0.08
#   avg_loss           = (-0.06-0.03-0.01) / 3 = -0.10/3
#   streak sequence     = W L W L L W -> longest losing streak = 2
# --------------------------------------------------------------------------- #

SIX_NET = [120.0, -60.0, 80.0, -30.0, -10.0, 40.0]
SIX_RET = [0.12, -0.06, 0.08, -0.03, -0.01, 0.04]
FLAT_MASK_10 = np.array([False] * 10)


def _t(net: float, ret: float, gross: float | None = None) -> SimpleNamespace:
    return SimpleNamespace(net_pnl=net, return_pct=ret, gross_pnl=net if gross is None else gross)


def _trades6() -> list[SimpleNamespace]:
    return [_t(n, r) for n, r in zip(SIX_NET, SIX_RET, strict=True)]


def _oracle(net: np.ndarray, ret: np.ndarray) -> dict[str, float]:
    """Independent numpy oracle — vectorised splits, no implementation code."""
    wins = net > 0
    losses = net < 0
    longest = current = 0
    for value in net:
        current = current + 1 if value < 0 else 0
        longest = max(longest, current)
    return {
        "win_rate": float(np.mean(wins)),
        "profit_factor": float(np.sum(net[wins]) / abs(np.sum(net[losses]))),
        "expectancy": float(np.mean(ret)),
        "avg_win": float(np.mean(ret[wins])),
        "avg_loss": float(np.mean(ret[losses])),
        "longest_losing_streak": float(longest),
    }


def test_six_trade_hand_computed_values() -> None:
    """All six hand constants; arithmetic in the module docstring."""
    metrics, warnings = compute_trade_metrics(_trades6(), FLAT_MASK_10)
    assert metrics["win_rate"] == pytest.approx(0.5, rel=1e-12)
    assert metrics["profit_factor"] == pytest.approx(2.4, rel=1e-12)  # 240/100, NET
    assert metrics["expectancy"] == pytest.approx(0.14 / 6, rel=1e-12)
    assert metrics["avg_win"] == pytest.approx(0.08, rel=1e-12)
    assert metrics["avg_loss"] == pytest.approx(-0.10 / 3, rel=1e-12)
    assert metrics["longest_losing_streak"] == 2.0
    assert metrics["num_trades"] == 6.0
    assert warnings == []


def test_six_trade_numpy_oracle_agrees() -> None:
    """Independent oracle (np.mean/np.sum splits) on the hand arrays."""
    net = np.array(SIX_NET)
    ret = np.array(SIX_RET)
    metrics, _ = compute_trade_metrics(_trades6(), FLAT_MASK_10)
    for key, expected in _oracle(net, ret).items():
        assert metrics[key] == pytest.approx(expected, rel=1e-12), key


def test_profit_factor_uses_net_not_gross() -> None:
    """OQ-0074: gross_pnl > 0 but net_pnl < 0 counts as a LOSS.
    trades: net [+10, -5], gross [+10, +20] -> PF = 10/5 = 2.0 (a gross
    basis would see no negative gross at all)."""
    trades = [_t(10.0, 0.01, gross=10.0), _t(-5.0, -0.02, gross=20.0)]
    metrics, warnings = compute_trade_metrics(trades, np.array([True, True, False]))
    assert metrics["profit_factor"] == pytest.approx(2.0, rel=1e-12)
    assert metrics["win_rate"] == pytest.approx(0.5, rel=1e-12)
    assert metrics["avg_loss"] == pytest.approx(-0.02, rel=1e-12)
    assert warnings == []


def test_breakeven_resets_streak_and_is_neither_win_nor_loss() -> None:
    """net_pnl == 0: resets the streak, is not a win, is not in avg_loss,
    but still counts in num_trades and expectancy (OQ-0073 ruling).
    net [+100, -50, 0, -30]: streak = 1 (0 resets), win_rate = 1/4,
    avg_loss = (-0.05 + -0.03)/2 = -0.04, expectancy = 0.02/4 = 0.005."""
    trades = [_t(100.0, 0.10), _t(-50.0, -0.05), _t(0.0, 0.0), _t(-30.0, -0.03)]
    metrics, warnings = compute_trade_metrics(trades, FLAT_MASK_10)
    assert metrics["longest_losing_streak"] == 1.0
    assert metrics["win_rate"] == pytest.approx(0.25, rel=1e-12)
    assert metrics["avg_loss"] == pytest.approx(-0.04, rel=1e-12)
    assert metrics["expectancy"] == pytest.approx(0.005, rel=1e-12)
    assert metrics["num_trades"] == 4.0
    assert warnings == []


def test_exposure_from_mask() -> None:
    """10-bar mask True on bars 2-6 (inclusive) -> 5/10 = 0.5."""
    mask = np.zeros(10, dtype=bool)
    mask[2:7] = True  # bars 2,3,4,5,6
    metrics, _ = compute_trade_metrics(_trades6(), mask)
    assert metrics["exposure"] == pytest.approx(0.5, rel=1e-12)


def test_exposure_empty_mask_null_with_warning() -> None:
    metrics, warnings = compute_trade_metrics(_trades6(), np.array([], dtype=bool))
    assert metrics["exposure"] is None
    assert any("exposure" in w for w in warnings), warnings


def test_no_trades_all_null_except_count() -> None:
    """No trades: everything None except num_trades 0.0, with a warning.
    (Empty mask here: exposure is independently null on an empty series.)"""
    metrics, warnings = compute_trade_metrics([], np.array([], dtype=bool))
    for key, value in metrics.items():
        if key == "num_trades":
            assert value == 0.0
        else:
            assert value is None, key
    assert any("no trades" in w for w in warnings), warnings


def test_no_losses_profit_factor_null_with_flag() -> None:
    """§4.7: profit factor null + a flag when there are no losses — the
    warning IS the flag (OQ-0074)."""
    trades = [_t(10.0, 0.01), _t(20.0, 0.02)]
    metrics, warnings = compute_trade_metrics(trades, FLAT_MASK_10)
    assert metrics["profit_factor"] is None
    assert any("profit factor" in w and "no losses" in w for w in warnings), warnings
    assert metrics["avg_loss"] is None  # no losing trades either
    assert metrics["win_rate"] == pytest.approx(1.0, rel=1e-12)


def test_no_winners_avg_win_null() -> None:
    trades = [_t(-10.0, -0.01), _t(-20.0, -0.02)]
    metrics, warnings = compute_trade_metrics(trades, FLAT_MASK_10)
    assert metrics["avg_win"] is None
    assert any("avg_win" in w for w in warnings), warnings
    assert metrics["avg_loss"] == pytest.approx(-0.015, rel=1e-12)
    assert metrics["win_rate"] == 0.0  # defined: 0 wins / 2 trades


def test_no_losers_avg_loss_null() -> None:
    trades = [_t(10.0, 0.01), _t(20.0, 0.02)]
    metrics, warnings = compute_trade_metrics(trades, FLAT_MASK_10)
    assert metrics["avg_loss"] is None
    assert any("avg_loss" in w for w in warnings), warnings
    assert metrics["avg_win"] == pytest.approx(0.015, rel=1e-12)


def test_every_value_none_or_finite_never_nan_inf() -> None:
    """I13: across null-heavy and normal cases, every value is None or finite."""
    cases = [
        ([], np.array([], dtype=bool)),
        ([_t(10.0, 0.01)], FLAT_MASK_10),
        (_trades6(), FLAT_MASK_10),
        ([_t(-10.0, -0.01)], FLAT_MASK_10),
    ]
    for trades, mask in cases:
        metrics, _ = compute_trade_metrics(trades, mask)
        for key, value in metrics.items():
            if value is None:
                continue
            assert math.isfinite(float(value)), (key, value)


def test_metrics_package_never_imports_engine() -> None:
    """Boundary: nlbt.metrics (all modules) must not import nlbt.engine."""
    metrics_dir = Path(__file__).resolve().parents[2] / "src" / "nlbt" / "metrics"
    assert metrics_dir.is_dir(), "nlbt.metrics package missing"
    sources = {p.name: p.read_text(encoding="utf-8") for p in sorted(metrics_dir.glob("*.py"))}
    assert "trades.py" in sources, "trades.py missing from the scan"
    for name, text in sources.items():
        for line in text.splitlines():
            stripped = line.strip()
            assert "import nlbt.engine" not in stripped, (name, stripped)
            assert "from nlbt.engine" not in stripped, (name, stripped)
