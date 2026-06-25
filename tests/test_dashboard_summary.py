import os
import unittest
import base64
from unittest.mock import patch

import src.web.app as web_app
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
        self.assertIn("can_place_orders = false", summary["safety"])
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
            [i["symbol"] for i in payload["dashboard_summary"]["instruments"]],
            ["SPY", "GLD"],
        )

    def test_dashboard_renders(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)

    def test_dashboard_safe_action_area_is_display_only(self):
        body = self.client.get("/").get_data(as_text=True)

        self.assertIn("data-safe-actions", body)
        self.assertIn("data-admin-refresh", body)
        self.assertIn("ETF Market Info", body)
        self.assertIn('href="/api/status"', body)
        self.assertIn('href="/health"', body)
        self.assertEqual(body.count("data-copy="), 3)
        self.assertNotIn("<form", body.lower())
        self.assertNotIn("method=\"post\"", body.lower())
        self.assertNotIn("setInterval", body)
        self.assertIn("Forward:", body)

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


class TestAdminRefresh(unittest.TestCase):
    def setUp(self):
        os.environ["DASHBOARD_PASSWORD"] = PASSWORD
        os.environ.pop("REAL_DATA_DIR", None)
        self.client = app.test_client()

    def tearDown(self):
        os.environ.pop("DASHBOARD_PASSWORD", None)
        os.environ.pop("DASHBOARD_USERNAME", None)
        os.environ.pop("REAL_DATA_DIR", None)

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
        headers = _basic()
        headers["X-Goblin-Action"] = "refresh-market-data"
        with patch.object(web_app, "refresh_market_data") as refresh, \
             patch.object(web_app, "run_forward_observation") as shadow:
            refresh.return_value = {
                "symbols": ["SPY", "GLD"],
                "output_dir": "/mnt/data/real",
                "latest_bar_date": {"SPY": "2026-06-22", "GLD": "2026-06-22"},
            }
            shadow.return_value = {
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
        self.assertTrue(payload["forward_observation_started"])
        self.assertEqual(payload["new_forward_records_last_run"], 0)
        refresh.assert_called_once_with(
            ["SPY", "GLD"], "2000-01-01",
            output_dir="/mnt/data/real", write_raw=False,
        )
        shadow.assert_called_once_with()

    def test_lock_releases_when_refresh_fails(self):
        os.environ["REAL_DATA_DIR"] = "/mnt/data/real"
        headers = _basic()
        headers["X-Goblin-Action"] = "refresh-market-data"
        with patch.object(web_app, "refresh_market_data", side_effect=RuntimeError("boom")):
            response = self.client.post("/admin/refresh", headers=headers)

        self.assertEqual(response.status_code, 500)
        self.assertTrue(web_app._refresh_lock.acquire(blocking=False))
        web_app._refresh_lock.release()

    def test_double_refresh_returns_409(self):
        os.environ["REAL_DATA_DIR"] = "/mnt/data/real"
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
