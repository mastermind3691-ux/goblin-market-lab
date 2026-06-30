import ast
import unittest
from pathlib import Path

from src.backtest.judge import judge_setup
from tools.run_smc_sweep_mss_candidate_evaluation import (
    _rejection_labels,
    evaluate_cell,
    generate_sweep_mss_setups,
)


def _flat_bars(price: float = 100.0, n: int = 40) -> list[dict]:
    return [
        {"ts": f"2024-01-01T{i:02d}:00:00", "open": price, "high": price + 0.1,
         "low": price - 0.1, "close": price, "volume": 10}
        for i in range(n)
    ]


def _bullish_sweep_then_mss_bars(
    pivot_left: int = 5, pivot_right: int = 2,
) -> list[dict]:
    """Low pivot at pivot_left, swept later, then close breaks frozen high."""
    bars = []
    base = 100.0
    n = pivot_left + 1 + pivot_right + 20
    for i in range(n):
        if i == pivot_left:
            o, h, lo, c = base - 5, base + 8, base - 8, base - 5
        elif i == pivot_left + pivot_right + 3:
            o, h, lo, c = base - 6, base - 4, base - 10, base - 5
        elif i == pivot_left + pivot_right + 5:
            o, h, lo, c = base + 10, base + 12, base + 9, base + 11
        else:
            o, h, lo, c = base, base + 1, base - 1, base
        bars.append({"ts": f"2024-01-{i+1:02d}T09:30:00-05:00",
                      "open": o, "high": h, "low": lo, "close": c, "volume": 10})
    return bars


def _bearish_sweep_then_mss_bars(
    pivot_left: int = 5, pivot_right: int = 2,
) -> list[dict]:
    """High pivot at pivot_left, swept later, then close breaks frozen low."""
    bars = []
    base = 100.0
    n = pivot_left + 1 + pivot_right + 20
    for i in range(n):
        if i == pivot_left:
            o, h, lo, c = base + 5, base + 8, base - 8, base + 5
        elif i == pivot_left + pivot_right + 3:
            o, h, lo, c = base + 6, base + 10, base + 4, base + 5
        elif i == pivot_left + pivot_right + 5:
            o, h, lo, c = base - 10, base - 9, base - 12, base - 11
        else:
            o, h, lo, c = base, base + 1, base - 1, base
        bars.append({"ts": f"2024-01-{i+1:02d}T09:30:00-05:00",
                      "open": o, "high": h, "low": lo, "close": c, "volume": 10})
    return bars


class TestSweepRequiresConfirmation(unittest.TestCase):
    def test_sweep_cannot_occur_before_pivot_confirmation(self):
        bars = _bullish_sweep_then_mss_bars(5, 2)
        setups, _ = generate_sweep_mss_setups(bars, 5, 2, mss_expiration_bars=12, target_r=2.0)
        for s in setups:
            self.assertGreater(s.metadata["sweep_i"], 5 + 2)


class TestMssUsesFrozenOpposingPivot(unittest.TestCase):
    def test_bullish_mss_freezes_high_pivot(self):
        bars = _bullish_sweep_then_mss_bars(5, 2)
        setups, _ = generate_sweep_mss_setups(bars, 5, 2, mss_expiration_bars=12, target_r=2.0)
        for s in setups:
            if s.side == "long":
                fwd_close = float(bars[s.metadata["mss_bar_i"]]["close"])
                self.assertGreater(fwd_close, s.metadata["frozen_mss_level"])

    def test_bearish_mss_freezes_low_pivot(self):
        bars = _bearish_sweep_then_mss_bars(5, 2)
        setups, _ = generate_sweep_mss_setups(bars, 5, 2, mss_expiration_bars=12, target_r=2.0)
        for s in setups:
            if s.side == "short":
                fwd_close = float(bars[s.metadata["mss_bar_i"]]["close"])
                self.assertLess(fwd_close, s.metadata["frozen_mss_level"])


