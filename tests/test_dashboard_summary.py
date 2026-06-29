import os
import unittest
import base64
from unittest.mock import patch

import src.web.app as web_app
from src.instruments.registry import INSTRUMENTS
from src.web.app import app, dashboard_summary

PASSWORD = "refresh-test-password"


def _basic(user: str = "admin", password: str = PASSWORD) -> dict:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


class TestDashboardSummary(unittest.TestCase):
    def test_summary_uses_existing_scorecard_and_shadow_fields(self):
        scorecards = [{
            "instrument": "SPY",
            "data_source": "yfinance",
            "last_bar_date": "2026-06-22",
            "price_adjustment": "unknown",
            "data_is_stale": False,
            "bars_tested": 2000,
            "available_bars": 6500,
        }]
        shadow = {"historical_bootstrap": 12, "forward_observed": 0}

        summary = dashboard_summary(scorecards, shadow)

        self.assertEqual(summary["outcome"]["headline"], "No proven edge yet")
        self.assertEqual(summary["outcome"]["forward"], "Forward evidence has not started")
        self.assertIn("Order placement locked", summary["safety"])
        self.assertIn("manual refreshes", summary["next_step"])
        spy = summary["instruments"][0]
        self.assertEqual(spy["symbol"], "SPY")
        self.assertEqual(spy["label"], "S&P 500 ETF")
        self.assertEqual(spy["source"], "yfinance")
        self.assertEqual(spy["adjustment"], "unknown")
        self.assertFalse(spy["data_is_stale"])

    def test_next_step_changes_after_forward_observation_starts(self):
        summary = dashboard_summary([], {"historical_bootstrap": 0, "forward_observed": 1})
        self.assertIn("keep collecting forward evidence", summary["next_step"])
        self.assertEqual(summary["outcome"]["forward"], "Forward evidence is collecting")

    def test_initialized_forward_status_is_honest(self):
        summary = dashboard_summary([], {
            "historical_bootstrap": 0,
            "forward_observed": 0,
            "forward_observation_started": True,
        })
        self.assertIn("initialized", summary["outcome"]["forward"])


class TestDashboardStatusApi(unittest.TestCase):
    def setUp(self):
        os.environ.pop("DASHBOARD_PASSWORD", None)
        self.client = app.test_client()

    def test_status_includes_dashboard_summary_and_safety_false(self):
        response = self.client.get("/api/status")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()

        self.assertFalse(payload["safety"]["can_place_orders"])
        self.assertIn("dashboard_summary", payload)
        self.assertEqual(
            sorted(i["symbol"] for i in payload["dashboard_summary"]["instruments"]),
            sorted(INSTRUMENTS),
        )

    def test_dashboard_renders(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)

    def test_dashboard_safe_action_area_is_display_only(self):
        body = self.client.get("/").get_data(as_text=True)

        self.assertIn("data-safe-actions", body)
        self.assertIn("data-admin-refresh", body)
        self.assertIn("data-cockpit-gauges", body)
        self.assertIn("data-safety-lock-gauge", body)
        self.assertIn("Order placement locked", body)
        self.assertIn("ETF Market Info", body)
        self.assertIn("watch-only", body)
        self.assertIn("No trade impact", body)
        self.assertIn('href="/api/status"', body)
        self.assertIn('href="/health"', body)
        self.assertEqual(body.count("data-copy="), 3)
        self.assertNotIn("<form", body.lower())
        self.assertNotIn("method=\"post\"", body.lower())
        self.assertNotIn("setInterval", body)
        self.assertNotIn("setinterval", body.lower())
        self.assertIn("Forward observations:", body)
        self.assertNotIn("can_place_orders =", body)
        self.assertNotIn("not_implemented", body)

    def test_dashboard_gauges_use_forward_and_trade_counts_only(self):
        scorecards = [{
            "instrument": "SPY",
            "strategy": "SmaDip",
            "headline": "No proven edge yet",
            "synthetic": False,
            "data_source": "yfinance",
            "price_adjustment": "unknown",
            "vs_benchmark": "lags",
            "data_is_stale": False,
            "exposure_pct": 0.12,
            "bars_tested": 2000,
            "available_bars": 6500,
            "last_bar_date": "2026-06-22",
            "strategy_return": "1.2%",
            "buy_and_hold_return": "5.6%",
            "trades": 7,
            "win_rate": "42.9%",
            "expectancy_per_trade": "0.001",
            "concentration": {"flagged": False, "note": ""},
            "verdict": "Not enough data yet.",
            "required_human_approval": True,
            "ready_for_pilot": False,
        }]
        shadow = {
            "historical_bootstrap": 999,
            "historical_sample_size": 999,
            "forward_observed": 4,
            "forward_sample_size": 0,
            "resolved": 999,
            "pending": 0,
            "forward_observation_started": True,
            "enough_forward_data": False,
            "forward_observed_through": {"SPY": "2026-06-22", "GLD": "2026-06-22"},
            "new_forward_records_last_run": 4,
            "verdict": "Forward shadow evidence collecting - not enough data.",
        }
        market_info = {
            "trade_impact": "none",
            "market_clock": {
                "market_state": "closed",
                "core_session": "09:30-16:00 ET",
                "next_open_est": "2026-06-23T09:30:00-04:00",
                "next_close_est": "2026-06-22T16:00:00-04:00",
                "holiday_calendar_accuracy": "not_implemented",
                "clock_note": "Regular-hours estimate; holidays are not modeled.",
            },
            "instruments": [{
                "symbol": "SPY",
                "display_name": "S&P 500 ETF",
                "source": "yfinance",
                "price_adjustment": "unknown",
                "latest_bar_date": "2026-06-22",
                "latest_close": 500.0,
                "day_change": 1.0,
                "day_change_pct": 0.002,
                "bars_available": 6500,
                "data_is_stale": False,
                "status": "watch_only",
                "trade_impact": "none",
                "sparkline_points": "0,20 100,10",
            }],
        }

        with patch.object(web_app, "compute_scorecards", return_value=scorecards), \
             patch.object(web_app, "shadow_summary", return_value=shadow), \
             patch.object(web_app, "market_info_payload", return_value=market_info):
            body = self.client.get("/").get_data(as_text=True)

        self.assertIn('data-forward-evidence-gauge data-forward-observation-count="4" data-forward-sample-size="0" data-forward-target="30"', body)
        self.assertIn("Forward observations", body)
        self.assertIn("Forward BUY evidence: 0 / 30", body)
        self.assertIn("The lab is watching completed bars. No BUY evidence samples yet.", body)
        self.assertIn("Historical bootstrap is not counted as forward proof.", body)
        self.assertNotIn('data-forward-sample-size="999"', body)
        self.assertIn('data-scorecard-evidence-progress data-trade-count="7" data-min-samples="30"', body)
        self.assertIn("This is sample progress, not edge strength.", body)
        self.assertIn("holiday calendar: not modeled", body)
        self.assertIn("SPY 2026-06-22", body)
        self.assertNotIn("{'GLD':", body)
        self.assertIn("Not enough forward BUY evidence yet", body)
        self.assertIn("Research-only: human approval required before anything advances. Pilot not ready.", body)

    def test_market_info_api_open_in_dev_and_read_only(self):
        with patch.object(web_app, "refresh_market_data") as refresh, \
             patch.object(web_app, "run_forward_observation") as forward:
            response = self.client.get("/api/market-info")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertFalse(payload["safety"]["can_place_orders"])
        self.assertEqual(payload["trade_impact"], "none")
        self.assertIn("market_clock", payload)
        self.assertIn("instruments", payload)
        refresh.assert_not_called()
        forward.assert_not_called()

    def test_market_info_api_get_only(self):
        self.assertEqual(self.client.post("/api/market-info").status_code, 405)
        post_routes = sorted(
            rule.rule for rule in app.url_map.iter_rules()
            if "POST" in rule.methods
        )
        self.assertEqual(post_routes, ["/admin/refresh"])


