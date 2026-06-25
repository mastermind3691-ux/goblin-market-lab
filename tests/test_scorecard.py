import unittest

from src.backtest.engine import BacktestResult
from src.data.base import DataMeta
from src.scorecard.scorecard import build_scorecard, concentration, strategy_label
from src.scorecard.language import find_prediction_language

REAL = DataMeta(source="vendor", synthetic=False, adjustment="adjusted")
REAL_UNKNOWN = DataMeta(source="vendor", synthetic=False, adjustment="unknown")
SYNTH = DataMeta(source="synthetic_random_walk", synthetic=True, adjustment="unadjusted")


def _result(returns, bh, n=50):
    # pad trade count via returns length; expectancy needs >=30 to be "enough"
    return BacktestResult(strategy="s", instrument="X", n_bars=500,
                          returns=returns, buy_and_hold_return=bh, warmup=100)


class TestScorecard(unittest.TestCase):
    def test_synthetic_is_never_evidence(self):
        card = build_scorecard(_result([0.05] * 40, 0.1), SYNTH)
        self.assertIn("PIPELINE VALIDATION ONLY", card["headline"])
        self.assertFalse(card["enough_data"])              # gated off
        self.assertFalse(card["distinguishable_from_zero"])
        self.assertIn("not evidence", card["verdict"].lower())

    def test_profitable_but_lags_buy_and_hold_says_so(self):
        # consistent small winners (positive expectancy) but B&H did far better
        returns = [0.02, 0.015, 0.025, 0.01, -0.005] * 8   # n=40, positive mean
        card = build_scorecard(_result(returns, bh=0.80), REAL)
        self.assertEqual(card["vs_benchmark"], "lags")
        self.assertIn("LAGS BUY-AND-HOLD", card["headline"])
        self.assertIn("lagged buy-and-hold", card["verdict"])

    def test_concentration_flagged_when_one_trade_dominates(self):
        returns = [1.0] + [0.001] * 39   # one huge winner dominates gross profit
        c = concentration(returns)
        self.assertTrue(c["flagged"])
        self.assertGreaterEqual(c["top1_share"], 0.5)

    def test_unknown_adjustment_is_surfaced(self):
        returns = [0.02, -0.01, 0.03, 0.01, -0.005] * 8
        card = build_scorecard(_result(returns, bh=0.05), REAL_UNKNOWN)
        self.assertEqual(card["price_adjustment"], "unknown")
        self.assertIn("adjustment for splits/dividends is unknown", card["verdict"])

    def test_strategy_label_is_human_readable(self):
        card = build_scorecard(
            BacktestResult(strategy="trend_filter", instrument="X", n_bars=500),
            REAL,
        )

        self.assertEqual(card["strategy"], "trend_filter")
        self.assertEqual(card["strategy_label"], "Trend Filter")
        self.assertEqual(strategy_label("new_test_rule"), "New Test Rule")

    def test_display_labels_are_human_readable(self):
        card = build_scorecard(_result([0.02, -0.01, 0.03] * 10, bh=0.8), REAL_UNKNOWN)

        self.assertEqual(card["price_adjustment"], "unknown")
        self.assertEqual(card["price_adjustment_label"], "Adjustment not verified")
        self.assertEqual(card["vs_benchmark_label"], "Lags buy-and-hold")
        self.assertTrue(card["win_rate_label"].endswith("%"))
        self.assertTrue(card["expectancy_per_trade_label"].endswith("per trade"))
        self.assertTrue(card["strategy_return_label"].endswith("%"))
        self.assertTrue(card["buy_and_hold_return_label"].endswith("%"))

    def test_no_prediction_language_in_output(self):
        for meta in (REAL, REAL_UNKNOWN, SYNTH):
            card = build_scorecard(_result([0.9] + [0.01] * 39, bh=0.2), meta)
            self.assertEqual(find_prediction_language(card["verdict"]), [])
            self.assertEqual(find_prediction_language(card["headline"]), [])
