import unittest
from src.paper.portfolio import PaperPortfolio


class TestPaperPortfolio(unittest.TestCase):
    def test_buy_then_sell_accounting(self):
        p = PaperPortfolio(starting_cash=1000.0)
        p.record_buy("SPY", 2, 100.0)        # spend 200
        self.assertAlmostEqual(p.cash, 800.0)
        r = p.record_sell("SPY", 2, 110.0)   # +10%
        self.assertAlmostEqual(p.cash, 1020.0)
        self.assertAlmostEqual(r, 0.10, places=6)
        self.assertEqual(p.closed_returns, [0.10])

    def test_cannot_overspend(self):
        p = PaperPortfolio(starting_cash=100.0)
        with self.assertRaises(ValueError):
            p.record_buy("SPY", 10, 100.0)

    def test_roundtrip_serialisation(self):
        p = PaperPortfolio(starting_cash=500.0)
        p.record_buy("GLD", 1, 50.0)
        d = p.to_dict()
        p2 = PaperPortfolio.from_dict(d)
        self.assertAlmostEqual(p2.cash, p.cash)
        self.assertIn("GLD", p2.positions)
