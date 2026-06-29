import ast
import unittest
from pathlib import Path

from src.strategies.smc_liquidity_sweep_reversion import (
    SMCLiquiditySweepReversionConfig,
)
from tools.run_smc_lsr_parameter_surface import (
    _rejection_labels,
    build_parameter_grid,
    evaluate_cell,
)


def _make_bars(n: int = 300) -> list[dict]:
    bars = []
    price = 100.0
    for i in range(n):
        delta = 0.5 * (1 if i % 3 == 0 else -1)
        o = price
        c = price + delta
        h = max(o, c) + 0.2
        lo = min(o, c) - 0.2
        bars.append({
            "ts": f"2024-01-{(i // 2) + 1:02d}T{9 + (i % 2) * 4:02d}:30:00-05:00",
            "open": o, "high": h, "low": lo, "close": c, "volume": 100,
        })
        price = c
    return bars


class TestParameterGrid(unittest.TestCase):
    def test_grid_has_multiple_cells(self):
        grid = build_parameter_grid()
        self.assertGreater(len(grid), 10)

    def test_grid_covers_all_dimensions(self):
        grid = build_parameter_grid()
        pivot_lefts = {c["pivot_left"] for c in grid}
        trend_filters = {c["trend_filter"] for c in grid}
        entry_modes = {c["entry_mode"] for c in grid}
        self.assertEqual(pivot_lefts, {5, 8, 13})
        self.assertEqual(trend_filters, {"off", "with_trend", "countertrend_only"})
        self.assertEqual(entry_modes, {"near", "mid"})

    def test_countertrend_cells_are_skipped(self):
        params = {
            "pivot_left": 8, "pivot_right": 3, "trend_filter": "countertrend_only",
            "entry_mode": "near", "mss_expiration_bars": 8,
            "order_expiration_bars": 8, "target_r": 2.0,
        }
        result = evaluate_cell(params, {"TEST": _make_bars()})
        self.assertTrue(result["skipped"])
        self.assertIn("not supported", result["skip_reason"])


class TestFrozenDefaultUnchanged(unittest.TestCase):
    def test_default_config_matches_v1_0(self):
        cfg = SMCLiquiditySweepReversionConfig()
        self.assertEqual(cfg.pivot_left, 8)
        self.assertEqual(cfg.pivot_right, 3)
        self.assertEqual(cfg.mss_expiration_bars, 8)
        self.assertEqual(cfg.order_expiration_bars, 8)
        self.assertEqual(cfg.entry_mode, "near")
        self.assertEqual(cfg.target_r, 2.0)
        self.assertEqual(cfg.current_trend_filter, "with_trend")


class TestReportCompleteness(unittest.TestCase):
    def test_all_cells_reported(self):
        bars = _make_bars()
        grid = build_parameter_grid()
        results = [evaluate_cell(p, {"T": bars}) for p in grid]
        self.assertEqual(len(results), len(grid))
        evaluated = [r for r in results if not r.get("skipped")]
        skipped = [r for r in results if r.get("skipped")]
        self.assertGreater(len(evaluated), 0)
        self.assertGreater(len(skipped), 0)
        self.assertEqual(len(evaluated) + len(skipped), len(grid))


