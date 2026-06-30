import re
import unittest
from pathlib import Path

from src.web.app import app

TEMPLATE_PATH = (
    Path(__file__).parents[1] / "src" / "web" / "templates" / "dashboard.html"
)

NEW_BLOCK_MARKERS = [
    ("candidate-card-start", "candidate-card-end"),
    ("forward-watch-card-start", "forward-watch-card-end"),
    ("data-status-card-start", "data-status-card-end"),
]

PROHIBITED_WORDS = ("edge", "promising", "approved", "pilot")


def _extract_block(body: str, start_marker: str, end_marker: str) -> str:
    start = body.index(f"<!-- {start_marker} -->")
    end = body.index(f"<!-- {end_marker} -->")
    return body[start:end]


class TestDashboardLayout(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.body = self.client.get("/").get_data(as_text=True)

    def test_active_candidate_present(self):
        self.assertIn("Sweep", self.body)
        self.assertIn("MSS Long-only", self.body)
        self.assertIn("WEAK_SAMPLE_RESEARCH_CANDIDATE", self.body)
        self.assertIn("Forward watch only", self.body)
        self.assertIn("Not proven. No trading approval.", self.body)
        self.assertIn("pivot 5/2", self.body)
        self.assertIn("MSS expiry 16", self.body)
        self.assertIn("target 2R", self.body)
        self.assertIn("no FVG", self.body)

    def test_candidate_diagnostic_numbers_present(self):
        self.assertIn("34", self.body)
        self.assertIn("21 / 13", self.body)
        self.assertIn("+29", self.body)
        self.assertIn("3.23", self.body)

    def test_candidate_caveats_present(self):
        for caveat in ("weak sample", "correlated ETFs", "adjustment unknown",
                       "SMH negative", "chosen after side split"):
            self.assertIn(caveat, self.body)

    def test_forward_watch_card_present(self):
        self.assertIn("Forward watch", self.body)
        self.assertIn("forward observations: 0", self.body)
        self.assertIn("No new forward setup yet.", self.body)

    def test_data_status_card_present(self):
        for symbol in ("GLD", "IAU", "SPY", "QQQ", "SMH"):
            self.assertIn(symbol, self.body)
        self.assertIn("yfinance 1H resampled to 4H", self.body)
        self.assertIn("adjustment: unknown", self.body)
        self.assertIn("RTH session bucket", self.body)

    def test_research_archive_collapsed_by_default(self):
        self.assertIn("<details", self.body)
        self.assertIn("data-research-archive", self.body)
        match = re.search(r"<details[^>]*data-research-archive[^>]*>", self.body)
        self.assertIsNotNone(match)
        self.assertNotIn(" open", match.group(0))
        self.assertIn("Research archive", self.body)

    def test_archive_contains_old_sections(self):
        self.assertIn("ETF Market Info", self.body)
        self.assertIn("Scorecards", self.body)

    def test_no_prohibited_words_in_new_blocks(self):
        for start_marker, end_marker in NEW_BLOCK_MARKERS:
            block = _extract_block(self.body, start_marker, end_marker).lower()
            for word in PROHIBITED_WORDS:
                self.assertNotIn(word, block,
                                  f"'{word}' found in block {start_marker}")

    def test_existing_required_attributes_still_present(self):
        self.assertIn("data-safe-actions", self.body)
        self.assertIn("data-admin-refresh", self.body)
        self.assertIn("data-cockpit-gauges", self.body)
        self.assertIn("data-safety-lock-gauge", self.body)
        self.assertIn("Order placement locked", self.body)
        self.assertEqual(self.body.count("data-copy="), 3)
        self.assertNotIn("<form", self.body.lower())


class TestNoBrokerExecutionPaths(unittest.TestCase):
    def test_template_adds_no_broker_or_order_routes(self):
        source = TEMPLATE_PATH.read_text(encoding="utf-8").lower()
        for phrase in ("place_order", "submit_order", "/execution", "/broker",
                       "/orders", "fetch(\"/admin/order"):
            self.assertNotIn(phrase, source)


if __name__ == "__main__":
    unittest.main()
