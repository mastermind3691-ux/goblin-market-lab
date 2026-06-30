import ast
import unittest
from pathlib import Path

from tools.run_smc_sweep_mss_long_only_confirmation import (
    run_long_only_confirmation,
)
from tools.run_smc_sweep_mss_confirmation import (
    FROZEN_MSS_EXPIRATION_BARS,
    FROZEN_PIVOT_LEFT,
    FROZEN_PIVOT_RIGHT,
    FROZEN_TARGET_R,
)
from src.data.base import DataMeta
from src.data.timeframe_csv_adapter import CsvDataSelection


def _mixed_long_short_bars(pivot_left=5, pivot_right=2, repeats=4):
    """Bars producing both bullish (long) and bearish (short) MSS setups."""
    bars = []
    base = 100.0
    block = pivot_left + 1 + pivot_right + 20
    for r in range(repeats):
        for i in range(block):
            if r % 2 == 0:
                # bullish sweep then bullish MSS -> long
                if i == pivot_left:
                    o, h, lo, c = base - 5, base + 8, base - 8, base - 5
                elif i == pivot_left + pivot_right + 3:
                    o, h, lo, c = base - 6, base - 4, base - 10, base - 5
                elif i == pivot_left + pivot_right + 5:
                    o, h, lo, c = base + 10, base + 12, base + 9, base + 11
                else:
                    o, h, lo, c = base, base + 1, base - 1, base
            else:
                # bearish sweep then bearish MSS -> short
                if i == pivot_left:
                    o, h, lo, c = base + 5, base + 8, base - 8, base + 5
                elif i == pivot_left + pivot_right + 3:
                    o, h, lo, c = base + 6, base + 10, base + 4, base + 5
                elif i == pivot_left + pivot_right + 5:
                    o, h, lo, c = base - 10, base - 9, base - 12, base - 11
                else:
                    o, h, lo, c = base, base + 1, base - 1, base
            bars.append({"ts": f"202{r}-01-{i+1:02d}T09:30:00-05:00",
                          "open": o, "high": h, "low": lo, "close": c, "volume": 10})
    return bars


class _FakeAdapter:
    def __init__(self, symbol_bars):
        self.symbol_bars = symbol_bars

    def select(self, symbol, timeframe, limit=999_999):
        bars = self.symbol_bars.get(symbol, [])
        return CsvDataSelection(
            bars=bars,
            meta=DataMeta(source="unit_test", synthetic=False, adjustment="unknown"),
            effective_timeframe="4H" if bars else "1D",
            warnings=(),
        )


class TestFrozenConfig(unittest.TestCase):
    def test_frozen_parameters_exact(self):
        bars = _mixed_long_short_bars()
        adapter = _FakeAdapter({"T": bars})
        result = run_long_only_confirmation(["T"], adapter)
        params = result["long_only_candidate"]["parameters"]
        self.assertEqual(params["pivot_left"], 5)
        self.assertEqual(params["pivot_right"], 2)
        self.assertEqual(params["mss_expiration_bars"], 16)
        self.assertEqual(params["target_r"], 2.0)
        self.assertEqual(FROZEN_PIVOT_LEFT, 5)
        self.assertEqual(FROZEN_PIVOT_RIGHT, 2)
        self.assertEqual(FROZEN_MSS_EXPIRATION_BARS, 16)
        self.assertEqual(FROZEN_TARGET_R, 2.0)
        self.assertEqual(params["side"], "long")


class TestLongExcludesShort(unittest.TestCase):
    def setUp(self):
        bars = _mixed_long_short_bars()
        adapter = _FakeAdapter({"T": bars})
        self.result = run_long_only_confirmation(["T"], adapter)

    def test_long_only_candidate_has_no_short_field(self):
        self.assertNotIn("short", self.result["long_only_candidate"])

    def test_short_only_diagnostic_present_and_labeled(self):
        self.assertIn("short_only_diagnostic", self.result)
        self.assertEqual(
            self.result["short_only_diagnostic"]["label"],
            "DIAGNOSTIC_REJECTED_BY_SPLIT",
        )

    def test_both_sides_have_setups_in_fixture(self):
        self.assertGreater(self.result["long_only_candidate"]["total_setups"], 0)
        self.assertGreater(self.result["short_only_diagnostic"]["total_setups"], 0)


