import json
import os
import tempfile
import unittest

from src.paper.persistence import atomic_write_json, load_json
from src.paper.shadow_tracker import (
    ShadowTracker, ShadowRecord, HORIZONS, MIN_SHADOW_SAMPLES, _make_key,
    ORIGIN_HISTORICAL, ORIGIN_FORWARD,
)
from src.safety.gate import can_place_orders, candidate_status
from src.strategies.base import Signal, Strategy
from src.strategies.sma_dip import SmaDip
from src.strategies.trend_filter import TrendFilter


def _bars(prices, start_day=1):
    return [{"ts": f"2024-01-{start_day + i:02d}", "open": p, "high": p + 1,
             "low": p - 1, "close": p, "volume": 1000}
            for i, p in enumerate(prices)]


class DateBuyStrategy(Strategy):
    name = "date_buy"

    def __init__(self, buy_dates):
        self.buy_dates = set(buy_dates)

    def signal(self, bars, position_open):
        if position_open:
            return Signal.SELL
        if bars[-1]["ts"] in self.buy_dates:
            return Signal.BUY
        return Signal.HOLD


class TestObserveNoLookAhead(unittest.TestCase):
    def test_signal_uses_only_bars_up_to_current(self):
        tracker = ShadowTracker()
        prices = [100] * 25 + [90] + [100] * 10
        bars = _bars(prices)
        added = tracker.observe_bars(SmaDip(window=20, dip_pct=0.05), "TEST", bars, warmup=20)
        self.assertGreaterEqual(added, 0)
        for rec in tracker.records:
            bar_idx = next(i for i, b in enumerate(bars) if b["ts"] == rec.signal_date)
            self.assertLess(bar_idx, len(bars))

    def test_records_buy_signals_only(self):
        tracker = ShadowTracker()
        prices = [100] * 25 + [90] + [100] * 10
        bars = _bars(prices)
        tracker.observe_bars(SmaDip(window=20, dip_pct=0.05), "TEST", bars, warmup=20)
        for rec in tracker.records:
            self.assertEqual(rec.signal_type, "BUY")


class TestNoDuplicates(unittest.TestCase):
    def test_no_duplicates_on_rerun(self):
        tracker = ShadowTracker()
        prices = [100] * 25 + [90] + [100] * 10
        bars = _bars(prices)
        strat = SmaDip(window=20, dip_pct=0.05)
        first_run = tracker.observe_bars(strat, "TEST", bars, warmup=20)
        second_run = tracker.observe_bars(strat, "TEST", bars, warmup=20)
        self.assertEqual(second_run, 0)
        self.assertEqual(len(tracker.records), first_run)

    def test_manual_observe_dedup(self):
        tracker = ShadowTracker()
        self.assertTrue(tracker.observe("s", "X", "2024-01-01", "BUY", 100.0))
        self.assertFalse(tracker.observe("s", "X", "2024-01-01", "BUY", 100.0))
        self.assertEqual(len(tracker.records), 1)


class TestOutcomePending(unittest.TestCase):
    def test_pending_when_not_enough_future_bars(self):
        tracker = ShadowTracker()
        tracker.observe("s", "X", "2024-01-05", "BUY", 100.0)
        bars = _bars([100] * 8)
        tracker.resolve_outcomes("X", bars)
        rec = tracker.records[0]
        self.assertFalse(rec.is_fully_resolved())


class TestOutcomeResolution(unittest.TestCase):
    def test_resolves_after_enough_bars(self):
        tracker = ShadowTracker()
        tracker.observe("s", "X", "2024-01-01", "BUY", 100.0)
        prices = [100] * 25
        prices[5] = 105
        prices[20] = 110
        bars = _bars(prices)
        tracker.resolve_outcomes("X", bars)
        rec = tracker.records[0]
        self.assertTrue(rec.is_fully_resolved())
        self.assertAlmostEqual(rec.outcomes["h5"]["return_pct"], 0.05, places=4)
        self.assertAlmostEqual(rec.outcomes["h20"]["return_pct"], 0.10, places=4)

    def test_does_not_reresolve(self):
        tracker = ShadowTracker()
        tracker.observe("s", "X", "2024-01-01", "BUY", 100.0)
        bars = _bars([100] * 25)
        tracker.resolve_outcomes("X", bars)
        old_h5 = tracker.records[0].outcomes["h5"]["return_pct"]
        bars_changed = _bars([200] * 25)
        tracker.resolve_outcomes("X", bars_changed)
        self.assertEqual(tracker.records[0].outcomes["h5"]["return_pct"], old_h5)

    def test_wrong_instrument_not_resolved(self):
        tracker = ShadowTracker()
        tracker.observe("s", "SPY", "2024-01-01", "BUY", 100.0)
        bars = _bars([100] * 25)
        tracker.resolve_outcomes("GLD", bars)
        self.assertFalse(tracker.records[0].is_fully_resolved())


