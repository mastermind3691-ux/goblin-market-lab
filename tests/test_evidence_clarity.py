import os
import unittest
from datetime import date

from src.backtest.engine import BacktestResult, backtest
from src.data.base import DataMeta
from src.safety.gate import can_place_orders
from src.scorecard.scorecard import (
    build_scorecard, concentration, _data_freshness, _exposure_pct,
    STALE_DATA_DAYS, LOW_EXPOSURE_THRESHOLD,
)
from src.scorecard.language import find_prediction_language
from src.strategies.sma_dip import SmaDip


REAL = DataMeta(source="yfinance", synthetic=False, adjustment="adjusted")
REAL_UNKNOWN = DataMeta(source="yfinance", synthetic=False, adjustment="unknown")
SYNTH = DataMeta(source="synthetic_random_walk", synthetic=True, adjustment="unadjusted")


def _bars(prices, start="2024-01-"):
    return [{"ts": f"{start}{i+1:02d}", "open": p, "high": p + 1,
             "low": p - 1, "close": p, "volume": 1000}
            for i, p in enumerate(prices)]


def _result(returns, bh=0.1, bars_in_pos=50, bars_tested=200):
    return BacktestResult(
        strategy="test_strat", instrument="TEST", n_bars=200,
        returns=returns, buy_and_hold_return=bh, warmup=100,
        bars_in_position=bars_in_pos, bars_tested=bars_tested,
    )


# --- Data freshness ---

class TestDataFreshness(unittest.TestCase):
    def test_recent_data_not_stale(self):
        bars = [{"ts": "2024-06-20"}]
        f = _data_freshness(bars, today=date(2024, 6, 22))
        self.assertEqual(f["last_bar_date"], "2024-06-20")
        self.assertEqual(f["data_age_days"], 2)
        self.assertFalse(f["data_is_stale"])

    def test_old_data_is_stale(self):
        bars = [{"ts": "2024-01-01"}]
        f = _data_freshness(bars, today=date(2024, 6, 22))
        self.assertTrue(f["data_is_stale"])
        self.assertGreater(f["data_age_days"], STALE_DATA_DAYS)

    def test_empty_bars_is_stale(self):
        f = _data_freshness([], today=date(2024, 6, 22))
        self.assertTrue(f["data_is_stale"])
        self.assertIsNone(f["last_bar_date"])

    def test_scorecard_has_freshness_fields(self):
        bars = _bars([100] * 10, start="2024-06-")
        r = _result([0.01] * 5, bars_in_pos=50, bars_tested=10)
        card = build_scorecard(r, REAL, bars=bars, today=date(2024, 6, 15))
        self.assertIn("last_bar_date", card)
        self.assertIn("data_age_days", card)
        self.assertIn("data_is_stale", card)
        self.assertEqual(card["last_bar_date"], "2024-06-10")
        self.assertEqual(card["data_age_days"], 5)
        self.assertFalse(card["data_is_stale"])

    def test_stale_flag_in_scorecard(self):
        bars = _bars([100] * 5, start="2023-01-")
        r = _result([0.01] * 5)
        card = build_scorecard(r, REAL, bars=bars, today=date(2024, 6, 22))
        self.assertTrue(card["data_is_stale"])


# --- Bars tested vs available ---

class TestBarsClarity(unittest.TestCase):
    def test_bars_tested_vs_available(self):
        bars = _bars([100] * 10)
        r = _result([0.01] * 5)
        card = build_scorecard(r, REAL, bars=bars, available_bars=5000)
        self.assertEqual(card["bars_tested"], 200)
        self.assertEqual(card["available_bars"], 5000)

    def test_available_defaults_to_bars_length(self):
        bars = _bars([100] * 10)
        r = _result([0.01] * 5)
        card = build_scorecard(r, REAL, bars=bars)
        self.assertEqual(card["available_bars"], 10)

    def test_date_range_tested(self):
        bars = _bars([100] * 5, start="2024-03-")
        r = _result([0.01] * 5)
        card = build_scorecard(r, REAL, bars=bars)
        self.assertEqual(card["date_range_tested"], ("2024-03-01", "2024-03-05"))


# --- Exposure / time in market ---

