import json
import os
import tempfile
import unittest
from datetime import datetime
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from src.data.csv_adapter import CsvAdapter
from src.data.market_info import (
    RECENT_SERIES_LIMIT,
    instrument_market_info,
    market_clock,
)


def _write_csv(path, closes):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("date,open,high,low,close,volume\n")
        for i, close in enumerate(closes, start=1):
            ts = (date(2026, 1, 1) + timedelta(days=i - 1)).isoformat()
            fh.write(f"{ts},{close},{close},{close},{close},1000\n")


class TestMarketInfo(unittest.TestCase):
    def test_day_change_and_pct_from_csv(self):
        with tempfile.TemporaryDirectory() as d:
            _write_csv(os.path.join(d, "SPY.csv"), [100, 105])
            with open(os.path.join(d, "SPY.meta.json"), "w", encoding="utf-8") as fh:
                json.dump({"source": "yfinance", "synthetic": False, "adjustment": "unknown"}, fh)

            info = instrument_market_info(CsvAdapter(d), "SPY")

        self.assertEqual(info["latest_close"], 105.0)
        self.assertEqual(info["previous_close"], 100.0)
        self.assertEqual(info["day_change"], 5.0)
        self.assertEqual(info["day_change_pct"], 0.05)
        self.assertEqual(info["source"], "yfinance")
        self.assertEqual(info["price_adjustment"], "unknown")
        self.assertEqual(info["status"], "watch_only")
        self.assertEqual(info["trade_impact"], "none")

    def test_recent_series_limited(self):
        with tempfile.TemporaryDirectory() as d:
            _write_csv(os.path.join(d, "GLD.csv"), list(range(1, 80)))
            with open(os.path.join(d, "GLD.meta.json"), "w", encoding="utf-8") as fh:
                json.dump({"source": "yfinance", "synthetic": False, "adjustment": "unknown"}, fh)

            info = instrument_market_info(CsvAdapter(d), "GLD", series_limit=999)

        self.assertEqual(len(info["recent_close_series"]), RECENT_SERIES_LIMIT)
        self.assertTrue(info["sparkline_points"])

    def test_market_clock_open_closed_weekend_and_disclaimer(self):
        tz = ZoneInfo("America/New_York")
        open_clock = market_clock(datetime(2026, 6, 25, 10, 0, tzinfo=tz))
        closed_clock = market_clock(datetime(2026, 6, 25, 18, 0, tzinfo=tz))
        weekend_clock = market_clock(datetime(2026, 6, 27, 12, 0, tzinfo=tz))

        self.assertTrue(open_clock["market_open"])
        self.assertEqual(open_clock["market_state"], "open")
        self.assertEqual(closed_clock["market_state"], "closed")
        self.assertEqual(weekend_clock["market_state"], "weekend")
        self.assertEqual(open_clock["holiday_calendar_accuracy"], "not_implemented")
        self.assertIn("holidays are not modeled", open_clock["clock_note"])


if __name__ == "__main__":
    unittest.main()