class TestOriginLabel(unittest.TestCase):
    def test_default_origin_is_historical(self):
        tracker = ShadowTracker()
        tracker.observe("s", "X", "2024-01-01", "BUY", 100.0)
        self.assertEqual(tracker.records[0].origin, ORIGIN_HISTORICAL)

    def test_observe_bars_uses_specified_origin(self):
        tracker = ShadowTracker()
        bars = _bars([100] * 25 + [90] + [100] * 10)
        tracker.observe_bars(SmaDip(window=20, dip_pct=0.05), "TEST", bars,
                             warmup=20, origin=ORIGIN_HISTORICAL)
        for rec in tracker.records:
            self.assertEqual(rec.origin, ORIGIN_HISTORICAL)

    def test_forward_origin_can_be_set(self):
        tracker = ShadowTracker()
        tracker.observe("s", "X", "2024-01-01", "BUY", 100.0,
                         origin=ORIGIN_FORWARD)
        self.assertEqual(tracker.records[0].origin, ORIGIN_FORWARD)

    def test_origin_persists_round_trip(self):
        tracker = ShadowTracker()
        tracker.observe("s", "X", "2024-01-01", "BUY", 100.0,
                         origin=ORIGIN_FORWARD)
        restored = ShadowTracker.from_dict(tracker.to_dict())
        self.assertEqual(restored.records[0].origin, ORIGIN_FORWARD)

    def test_legacy_record_without_origin_defaults_historical(self):
        d = {"records": [{"key": "s:X:2024-01-01", "strategy": "s",
              "instrument": "X", "signal_date": "2024-01-01",
              "signal_type": "BUY", "entry_price": 100.0}]}
        tracker = ShadowTracker.from_dict(d)
        self.assertEqual(tracker.records[0].origin, ORIGIN_HISTORICAL)


class TestForwardObservationMode(unittest.TestCase):
    def test_first_forward_run_initializes_without_records(self):
        tracker = ShadowTracker()
        bars = _bars([100, 101, 102])

        tracker.initialize_forward_observation({"SPY": bars[-1]["ts"]})

        self.assertTrue(tracker.forward_observation_started)
        self.assertEqual(tracker.forward_started_after["SPY"], "2024-01-03")
        self.assertEqual(tracker.forward_observed_through["SPY"], "2024-01-03")
        self.assertEqual(tracker.summary()["forward_observed"], 0)
        self.assertFalse(tracker.summary()["enough_forward_data"])

    def test_second_forward_run_with_no_newer_bars_creates_no_duplicates(self):
        tracker = ShadowTracker()
        bars = _bars([100, 101, 102])
        tracker.initialize_forward_observation({"SPY": bars[-1]["ts"]})

        added = tracker.observe_forward_bars(
            DateBuyStrategy(["2024-01-03"]), "SPY", bars,
            tracker.forward_observed_through["SPY"], warmup=0,
        )

        self.assertEqual(added, 0)
        self.assertEqual(len(tracker.records), 0)

    def test_forward_run_records_only_new_bar_signal(self):
        tracker = ShadowTracker()
        bars = _bars([100, 101, 102])
        tracker.initialize_forward_observation({"SPY": bars[-1]["ts"]})
        newer = _bars([100, 101, 102, 90])

        added = tracker.observe_forward_bars(
            DateBuyStrategy(["2024-01-02", "2024-01-04"]), "SPY", newer,
            tracker.forward_observed_through["SPY"], warmup=0,
        )
        tracker.forward_observed_through["SPY"] = newer[-1]["ts"]

        self.assertEqual(added, 1)
        self.assertEqual(tracker.records[0].signal_date, "2024-01-04")
        self.assertEqual(tracker.records[0].origin, ORIGIN_FORWARD)

    def test_historical_records_remain_historical_after_forward_run(self):
        tracker = ShadowTracker()
        tracker.observe("date_buy", "SPY", "2024-01-02", "BUY", 101,
                        origin=ORIGIN_HISTORICAL)
        tracker.initialize_forward_observation({"SPY": "2024-01-03"})
        bars = _bars([100, 101, 102, 90])

        tracker.observe_forward_bars(
            DateBuyStrategy(["2024-01-02", "2024-01-04"]), "SPY", bars,
            "2024-01-03", warmup=0,
        )

        self.assertEqual(tracker.records[0].origin, ORIGIN_HISTORICAL)
        self.assertEqual(tracker.summary()["historical_bootstrap"], 1)
        self.assertEqual(tracker.summary()["forward_observed"], 1)

    def test_forward_outcomes_pending_until_future_bars_exist(self):
        tracker = ShadowTracker()
        tracker.observe("s", "SPY", "2024-01-03", "BUY", 100,
                        origin=ORIGIN_FORWARD)
        tracker.resolve_outcomes("SPY", _bars([100, 100, 100, 100]))

        self.assertEqual(tracker.summary()["forward_sample_size"], 0)
        self.assertFalse(tracker.records[0].is_fully_resolved())

    def test_forward_outcomes_resolve_after_enough_future_bars(self):
        tracker = ShadowTracker()
        bars = _bars([100] * 25)
        tracker.observe("s", "SPY", bars[0]["ts"], "BUY", 100,
                        origin=ORIGIN_FORWARD)
        tracker.resolve_outcomes("SPY", bars)

        self.assertEqual(tracker.summary()["forward_sample_size"], 1)
        self.assertTrue(tracker.records[0].is_fully_resolved())


