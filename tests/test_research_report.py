import ast
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from src.backtest.judge import JudgeResult, SetupEvent
from src.data.base import DataMeta
from src.backtest.research_report import build_research_report
from src.data.timeframe_csv_adapter import CsvDataSelection, TimeframeCsvAdapter
from tools.run_smc_lsr_evaluation import evaluate_symbol


def setup(created_i=0):
    return SetupEvent(
        side="long",
        created_i=created_i,
        valid_from_i=created_i + 1,
        entry=100,
        invalidation=99,
        target=102,
        expires_i=created_i + 2,
    )


def result(status, r_result=None, filled=True):
    return JudgeResult(
        status=status,
        filled_i=1 if filled else None,
        closed_i=2 if status not in {"NO_FILL", "PENDING"} else None,
        entry=100,
        exit_price=None,
        r_result=r_result,
        reason="test fixture",
        bars_held=1 if filled else 0,
        metadata={},
    )


class TestResearchReport(unittest.TestCase):
    def report(self, results):
        bars = [{"ts": "2024-01-01"}] * max(1, len(results))
        setups = [setup(i) for i in range(len(results))]
        return build_research_report("SPY", "1d", bars, setups, results)

    def mixed_results(self):
        return [
            result("WIN", 2.0),
            result("WIN", 1.0),
            result("LOSS", -1.0),
            result("NO_FILL", filled=False),
            result("AMBIGUOUS_WORST_CASE", -1.0),
            result("PENDING"),
        ]

    def test_counts_outcomes_and_fills(self):
        report = self.report(self.mixed_results())
        self.assertEqual(6, report["total_setups"])
        self.assertEqual(5, report["filled_setups"])
        self.assertEqual((2, 1, 1, 1, 1), (
            report["wins"], report["losses"], report["no_fills"],
            report["ambiguous_worst_case"], report["pending"],
        ))

    def test_conservative_ambiguous_result_is_minus_one_r(self):
        report = self.report([result("AMBIGUOUS_WORST_CASE", -1.0)])
        self.assertEqual(0.0, report["net_r"])
        self.assertEqual(-1.0, report["conservative_net_r"])

    def test_expectancy_and_conservative_expectancy(self):
        report = self.report(self.mixed_results())
        self.assertAlmostEqual(2 / 3, report["expectancy_r"])
        self.assertAlmostEqual(0.25, report["conservative_expectancy_r"])
        self.assertEqual(report["expectancy_r"], report["average_r"])
        self.assertEqual(
            report["conservative_expectancy_r"], report["conservative_average_r"]
        )

    def test_profit_factor_in_r(self):
        report = self.report(self.mixed_results())
        self.assertEqual(3.0, report["profit_factor_r"])
        self.assertAlmostEqual(2 / 3, report["largest_winning_trade_contribution"])

    def test_removing_best_trade(self):
        report = self.report(self.mixed_results())
        self.assertEqual(0.0, report["result_after_removing_best_trade"])
        self.assertEqual(-1.0, report["conservative_result_after_removing_best_trade"])

    def test_removing_best_two_trades(self):
        report = self.report(self.mixed_results())
        self.assertEqual(-1.0, report["result_after_removing_best_two_trades"])
        self.assertEqual(-2.0, report["conservative_result_after_removing_best_two_trades"])

    def test_sample_size_warning_appears(self):
        report = self.report(self.mixed_results())
        self.assertEqual("INSUFFICIENT_SAMPLE", report["sample_status"])
        self.assertIn("INSUFFICIENT_SAMPLE", report["warnings"][0])

    def test_weak_sample_warning_appears_below_one_hundred(self):
        report = self.report([result("LOSS", -1.0) for _ in range(30)])
        self.assertEqual("WEAK_SAMPLE", report["sample_status"])
        self.assertIn("WEAK_SAMPLE", report["warnings"][0])

    def test_per_year_split_uses_setup_creation_timestamp(self):
        bars = [{"ts": "2023-12-31"}, {"ts": "2024-01-01"}]
        setups = [setup(0), setup(1)]
        results = [result("WIN", 2.0), result("LOSS", -1.0)]
        report = build_research_report("SPY", "1d", bars, setups, results)
        self.assertEqual({"2023", "2024"}, set(report["per_year"]))

    def test_report_and_cli_have_no_prohibited_imports(self):
        root = Path(__file__).parents[1]
        paths = [
            root / "src" / "backtest" / "research_report.py",
            root / "src" / "data" / "timeframe_csv_adapter.py",
            root / "tools" / "run_smc_lsr_evaluation.py",
        ]
        prohibited = {"dashboard", "broker", "orders", "execution", "live"}
        for path in paths:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            modules = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
            modules.update(
                alias.name
                for node in ast.walk(tree)
                if isinstance(node, ast.Import)
                for alias in node.names
            )
            roots = {name.split(".")[0] for name in modules if name}
            self.assertTrue(prohibited.isdisjoint(roots), path)

    def test_cli_help_runs_directly_without_pythonpath(self):
        root = Path(__file__).parents[1]
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        completed = subprocess.run(
            [sys.executable, str(root / "tools" / "run_smc_lsr_evaluation.py"), "--help"],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertIn("usage: run_smc_lsr_evaluation.py", completed.stdout)

    def test_cli_reports_requested_and_effective_csv_timeframes(self):
        class FakeCsvAdapter:
            def select(self, symbol, timeframe, limit=500):
                return CsvDataSelection(
                    [], DataMeta("fixture", False, "adjusted"), "1D"
                )

        adapter = FakeCsvAdapter()
        report = evaluate_symbol(adapter, "GLD", "4H")

        self.assertEqual("4H", report["requested_timeframe"])
        self.assertEqual("1D", report["effective_timeframe"])
        self.assertEqual("1D", report["timeframe"])
        self.assertTrue(any(
            warning.startswith("REQUESTED_TIMEFRAME_UNAVAILABLE")
            for warning in report["warnings"]
        ))

    def test_daily_request_has_no_timeframe_warning(self):
        class FakeCsvAdapter:
            def select(self, symbol, timeframe, limit=500):
                return CsvDataSelection(
                    [], DataMeta("fixture", False, "adjusted"), "1D"
                )

        report = evaluate_symbol(FakeCsvAdapter(), "SPY", "daily")
        self.assertEqual("daily", report["requested_timeframe"])
        self.assertEqual("1D", report["effective_timeframe"])
        self.assertFalse(any(
            warning.startswith("REQUESTED_TIMEFRAME_UNAVAILABLE")
            for warning in report["warnings"]
        ))

    def test_true_4h_csv_is_selected_when_contract_is_satisfied(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            timeframe_dir = root / "real" / "4h"
            timeframe_dir.mkdir(parents=True)
            (timeframe_dir / "GLD.csv").write_text(
                "ts,open,high,low,close,volume\n"
                "2024-01-02T09:30:00,100,102,99,101,10\n"
                "2024-01-02T13:30:00,101,103,100,102,12\n",
                encoding="utf-8",
            )
            (timeframe_dir / "GLD.meta.json").write_text(
                '{"source":"fixture_4h","synthetic":false,'
                '"adjustment":"adjusted","timeframe":"4H"}',
                encoding="utf-8",
            )

            report = evaluate_symbol(TimeframeCsvAdapter(str(root)), "GLD", "4H")

        self.assertEqual("4H", report["requested_timeframe"])
        self.assertEqual("4H", report["effective_timeframe"])
        self.assertEqual("4H", report["timeframe"])
        self.assertEqual("fixture_4h", report["data"]["source"])
        self.assertFalse(report["data"]["synthetic"])
        self.assertEqual("adjusted", report["data"]["adjustment"])
        self.assertFalse(any(
            warning.startswith("REQUESTED_TIMEFRAME_UNAVAILABLE")
            for warning in report["warnings"]
        ))

    def test_synthetic_4h_csv_is_not_selected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            real_dir = root / "real"
            timeframe_dir = real_dir / "4h"
            timeframe_dir.mkdir(parents=True)
            csv_text = (
                "ts,open,high,low,close,volume\n"
                "2024-01-02T09:30:00,100,102,99,101,10\n"
                "2024-01-02T13:30:00,101,103,100,102,12\n"
            )
            (timeframe_dir / "SPY.csv").write_text(csv_text, encoding="utf-8")
            (timeframe_dir / "SPY.meta.json").write_text(
                '{"source":"synthetic_fixture","synthetic":true,'
                '"adjustment":"unknown","timeframe":"4H"}',
                encoding="utf-8",
            )
            (real_dir / "SPY.csv").write_text(
                "date,open,high,low,close,volume\n"
                "2024-01-02,100,102,99,101,10\n",
                encoding="utf-8",
            )
            (real_dir / "SPY.meta.json").write_text(
                '{"source":"daily_fixture","synthetic":false,'
                '"adjustment":"unknown"}',
                encoding="utf-8",
            )

            report = evaluate_symbol(TimeframeCsvAdapter(str(root)), "SPY", "4H")

        self.assertEqual("1D", report["effective_timeframe"])
        self.assertEqual("daily_fixture", report["data"]["source"])
        self.assertTrue(any(
            warning.startswith("REQUESTED_TIMEFRAME_UNAVAILABLE")
            for warning in report["warnings"]
        ))


if __name__ == "__main__":
    unittest.main()
