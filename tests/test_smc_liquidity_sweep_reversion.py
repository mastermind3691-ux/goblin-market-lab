import ast
import unittest
from pathlib import Path

from src.backtest.judge import judge_setup
from src.strategies.smc_liquidity_sweep_reversion import (
    CANDIDATE_NAME,
    SMCLiquiditySweepReversionConfig,
    generate_smc_liquidity_sweep_setups,
)


def bar(open_, high, low, close):
    return {"open": open_, "high": high, "low": low, "close": close}


class TestSMCLiquiditySweepReversion(unittest.TestCase):
    def config(self, **changes):
        values = dict(
            pivot_left=1,
            pivot_right=1,
            mss_expiration_bars=3,
            order_expiration_bars=3,
            current_trend_filter="disabled",
        )
        values.update(changes)
        return SMCLiquiditySweepReversionConfig(**values)

    def bearish_bars(self):
        return [
            bar(100, 105, 95, 100),
            bar(104, 110, 98, 105),
            bar(100, 106, 94, 98),
            bar(100, 107, 96, 102),
            bar(108, 112, 100, 108),
            bar(99, 101, 97, 98),
            bar(95, 99, 92, 93),
        ]

    def bullish_bars(self):
        return [
            bar(100, 105, 95, 100),
            bar(96, 102, 90, 95),
            bar(102, 110, 94, 105),
            bar(102, 108, 96, 100),
            bar(92, 100, 88, 92),
            bar(101, 104, 99, 102),
            bar(110, 112, 101, 111),
        ]

    def generate_one(self, bars, **config_changes):
        setups = generate_smc_liquidity_sweep_setups(
            bars, self.config(**config_changes)
        )
        self.assertEqual(1, len(setups))
        return setups[0]

    def test_pivot_confirmed_on_sweep_bar_is_not_yet_usable(self):
        bars = [
            bar(100, 105, 95, 100),
            bar(104, 110, 98, 105),
            bar(100, 106, 94, 98),
            bar(101, 107, 96, 102),
            bar(95, 108, 93, 93.5),
            bar(108, 112, 95, 108),  # confirms low at 4, then sweeps known high
            bar(98, 100, 96, 97),
            bar(94, 94.5, 92, 93.5),
        ]
        setup = self.generate_one(bars)
        self.assertEqual(5, setup.metadata["sweep_i"])
        self.assertEqual(2, setup.metadata["mss_pivot_i"])
        self.assertNotEqual(4, setup.metadata["mss_pivot_i"])

    def test_sweep_uses_only_previously_confirmed_pivots(self):
        early_only = self.bearish_bars()[1:]
        self.assertEqual(
            [], generate_smc_liquidity_sweep_setups(early_only, self.config())
        )
        setup = self.generate_one(self.bearish_bars())
        self.assertLessEqual(
            setup.metadata["swept_pivot_usable_i"], setup.metadata["sweep_i"]
        )

    def test_bearish_sweep_freezes_opposing_low(self):
        setup = self.generate_one(self.bearish_bars())
        self.assertEqual((2, 94.0), (
            setup.metadata["mss_pivot_i"], setup.metadata["mss_pivot_level"]
        ))

    def test_bullish_sweep_freezes_opposing_high(self):
        setup = self.generate_one(self.bullish_bars())
        self.assertEqual((2, 110.0), (
            setup.metadata["mss_pivot_i"], setup.metadata["mss_pivot_level"]
        ))

    def test_same_bar_sweep_to_mss_does_not_emit(self):
        bars = self.bearish_bars()[:4] + [bar(100, 112, 92, 93)]
        self.assertEqual([], generate_smc_liquidity_sweep_setups(bars, self.config()))

    def test_dual_sweep_outside_bar_is_ignored(self):
        bars = self.bearish_bars()[:4] + [
            bar(100, 112, 92, 100),
            bar(99, 101, 97, 98),
            bar(95, 99, 92, 93),
        ]
        self.assertEqual([], generate_smc_liquidity_sweep_setups(bars, self.config()))

    def test_active_sequence_cannot_be_overwritten_by_opposite_sweep(self):
        bars = self.bearish_bars()
        bars[5] = bar(96, 101, 92, 95)  # bullish sweep while bearish sequence is active
        setup = self.generate_one(bars)
        self.assertEqual("short", setup.side)
        self.assertEqual(4, setup.metadata["sweep_i"])

    def test_one_structural_transition_per_bar(self):
        bars = self.bearish_bars() + [
            bar(95, 98, 90, 92),
            bar(90, 92, 80, 85),
        ]
        setups = generate_smc_liquidity_sweep_setups(bars, self.config())
        self.assertEqual(1, len(setups))
        self.assertEqual(6, setups[0].created_i)

    def test_sweep_expires_before_late_mss(self):
        bars = self.bearish_bars()[:5] + [
            bar(101, 103, 99, 101),
            bar(101, 103, 100, 102),
            bar(100, 102, 98, 100),
            bar(93, 93.5, 90, 93),
        ]
        self.assertEqual([], generate_smc_liquidity_sweep_setups(bars, self.config()))

    def test_bearish_mss_and_fvg_emit_short_setup(self):
        setup = self.generate_one(self.bearish_bars())
        self.assertEqual("short", setup.side)
        self.assertEqual(CANDIDATE_NAME, setup.metadata["strategy"])
        self.assertTrue(setup.metadata["diagnostic_only"])

    def test_bullish_mss_and_fvg_emit_long_setup(self):
        setup = self.generate_one(self.bullish_bars())
        self.assertEqual("long", setup.side)
        self.assertEqual(CANDIDATE_NAME, setup.metadata["strategy"])

    def test_setup_is_eligible_only_after_creation_bar(self):
        setup = self.generate_one(self.bearish_bars())
        self.assertEqual(setup.created_i + 1, setup.valid_from_i)

    def test_bearish_entry_invalidation_and_target_math_for_all_modes(self):
        expected = {
            "near": (99.0, 112.0, 73.0),
            "mid": (99.5, 112.0, 74.5),
            "deep": (100.0, 112.0, 76.0),
        }
        for mode, prices in expected.items():
            with self.subTest(mode=mode):
                setup = self.generate_one(self.bearish_bars(), entry_mode=mode)
                self.assertEqual(prices, (setup.entry, setup.invalidation, setup.target))

    def test_bullish_entry_invalidation_and_target_math_for_all_modes(self):
        expected = {
            "near": (101.0, 88.0, 127.0),
            "mid": (100.5, 88.0, 125.5),
            "deep": (100.0, 88.0, 124.0),
        }
        for mode, prices in expected.items():
            with self.subTest(mode=mode):
                setup = self.generate_one(self.bullish_bars(), entry_mode=mode)
                self.assertEqual(prices, (setup.entry, setup.invalidation, setup.target))

    def test_physically_impossible_bar_is_rejected(self):
        bad = [bar(101, 100, 90, 95)]
        with self.assertRaisesRegex(ValueError, "high"):
            generate_smc_liquidity_sweep_setups(bad, self.config())

    def test_confirmed_and_usable_pivot_timestamps_are_distinct(self):
        setup = self.generate_one(self.bearish_bars())
        self.assertEqual(
            setup.metadata["swept_pivot_confirmed_i"] + 1,
            setup.metadata["swept_pivot_usable_i"],
        )
        self.assertEqual(
            setup.metadata["mss_pivot_confirmed_i"] + 1,
            setup.metadata["mss_pivot_usable_i"],
        )

    def test_enabled_trend_filter_blocks_countertrend_setups(self):
        bullish = self.bullish_bars()
        bullish[0] = bar(1000, 1005, 995, 1000)
        bearish = self.bearish_bars()
        bearish[0] = bar(1, 1.05, 0.95, 1)
        cfg = self.config(current_trend_filter="with_trend", current_ema_len=7)
        self.assertEqual([], generate_smc_liquidity_sweep_setups(bullish, cfg))
        self.assertEqual([], generate_smc_liquidity_sweep_setups(bearish, cfg))

    def test_generated_setup_runs_through_judge(self):
        source = self.bearish_bars()
        setup = self.generate_one(source)
        continuations = {
            "WIN": [bar(98, 100, 90, 95), bar(90, 98, 73, 80)],
            "LOSS": [bar(98, 100, 90, 95), bar(105, 112, 90, 108)],
            "NO_FILL": [
                bar(95, 98, 90, 94),
                bar(94, 98, 85, 90),
                bar(90, 98, 80, 85),
            ],
        }
        for status, extra in continuations.items():
            with self.subTest(status=status):
                self.assertEqual(status, judge_setup(setup, source + extra).status)

    def test_module_has_no_prohibited_dependencies(self):
        path = Path(__file__).parents[1] / "src" / "strategies" / "smc_liquidity_sweep_reversion.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        imported.update(
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        )
        prohibited = {"broker", "orders", "execution", "live"}
        roots = {name.split(".")[0] for name in imported if name}
        self.assertTrue(prohibited.isdisjoint(roots))


if __name__ == "__main__":
    unittest.main()
