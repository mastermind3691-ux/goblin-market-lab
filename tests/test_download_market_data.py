import unittest
import tempfile
import json
import os
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd

from src.data.base import DataMeta
from tools.download_market_data import dataframe_to_csv_result, dataframe_to_csv_text
from tools.refresh_market_data import refresh_market_data


def _mock_dataframe():
    """Fixture: a small DataFrame mimicking yfinance's return format."""
    dates = pd.to_datetime(["2023-01-05", "2023-01-04", "2023-01-03", "2023-01-02"])
    return pd.DataFrame({
        "Open": [380.0, 378.0, 377.0, 375.0],
        "High": [381.0, 379.0, 378.0, 376.0],
        "Low": [379.0, 377.0, 376.0, 374.0],
        "Close": [380.5, 378.5, 377.5, 375.5],
        "Volume": [1000000, 1100000, 1200000, 1300000],
    }, index=dates)


def _mock_multiindex_dataframe():
    """Fixture: multi-level columns like yfinance auto_adjust=False."""
    dates = pd.to_datetime(["2023-01-02", "2023-01-03"])
    arrays = [["Open", "High", "Low", "Close", "Volume"],
              ["SPY", "SPY", "SPY", "SPY", "SPY"]]
    cols = pd.MultiIndex.from_arrays(arrays)
    data = [[375.0, 376.0, 374.0, 375.5, 1300000],
            [377.0, 378.0, 376.0, 377.5, 1200000]]
    return pd.DataFrame(data, index=dates, columns=cols)


def _mock_incomplete_latest_dataframe():
    dates = pd.to_datetime(["2026-06-25", "2026-06-26"])
    return pd.DataFrame({
        "Open": [734.0, 729.0],
        "High": [739.0, 736.0],
        "Low": [729.0, 727.0],
        "Close": [734.3, float("nan")],
        "Adj Close": [734.3, float("nan")],
        "Volume": [53934400, 69241946],
    }, index=dates)


class TestDataframeToCsv(unittest.TestCase):
    def test_sorts_ascending_and_normalizes_columns(self):
        df = _mock_dataframe()
        text = dataframe_to_csv_text(df)
        lines = text.strip().split("\n")
        header = lines[0]
        self.assertIn("date", header)
        self.assertIn("open", header)
        self.assertIn("close", header)
        dates = [line.split(",")[0] for line in lines[1:]]
        self.assertEqual(dates, sorted(dates))

    def test_output_has_all_rows(self):
        df = _mock_dataframe()
        text = dataframe_to_csv_text(df)
        lines = [l for l in text.strip().split("\n") if l]
        self.assertEqual(len(lines), 5)  # header + 4 rows

    def test_omits_vendor_incomplete_row_with_missing_close(self):
        df = _mock_incomplete_latest_dataframe()

        result = dataframe_to_csv_result(df)

        self.assertNotIn("2026-06-26", result["csv_text"])
        self.assertEqual(result["latest_vendor_row_date"], "2026-06-26")
        self.assertEqual(result["excluded_rows"], [{
            "date": "2026-06-26",
            "reason": "excluded because Close/Adj Close was NaN",
        }])


class TestFetchBarsMocked(unittest.TestCase):
    @patch("tools.download_market_data.fetch_bars")
    def test_fetch_returns_dataframe(self, mock_fetch):
        mock_fetch.return_value = _mock_dataframe()
        df = mock_fetch("SPY", "2023-01-01", "2023-01-06")
        self.assertEqual(len(df), 4)
        self.assertIn("Close", df.columns)

    @patch("tools.download_market_data.fetch_bars")
    def test_fetch_empty_raises(self, mock_fetch):
        mock_fetch.side_effect = ValueError("No data returned for FAKE.")
        with self.assertRaises(ValueError):
            mock_fetch("FAKE", "2023-01-01", "2023-01-06")


class TestMultiIndexHandling(unittest.TestCase):
    def test_multiindex_columns_flattened(self):
        df = _mock_multiindex_dataframe()
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        text = dataframe_to_csv_text(df)
        lines = text.strip().split("\n")
        self.assertIn("open", lines[0])
        self.assertEqual(len(lines), 3)  # header + 2 rows


class TestCsvValidatorAcceptsOutput(unittest.TestCase):
    def test_normalized_csv_passes_validator(self):
        from src.data.csv_validator import validate_csv
        df = _mock_dataframe()
        text = dataframe_to_csv_text(df)
        result = validate_csv(text)
        self.assertTrue(result.ok, f"Errors: {result.errors}")
        self.assertEqual(result.bar_count, 4)
        self.assertEqual(result.date_range, ("2023-01-02", "2023-01-05"))