class TestPersistenceRoundTrip(unittest.TestCase):
    def test_save_and_restore(self):
        tracker = ShadowTracker()
        tracker.observe("sma_dip", "SPY", "2024-01-05", "BUY", 450.0,
                        data_source="yfinance", adjustment="unknown")
        bars = _bars([450 + i for i in range(25)])
        tracker.resolve_outcomes("SPY", bars)

        d = tempfile.mkdtemp()
        path = os.path.join(d, "shadow_test.json")
        atomic_write_json(path, tracker.to_dict())

        loaded = load_json(path)
        restored = ShadowTracker.from_dict(loaded)
        self.assertEqual(len(restored.records), 1)
        self.assertEqual(restored.records[0].strategy, "sma_dip")
        self.assertEqual(restored.records[0].entry_price, 450.0)
        self.assertTrue(restored.records[0].is_fully_resolved())

    def test_restored_tracker_dedup_works(self):
        tracker = ShadowTracker()
        tracker.observe("s", "X", "2024-01-01", "BUY", 100.0)
        restored = ShadowTracker.from_dict(tracker.to_dict())
        self.assertFalse(restored.observe("s", "X", "2024-01-01", "BUY", 100.0))

    def test_forward_metadata_persists_round_trip(self):
        tracker = ShadowTracker()
        tracker.initialize_forward_observation({"SPY": "2024-01-03"})
        restored = ShadowTracker.from_dict(tracker.to_dict())
        self.assertTrue(restored.forward_observation_started)
        self.assertEqual(restored.forward_started_after, {"SPY": "2024-01-03"})
        self.assertEqual(restored.forward_observed_through, {"SPY": "2024-01-03"})


