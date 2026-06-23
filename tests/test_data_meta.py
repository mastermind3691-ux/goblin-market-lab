import json
import os
import tempfile
import unittest

from src.data.base import DataMeta
from src.data.csv_adapter import CsvAdapter


class TestDataMeta(unittest.TestCase):
    def test_invalid_adjustment_rejected(self):
        with self.assertRaises(ValueError):
            DataMeta(source="x", synthetic=False, adjustment="kinda")

    def test_evidence_grade(self):
        self.assertEqual(DataMeta("x", True, "unadjusted").evidence_grade(),
                         "pipeline_validation_only")
        self.assertEqual(DataMeta("x", False, "unknown").evidence_grade(),
                         "real_unverified_adjustment")
        self.assertEqual(DataMeta("x", False, "adjusted").evidence_grade(), "real")

    def test_csv_adapter_reads_sidecar(self):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "SPY.csv"), "w") as f:
            f.write("ts,open,high,low,close,volume\n2023-01-01,1,1,1,1,1\n")
        with open(os.path.join(d, "SPY.meta.json"), "w") as f:
            json.dump({"source": "synthetic_random_walk", "synthetic": True,
                       "adjustment": "unadjusted"}, f)
        meta = CsvAdapter(d).meta("SPY")
        self.assertTrue(meta.synthetic)
        self.assertEqual(meta.adjustment, "unadjusted")

    def test_csv_adapter_default_when_no_sidecar(self):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "QQQ.csv"), "w") as f:
            f.write("ts,open,high,low,close,volume\n2023-01-01,1,1,1,1,1\n")
        meta = CsvAdapter(d).meta("QQQ")
        self.assertFalse(meta.synthetic)
        self.assertEqual(meta.adjustment, "unknown")
