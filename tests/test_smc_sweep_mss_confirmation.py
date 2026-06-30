import ast
import unittest
from pathlib import Path

from tools.run_smc_sweep_mss_confirmation import (
    FROZEN_MSS_EXPIRATION_BARS,
    FROZEN_PIVOT_LEFT,
    FROZEN_PIVOT_RIGHT,
    FROZEN_TARGET_R,
    _cost_stress,
    _outlier_removal,
    _permutation_test,
    run_confirmation,
)
from src.data.timeframe_csv_adapter import TimeframeCsvAdapter


def _bullish_sweep_then_mss_bars(pivot_left=5, pivot_right=2, repeats=3):
    bars = []
    base = 100.0
    block = pivot_left + 1 + pivot_right + 20
    for r in range(repeats):
        for i in range(block):
            if i == pivot_left:
                o, h, lo, c = base - 5, base + 8, base - 8, base - 5
            elif i == pivot_left + pivot_right + 3:
                o, h, lo, c = base - 6, base - 4, base - 10, base - 5
            elif i == pivot_left + pivot_right + 5:
                o, h, lo, c = base + 10, base + 12, base + 9, base + 11
            else:
                o, h, lo, c = base, base + 1, base - 1, base
            bars.append({"ts": f"2024-{r+1:02d}-{i+1:02d}T09:30:00-05:00",
                          "open": o, "high": h, "low": lo, "close": c, "volume": 10})
    return bars


class _FakeAdapter:
    def __init__(self, symbol_bars):
        self.symbol_bars = symbol_bars

    def select(self, symbol, timeframe, limit=999_999):
        from src.data.base import DataMeta
        from src.data.timeframe_csv_adapter import CsvDataSelection
        bars = self.symbol_bars.get(symbol, [])
        return CsvDataSelection(
            bars=bars,
            meta=DataMeta(source="unit_test", synthetic=False, adjustment="unknown"),
            effective_timeframe="4H" if bars else "1D",
            warnings=(),
        )


class TestFrozenConfig(unittest.TestCase):
    def test_frozen_parameters_exact(self):
        self.assertEqual(FROZEN_PIVOT_LEFT, 5)
        self.assertEqual(FROZEN_PIVOT_RIGHT, 2)
        self.assertEqual(FROZEN_MSS_EXPIRATION_BARS, 16)
        self.assertEqual(FROZEN_TARGET_R, 2.0)


class TestReportStructure(unittest.TestCase):
    def setUp(self):
        bars = _bullish_sweep_then_mss_bars()
        adapter = _FakeAdapter({"T": bars})
        self.result = run_confirmation(["T"], adapter)

    def test_per_symbol_split_present(self):
        self.assertIn("T", self.result["per_symbol"])

    def test_long_short_split_present(self):
        self.assertIn("long", self.result["by_side"])
        self.assertIn("short", self.result["by_side"])
        for side in ("long", "short"):
            self.assertIn("count", self.result["by_side"][side])
            self.assertIn("net_r", self.result["by_side"][side])

    def test_per_year_split_present(self):
        self.assertIsInstance(self.result["per_year"], dict)


class TestOutlierRemoval(unittest.TestCase):
    def test_removal_math(self):
        values = [2.0, 2.0, -1.0, -1.0, -1.0]
        result = _outlier_removal(values)
        self.assertEqual(result["net_r"], 1.0)
        self.assertEqual(result["result_after_removing_best_1"], -1.0)
        self.assertEqual(result["result_after_removing_best_2"], -3.0)
        self.assertEqual(result["result_after_removing_best_3"], -2.0)

    def test_fragile_flagged_when_flips_negative(self):
        values = [5.0, -1.0, -1.0]
        result = _outlier_removal(values)
        self.assertTrue(result["net_r"] > 0)
        self.assertTrue(result["fragile_outlier"])

    def test_not_fragile_when_robust(self):
        values = [2.0, 2.0, 2.0, 2.0, -1.0, -1.0]
        result = _outlier_removal(values)
        self.assertFalse(result["fragile_outlier"])


class TestCostStress(unittest.TestCase):
    def test_penalty_math(self):
        values = [2.0, -1.0, 2.0, -1.0]
        rows = _cost_stress(values)
        self.assertEqual(len(rows), 3)
        penalty_05 = next(r for r in rows if r["penalty_r_per_trade"] == 0.05)
        expected = sum(values) - 0.05 * len(values)
        self.assertAlmostEqual(penalty_05["adjusted_net_r"], expected, places=10)
        self.assertEqual(penalty_05["remains_positive"], expected > 0)


class TestPermutationTest(unittest.TestCase):
    def test_deterministic_with_seed(self):
        values = [2.0, -1.0, 2.0, -1.0, 2.0, -1.0]
        result_a = _permutation_test(values)
        result_b = _permutation_test(values)
        self.assertEqual(result_a, result_b)

    def test_skipped_when_too_few_values(self):
        result = _permutation_test([1.0])
        self.assertFalse(result["implemented"])
        self.assertIn("reason", result)

    def test_implemented_reports_percentile(self):
        values = [2.0, -1.0, 2.0, -1.0, 2.0]
        result = _permutation_test(values)
        self.assertTrue(result["implemented"])
        self.assertIn("percentile_of_actual", result)


class TestSampleWarnings(unittest.TestCase):
    def test_weak_sample_warning_present(self):
        bars = _bullish_sweep_then_mss_bars(repeats=1)
        adapter = _FakeAdapter({"T": bars})
        result = run_confirmation(["T"], adapter)
        joined = " ".join(result["warnings"])
        self.assertIn("WEAK_SAMPLE", joined)


class TestMultipleComparisonsWarning(unittest.TestCase):
    def test_warning_present(self):
        bars = _bullish_sweep_then_mss_bars()
        adapter = _FakeAdapter({"T": bars})
        result = run_confirmation(["T"], adapter)
        joined = " ".join(result["warnings"])
        self.assertIn("MULTIPLE_COMPARISONS_RISK", joined)


class TestNoProhibitedContent(unittest.TestCase):
    def test_no_prohibited_imports_or_wording(self):
        path = Path(__file__).parents[1] / "tools" / "run_smc_sweep_mss_confirmation.py"
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        modules = {node.module for node in ast.walk(tree)
                    if isinstance(node, ast.ImportFrom)}
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