class TestSummaryOriginSplit(unittest.TestCase):
    def test_historical_only_verdict(self):
        tracker = ShadowTracker()
        for i in range(MIN_SHADOW_SAMPLES):
            tracker.observe("s", "X", f"2024-01-{i+1:02d}", "BUY", 100.0,
                             origin=ORIGIN_HISTORICAL)
        bars = _bars(list(range(100, 100 + MIN_SHADOW_SAMPLES + 25)))
        tracker.resolve_outcomes("X", bars)
        s = tracker.summary()
        self.assertEqual(s["historical_bootstrap"], MIN_SHADOW_SAMPLES)
        self.assertEqual(s["forward_observed"], 0)
        self.assertEqual(s["forward_sample_size"], 0)
        self.assertGreater(s["historical_sample_size"], 0)
        self.assertFalse(s["enough_data"])
        self.assertIn("forward evidence not started", s["verdict"])
        self.assertNotIn("review only", s["verdict"])

    def test_forward_not_enough_data_verdict(self):
        tracker = ShadowTracker()
        tracker.observe("s", "X", "2024-01-01", "BUY", 100.0,
                         origin=ORIGIN_FORWARD)
        bars = _bars([100] * 25)
        tracker.resolve_outcomes("X", bars)
        s = tracker.summary()
        self.assertEqual(s["forward_observed"], 1)
        self.assertFalse(s["enough_data"])
        self.assertIn("not enough data", s["verdict"])

    def test_forward_enough_data_verdict(self):
        tracker = ShadowTracker()
        prices = list(range(100, 100 + MIN_SHADOW_SAMPLES + 25))
        bars = _bars(prices)
        for i in range(MIN_SHADOW_SAMPLES):
            tracker.observe("s", "X", bars[i]["ts"], "BUY", bars[i]["close"],
                             origin=ORIGIN_FORWARD)
        tracker.resolve_outcomes("X", bars)
        s = tracker.summary()
        self.assertTrue(s["enough_data"])
        self.assertIn("review only", s["verdict"])

    def test_summary_counts_both_origins(self):
        tracker = ShadowTracker()
        tracker.observe("s", "X", "2024-01-01", "BUY", 100.0,
                         origin=ORIGIN_HISTORICAL)
        tracker.observe("s", "X", "2024-01-02", "BUY", 101.0,
                         origin=ORIGIN_FORWARD)
        s = tracker.summary()
        self.assertEqual(s["total"], 2)
        self.assertEqual(s["historical_bootstrap"], 1)
        self.assertEqual(s["forward_observed"], 1)

    def test_forward_sample_size_zero_when_only_historical(self):
        tracker = ShadowTracker()
        for i in range(5):
            tracker.observe("s", "X", f"2024-01-{i+1:02d}", "BUY", 100.0,
                             origin=ORIGIN_HISTORICAL)
        s = tracker.summary()
        self.assertEqual(s["forward_sample_size"], 0)

    def test_not_enough_data_below_threshold(self):
        tracker = ShadowTracker()
        for i in range(5):
            tracker.observe("s", "X", f"2024-01-{i+1:02d}", "BUY", 100.0)
        s = tracker.summary()
        self.assertFalse(s["enough_data"])
        self.assertIn("forward evidence not started", s["verdict"])

    def test_summary_safety_labels(self):
        s = ShadowTracker().summary()
        self.assertEqual(s["trade_impact"], "none")
        self.assertEqual(s["paper_portfolio_impact"], "none")
        self.assertTrue(s["required_human_approval"])
        self.assertFalse(s["ready_for_pilot"])

    def test_hit_rate_calculated(self):
        tracker = ShadowTracker()
        bars = _bars([100 + i for i in range(30)])
        for i in range(10):
            tracker.observe("s", "X", bars[i]["ts"], "BUY", bars[i]["close"])
        tracker.resolve_outcomes("X", bars)
        s = tracker.summary()
        self.assertIsNotNone(s["hit_rate_5bar"])
        self.assertIsNotNone(s["avg_return_5bar"])


class TestExistingScorecardsUnchanged(unittest.TestCase):
    def test_scorecard_still_works(self):
        from src.backtest.engine import BacktestResult
        from src.data.base import DataMeta
        from src.scorecard.scorecard import build_scorecard

        synth = DataMeta(source="synthetic", synthetic=True, adjustment="unadjusted")
        r = BacktestResult(strategy="s", instrument="X", n_bars=500,
                           returns=[0.05] * 40, buy_and_hold_return=0.1, warmup=100,
                           bars_in_position=50, bars_tested=400)
        card = build_scorecard(r, synth, bars=_bars([100] * 5))
        self.assertIn("PIPELINE VALIDATION ONLY", card["headline"])
        self.assertFalse(card["enough_data"])

    def test_real_unknown_still_downgraded(self):
        from src.backtest.engine import BacktestResult
        from src.data.base import DataMeta
        from src.scorecard.scorecard import build_scorecard

        real_unk = DataMeta(source="yfinance", synthetic=False, adjustment="unknown")
        r = BacktestResult(strategy="s", instrument="X", n_bars=500,
                           returns=[0.02, -0.01, 0.03, 0.01, -0.005] * 8,
                           buy_and_hold_return=0.05, warmup=100,
                           bars_in_position=50, bars_tested=400)
        card = build_scorecard(r, real_unk, bars=_bars([100] * 5))
        self.assertEqual(card["evidence_grade"], "real_unverified_adjustment")


class TestSafetyPreserved(unittest.TestCase):
    def test_can_place_orders_false(self):
        self.assertFalse(can_place_orders())

    def test_candidate_gate_unchanged(self):
        g = candidate_status("test")
        self.assertTrue(g.required_human_approval)
        self.assertFalse(g.ready_for_pilot)

    def test_no_forbidden_dirs(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for name in ("broker", "orders", "execution"):
            self.assertFalse(
                os.path.isdir(os.path.join(root, "src", name)),
                f"Forbidden directory src/{name}/ exists",
            )
