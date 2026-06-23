import unittest
from src.backtest.expectancy import expectancy_report


class TestExpectancy(unittest.TestCase):
    def test_no_trades(self):
        r = expectancy_report([])
        self.assertEqual(r.n, 0)
        self.assertFalse(r.enough_data)

    def test_small_sample_is_honest_about_not_enough_data(self):
        r = expectancy_report([0.05, -0.02, 0.03])  # only 3 trades
        self.assertFalse(r.enough_data)
        self.assertIn("Not enough data", r.verdict)

    def test_clear_positive_edge_with_enough_samples(self):
        # Strongly positive mean with realistic spread (not a degenerate constant).
        returns = [0.05, 0.04, 0.06, 0.03, -0.01] * 8  # n=40, mean well above 0
        r = expectancy_report(returns)
        self.assertTrue(r.enough_data)
        self.assertTrue(r.distinguishable_from_zero)
        self.assertGreater(r.expectancy, 0)

    def test_noisy_zero_mean_is_not_distinguishable(self):
        returns = [0.02, -0.02] * 20  # n=40, mean ~0
        r = expectancy_report(returns)
        self.assertTrue(r.enough_data)
        self.assertFalse(r.distinguishable_from_zero)
