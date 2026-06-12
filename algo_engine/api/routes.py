"""Algo Engine v1.0 - Flask API Routes"""
import json, time
from flask import Blueprint, jsonify, request, Response, stream_with_context
from ..engine.signal_orchestrator import SignalOrchestrator
from ..config import DEFAULT_SYMBOL, DEFAULT_INTERVAL

api = Blueprint("algo_engine", __name__, url_prefix="/api/v2")
orchestrator = SignalOrchestrator()


@api.route("/health")
def health():
    return jsonify({"status": "ok", "service": "algo-engine-v2"})


@api.route("/signal", methods=["POST"])
def generate_signal():
    """Generate a signal with Trend Gate + State Machine + Dynamic SL/TP."""
    body = request.get_json(silent=True) or {}
    symbol = body.get("symbol", DEFAULT_SYMBOL).upper()
    interval = body.get("interval", DEFAULT_INTERVAL)
    return jsonify(orchestrator.process_candle(symbol, interval))


@api.route("/state", methods=["GET"])
def get_state():
    """Get current state: active signals, history, stats."""
    symbol = request.args.get("symbol")
    return jsonify(orchestrator.get_state(symbol))


@api.route("/journal", methods=["GET"])
def get_journal():
    """Get trade journal history."""
    limit = request.args.get("limit", 50, type=int)
    symbol = request.args.get("symbol")
    from ..engine.trade_journal import TradeJournal
    tj = TradeJournal()
    return jsonify({"history": tj.history(limit=limit, symbol=symbol), "stats": tj.stats()})


@api.route("/stream")
def stream():
    """SSE endpoint for real-time signal updates (polls every 5s).

    Pushes candle data + active signals + journal + signal events
    so the frontend has everything it needs for the dashboard.
    """
    symbol = request.args.get("symbol", DEFAULT_SYMBOL).upper()
    interval = request.args.get("interval", DEFAULT_INTERVAL)
    from ..config import CANDLE_LIMIT_STREAM
    from ..engine.trade_journal import TradeJournal

    def generate():
        tj = TradeJournal()
        while True:
            try:
                # 1. Process signal (confluence + state machine)
                result = orchestrator.process_candle(symbol, interval)

                # 2. Fetch candle data for the price chart
                candles = []
                try:
                    raw = orchestrator.client.klines(symbol, interval, limit=CANDLE_LIMIT_STREAM)
                    candles = [
                        {
                            "time": c["time"],
                            "open": float(c["open"]),
                            "high": float(c["high"]),
                            "low": float(c["low"]),
                            "close": float(c["close"]),
                            "volume": float(c.get("volume", 0)),
                        }
                        for c in raw
                    ]
                except Exception:
                    candles = []

                # 3. Build payload with normalized field names for the frontend
                payload = {
                    "success": result.get("success", False),
                    "symbol": symbol,
                    "interval": interval,
                    "current_price": result.get("current_price"),
                    "timestamp": result.get("timestamp", int(time.time())),
                    "signal": result.get("new_signal"),
                    "last_signal": result.get("new_signal") or (
                        result.get("active_signals", [])[-1] if result.get("active_signals") else None
                    ),
                    "candles": candles,
                    # Frontend expects 'active' — active positions list
                    "active": result.get("active_signals", []),
                    # Frontend expects 'journal' — trade journal data
                    "journal": {
                        "history": tj.history(limit=50, symbol=symbol),
                        "stats": tj.stats(),
                    },
                }

                yield f"data: {json.dumps(payload)}\n\n"
                time.sleep(5)
            except Exception as e:
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
                time.sleep(10)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@api.route("/reset", methods=["POST"])
def reset_state():
    """Reset state machine (clear all active signals)."""
    from ..engine.signal_state_machine import SignalStateMachine
    orchestrator.state_machine = SignalStateMachine()
    return jsonify({"success": True, "message": "State machine reset"})


def create_api_blueprint():
    return api
