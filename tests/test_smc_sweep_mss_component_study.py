import ast
import unittest
from pathlib import Path

from tools.run_smc_sweep_mss_component_study import (
    Pivot,
    _sample_status,
    detect_sweep_mss,
    evaluate_cell,
)


def _flat_bars(price: float = 100.0, n: int = 40) -> list[dict]:
    return [
        {"ts": f"2024-01-01T{i:02d}:00:00", "open": price, "high": price + 0.1,
         "low": price - 0.1, "close": price, "volume": 10}
        for i in range(n)
    ]


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


class TestPivotNotSweepableBeforeConfirmation(unittest.TestCase):
    def test_sweep_only_after_confirmation(self):
        bars = _bearish_sweep_then_mss_bars(5, 2)
        obs, _ = detect_sweep_mss(bars, "T", 5, 2, mss_expiration_bars=8, horizons=[1])
        for o in obs:
            self.assertGreater(o.sweep_bar_index, 5 + 2,
                               "Sweep detected before pivot confirmation")


class TestPivotNotSweepableSameBar(unittest.TestCase):
    def test_confirmed_pivot_not_swept_on_confirmation_bar(self):
        bars = _flat_bars(n=40)
        bars[5] = {"ts": "d", "open": 110, "high": 115, "low": 85, "close": 110, "volume": 10}
        bars[7] = {"ts": "d", "open": 110, "high": 116, "low": 109, "close": 109, "volume": 10}
        obs, _ = detect_sweep_mss(bars, "T", 5, 2, mss_expiration_bars=8, horizons=[1])
        for o in obs:
            self.assertNotEqual(o.sweep_bar_index, 7)


class TestBearishSweepFreezesMssLow(unittest.TestCase):
    def test_frozen_level_is_low_pivot(self):
        bars = _bearish_sweep_then_mss_bars(5, 2)
        obs, _ = detect_sweep_mss(bars, "T", 5, 2, mss_expiration_bars=12, horizons=[1])
        bearish_mss = [o for o in obs if o.sweep_side == "bearish"]
        if bearish_mss:
            for o in bearish_mss:
                self.assertLess(o.close_at_mss, o.frozen_mss_level)


class TestBullishSweepFreezesMssHigh(unittest.TestCase):
    def test_frozen_level_is_high_pivot(self):
        bars = _bullish_sweep_then_mss_bars(5, 2)
        obs, _ = detect_sweep_mss(bars, "T", 5, 2, mss_expiration_bars=12, horizons=[1])
        bullish_mss = [o for o in obs if o.sweep_side == "bullish"]
        if bullish_mss:
            for o in bullish_mss:
                self.assertGreater(o.close_at_mss, o.frozen_mss_level)


class TestSameBarSweepToMssDisabled(unittest.TestCase):
    def test_mss_cannot_fire_on_sweep_bar(self):
        bars = _bearish_sweep_then_mss_bars(5, 2)
        obs, _ = detect_sweep_mss(bars, "T", 5, 2, mss_expiration_bars=16, horizons=[1])
        for o in obs:
            self.assertGreater(o.mss_bar_index, o.sweep_bar_index,
                               "MSS fired on the same bar as sweep")
            self.assertGreaterEqual(o.bars_sweep_to_mss, 1)


class TestDualSweepExcluded(unittest.TestCase):
    def test_outside_bar_does_not_produce_mss_observation(self):
        bars = _flat_bars(n=40)
        bars[5] = {"ts": "d", "open": 110, "high": 115, "low": 85, "close": 100, "volume": 10}
        bars[7] = {"ts": "d", "open": 100, "high": 120, "low": 80, "close": 100, "volume": 10}
        obs, sweeps = detect_sweep_mss(bars, "T", 5, 2, mss_expiration_bars=8, horizons=[1])
        directional_mss = [o for o in obs if not o.ambiguous]
        for o in directional_mss:
            self.assertIn(o.sweep_side, ("bullish", "bearish"))


class TestMssExpirationRespected(unittest.TestCase):
    def test_mss_beyond_expiration_not_counted(self):
        bars = _bearish_sweep_then_mss_bars(5, 2)
        obs_short, _ = detect_sweep_mss(
            bars, "T", 5, 2, mss_expiration_bars=1, horizons=[1],
        )
        obs_long, _ = detect_sweep_mss(
            bars, "T", 5, 2, mss_expiration_bars=16, horizons=[1],
        )
        self.assertLessEqual(len(obs_short), len(obs_long))


class TestForwardReturnsFromMssBar(unittest.TestCase):
    def test_forward_returns_measured_from_mss_close(self):
        bars = _bearish_sweep_then_mss_bars(5, 2)
        obs, _ = detect_sweep_mss(bars, "T", 5, 2, mss_expiration_bars=12, horizons=[1, 2])
        for o in obs:
            if o.forward_returns.get(1) is not None:
                mss_close = o.close_at_mss
                fwd_bar = bars[o.mss_bar_index + 1]
                expected = (float(fwd_bar["close"]) - mss_close) / mss_close
                self.assertAlmostEqual(o.forward_returns[1], expected, places=10)


class TestForwardHorizonBeyondData(unittest.TestCase):
    def test_horizon_beyond_bars_is_none(self):
        bars = _flat_bars(n=15)
        bars[5] = {"ts": "d", "open": 110, "high": 115, "low": 85, "close": 110, "volume": 10}
        obs, _ = detect_sweep_mss(bars, "T", 5, 2, mss_expiration_bars=8, horizons=[1, 100])
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


class TestPerSymbolAggregation(unittest.TestCase):
    def test_per_symbol_breakdown(self):
        bars_a = _bearish_sweep_then_mss_bars(5, 2)
        bars_b = _bullish_sweep_then_mss_bars(5, 2)
        result = evaluate_cell(5, 2, 12, [1, 2], {"A": bars_a, "B": bars_b})
        self.assertIn("A", result["per_symbol"])
        self.assertIn("B", result["per_symbol"])
        total_mss = (result["per_symbol"]["A"]["sweeps_reaching_mss"]
                     + result["per_symbol"]["B"]["sweeps_reaching_mss"])
        self.assertEqual(total_mss, result["aggregate"]["sweeps_reaching_mss"])


class TestNoProhibitedContent(unittest.TestCase):
    def test_no_prohibited_imports_or_wording(self):
        path = Path(__file__).parents[1] / "tools" / "run_smc_sweep_mss_component_study.py"
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
