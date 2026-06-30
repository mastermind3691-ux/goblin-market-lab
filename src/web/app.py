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
import threading

from flask import Flask, jsonify, render_template, request

from .auth import auth_enabled, require_auth
from ..backtest.engine import backtest
from ..data.csv_adapter import CsvAdapter
from ..data.market_info import market_info_payload
from ..instruments.registry import INSTRUMENTS
from ..paper.persistence import load_json
from ..paper.shadow_tracker import ShadowTracker
from ..safety.gate import safety_state
from ..scorecard.scorecard import build_scorecard
from tools.refresh_market_data import refresh_market_data
from tools.run_shadow_tracking import run_forward_observation, shadow_state_path

DATA_DIR = os.getenv("DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "..", "data"))
REFRESH_ACTION_HEADER = "refresh-market-data"
REFRESH_SYMBOLS = list(INSTRUMENTS.keys())
REFRESH_START = "2000-01-01"
_refresh_lock = threading.Lock()


def _strategies():
    # Imported here to keep module import-time light and avoid cycles.
    from ..strategies.sma_dip import SmaDip
    from ..strategies.trend_filter import TrendFilter
    return [SmaDip(), TrendFilter()]


def compute_scorecards() -> list[dict]:
    adapter = CsvAdapter(DATA_DIR)
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
    saved = load_json(shadow_state_path())
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
    if shadow.get("forward_observed", 0) > 0:
        forward_status = "Forward evidence is collecting"
    elif shadow.get("forward_observation_started", False):
        forward_status = "Forward observation initialized"
    else:
        forward_status = "Forward evidence has not started"

    return {
        "instruments": instruments,
        "outcome": {
            "headline": "No proven edge yet",
            "measurement": "Strategies are being measured, not trusted",
            "historical": "Historical shadow replay exists" if shadow.get("historical_bootstrap", 0) else "Historical shadow replay not started",
            "forward": forward_status,
        },
        "safety": [
            "No real trades",
            "No paper portfolio trades yet",
            "No broker/order/execution code",
            "Order placement locked",
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

    @app.get("/api/market-info")
    @require_auth
    def api_market_info():
        s = safety_state()
        payload = market_info_payload(DATA_DIR)
        payload["safety"] = {
            "can_place_orders": s.can_place_orders,
        }
        return jsonify(payload)

    @app.post("/admin/refresh")
    @require_auth
    def admin_refresh():
        if not auth_enabled():
            return jsonify({
                "ok": False,
                "error": "DASHBOARD_PASSWORD is required before admin refresh can run.",
            }), 401
        if request.headers.get("X-Goblin-Action") != REFRESH_ACTION_HEADER:
            return jsonify({
                "ok": False,
                "error": "Missing or invalid X-Goblin-Action header.",
            }), 403
        real_data_dir = (os.getenv("REAL_DATA_DIR") or "").strip()
        if not real_data_dir:
            return jsonify({
                "ok": False,
                "error": "REAL_DATA_DIR is required for dashboard refresh.",
                "setup": "Set REAL_DATA_DIR=/mnt/data/real and mount a Railway volume at /mnt/data.",
            }), 400
        state_path = (os.getenv("SHADOW_STATE_PATH") or "").strip()
        if not state_path:
            return jsonify({
                "ok": False,
                "error": "SHADOW_STATE_PATH is required for dashboard refresh.",
                "setup": "Set SHADOW_STATE_PATH=/mnt/data/shadow_state.json on the mounted Railway volume.",
            }), 400
        if not _refresh_lock.acquire(blocking=False):
            return jsonify({
                "ok": False,
                "error": "Refresh is already running.",
            }), 409

        try:
            refresh = refresh_market_data(
                REFRESH_SYMBOLS, REFRESH_START,
                output_dir=real_data_dir,
                write_raw=False,
            )
            shadow = run_forward_observation(
                real_data_dir=real_data_dir,
                state_path=state_path,
            )
            s = safety_state()
            return jsonify({
                "ok": True,
                "primary_source": refresh["primary_source"],
                "symbols_refreshed": refresh["symbols"],
                "source_used": refresh["source_used"],
                "fallback_source_used": refresh["fallback_source_used"],
                "fallback_reason": refresh["fallback_reason"],
                "output_dir": refresh["output_dir"],
                "latest_bar_date": refresh["latest_bar_date"],
                "latest_vendor_row_date": refresh["latest_vendor_row_date"],
                "excluded_vendor_rows": refresh["excluded_vendor_rows"],
                "shadow_state_path": shadow["path"],
                "shadow_total": shadow["total"],
                "historical_bootstrap": shadow["historical_bootstrap"],
                "forward_observed": shadow["forward_observed"],
                "forward_observation_started": shadow["forward_observation_started"],
                "forward_started_after": shadow["forward_started_after"],
                "forward_observed_through": shadow["forward_observed_through"],
                "new_forward_records_last_run": shadow["new_forward_records_last_run"],
                "forward_sample_size": shadow["forward_sample_size"],
                "enough_forward_data": shadow["enough_forward_data"],
                "forward_message": shadow["forward_message"],
                "can_place_orders": s.can_place_orders,
            })
        except Exception:
            return jsonify({
                "ok": False,
                "error": "Refresh failed.",
                "can_place_orders": safety_state().can_place_orders,
            }), 500
        finally:
            _refresh_lock.release()

    @app.get("/")
    @require_auth
    def index():
        scorecards = compute_scorecards()
        shadow = shadow_summary()
        return render_template("dashboard.html",
                               safety=safety_state(),
                               scorecards=scorecards,
                               shadow=shadow,
                               summary=dashboard_summary(scorecards, shadow),
                               market_info=market_info_payload(DATA_DIR))

    return app


app = create_app()


def run_web() -> None:
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5060")))


if __name__ == "__main__":
    run_web()
