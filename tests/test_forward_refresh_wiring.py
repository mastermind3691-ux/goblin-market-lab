import csv
import json
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from src.paper.persistence import atomic_write_json, load_json
from src.paper.shadow_tracker import ShadowTracker
from tools.run_shadow_tracking import run_forward_observation


def _write_bars(directory: str, symbol: str, dates: list[date]) -> None:
    path = os.path.join(directory, f"{symbol}.csv")
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["date", "open", "high", "low", "close", "volume"],
        )
        writer.writeheader()
        for index, bar_date in enumerate(dates):
            close = 100.0 + index
            writer.writerow({
                "date": bar_date.isoformat(),
                "open": close,
                "high": close + 1,
                "low": close - 1,
                "close": close,
                "volume": 1000,
            })

    with open(os.path.join(directory, f"{symbol}.meta.json"), "w", encoding="utf-8") as fh:
        json.dump({
            "source": "yfinance",
            "synthetic": False,
            "adjustment": "unknown",
        }, fh)


class TestForwardRefreshWiring(unittest.TestCase):
    def test_new_completed_bars_persist_across_restart(self):
        dates = []
        current = date(2026, 1, 2)
        while current <= date(2026, 6, 26):
            if current.weekday() < 5:
                dates.append(current)
            current += timedelta(days=1)
        before_close = datetime(
            2026, 6, 26, 15, 59,
            tzinfo=ZoneInfo("America/New_York"),
        )
        after_close = datetime(
            2026, 6, 26, 16, 1,
            tzinfo=ZoneInfo("America/New_York"),
        )
        with tempfile.TemporaryDirectory() as real_dir:
            state_path = os.path.join(real_dir, "shadow_state.json")
            tracker = ShadowTracker()
            tracker.observe("historical_check", "SPY", "2025-12-31", "BUY", 99.0)
            atomic_write_json(state_path, tracker.to_dict())
            for symbol in ("SPY", "GLD"):
                _write_bars(real_dir, symbol, dates[:-1])

            initialized = run_forward_observation(
                real_data_dir=real_dir,
                state_path=state_path,
                now=before_close,
            )
            self.assertEqual(initialized["forward_observed"], 0)
            self.assertEqual(initialized["historical_bootstrap"], 1)

            for symbol in ("SPY", "GLD"):
                _write_bars(real_dir, symbol, dates)

            before_close_refresh = run_forward_observation(
                real_data_dir=real_dir,
                state_path=state_path,
                now=before_close,
            )
            self.assertEqual(before_close_refresh["new_forward_records_last_run"], 0)

            refreshed = run_forward_observation(
                real_data_dir=real_dir,
                state_path=state_path,
                now=after_close,
            )

            self.assertEqual(refreshed["new_forward_records_last_run"], 4)
            self.assertEqual(refreshed["forward_observed"], 4)
            self.assertEqual(refreshed["historical_bootstrap"], 1)
            self.assertEqual(refreshed["forward_sample_size"], 0)
            self.assertEqual(
                refreshed["forward_observed_through"],
                {"SPY": dates[-1].isoformat(), "GLD": dates[-1].isoformat()},
            )

            restored = ShadowTracker.from_dict(load_json(state_path))
            self.assertEqual(restored.summary()["forward_observed"], 4)
            self.assertEqual(restored.summary()["historical_bootstrap"], 1)

            rerun = run_forward_observation(
                real_data_dir=real_dir,
                state_path=state_path,
                now=after_close,
            )
            self.assertEqual(rerun["new_forward_records_last_run"], 0)
            self.assertEqual(rerun["forward_observed"], 4)


if __name__ == "__main__":
    unittest.main()