@patch.dict(os.environ, {"TIINGO_API_KEY": ""})
class TestRefreshMarketData(unittest.TestCase):
    @patch("tools.refresh_market_data.fetch_bars")
    def test_write_raw_false_skips_raw_copy(self, mock_fetch):
        mock_fetch.return_value = _mock_dataframe()
        with tempfile.TemporaryDirectory() as d:
            result = refresh_market_data(
                ["SPY"], "2023-01-01", "2023-01-06",
                output_dir=d, write_raw=False,
            )

        self.assertEqual(result["symbols"], ["SPY"])
        self.assertIsNone(result["refreshed"][0]["raw_path"])
        self.assertEqual(result["source_used"], {"SPY": "yfinance"})
        self.assertEqual(result["fallback_source_used"], {"SPY": "yfinance"})
        self.assertIn("TIINGO_API_KEY", result["fallback_reason"]["SPY"])

    @patch("tools.refresh_market_data.fetch_bars")
    def test_default_end_includes_bar_after_market_close(self, mock_fetch):
        mock_fetch.return_value = _mock_dataframe()
        now = datetime(2026, 6, 26, 16, 1,
                       tzinfo=ZoneInfo("America/New_York"))

        with tempfile.TemporaryDirectory() as d:
            result = refresh_market_data(
                ["SPY"], "2023-01-01",
                output_dir=d, write_raw=False, now=now,
            )

        mock_fetch.assert_called_once_with("SPY", "2023-01-01", "2026-06-27")
        self.assertEqual(result["download_end_exclusive"], "2026-06-27")

    @patch("tools.refresh_market_data.fetch_bars")
    def test_reports_raw_latest_row_separately_from_accepted_bar(self, mock_fetch):
        mock_fetch.return_value = _mock_incomplete_latest_dataframe()

        with tempfile.TemporaryDirectory() as d:
            result = refresh_market_data(
                ["SPY"], "2000-01-01", "2026-06-27",
                output_dir=d, write_raw=False,
            )

        self.assertEqual(result["latest_bar_date"], {"SPY": "2026-06-25"})
        self.assertEqual(result["latest_vendor_row_date"], {"SPY": "2026-06-26"})
        self.assertEqual(result["excluded_vendor_rows"], [{
            "symbol": "SPY",
            "date": "2026-06-26",
            "reason": "excluded because Close/Adj Close was NaN",
            "source": "yfinance",
        }])


class StubTiingoAdapter:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error

    def fetch(self, symbol, start, end):
        if self.error:
            raise self.error
        return self.result

    def diagnostics(self, symbol):
        return {}


class TestRefreshProviderSelection(unittest.TestCase):
    @patch.dict(os.environ, {"TIINGO_API_KEY": "fixture-env-key"})
    @patch("tools.refresh_market_data.TiingoEodAdapter")
    @patch("tools.refresh_market_data.fetch_bars")
    def test_environment_key_selects_tiingo(self, yfinance_fetch, adapter_class):
        adapter_class.return_value = StubTiingoAdapter(result={
            "bars": [{
                "ts": "2026-06-26", "open": 735.0, "high": 737.0,
                "low": 733.0, "close": 736.0, "volume": 1000.0,
            }],
            "meta": DataMeta(source="tiingo", synthetic=False, adjustment="adjusted"),
            "latest_vendor_row_date": "2026-06-26",
            "excluded_vendor_rows": [],
        })

        with tempfile.TemporaryDirectory() as directory:
            result = refresh_market_data(
                ["SPY"], "2000-01-01", "2026-06-27",
                output_dir=directory, write_raw=False,
            )

        adapter_class.assert_called_once_with(api_key="fixture-env-key", now=None)
        yfinance_fetch.assert_not_called()
        self.assertEqual(result["source_used"], {"SPY": "tiingo"})

    @patch("tools.refresh_market_data.fetch_bars")
    def test_tiingo_is_primary_and_can_advance_latest_bar(self, yfinance_fetch):
        yfinance_fetch.return_value = _mock_incomplete_latest_dataframe()
        tiingo = StubTiingoAdapter(result={
            "bars": [{
                "ts": "2026-06-26", "open": 735.0, "high": 737.0,
                "low": 733.0, "close": 736.0, "volume": 1000.0,
            }],
            "meta": DataMeta(source="tiingo", synthetic=False, adjustment="adjusted"),
            "latest_vendor_row_date": "2026-06-26",
            "excluded_vendor_rows": [],
        })

        with tempfile.TemporaryDirectory() as directory:
            result = refresh_market_data(
                ["SPY"], "2000-01-01", "2026-06-27",
                output_dir=directory, write_raw=False,
                tiingo_adapter=tiingo,
            )
            with open(os.path.join(directory, "SPY.meta.json"), encoding="utf-8") as fh:
                meta = json.load(fh)

        yfinance_fetch.assert_not_called()
        self.assertEqual(result["source_used"], {"SPY": "tiingo"})
        self.assertEqual(result["fallback_source_used"], {"SPY": None})
        self.assertEqual(result["latest_bar_date"], {"SPY": "2026-06-26"})
        self.assertEqual(meta, {
            "source": "tiingo", "synthetic": False, "adjustment": "adjusted",
        })

    @patch("tools.refresh_market_data.fetch_bars")
    def test_tiingo_failure_uses_yfinance_fallback(self, yfinance_fetch):
        yfinance_fetch.return_value = _mock_dataframe()
        tiingo = StubTiingoAdapter(error=RuntimeError("fixture outage"))

        with tempfile.TemporaryDirectory() as directory:
            result = refresh_market_data(
                ["GLD"], "2000-01-01", "2026-06-27",
                output_dir=directory, write_raw=False,
                tiingo_adapter=tiingo,
            )

        yfinance_fetch.assert_called_once()
        self.assertEqual(result["source_used"], {"GLD": "yfinance"})
        self.assertEqual(result["fallback_source_used"], {"GLD": "yfinance"})
        self.assertIn("RuntimeError", result["fallback_reason"]["GLD"])
