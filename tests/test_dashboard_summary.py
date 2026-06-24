import os
import unittest

from src.web.app import app, dashboard_summary


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
        self.assertIn('href="/api/status"', body)
        self.assertIn('href="/health"', body)
        self.assertEqual(body.count("data-copy="), 3)
        self.assertNotIn("<form", body.lower())
        self.assertNotIn("method=\"post\"", body.lower())


if __name__ == "__main__":
    unittest.main()
