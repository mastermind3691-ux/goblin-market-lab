import ast
import io
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd

from src.data.timeframe_csv_adapter import TimeframeCsvAdapter
from tools.download_real_4h_data import download_and_import, resample_rth_1h_to_4h_csv
from tools.run_smc_lsr_evaluation import evaluate_symbol


def hourly_fixture() -> pd.DataFrame:
    index = pd.date_range(
        "2024-01-02 09:30", periods=7, freq="1h", tz="America/New_York"
    )
    return pd.DataFrame({
        "Open": [100, 101, 102, 103, 104, 105, 106],
        "High": [102, 103, 104, 105, 106, 107, 108],
        "Low": [99, 100, 101, 102, 103, 104, 105],
        "Close": [101, 102, 103, 104, 105, 106, 107],
        "Volume": [10, 11, 12, 13, 14, 15, 16],
    }, index=index)


class TestDownloadRealFourHourData(unittest.TestCase):
    def test_resample_uses_real_hourly_ohlcv_math(self):
        text = resample_rth_1h_to_4h_csv(
            hourly_fixture(),
            now=datetime(2024, 1, 3, tzinfo=ZoneInfo("America/New_York")),
        )
        rows = list(pd.read_csv(io.StringIO(text)).to_dict("records"))
        self.assertEqual(2, len(rows))
        self.assertEqual((100, 105, 99, 104, 46), (
            rows[0]["open"], rows[0]["high"], rows[0]["low"],
            rows[0]["close"], rows[0]["volume"],
        ))
        self.assertEqual((104, 108, 103, 107, 45), (
            rows[1]["open"], rows[1]["high"], rows[1]["low"],
            rows[1]["close"], rows[1]["volume"],
        ))

    @patch("tools.download_real_4h_data.fetch_1h_bars")
    def test_download_creates_csv_and_truthful_sidecar(self, fetch):
        fetch.return_value = hourly_fixture()
        with tempfile.TemporaryDirectory() as directory:
            result = download_and_import(
                "GLD", output_dir=directory,
                now=datetime(2024, 1, 3, tzinfo=ZoneInfo("America/New_York")),
            )
            metadata = json.loads(Path(result["meta_path"]).read_text(encoding="utf-8"))
            self.assertTrue(Path(result["csv_path"]).is_file())
            self.assertTrue(Path(result["meta_path"]).is_file())
        self.assertEqual("GLD", metadata["symbol"])
        self.assertEqual("4H", metadata["timeframe"])
        self.assertEqual("yfinance_1h", metadata["source"])
        self.assertFalse(metadata["synthetic"])
        self.assertEqual("unknown", metadata["adjustment"])
        self.assertEqual("1H", metadata["resampled_from"])
        self.assertEqual("RTH", metadata["session_policy"])

    def test_invalid_downloaded_data_is_rejected(self):
        invalid = hourly_fixture().drop(columns=["Low"])
        with self.assertRaisesRegex(ValueError, "missing columns"):
            resample_rth_1h_to_4h_csv(invalid)

    @patch("tools.download_real_4h_data.fetch_1h_bars")
    def test_evaluation_uses_downloaded_verified_4h_data(self, fetch):
        fetch.return_value = hourly_fixture()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "real" / "4h"
            download_and_import(
                "SPY", output_dir=str(output),
                now=datetime(2024, 1, 3, tzinfo=ZoneInfo("America/New_York")),
            )
            report = evaluate_symbol(TimeframeCsvAdapter(str(root)), "SPY", "4H")

        self.assertEqual("4H", report["effective_timeframe"])
        self.assertEqual("yfinance_1h", report["data"]["source"])
        self.assertFalse(any(
            warning.startswith("REQUESTED_TIMEFRAME_UNAVAILABLE")
            for warning in report["warnings"]
        ))

    def test_module_has_no_prohibited_imports_or_wording(self):
        path = Path(__file__).parents[1] / "tools" / "download_real_4h_data.py"
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        modules = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        modules.update(
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        )
        prohibited = {"dashboard", "broker", "orders", "execution", "live"}
        roots = {name.split(".")[0] for name in modules if name}
        self.assertTrue(prohibited.isdisjoint(roots))
        lowered = source.lower()
        for phrase in ("edge", "promising", "approved", "pilot"):
            self.assertNotIn(phrase, lowered)


if __name__ == "__main__":
    unittest.main()
