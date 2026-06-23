"""Thin Flask app. Renders from template files — NO embedded HTML mega-strings.

Routes:
  /            -> dashboard page (server-rendered scorecards)
  /health      -> 200 liveness
  /api/status  -> JSON: safety state + scorecards

This layer is presentation only. It imports the read-only research modules and
the safety gate. It imports nothing that can place an order, because no such
module exists. Keep this file small; if it grows, split routes out — do not let
it become a second dashboard.py.
"""

from __future__ import annotations

import os

from flask import Flask, jsonify, render_template

from .auth import require_auth
from ..backtest.engine import backtest
from ..data.csv_adapter import CsvAdapter
from ..instruments.registry import INSTRUMENTS
from ..safety.gate import safety_state
from ..scorecard.scorecard import build_scorecard

DATA_DIR = os.getenv("DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "..", "data"))
REAL_DIR = os.path.join(DATA_DIR, "real")


def _strategies():
    # Imported here to keep module import-time light and avoid cycles.
    from ..strategies.sma_dip import SmaDip
    from ..strategies.trend_filter import TrendFilter
    return [SmaDip(), TrendFilter()]


def compute_scorecards() -> list[dict]:
    real = REAL_DIR if os.path.isdir(REAL_DIR) else None
    adapter = CsvAdapter(DATA_DIR, real_dir=real)
    cards: list[dict] = []
    for symbol, inst in INSTRUMENTS.items():
        try:
            all_bars = adapter.bars(symbol, limit=999_999)
            bars = all_bars[-2000:]
        except FileNotFoundError:
            continue
        for strat in _strategies():
            meta = adapter.meta(symbol)
            result = backtest(strat, symbol, bars, fee_bps=inst.fee_bps)
            cards.append(build_scorecard(result, meta, bars=bars,
                                         available_bars=len(all_bars)))
    return cards


def create_app() -> Flask:
    app = Flask(__name__, template_folder="templates")

    @app.get("/health")
    def health():
        return "ok", 200

    @app.get("/api/status")
    @require_auth
    def api_status():
        s = safety_state()
        return jsonify({
            "safety": {
                "force_paper_only": s.force_paper_only,
                "can_place_orders": s.can_place_orders,
                "verdict": s.verdict,
            },
            "scorecards": compute_scorecards(),
        })

    @app.get("/")
    @require_auth
    def index():
        return render_template("dashboard.html",
                               safety=safety_state(),
                               scorecards=compute_scorecards())

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5060")))
