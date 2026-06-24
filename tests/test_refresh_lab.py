import os
import unittest
from unittest.mock import patch

import tools.refresh_lab as refresh_lab_module
from src.safety.gate import can_place_orders
from tools.refresh_lab import refresh_lab


class TestRefreshLab(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("REAL_DATA_DIR", None)

    def test_requires_real_data_dir(self):
        os.environ.pop("REAL_DATA_DIR", None)
        with patch.object(refresh_lab_module, "refresh_market_data") as refresh:
            with self.assertRaises(RuntimeError):
                refresh_lab(["SPY", "GLD"], "2000-01-01")
        refresh.assert_not_called()

    def test_uses_supplied_symbols_start_and_write_raw_false(self):
        os.environ["REAL_DATA_DIR"] = "/mnt/data/real"
        with patch.object(refresh_lab_module, "refresh_market_data") as refresh, \
             patch.object(refresh_lab_module, "run_forward_observation") as forward:
            refresh.return_value = {
                "symbols": ["SPY", "GLD"],
                "latest_bar_date": {"SPY": "2026-06-22", "GLD": "2026-06-22"},
                "output_dir": "/mnt/data/real",
            }
            forward.return_value = {
                "forward_observation_started": True,
                "forward_observed_through": {"SPY": "2026-06-22", "GLD": "2026-06-22"},
                "new_forward_records_last_run": 0,
                "forward_sample_size": 0,
            }

            summary = refresh_lab(["SPY", "GLD"], "2000-01-01")

        refresh.assert_called_once_with(
            ["SPY", "GLD"], "2000-01-01",
            output_dir="/mnt/data/real", write_raw=False,
        )
        forward.assert_called_once_with()
        self.assertEqual(summary["symbols_refreshed"], ["SPY", "GLD"])
        self.assertFalse(summary["can_place_orders"])

    def test_can_place_orders_false(self):
        self.assertFalse(can_place_orders())

    def test_no_forbidden_dirs(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for name in ("broker", "orders", "execution"):
            self.assertFalse(os.path.isdir(os.path.join(root, "src", name)))


if __name__ == "__main__":
    unittest.main()
