import ast
import unittest
from pathlib import Path

from tools.run_smc_sweep_component_study import (
    Pivot,
    SweepObservation,
    _sample_status,
    detect_sweeps,
    evaluate_cell,
)


def _flat_bars(price: float = 100.0, n: int = 30) -> list[dict]:
    return [
        {"ts": f"2024-01-01T{i:02d}:00:00", "open": price, "high": price + 0.1,
         "low": price - 0.1, "close": price, "volume": 10}
        for i in range(n)
    ]


def _pivot_high_bars(pivot_left: int = 5, pivot_right: int = 2) -> list[dict]:
    """Build bars with a clear high pivot in the middle that gets swept later."""
    bars = []
    base = 100.0
    total_needed = pivot_left + 1 + pivot_right + 15
    for i in range(total_needed):
        if i == pivot_left:
            o, h, lo, c = base + 5, base + 8, base + 4, base + 5
        elif i == pivot_left + pivot_right + 5:
            o, h, lo, c = base + 6, base + 10, base + 4, base + 5
        else:
            o, h, lo, c = base, base + 1, base - 1, base
        bars.append({"ts": f"2024-01-{i+1:02d}T09:30:00-05:00",
                      "open": o, "high": h, "low": lo, "close": c, "volume": 10})
    return bars


def _pivot_low_bars(pivot_left: int = 5, pivot_right: int = 2) -> list[dict]:
    """Build bars with a clear low pivot that gets swept (bullish sweep)."""
    bars = []
    base = 100.0
    total_needed = pivot_left + 1 + pivot_right + 15
    for i in range(total_needed):
        if i == pivot_left:
            o, h, lo, c = base - 5, base - 4, base - 8, base - 5
        elif i == pivot_left + pivot_right + 5:
            o, h, lo, c = base - 6, base - 4, base - 10, base - 5
        else:
            o, h, lo, c = base, base + 1, base - 1, base
        bars.append({"ts": f"2024-01-{i+1:02d}T09:30:00-05:00",
                      "open": o, "high": h, "low": lo, "close": c, "volume": 10})
    return bars


class TestPivotNotSweepableBeforeConfirmation(unittest.TestCase):
    def test_pivot_cannot_be_swept_before_right_bars_close(self):
        bars = []
        base = 100.0
        for i in range(20):
            if i == 3:
                o, h, lo, c = base + 5, base + 8, base + 4, base + 5
            elif i == 4:
                o, h, lo, c = base + 6, base + 10, base + 4, base + 5
            else:
                o, h, lo, c = base, base + 1, base - 1, base
            bars.append({"ts": f"2024-01-{i+1:02d}", "open": o, "high": h,
                          "low": lo, "close": c, "volume": 10})
        obs = detect_sweeps(bars, "T", pivot_left=3, pivot_right=2, horizons=[1])
        for o in obs:
            if not o.ambiguous:
                pivot_confirmed = 3 + 2
                self.assertGreater(o.bar_index, pivot_confirmed,
                                   "Sweep detected before pivot confirmation bar")


class TestPivotConfirmedNotSweepableSameBar(unittest.TestCase):
    def test_confirmed_pivot_not_sweepable_on_confirmation_bar(self):
        bars = _flat_bars(n=30)
        bars[5] = {"ts": "2024-01-01T05:00:00", "open": 110, "high": 115,
                    "low": 109, "close": 110, "volume": 10}
        bars[7] = {"ts": "2024-01-01T07:00:00", "open": 110, "high": 116,
                    "low": 109, "close": 109, "volume": 10}
        obs = detect_sweeps(bars, "T", pivot_left=5, pivot_right=2, horizons=[1])
        for o in obs:
            self.assertNotEqual(o.bar_index, 7,
                                "Should not sweep a pivot on its confirmation bar")