class TestPerSymbolAndPerYear(unittest.TestCase):
    def setUp(self):
        bars = _mixed_long_short_bars()
        adapter = _FakeAdapter({"T": bars})
        self.result = run_long_only_confirmation(["T"], adapter)

    def test_per_symbol_long_only(self):
        self.assertIn("T", self.result["per_symbol_long_only"])
        self.assertIn("net_r", self.result["per_symbol_long_only"]["T"])

    def test_per_year_long_only(self):
        self.assertIsInstance(self.result["per_year_long_only"], dict)
        self.assertGreater(len(self.result["per_year_long_only"]), 0)


class TestOutlierAndCostStress(unittest.TestCase):
    def test_outlier_removal_keys(self):
        bars = _mixed_long_short_bars()
        adapter = _FakeAdapter({"T": bars})
        result = run_long_only_confirmation(["T"], adapter)
        ord_block = result["outlier_removal_long_only"]["ordinary"]
        for key in (
            "net_r", "result_after_removing_best_1",
            "result_after_removing_best_2", "result_after_removing_best_3",
            "fragile_outlier",
        ):
            self.assertIn(key, ord_block)

    def test_cost_stress_three_levels(self):
        bars = _mixed_long_short_bars()
        adapter = _FakeAdapter({"T": bars})
        result = run_long_only_confirmation(["T"], adapter)
        penalties = [r["penalty_r_per_trade"] for r in result["cost_slippage_stress_long_only"]]
        self.assertEqual(penalties, [0.05, 0.10, 0.20])


class TestPermutationDeterministic(unittest.TestCase):
    def test_same_result_twice(self):
        bars = _mixed_long_short_bars()
        adapter = _FakeAdapter({"T": bars})
        r1 = run_long_only_confirmation(["T"], adapter)
        r2 = run_long_only_confirmation(["T"], adapter)
        self.assertEqual(
            r1["permutation_null_test_long_only"],
            r2["permutation_null_test_long_only"],
        )


class TestSampleAndComparisonWarnings(unittest.TestCase):
    def test_weak_sample_warning(self):
        bars = _mixed_long_short_bars(repeats=2)
        adapter = _FakeAdapter({"T": bars})
        result = run_long_only_confirmation(["T"], adapter)
        joined = " ".join(result["warnings"])
        self.assertIn("WEAK_SAMPLE", joined)

    def test_multiple_comparisons_warning(self):
        bars = _mixed_long_short_bars()
        adapter = _FakeAdapter({"T": bars})
        result = run_long_only_confirmation(["T"], adapter)
        joined = " ".join(result["warnings"])
        self.assertIn("MULTIPLE_COMPARISONS_RISK", joined)

    def test_comparison_block_present(self):
        bars = _mixed_long_short_bars()
        adapter = _FakeAdapter({"T": bars})
        result = run_long_only_confirmation(["T"], adapter)
        comp = result["comparison_to_combined"]
        self.assertIn("combined_net_r", comp)
        self.assertIn("long_only_net_r", comp)
        self.assertIn("short_only_net_r", comp)
        self.assertAlmostEqual(
            comp["combined_net_r"],
            comp["long_only_net_r"] + comp["short_only_net_r"],
            places=10,
        )


class TestNoProhibitedContent(unittest.TestCase):
    def test_no_prohibited_imports_or_wording(self):
        path = Path(__file__).parents[1] / "tools" / "run_smc_sweep_mss_long_only_confirmation.py"
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