class TestAdminRefresh(unittest.TestCase):
    def setUp(self):
        os.environ["DASHBOARD_PASSWORD"] = PASSWORD
        os.environ.pop("REAL_DATA_DIR", None)
        self.client = app.test_client()

    def tearDown(self):
        os.environ.pop("DASHBOARD_PASSWORD", None)
        os.environ.pop("DASHBOARD_USERNAME", None)
        os.environ.pop("REAL_DATA_DIR", None)
        os.environ.pop("SHADOW_STATE_PATH", None)

    def test_refresh_requires_auth(self):
        response = self.client.post(
            "/admin/refresh",
            headers={"X-Goblin-Action": "refresh-market-data"},
        )
        self.assertEqual(response.status_code, 401)

    def test_market_info_requires_auth_when_password_set(self):
        self.assertEqual(self.client.get("/api/market-info").status_code, 401)
        self.assertEqual(self.client.get("/api/market-info", headers=_basic()).status_code, 200)

    def test_refresh_refuses_when_dashboard_password_unset(self):
        os.environ.pop("DASHBOARD_PASSWORD", None)
        os.environ["REAL_DATA_DIR"] = "/mnt/data/real"
        headers = {"X-Goblin-Action": "refresh-market-data"}
        with patch.object(web_app, "refresh_market_data") as refresh, \
             patch.object(web_app, "run_forward_observation") as shadow:
            response = self.client.post("/admin/refresh", headers=headers)

        self.assertEqual(response.status_code, 401)
        refresh.assert_not_called()
        shadow.assert_not_called()

    def test_get_refresh_not_allowed(self):
        response = self.client.get("/admin/refresh", headers=_basic())
        self.assertEqual(response.status_code, 405)

    def test_missing_or_wrong_action_header_returns_403(self):
        os.environ["REAL_DATA_DIR"] = "/tmp/not-used"
        self.assertEqual(self.client.post("/admin/refresh", headers=_basic()).status_code, 403)
        headers = _basic()
        headers["X-Goblin-Action"] = "wrong"
        self.assertEqual(self.client.post("/admin/refresh", headers=headers).status_code, 403)

    def test_missing_real_data_dir_returns_400_before_refresh(self):
        headers = _basic()
        headers["X-Goblin-Action"] = "refresh-market-data"
        with patch.object(web_app, "refresh_market_data") as refresh:
            response = self.client.post("/admin/refresh", headers=headers)

        self.assertEqual(response.status_code, 400)
        self.assertIn("REAL_DATA_DIR", response.get_json()["setup"])
        refresh.assert_not_called()

    def test_successful_refresh_uses_fixed_inputs_and_reports_safety(self):
        os.environ["REAL_DATA_DIR"] = "/mnt/data/real"
        os.environ["SHADOW_STATE_PATH"] = "/mnt/data/shadow_state.json"
        headers = _basic()
        headers["X-Goblin-Action"] = "refresh-market-data"
        with patch.object(web_app, "refresh_market_data") as refresh, \
             patch.object(web_app, "run_forward_observation") as shadow:
            refresh.return_value = {
                "primary_source": "tiingo",
                "symbols": ["SPY", "GLD"],
                "source_used": {"SPY": "tiingo", "GLD": "tiingo"},
                "fallback_source_used": {"SPY": None, "GLD": None},
                "fallback_reason": {},
                "output_dir": "/mnt/data/real",
                "latest_bar_date": {"SPY": "2026-06-22", "GLD": "2026-06-22"},
                "latest_vendor_row_date": {
                    "SPY": "2026-06-23", "GLD": "2026-06-23",
                },
                "excluded_vendor_rows": [{
                    "symbol": "SPY",
                    "date": "2026-06-23",
                    "reason": "excluded because Close/Adj Close was NaN",
                }],
            }
            shadow.return_value = {
                "path": "/mnt/data/shadow_state.json",
                "total": 429,
                "historical_bootstrap": 429,
                "forward_observed": 0,
                "forward_observation_started": True,
                "forward_started_after": {"SPY": "2026-06-22", "GLD": "2026-06-22"},
                "forward_observed_through": {"SPY": "2026-06-22", "GLD": "2026-06-22"},
                "new_forward_records_last_run": 0,
                "forward_sample_size": 0,
                "enough_forward_data": False,
                "forward_message": "Forward observation initialized - waiting for next completed bar.",
            }
            response = self.client.post("/admin/refresh", headers=headers)

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["can_place_orders"])
        self.assertEqual(payload["symbols_refreshed"], ["SPY", "GLD"])
        self.assertEqual(payload["primary_source"], "tiingo")
        self.assertEqual(payload["source_used"]["SPY"], "tiingo")
        self.assertEqual(payload["latest_bar_date"]["SPY"], "2026-06-22")
        self.assertEqual(payload["latest_vendor_row_date"]["SPY"], "2026-06-23")
        self.assertEqual(payload["excluded_vendor_rows"][0]["symbol"], "SPY")
        self.assertIn("Close/Adj Close", payload["excluded_vendor_rows"][0]["reason"])
        self.assertTrue(payload["forward_observation_started"])
        self.assertEqual(payload["new_forward_records_last_run"], 0)
        refresh.assert_called_once_with(
            ["SPY", "GLD"], "2000-01-01",
            output_dir="/mnt/data/real", write_raw=False,
        )
        shadow.assert_called_once_with(
            real_data_dir="/mnt/data/real",
            state_path="/mnt/data/shadow_state.json",
        )

    def test_missing_shadow_state_path_returns_400_before_refresh(self):
        os.environ["REAL_DATA_DIR"] = "/mnt/data/real"
        headers = _basic()
        headers["X-Goblin-Action"] = "refresh-market-data"

        with patch.object(web_app, "refresh_market_data") as refresh:
            response = self.client.post("/admin/refresh", headers=headers)

        self.assertEqual(response.status_code, 400)
        self.assertIn("SHADOW_STATE_PATH", response.get_json()["setup"])
        refresh.assert_not_called()

    def test_lock_releases_when_refresh_fails(self):
        os.environ["REAL_DATA_DIR"] = "/mnt/data/real"
        os.environ["SHADOW_STATE_PATH"] = "/mnt/data/shadow_state.json"
        headers = _basic()
        headers["X-Goblin-Action"] = "refresh-market-data"
        with patch.object(web_app, "refresh_market_data", side_effect=RuntimeError("boom")):
            response = self.client.post("/admin/refresh", headers=headers)

        self.assertEqual(response.status_code, 500)
        self.assertTrue(web_app._refresh_lock.acquire(blocking=False))
        web_app._refresh_lock.release()

    def test_double_refresh_returns_409(self):
        os.environ["REAL_DATA_DIR"] = "/mnt/data/real"
        os.environ["SHADOW_STATE_PATH"] = "/mnt/data/shadow_state.json"
        headers = _basic()
        headers["X-Goblin-Action"] = "refresh-market-data"
        self.assertTrue(web_app._refresh_lock.acquire(blocking=False))
        try:
            response = self.client.post("/admin/refresh", headers=headers)
        finally:
            web_app._refresh_lock.release()

        self.assertEqual(response.status_code, 409)


if __name__ == "__main__":
    unittest.main()