class TestSameBarSweepToMssDisabled(unittest.TestCase):
    def test_mss_bar_always_after_sweep_bar(self):
        bars = _bullish_sweep_then_mss_bars(5, 2)
        setups, _ = generate_sweep_mss_setups(bars, 5, 2, mss_expiration_bars=16, target_r=2.0)
        for s in setups:
            self.assertGreater(s.metadata["mss_bar_i"], s.metadata["sweep_i"])


class TestDualSweepIgnored(unittest.TestCase):
    def test_outside_bar_does_not_directly_create_setup(self):
        bars = _flat_bars(n=40)
        bars[5] = {"ts": "d", "open": 110, "high": 115, "low": 85, "close": 100, "volume": 10}
        bars[7] = {"ts": "d", "open": 100, "high": 120, "low": 80, "close": 100, "volume": 10}
        setups, sweeps = generate_sweep_mss_setups(
            bars, 5, 2, mss_expiration_bars=8, target_r=2.0,
        )
        for s in setups:
            self.assertIn(s.metadata["sweep_side"], ("bullish", "bearish"))


class TestEntryValidFromIsCreatedPlusOne(unittest.TestCase):
    def test_valid_from_i(self):
        bars = _bullish_sweep_then_mss_bars(5, 2)
        setups, _ = generate_sweep_mss_setups(bars, 5, 2, mss_expiration_bars=12, target_r=2.0)
        for s in setups:
            self.assertEqual(s.valid_from_i, s.created_i + 1)
            self.assertEqual(s.created_i, s.metadata["mss_bar_i"])


class TestLongInvalidationAndTargetMath(unittest.TestCase):
    def test_long_setup_math(self):
        bars = _bullish_sweep_then_mss_bars(5, 2)
        setups, _ = generate_sweep_mss_setups(bars, 5, 2, mss_expiration_bars=12, target_r=2.0)
        longs = [s for s in setups if s.side == "long"]
        self.assertGreater(len(longs), 0)
        for s in longs:
            next_bar = bars[s.valid_from_i]
            self.assertAlmostEqual(s.entry, float(next_bar["open"]), places=10)
            sweep_bar = bars[s.metadata["sweep_i"]]
            self.assertAlmostEqual(s.invalidation, float(sweep_bar["low"]), places=10)
            risk = abs(s.entry - s.invalidation)
            self.assertAlmostEqual(s.target, s.entry + risk * 2.0, places=10)


class TestShortInvalidationAndTargetMath(unittest.TestCase):
    def test_short_setup_math(self):
        bars = _bearish_sweep_then_mss_bars(5, 2)
        setups, _ = generate_sweep_mss_setups(bars, 5, 2, mss_expiration_bars=12, target_r=1.5)
        shorts = [s for s in setups if s.side == "short"]
        self.assertGreater(len(shorts), 0)
        for s in shorts:
            next_bar = bars[s.valid_from_i]
            self.assertAlmostEqual(s.entry, float(next_bar["open"]), places=10)
            sweep_bar = bars[s.metadata["sweep_i"]]
            self.assertAlmostEqual(s.invalidation, float(sweep_bar["high"]), places=10)
            risk = abs(s.entry - s.invalidation)
            self.assertAlmostEqual(s.target, s.entry - risk * 1.5, places=10)


class TestJudgeReceivesValidSetups(unittest.TestCase):
    def test_judge_runs_without_error(self):
        bars = _bullish_sweep_then_mss_bars(5, 2)
        setups, _ = generate_sweep_mss_setups(bars, 5, 2, mss_expiration_bars=12, target_r=2.0)
        for s in setups:
            result = judge_setup(s, bars)
            self.assertIn(result.status, (
                "WIN", "LOSS", "NO_FILL", "PENDING", "AMBIGUOUS_WORST_CASE",
            ))


