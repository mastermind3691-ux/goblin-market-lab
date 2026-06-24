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
from ..paper.persistence import load_json
from ..paper.shadow_tracker import ShadowTracker
from ..safety.gate import safety_state
from ..scorecard.scorecard import build_scorecard

DATA_DIR = os.getenv("DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "..", "data"))
REAL_DIR = os.path.join(DATA_DIR, "real")
SHADOW_PATH = os.getenv("SHADOW_STATE_PATH",
                         os.path.join(os.path.dirname(__file__), "..", "..", "shadow_state.json"))


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


def shadow_summary() -> dict:
    saved = load_json(SHADOW_PATH)
    if not saved:
        return ShadowTracker().summary()
    return ShadowTracker.from_dict(saved).summary()


def dashboard_summary(scorecards: list[dict], shadow: dict) -> dict:
    instruments = []
    for symbol, inst in INSTRUMENTS.items():
        cards = [c for c in scorecards if c["instrument"] == symbol]
        first = cards[0] if cards else {}
        instruments.append({
            "symbol": symbol,
            "label": inst.label,
            "source": first.get("data_source", "unknown"),
            "latest_bar": first.get("last_bar_date"),
            "adjustment": first.get("price_adjustment", "unknown"),
            "data_is_stale": first.get("data_is_stale", True),
            "bars_tested": max((c.get("bars_tested", 0) for c in cards), default=0),
            "available_bars": first.get("available_bars", 0),
        })

    if shadow.get("forward_observed", 0) == 0:
        next_step = "Next: run manual refreshes over time to begin forward observation."
    else:
        next_step = "Next: keep collecting forward evidence before considering paper portfolio simulation."

    return {
        "instruments": instruments,
        "outcome": {
            "headline": "No proven edge yet",
            "measurement": "Strategies are being measured, not trusted",
            "historical": "Historical shadow replay exists" if shadow.get("historical_bootstrap", 0) else "Historical shadow replay not started",
            "forward": "Forward evidence has not started" if shadow.get("forward_observed", 0) == 0 else "Forward evidence is collecting",
        },
        "safety": [
            "No real trades",
            "No paper portfolio trades yet",
            "No broker/order/execution code",
            "can_place_orders = false",
        ],
        "next_step": next_step,
    }


def create_app() -> Flask:
    app = Flask(__name__, template_folder="templates")

    @app.get("/health")
    def health():
        return "ok", 200

    @app.get("/api/status")
    @require_auth
    def api_status():
        s = safety_state()
        scorecards = compute_scorecards()
        shadow = shadow_summary()
        return jsonify({
            "safety": {
                "force_paper_only": s.force_paper_only,
                "can_place_orders": s.can_place_orders,
                "verdict": s.verdict,
            },
            "scorecards": scorecards,
            "shadow_summary": shadow,
            "dashboard_summary": dashboard_summary(scorecards, shadow),
        })

    @app.get("/")
    @require_auth
    def index():
        scorecards = compute_scorecards()
        shadow = shadow_summary()
        return render_template("dashboard.html",
                               safety=safety_state(),
                               scorecards=scorecards,
                               shadow=shadow,
                               summary=dashboard_summary(scorecards, shadow))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5060")))
