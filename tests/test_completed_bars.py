import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from src.data.completed_bars import (
    completed_daily_bars,
    is_completed_daily_bar,
    yfinance_exclusive_end,
)


ET = ZoneInfo("America/New_York")


class TestCompletedDailyBars(unittest.TestCase):
    def test_current_weekday_bar_completes_at_regular_close(self):
        before_close = datetime(2026, 6, 26, 15, 59, tzinfo=ET)
        at_close = datetime(2026, 6, 26, 16, 0, tzinfo=ET)

        self.assertFalse(is_completed_daily_bar("2026-06-26", before_close))
        self.assertTrue(is_completed_daily_bar("2026-06-26", at_close))

    def test_weekend_keeps_friday_and_rejects_weekend_bar(self):
        saturday = datetime(2026, 6, 27, 12, 0, tzinfo=ET)
        bars = [
            {"ts": "2026-06-26"},
            {"ts": "2026-06-27"},
        ]

        self.assertEqual(completed_daily_bars(bars, saturday), [bars[0]])

    def test_yfinance_end_is_exclusive_and_close_aware(self):
        before_close = datetime(2026, 6, 26, 15, 59, tzinfo=ET)
        after_close = datetime(2026, 6, 26, 16, 1, tzinfo=ET)
        saturday = datetime(2026, 6, 27, 12, 0, tzinfo=ET)

        self.assertEqual(yfinance_exclusive_end(before_close), "2026-06-26")
        self.assertEqual(yfinance_exclusive_end(after_close), "2026-06-27")
        self.assertEqual(yfinance_exclusive_end(saturday), "2026-06-27")


if __name__ == "__main__":
    unittest.main()