class TestAmbiguousWorstCasePropagates(unittest.TestCase):
    def test_target_and_invalidation_same_bar_is_worst_case(self):
        bars = _bullish_sweep_then_mss_bars(5, 2)
        setups, _ = generate_sweep_mss_setups(bars, 5, 2, mss_expiration_bars=12, target_r=0.001)
        for s in setups:
            result = judge_setup(s, bars)
            if result.status == "AMBIGUOUS_WORST_CASE":
                self.assertEqual(result.r_result, -1.0)


class TestSampleAndOutlierLabels(unittest.TestCase):
    def test_insufficient_sample(self):
        row = {
            "wins": 2, "losses": 3, "conservative_expectancy_r": 0.1,
            "fill_rate": 0.5, "net_r": 1.0,
            "result_after_removing_best_trade": 0.5,
            "result_after_removing_best_two_trades": 0.2,
        }
        self.assertIn("INSUFFICIENT_SAMPLE", _rejection_labels(row))

    def test_weak_sample(self):
        row = {
            "wins": 20, "losses": 15, "conservative_expectancy_r": 0.1,
            "fill_rate": 0.5, "net_r": 1.0,
            "result_after_removing_best_trade": 0.5,
            "result_after_removing_best_two_trades": 0.2,
        }
        labels = _rejection_labels(row)
        self.assertIn("WEAK_SAMPLE", labels)
        self.assertNotIn("INSUFFICIENT_SAMPLE", labels)

    def test_negative_expectancy(self):
        row = {
            "wins": 50, "losses": 60, "conservative_expectancy_r": -0.2,
            "fill_rate": 0.5, "net_r": -3.0,
            "result_after_removing_best_trade": -4.0,
            "result_after_removing_best_two_trades": -5.0,
        }
        self.assertIn("NEGATIVE_EXPECTANCY", _rejection_labels(row))

    def test_low_fill_rate(self):
        row = {
            "wins": 50, "losses": 60, "conservative_expectancy_r": 0.1,
            "fill_rate": 0.1, "net_r": 1.0,
            "result_after_removing_best_trade": 0.5,
            "result_after_removing_best_two_trades": 0.2,
        }
        self.assertIn("LOW_FILL_RATE", _rejection_labels(row))

    def test_fragile_outlier(self):
        row = {
            "wins": 50, "losses": 60, "conservative_expectancy_r": 0.1,
            "fill_rate": 0.5, "net_r": 2.0,
            "result_after_removing_best_trade": -1.0,
            "result_after_removing_best_two_trades": -3.0,
        }
        self.assertIn("FRAGILE_OUTLIER", _rejection_labels(row))

    def test_not_fragile_when_still_positive(self):
        row = {
            "wins": 50, "losses": 60, "conservative_expectancy_r": 0.1,
            "fill_rate": 0.5, "net_r": 5.0,
            "result_after_removing_best_trade": 3.0,
            "result_after_removing_best_two_trades": 1.0,
        }
        self.assertNotIn("FRAGILE_OUTLIER", _rejection_labels(row))


class TestPerSymbolAggregation(unittest.TestCase):
    def test_per_symbol_breakdown_sums_to_aggregate(self):
        bars_a = _bullish_sweep_then_mss_bars(5, 2)
        bars_b = _bearish_sweep_then_mss_bars(5, 2)
        result = evaluate_cell(5, 2, 12, 2.0, {"A": bars_a, "B": bars_b})
        self.assertIn("A", result["per_symbol"])
        self.assertIn("B", result["per_symbol"])
        total_setups = (result["per_symbol"]["A"]["total_setups"]
                         + result["per_symbol"]["B"]["total_setups"])
        self.assertEqual(total_setups, result["total_setups"])


class TestNoProhibitedContent(unittest.TestCase):
    def test_no_prohibited_imports_or_wording(self):
        path = Path(__file__).parents[1] / "tools" / "run_smc_sweep_mss_candidate_evaluation.py"
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
