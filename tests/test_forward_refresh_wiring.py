import csv
import json
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd

from src.data.base import DataMeta
from src.paper.persistence import atomic_write_json, load_json
from src.paper.shadow_tracker import ShadowTracker
from tools.run_shadow_tracking import run_forward_observation
from tools.refresh_market_data import refresh_market_data


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


class FixtureTiingoAdapter:
    def __init__(self, bars):
        self.bars = bars

    def fetch(self, symbol, start, end):
        return {
            "bars": self.bars,
            "meta": DataMeta(
                source="tiingo", synthetic=False, adjustment="adjusted",
            ),
            "latest_vendor_row_date": self.bars[-1]["ts"],
            "excluded_vendor_rows": [],
        }

    def diagnostics(self, symbol):
        return {}


@patch.dict(os.environ, {"TIINGO_API_KEY": ""})
class TestForwardRefreshWiring(unittest.TestCase):
    @patch("tools.refresh_market_data.fetch_bars")
    def test_incomplete_vendor_row_does_not_create_forward_record(self, fetch):
        fetch.return_value = pd.DataFrame({
            "Open": [734.0, 729.0],
            "High": [739.0, 736.0],
            "Low": [729.0, 727.0],
            "Close": [734.3, float("nan")],
            "Adj Close": [734.3, float("nan")],
            "Volume": [53934400, 69241946],
        }, index=pd.to_datetime(["2026-06-25", "2026-06-26"]))

        with tempfile.TemporaryDirectory() as real_dir:
            state_path = os.path.join(real_dir, "shadow_state.json")
            refresh = refresh_market_data(
                ["SPY", "GLD"], "2000-01-01", "2026-06-27",
                output_dir=real_dir, write_raw=False,
            )
            shadow = run_forward_observation(
                real_data_dir=real_dir,
                state_path=state_path,
                now=datetime(2026, 6, 26, 17, 0,
                             tzinfo=ZoneInfo("America/New_York")),
            )

        self.assertEqual(refresh["latest_bar_date"], {
            "SPY": "2026-06-25", "GLD": "2026-06-25",
        })
        self.assertEqual(len(refresh["excluded_vendor_rows"]), 2)
        self.assertEqual(shadow["forward_observed"], 0)
        self.assertEqual(shadow["forward_observed_through"], {
            "SPY": "2026-06-25", "GLD": "2026-06-25",
        })

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

    def test_tiingo_new_accepted_bar_creates_forward_records(self):
        dates = []
        current = date(2026, 1, 2)
        while current <= date(2026, 6, 26):
            if current.weekday() < 5:
                dates.append(current)
            current += timedelta(days=1)
        tiingo_bars = [
            {
                "ts": bar_date.isoformat(),
                "open": 100.0 + index,
                "high": 101.0 + index,
                "low": 99.0 + index,
                "close": 100.0 + index,
                "volume": 1000.0,
            }
            for index, bar_date in enumerate(dates)
        ]
        after_close = datetime(
            2026, 6, 26, 17, 0,
            tzinfo=ZoneInfo("America/New_York"),
        )

        with tempfile.TemporaryDirectory() as real_dir:
            state_path = os.path.join(real_dir, "shadow_state.json")
            for symbol in ("SPY", "GLD"):
                _write_bars(real_dir, symbol, dates[:-1])
            run_forward_observation(
                real_data_dir=real_dir, state_path=state_path, now=after_close,
            )

            refresh = refresh_market_data(
                ["SPY", "GLD"], "2000-01-01", "2026-06-27",
                output_dir=real_dir, write_raw=False,
                tiingo_adapter=FixtureTiingoAdapter(tiingo_bars),
            )
            forward = run_forward_observation(
                real_data_dir=real_dir, state_path=state_path, now=after_close,
            )
            persisted = ShadowTracker.from_dict(load_json(state_path))

        self.assertEqual(refresh["source_used"], {
            "SPY": "tiingo", "GLD": "tiingo",
        })
        self.assertEqual(refresh["latest_bar_date"], {
            "SPY": "2026-06-26", "GLD": "2026-06-26",
        })
        self.assertEqual(forward["new_forward_records_last_run"], 4)
        new_records = [
            record for record in persisted.records
            if record.signal_date == "2026-06-26"
        ]
        self.assertEqual(len(new_records), 4)
        self.assertTrue(all(record.data_source == "tiingo" for record in new_records))
        self.assertTrue(all(record.adjustment == "adjusted" for record in new_records))


if __name__ == "__main__":
    unittest.main()
