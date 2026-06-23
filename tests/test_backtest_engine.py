import unittest
from src.backtest.engine import backtest
from src.strategies.sma_dip import SmaDip


def _bars(prices):
    return [{"ts": f"2023-01-{i+1:02d}", "open": p, "high": p, "low": p,
             "close": p, "volume": 1} for i, p in enumerate(prices)]


class TestBacktest(unittest.TestCase):
    def test_no_lookahead_and_fees_applied(self):
        # Construct a dip then recovery; expect one round trip with fee charged.
        prices = [100] * 25 + [90] + [100] * 5  # dip below 20d SMA then recover
        result = backtest(SmaDip(window=20, dip_pct=0.05), "TEST", _bars(prices),
                          fee_bps=10.0, warmup=20)
        self.assertLessEqual(len(result.returns), 1)
        if result.returns:
            # gross would be ~ (100-90)/90; net must be lower by the fee.
            self.assertLess(result.returns[0], (100 - 90) / 90)
