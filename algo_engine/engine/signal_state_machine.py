"""
Algo Engine v1.0 — Signal State Machine
Manages signal lifecycle: DETECTED -> ACTIVE -> HIT_SL/HIT_TP/EXPIRED
"""

import time
import uuid
from enum import Enum
from typing import Dict, List, Optional, Any


class SignalState(Enum):
    DETECTED = "DETECTED"      # Newly formed, not yet acted upon
    ACTIVE = "ACTIVE"          # Price entered the zone, position should be open
    SL_HIT = "SL_HIT"          # Stop loss triggered
    TP_HIT = "TP_HIT"          # Take profit triggered
    EXPIRED = "EXPIRED"        # Signal expired without action
    INVALID = "INVALID"        # Failed validation checks


class Signal:
    """A single trading signal with full lifecycle tracking."""

    def __init__(
        self,
        symbol: str,
        interval: str,
        direction: str,  # 'long' or 'short'
        entry_zone_low: float,
        entry_zone_high: float,
        sl_price: float,
        tp_price: float,
        confidence: str,  # 'HIGH', 'MEDIUM', 'LOW'
        components: List[str],
        score: float,
        reasoning: List[str],
        regime: Dict,
    ):
        self.id = str(uuid.uuid4())[:8]
        self.symbol = symbol
        self.interval = interval
        self.direction = direction
        self.entry_zone_low = entry_zone_low
        self.entry_zone_high = entry_zone_high
        self.sl_price = sl_price
        self.tp_price = tp_price
        self.confidence = confidence
        self.components = components
        self.score = score
        self.reasoning = reasoning
        self.regime = regime

        self.state = SignalState.DETECTED
        self.detected_at = int(time.time())
        self.activated_at = None
        self.closed_at = None
        self.entry_price = None
        self.exit_price = None
        self.pnl_pct = None
        self.bars_held = 0
        self.max_bars = 30  # Expire after 30 candles without action
        self.expiry_time = self.detected_at + 7200  # 2 hours

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "interval": self.interval,
            "direction": self.direction,
            "state": self.state.value,
            "entry_zone": {"low": self.entry_zone_low, "high": self.entry_zone_high},
            "sl_price": self.sl_price,
            "tp_price": self.tp_price,
            "confidence": self.confidence,
            "components": self.components,
            "score": self.score,
            "reasoning": self.reasoning,
            "regime": self.regime,
            "detected_at": self.detected_at,
            "activated_at": self.activated_at,
            "closed_at": self.closed_at,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "pnl_pct": self.pnl_pct,
            "bars_held": self.bars_held,
        }


