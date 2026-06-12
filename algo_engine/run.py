"""
Algo Engine v1.0 — Startup Script
Registers the Flask blueprint and runs the server.
Usage: python algo-engine/run.py
"""

import os
import sys

# Add project root and algo_engine parent to path so imports resolve
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask
from algo_engine.api.routes import create_api_blueprint
from algo_engine.config import SERVER_PORT

app = Flask(__name__)
api = create_api_blueprint()
app.register_blueprint(api)


@app.route("/")
def index():
    return {
        "service": "algo-engine-v2",
        "endpoints": {
            "health": "/api/v2/health",
            "signal": "/api/v2/signal (POST)",
            "state": "/api/v2/state",
            "journal": "/api/v2/journal",
            "stream": "/api/v2/stream (SSE)",
            "reset": "/api/v2/reset (POST)",
        },
        "docs": "https://codebuff.com/docs",
    }


if __name__ == "__main__":
    port = int(os.environ.get("PORT", SERVER_PORT))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    print(f"\n  Algo Engine v1.0")
    print(f"  Server: http://localhost:{port}")
    print(f"  API:    http://localhost:{port}/api/v2/health")
    print(f"  Stream: http://localhost:{port}/api/v2/stream?symbol=BTCUSDT\n")
    app.run(host="0.0.0.0", port=port, debug=debug)