class TestSampleWarnings(unittest.TestCase):
    def test_insufficient_sample_label(self):
        row = {
            "wins": 2, "losses": 3, "conservative_expectancy_r": 0.1,
            "fill_rate": 0.5, "net_r": 1.0,
            "result_after_removing_best_trade": 0.5,
            "result_after_removing_best_two_trades": 0.2,
        }
        labels = _rejection_labels(row)
        self.assertIn("INSUFFICIENT_SAMPLE", labels)
        self.assertNotIn("WEAK_SAMPLE", labels)

    def test_weak_sample_label(self):
        row = {
            "wins": 20, "losses": 15, "conservative_expectancy_r": 0.1,
            "fill_rate": 0.5, "net_r": 1.0,
            "result_after_removing_best_trade": 0.5,
            "result_after_removing_best_two_trades": 0.2,
        }
        labels = _rejection_labels(row)
        self.assertNotIn("INSUFFICIENT_SAMPLE", labels)
        self.assertIn("WEAK_SAMPLE", labels)

    def test_negative_expectancy_label(self):
        row = {
            "wins": 50, "losses": 60, "conservative_expectancy_r": -0.3,
            "fill_rate": 0.5, "net_r": -5.0,
            "result_after_removing_best_trade": -6.0,
            "result_after_removing_best_two_trades": -7.0,
        }
        labels = _rejection_labels(row)
        self.assertIn("NEGATIVE_EXPECTANCY", labels)

    def test_low_fill_rate_label(self):
        row = {
            "wins": 50, "losses": 60, "conservative_expectancy_r": 0.1,
            "fill_rate": 0.15, "net_r": 1.0,
            "result_after_removing_best_trade": 0.5,
            "result_after_removing_best_two_trades": 0.2,
        }
        labels = _rejection_labels(row)
        self.assertIn("LOW_FILL_RATE", labels)


class TestFragileOutlier(unittest.TestCase):
    def test_fragile_when_removing_best_flips_negative(self):
        row = {
            "wins": 50, "losses": 60, "conservative_expectancy_r": 0.1,
            "fill_rate": 0.5, "net_r": 2.0,
            "result_after_removing_best_trade": -1.0,
            "result_after_removing_best_two_trades": -3.0,
        }
        labels = _rejection_labels(row)
        self.assertIn("FRAGILE_OUTLIER", labels)

    def test_not_fragile_when_still_positive(self):
        row = {
            "wins": 50, "losses": 60, "conservative_expectancy_r": 0.1,
            "fill_rate": 0.5, "net_r": 5.0,
            "result_after_removing_best_trade": 3.0,
            "result_after_removing_best_two_trades": 1.0,
        }
        labels = _rejection_labels(row)
        self.assertNotIn("FRAGILE_OUTLIER", labels)


class TestNoProhibitedContent(unittest.TestCase):
    def test_no_prohibited_imports_or_wording(self):
        path = Path(__file__).parents[1] / "tools" / "run_smc_lsr_parameter_surface.py"
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


class TestExistingSingleEvaluation(unittest.TestCase):
    def test_single_evaluation_still_works(self):
        from tools.run_smc_lsr_evaluation import evaluate_symbol
        from src.data.timeframe_csv_adapter import TimeframeCsvAdapter
        import tempfile, json, os

        bars = _make_bars(50)
        with tempfile.TemporaryDirectory() as td:
            real_4h = os.path.join(td, "real", "4h")
            os.makedirs(real_4h)
            import pandas as pd
            pd.DataFrame(bars).to_csv(os.path.join(real_4h, "TEST.csv"), index=False)
            daily_csv = os.path.join(td, "TEST.csv")
            pd.DataFrame(bars[:5]).to_csv(daily_csv, index=False)
            daily_meta = os.path.join(td, "TEST.meta.json")
            with open(daily_meta, "w") as f:
                json.dump({"symbol": "TEST", "source": "unit_test",
                           "synthetic": True, "adjustment": "unknown"}, f)
            meta = {
                "symbol": "TEST", "timeframe": "4H", "source": "unit_test",
                "synthetic": False, "adjustment": "unknown",
                "session_policy": "RTH", "bar_count": len(bars),
                "timezone": "America/New_York",
            }
            with open(os.path.join(real_4h, "TEST.meta.json"), "w") as f:
                json.dump(meta, f)

            adapter = TimeframeCsvAdapter(td, real_dir=os.path.join(td, "real"))
            report = evaluate_symbol(adapter, "TEST", "4H")
        self.assertIn("strategy", report)
        self.assertEqual(report["requested_timeframe"], "4H")


if __name__ == "__main__":
    unittest.main()