class SignalStateMachine:
    """Manages all active signals through their lifecycle."""

    def __init__(self, max_age_candles: int = 30, max_age_seconds: int = 7200):
        self.signals: Dict[str, Signal] = {}
        self.history: List[Dict] = []
        self.max_age_candles = max_age_candles
        self.max_age_seconds = max_age_seconds

    def add_signal(self, signal: Signal) -> str:
        """Add a new DETECTED signal. Returns the signal ID."""
        # Avoid duplicates: same direction + same price level within 0.3%
        for sig in self.signals.values():
            if sig.state not in (SignalState.DETECTED, SignalState.ACTIVE):
                continue
            if sig.symbol != signal.symbol or sig.direction != signal.direction:
                continue
            price_diff = abs(sig.entry_zone_low - signal.entry_zone_low) / max(sig.entry_zone_low, 0.01)
            if price_diff < 0.003:  # 0.3% proximity
                # Keep the stronger signal
                if signal.score > sig.score:
                    self.signals[sig.id] = signal
                    return signal.id
                return sig.id

        self.signals[signal.id] = signal
        return signal.id

    def check_price(self, symbol: str, current_price: float, low: float, high: float, candle_close: float, volume: float) -> List[Dict]:
        """
        Update signal states based on new candle data.
        Returns list of state transitions (for event emission).
        """
        transitions = []
        now = int(time.time())
        to_remove = []

        for sig_id, sig in self.signals.items():
            if sig.symbol != symbol:
                continue

            sig.bars_held += 1

            # Check expiry
            if sig.bars_held > self.max_age_candles or now > sig.expiry_time:
                old_state = sig.state
                sig.state = SignalState.EXPIRED
                sig.closed_at = now
                transitions.append({"id": sig_id, "from": old_state.value, "to": "EXPIRED", "reason": "expired"})
                to_remove.append(sig_id)
                continue

            # DETECTED -> ACTIVE: price enters the zone
            if sig.state == SignalState.DETECTED:
                if sig.direction == "long":
                    if low <= sig.entry_zone_high and candle_close > sig.entry_zone_low:
                        sig.state = SignalState.ACTIVE
                        sig.activated_at = now
                        sig.entry_price = candle_close
                        transitions.append({"id": sig_id, "from": "DETECTED", "to": "ACTIVE",
                                          "reason": f"Price entered long zone at {candle_close:.2f}"})
                else:  # short
                    if high >= sig.entry_zone_low and candle_close < sig.entry_zone_high:
                        sig.state = SignalState.ACTIVE
                        sig.activated_at = now
                        sig.entry_price = candle_close
                        transitions.append({"id": sig_id, "from": "DETECTED", "to": "ACTIVE",
                                          "reason": f"Price entered short zone at {candle_close:.2f}"})

            # ACTIVE -> SL_HIT or TP_HIT
            if sig.state == SignalState.ACTIVE:
                if sig.direction == "long":
                    if low <= sig.sl_price:
                        sig.state = SignalState.SL_HIT
                        sig.closed_at = now
                        sig.exit_price = sig.sl_price
                        sig.pnl_pct = ((sig.sl_price / sig.entry_price) - 1) * 100 if sig.entry_price else 0
                        transitions.append({"id": sig_id, "from": "ACTIVE", "to": "SL_HIT",
                                          "reason": f"SL hit at {sig.sl_price:.2f}, PnL: {sig.pnl_pct:.2f}%"})
                        to_remove.append(sig_id)
                    elif high >= sig.tp_price:
                        sig.state = SignalState.TP_HIT
                        sig.closed_at = now
                        sig.exit_price = sig.tp_price
                        sig.pnl_pct = ((sig.tp_price / sig.entry_price) - 1) * 100 if sig.entry_price else 0
                        transitions.append({"id": sig_id, "from": "ACTIVE", "to": "TP_HIT",
                                          "reason": f"TP hit at {sig.tp_price:.2f}, PnL: {sig.pnl_pct:.2f}%"})
                        to_remove.append(sig_id)
                else:  # short
                    if high >= sig.sl_price:
                        sig.state = SignalState.SL_HIT
                        sig.closed_at = now
                        sig.exit_price = sig.sl_price
                        sig.pnl_pct = ((sig.entry_price / sig.sl_price) - 1) * 100 if sig.sl_price else 0
                        transitions.append({"id": sig_id, "from": "ACTIVE", "to": "SL_HIT",
                                          "reason": f"SL hit at {sig.sl_price:.2f}, PnL: {sig.pnl_pct:.2f}%"})
                        to_remove.append(sig_id)
                    elif low <= sig.tp_price:
                        sig.state = SignalState.TP_HIT
                        sig.closed_at = now
                        sig.exit_price = sig.tp_price
                        sig.pnl_pct = ((sig.entry_price / sig.tp_price) - 1) * 100 if sig.tp_price else 0
                        transitions.append({"id": sig_id, "from": "ACTIVE", "to": "TP_HIT",
                                          "reason": f"TP hit at {sig.tp_price:.2f}, PnL: {sig.pnl_pct:.2f}%"})
                        to_remove.append(sig_id)

        # Archive removed signals to history
        for sig_id in to_remove:
            sig = self.signals.pop(sig_id, None)
            if sig:
                self.history.append(sig.to_dict())

        return transitions

    def get_active_signals(self, symbol: str = None) -> List[Dict]:
        """Get all active (DETECTED or ACTIVE) signals."""
        result = []
        for sig in self.signals.values():
            if sig.state not in (SignalState.DETECTED, SignalState.ACTIVE):
                continue
            if symbol and sig.symbol != symbol:
                continue
            result.append(sig.to_dict())
        return result

    def get_history(self, limit: int = 50, symbol: str = None) -> List[Dict]:
        """Get closed signal history."""
        h = list(self.history)
        if symbol:
            h = [s for s in h if s.get("symbol") == symbol]
        return h[-limit:]

    def cleanup_stale(self) -> int:
        """Expire stale signals that have been DETECTED or ACTIVE too long.
        Returns the number of signals expired.
        """
        now = int(time.time())
        to_remove = []
        for sig_id, sig in self.signals.items():
            if sig.state == SignalState.DETECTED:
                # Expire DETECTED signals that haven't activated within max_age_candles
                if sig.bars_held > self.max_age_candles // 2:
                    sig.state = SignalState.EXPIRED
                    sig.closed_at = now
                    to_remove.append(sig_id)
            elif sig.state == SignalState.ACTIVE:
                # Expire ACTIVE signals that have been open too long
                if sig.bars_held > self.max_age_candles:
                    sig.state = SignalState.EXPIRED
                    sig.closed_at = now
                    to_remove.append(sig_id)
        for sig_id in to_remove:
            sig = self.signals.pop(sig_id, None)
            if sig:
                self.history.append(sig.to_dict())
        return len(to_remove)

    def get_stats(self) -> Dict:
        """Get win/loss statistics."""
        closed = [s for s in self.history if s.get("state") in ("SL_HIT", "TP_HIT")]
        total = len(closed)
        wins = sum(1 for s in closed if s.get("pnl_pct", 0) > 0)
        losses = total - wins
        return {
            "total": total,
            "active": sum(1 for s in self.signals.values() if s.state in (SignalState.DETECTED, SignalState.ACTIVE)),
            "wins": wins,
            "losses": losses,
            "win_rate": round(wins / total * 100, 1) if total > 0 else 0,
            "total_pnl": round(sum(s.get("pnl_pct", 0) for s in closed), 2),
        }