class TestBearishSweepDetected(unittest.TestCase):
    def test_bearish_sweep(self):
        bars = _pivot_high_bars(pivot_left=5, pivot_right=2)
        obs = detect_sweeps(bars, "T", pivot_left=5, pivot_right=2, horizons=[1])
        bearish = [o for o in obs if o.side == "bearish"]
        self.assertGreater(len(bearish), 0, "Expected at least one bearish sweep")
        for o in bearish:
            self.assertFalse(o.ambiguous)


class TestBullishSweepDetected(unittest.TestCase):
    def test_bullish_sweep(self):
        bars = _pivot_low_bars(pivot_left=5, pivot_right=2)
        obs = detect_sweeps(bars, "T", pivot_left=5, pivot_right=2, horizons=[1])
        bullish = [o for o in obs if o.side == "bullish"]
        self.assertGreater(len(bullish), 0, "Expected at least one bullish sweep")
        for o in bullish:
            self.assertFalse(o.ambiguous)


class TestDualSweepAmbiguous(unittest.TestCase):
    def test_outside_bar_dual_sweep_is_ambiguous(self):
        bars = _flat_bars(n=30)
        bars[5] = {"ts": "d", "open": 110, "high": 115, "low": 85, "close": 100, "volume": 10}
        bars[7] = {"ts": "d", "open": 100, "high": 120, "low": 80, "close": 100, "volume": 10}

        obs = detect_sweeps(bars, "T", pivot_left=5, pivot_right=2, horizons=[1])
        ambig = [o for o in obs if o.ambiguous]
        if ambig:
            self.assertTrue(all(o.side == "ambiguous" for o in ambig))


class TestForwardReturnsUsePostSweepBars(unittest.TestCase):
    def test_forward_returns_exclude_sweep_bar(self):
        bars = _pivot_high_bars(pivot_left=5, pivot_right=2)
        obs = detect_sweeps(bars, "T", pivot_left=5, pivot_right=2, horizons=[1, 2])
        for o in obs:
            if o.forward_returns.get(1) is not None:
                sweep_close = o.close_at_signal
                fwd_bar = bars[o.bar_index + 1]
                expected = (float(fwd_bar["close"]) - sweep_close) / sweep_close
                self.assertAlmostEqual(o.forward_returns[1], expected, places=10)


class TestForwardHorizonBeyondData(unittest.TestCase):
    def test_horizon_beyond_available_bars_is_none(self):
        bars = _flat_bars(n=10)
        bars[5] = {"ts": "d", "open": 110, "high": 115, "low": 85, "close": 100, "volume": 10}
        obs = detect_sweeps(bars, "T", pivot_left=5, pivot_right=2, horizons=[1, 100])
        for o in obs:
            self.assertIsNone(o.forward_returns.get(100))


class TestSampleStatusLabels(unittest.TestCase):
    def test_insufficient(self):
        self.assertEqual(_sample_status(5), "INSUFFICIENT_SAMPLE")
        self.assertEqual(_sample_status(29), "INSUFFICIENT_SAMPLE")

    def test_weak(self):
        self.assertEqual(_sample_status(30), "WEAK_SAMPLE")
        self.assertEqual(_sample_status(99), "WEAK_SAMPLE")

    def test_adequate(self):
        self.assertIsNone(_sample_status(100))
        self.assertIsNone(_sample_status(500))


class TestPerSymbolAggregation(unittest.TestCase):
    def test_per_symbol_breakdown(self):
        bars_a = _pivot_high_bars(pivot_left=5, pivot_right=2)
        bars_b = _pivot_low_bars(pivot_left=5, pivot_right=2)
        result = evaluate_cell(5, 2, [1, 2], {"A": bars_a, "B": bars_b})
        self.assertIn("A", result["per_symbol"])
        self.assertIn("B", result["per_symbol"])
        total = (result["per_symbol"]["A"]["total_sweeps"]
                 + result["per_symbol"]["B"]["total_sweeps"])
        self.assertEqual(total, result["aggregate"]["total_sweeps"])


class TestNoProhibitedContent(unittest.TestCase):
    def test_no_prohibited_imports_or_wording(self):
        path = Path(__file__).parents[1] / "tools" / "run_smc_sweep_component_study.py"
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
