import json
import os
import unittest
from unittest.mock import patch

from src.data.base import MarketDataAdapter
from src.data.tiingo_adapter import TiingoEodAdapter


class FakeResponse:
    def __init__(self, payload):
        self.body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.body


def adjusted_row(row_date, close=100.0, adj_close=50.0):
    return {
        "date": f"{row_date}T00:00:00.000Z",
        "open": close - 1,
        "high": close + 1,
        "low": close - 2,
        "close": close,
        "volume": 1000,
        "adjOpen": adj_close - 1,
        "adjHigh": adj_close + 1,
        "adjLow": adj_close - 2,
        "adjClose": adj_close,
        "adjVolume": 2000,
    }


class TestTiingoEodAdapter(unittest.TestCase):
    def test_implements_market_data_adapter_and_uses_adjusted_prices(self):
        seen = {}

        def opener(req, timeout):
            seen["authorization"] = req.headers["Authorization"]
            seen["url"] = req.full_url
            seen["timeout"] = timeout
            return FakeResponse([adjusted_row("2024-01-02")])

        adapter = TiingoEodAdapter(api_key="fixture-key", open_url=opener)
        bars = adapter.bars("SPY")
        meta = adapter.meta("SPY")

        self.assertIsInstance(adapter, MarketDataAdapter)
        self.assertEqual(bars[0]["close"], 50.0)
        self.assertEqual(bars[0]["volume"], 2000.0)
        self.assertEqual(meta.source, "tiingo")
        self.assertFalse(meta.synthetic)
        self.assertEqual(meta.adjustment, "adjusted")
        self.assertEqual(seen["authorization"], "Token fixture-key")
        self.assertIn("startDate=2000-01-01", seen["url"])
        self.assertEqual(seen["timeout"], 30)

    def test_rejects_incomplete_adjusted_row_with_diagnostics(self):
        clean = adjusted_row("2026-06-25", adj_close=734.3)
        incomplete = adjusted_row("2026-06-26", adj_close=735.0)
        incomplete["adjClose"] = float("nan")

        adapter = TiingoEodAdapter(
            api_key="fixture-key",
            open_url=lambda req, timeout: FakeResponse([clean, incomplete]),
        )
        result = adapter.fetch("SPY")

        self.assertEqual([bar["ts"] for bar in result["bars"]], ["2026-06-25"])
        self.assertEqual(result["latest_vendor_row_date"], "2026-06-26")
        self.assertEqual(result["excluded_vendor_rows"], [{
            "symbol": "SPY",
            "date": "2026-06-26",
            "reason": "excluded because Close was NaN or incomplete",
        }])
        self.assertEqual(result["meta"].adjustment, "adjusted")

    def test_truthfully_labels_raw_field_fallback_unadjusted(self):
        row = {
            "date": "2024-01-02T00:00:00.000Z",
            "open": 99,
            "high": 101,
            "low": 98,
            "close": 100,
            "volume": 1000,
        }
        adapter = TiingoEodAdapter(
            api_key="fixture-key",
            open_url=lambda req, timeout: FakeResponse([row]),
        )

        result = adapter.fetch("GLD")

        self.assertEqual(result["bars"][0]["close"], 100.0)
        self.assertEqual(result["meta"].adjustment, "unadjusted")

    def test_missing_environment_key_fails_without_network(self):
        called = False

        def opener(req, timeout):
            nonlocal called
            called = True
            return FakeResponse([])

        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError):
                TiingoEodAdapter(open_url=opener)

        self.assertFalse(called)


if __name__ == "__main__":
    unittest.main()