class TestExposure(unittest.TestCase):
    def test_exposure_pct_basic(self):
        r = _result([], bars_in_pos=100, bars_tested=200)
        self.assertAlmostEqual(_exposure_pct(r), 0.5)

    def test_zero_bars_tested(self):
        r = _result([], bars_in_pos=0, bars_tested=0)
        self.assertEqual(_exposure_pct(r), 0.0)

    def test_full_exposure(self):
        r = _result([], bars_in_pos=200, bars_tested=200)
        self.assertAlmostEqual(_exposure_pct(r), 1.0)

    def test_exposure_in_scorecard(self):
        r = _result([0.01] * 5, bars_in_pos=60, bars_tested=200)
        card = build_scorecard(r, REAL, bars=_bars([100] * 5))
        self.assertEqual(card["exposure_pct"], 0.3)

    def test_backtest_engine_tracks_exposure(self):
        prices = [100] * 25 + [90] + [100] * 74
        bars = _bars(prices)
        result = backtest(SmaDip(window=20, dip_pct=0.05), "TEST", bars,
                          fee_bps=5.0, warmup=20)
        self.assertGreater(result.bars_tested, 0)
        self.assertGreaterEqual(result.bars_in_position, 0)
        self.assertLessEqual(result.bars_in_position, result.bars_tested)


# --- Benchmark wording with exposure ---

class TestBenchmarkWording(unittest.TestCase):
    def test_lags_with_low_exposure_mentions_it(self):
        r = _result([0.01] * 40, bh=0.5, bars_in_pos=30, bars_tested=200)
        card = build_scorecard(r, REAL, bars=_bars([100] * 5))
        self.assertIn("lower market exposure", card["verdict"])

    def test_lags_with_high_exposure_no_mention(self):
        r = _result([0.01] * 40, bh=0.5, bars_in_pos=150, bars_tested=200)
        card = build_scorecard(r, REAL, bars=_bars([100] * 5))
        self.assertIn("lagged buy-and-hold", card["verdict"])
        self.assertNotIn("lower market exposure", card["verdict"])

    def test_beats_benchmark_no_exposure_qualifier(self):
        r = _result([0.1] * 40, bh=0.05, bars_in_pos=30, bars_tested=200)
        card = build_scorecard(r, REAL, bars=_bars([100] * 5))
        self.assertIn("beat buy-and-hold", card["verdict"])

    def test_exposure_in_verdict_text(self):
        r = _result([0.01] * 40, bh=0.5, bars_in_pos=60, bars_tested=200)
        card = build_scorecard(r, REAL, bars=_bars([100] * 5))
        self.assertIn("time in market", card["verdict"])


# --- Synthetic still gated ---

class TestSyntheticStillGated(unittest.TestCase):
    def test_synthetic_pipeline_validation_only(self):
        r = _result([0.05] * 40)
        card = build_scorecard(r, SYNTH, bars=_bars([100] * 5))
        self.assertIn("PIPELINE VALIDATION ONLY", card["headline"])
        self.assertFalse(card["enough_data"])
        self.assertFalse(card["distinguishable_from_zero"])
        self.assertIn("not evidence", card["verdict"].lower())


# --- Real unknown adjustment ---

class TestRealUnknownAdjustment(unittest.TestCase):
    def test_unknown_adjustment_downgraded(self):
        r = _result([0.02, -0.01, 0.03, 0.01, -0.005] * 8, bh=0.05)
        card = build_scorecard(r, REAL_UNKNOWN, bars=_bars([100] * 5))
        self.assertEqual(card["evidence_grade"], "real_unverified_adjustment")
        self.assertIn("adjustment for splits/dividends is unknown", card["verdict"])


# --- No prediction language ---

class TestNoPredictionLanguage(unittest.TestCase):
    def test_no_banned_phrases(self):
        for meta in (REAL, REAL_UNKNOWN, SYNTH):
            r = _result([0.01] * 40, bars_in_pos=60, bars_tested=200)
            card = build_scorecard(r, meta, bars=_bars([100] * 5))
            self.assertEqual(find_prediction_language(card["verdict"]), [])
            self.assertEqual(find_prediction_language(card["headline"]), [])


# --- Safety ---

class TestSafetyStillHolds(unittest.TestCase):
    def test_can_place_orders_still_false(self):
        self.assertFalse(can_place_orders())

    def test_no_forbidden_dirs(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for name in ("broker", "orders", "execution"):
            self.assertFalse(
                os.path.isdir(os.path.join(root, "src", name)),
                f"Forbidden directory src/{name}/ exists",
            )
