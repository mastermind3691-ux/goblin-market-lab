import ast
import json
import tempfile
import unittest
from pathlib import Path

from src.data.four_hour_csv import validate_4h_csv_text
from src.data.timeframe_csv_adapter import TimeframeCsvAdapter
from tools.prepare_real_4h_data import import_real_4h_csv
from tools.run_smc_lsr_evaluation import evaluate_symbol


VALID_4H = (
    "timestamp,open,high,low,close,volume\n"
    "2024-01-02T09:30:00,100,102,99,101,10\n"
    "2024-01-02T13:30:00,101,103,100,102,12\n"
)


def write_daily_fallback(root: Path, symbol: str) -> None:
    real_dir = root / "real"
    real_dir.mkdir(parents=True, exist_ok=True)
    (real_dir / f"{symbol}.csv").write_text(
        "date,open,high,low,close,volume\n"
        "2024-01-02,100,102,99,101,10\n",
        encoding="utf-8",
    )
    (real_dir / f"{symbol}.meta.json").write_text(
        json.dumps({
            "source": "daily_fixture",
            "synthetic": False,
            "adjustment": "unknown",
        }),
        encoding="utf-8",
    )


class TestRealFourHourData(unittest.TestCase):
    def test_valid_4h_import_is_selected_over_daily_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_daily_fallback(root, "GLD")
            imported = import_real_4h_csv(
                "GLD", VALID_4H, "vendor_fixture", "adjusted",
                "America/New_York", "RTH", output_dir=str(root / "real" / "4h"),
            )
            selection = TimeframeCsvAdapter(str(root)).select("GLD", "4H")

        self.assertEqual(2, imported["row_count"])
        self.assertEqual("4H", selection.effective_timeframe)
        self.assertEqual("vendor_fixture", selection.meta.source)
        self.assertFalse(selection.meta.synthetic)

    def test_missing_sidecar_falls_back_with_explicit_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_daily_fallback(root, "GLD")
            timeframe_dir = root / "real" / "4h"
            timeframe_dir.mkdir()
            (timeframe_dir / "GLD.csv").write_text(VALID_4H, encoding="utf-8")
            selection = TimeframeCsvAdapter(str(root)).select("GLD", "4H")

        self.assertEqual("1D", selection.effective_timeframe)
        self.assertTrue(any(
            warning.startswith("FOUR_HOUR_DATA_REJECTED")
            for warning in selection.warnings
        ))

    def test_daily_spaced_csv_is_rejected(self):
        result = validate_4h_csv_text(
            "timestamp,open,high,low,close\n"
            "2024-01-02T09:30:00,100,102,99,101\n"
            "2024-01-03T09:30:00,101,103,100,102\n"
        )
        self.assertFalse(result.ok)
        self.assertTrue(any("daily spacing" in error for error in result.errors))

    def test_empty_csv_is_rejected(self):
        result = validate_4h_csv_text("timestamp,open,high,low,close\n")
        self.assertFalse(result.ok)
        self.assertTrue(any("empty file" in error for error in result.errors))

    def test_missing_ohlc_column_is_rejected(self):
        result = validate_4h_csv_text(
            "timestamp,open,high,close\n"
            "2024-01-02T09:30:00,100,102,101\n"
        )
        self.assertFalse(result.ok)
        self.assertTrue(any("missing required columns" in error for error in result.errors))

    def test_impossible_ohlc_is_rejected(self):
        result = validate_4h_csv_text(
            "timestamp,open,high,low,close\n"
            "2024-01-02T09:30:00,100,99,98,101\n"
            "2024-01-02T13:30:00,101,103,100,102\n"
        )
        self.assertFalse(result.ok)
        self.assertTrue(any("high is below" in error for error in result.errors))

    def test_duplicate_timestamps_are_rejected(self):
        result = validate_4h_csv_text(
            "timestamp,open,high,low,close\n"
            "2024-01-02T09:30:00,100,102,99,101\n"
            "2024-01-02T09:30:00,101,103,100,102\n"
        )
        self.assertFalse(result.ok)
        self.assertTrue(any("duplicate timestamp" in error for error in result.errors))

    def test_unsorted_timestamps_are_rejected(self):
        result = validate_4h_csv_text(
            "timestamp,open,high,low,close\n"
            "2024-01-02T13:30:00,101,103,100,102\n"
            "2024-01-02T09:30:00,100,102,99,101\n"
        )
        self.assertFalse(result.ok)
        self.assertTrue(any("not sorted" in error for error in result.errors))

    def test_report_uses_4h_only_for_verified_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            import_real_4h_csv(
                "SPY", VALID_4H, "vendor_fixture", "unknown",
                "America/New_York", "unknown", resampled_from="1H",
                output_dir=str(root / "real" / "4h"),
            )
            report = evaluate_symbol(TimeframeCsvAdapter(str(root)), "SPY", "4H")

        self.assertEqual("4H", report["requested_timeframe"])
        self.assertEqual("4H", report["effective_timeframe"])
        self.assertEqual("vendor_fixture", report["data"]["source"])
        self.assertFalse(report["data"]["synthetic"])
        self.assertFalse(any(
            warning.startswith("REQUESTED_TIMEFRAME_UNAVAILABLE")
            for warning in report["warnings"]
        ))
        self.assertTrue(any(
            warning.startswith("FOUR_HOUR_DATA_WARNING")
            for warning in report["warnings"]
        ))

    def test_daily_fallback_still_applies_without_4h_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_daily_fallback(root, "SPY")
            report = evaluate_symbol(TimeframeCsvAdapter(str(root)), "SPY", "4H")

        self.assertEqual("1D", report["effective_timeframe"])
        self.assertTrue(any(
            warning.startswith("REQUESTED_TIMEFRAME_UNAVAILABLE")
            for warning in report["warnings"]
        ))

    def test_modules_have_no_prohibited_imports(self):
        root = Path(__file__).parents[1]
        prohibited = {"dashboard", "broker", "orders", "execution", "live"}
        for relative in (
            "src/data/four_hour_csv.py",
            "src/data/timeframe_csv_adapter.py",
            "tools/prepare_real_4h_data.py",
        ):
            tree = ast.parse((root / relative).read_text(encoding="utf-8"))
            modules = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
            modules.update(
                alias.name
                for node in ast.walk(tree)
                if isinstance(node, ast.Import)
                for alias in node.names
            )
            roots = {name.split(".")[0] for name in modules if name}
            self.assertTrue(prohibited.isdisjoint(roots), relative)


if __name__ == "__main__":
    unittest.main()
