import csv
import json
import os
import tempfile
import unittest

from src.data.csv_validator import validate_csv, MIN_BARS_FOR_BACKTEST
from src.data.csv_adapter import CsvAdapter
from src.data.base import DataMeta
from src.safety.gate import can_place_orders


def _make_csv(rows, header="date,open,high,low,close,volume"):
    lines = [header]
    for r in rows:
        lines.append(",".join(str(v) for v in r))
    return "\n".join(lines)


def _good_rows(n=200):
    return [
        (f"2023-{1 + i // 28:02d}-{1 + i % 28:02d}", 100 + i * 0.1,
         101 + i * 0.1, 99 + i * 0.1, 100.5 + i * 0.1, 1000000)
        for i in range(n)
    ]


GOOD_CSV = _make_csv(_good_rows(200))


class TestValidCsv(unittest.TestCase):
    def test_valid_csv_passes(self):
        result = validate_csv(GOOD_CSV)
        self.assertTrue(result.ok)
        self.assertEqual(result.bar_count, 200)
        self.assertIsNotNone(result.date_range)
        self.assertEqual(len(result.errors), 0)

    def test_ts_alias_accepted(self):
        text = "ts,open,high,low,close,volume\n2023-01-01,10,11,9,10.5,100\n"
        result = validate_csv(text)
        self.assertTrue(result.ok)
        self.assertEqual(result.rows[0]["date"], "2023-01-01")

    def test_volume_optional(self):
        text = "date,open,high,low,close\n2023-01-01,10,11,9,10.5\n"
        result = validate_csv(text)
        self.assertTrue(result.ok)
        self.assertEqual(result.rows[0]["volume"], 0.0)


class TestMissingColumns(unittest.TestCase):
    def test_missing_required_column(self):
        text = "date,open,high,low\n2023-01-01,10,11,9\n"
        result = validate_csv(text)
        self.assertFalse(result.ok)
        self.assertTrue(any("close" in e for e in result.errors))

    def test_empty_file(self):
        result = validate_csv("")
        self.assertFalse(result.ok)


class TestDuplicateDates(unittest.TestCase):
    def test_duplicate_dates_rejected(self):
        text = _make_csv([
            ("2023-01-01", 10, 11, 9, 10.5, 100),
            ("2023-01-01", 10, 11, 9, 10.5, 100),
        ])
        result = validate_csv(text)
        self.assertFalse(result.ok)
        self.assertTrue(any("Duplicate" in e for e in result.errors))


class TestBadPrices(unittest.TestCase):
    def test_zero_close(self):
        text = _make_csv([("2023-01-01", 10, 11, 9, 0, 100)])
        result = validate_csv(text)
        self.assertFalse(result.ok)

    def test_negative_open(self):
        text = _make_csv([("2023-01-01", -5, 11, 9, 10, 100)])
        result = validate_csv(text)
        self.assertFalse(result.ok)

    def test_high_less_than_low(self):
        text = _make_csv([("2023-01-01", 10, 8, 9, 10, 100)])
        result = validate_csv(text)
        self.assertFalse(result.ok)
        self.assertTrue(any("high" in e.lower() and "low" in e.lower() for e in result.errors))

    def test_negative_volume(self):
        text = _make_csv([("2023-01-01", 10, 11, 9, 10.5, -50)])
        result = validate_csv(text)
        self.assertFalse(result.ok)

    def test_non_numeric_ohlc(self):
        text = "date,open,high,low,close,volume\n2023-01-01,abc,11,9,10,100\n"
        result = validate_csv(text)
        self.assertFalse(result.ok)


class TestUnsortedDates(unittest.TestCase):
    def test_unsorted_gets_sorted_with_warning(self):
        text = _make_csv([
            ("2023-01-05", 10, 11, 9, 10.5, 100),
            ("2023-01-01", 10, 11, 9, 10.5, 100),
            ("2023-01-03", 10, 11, 9, 10.5, 100),
        ])
        result = validate_csv(text)
        self.assertTrue(result.ok)
        self.assertTrue(any("sorted" in w.lower() for w in result.warnings))
        dates = [r["date"] for r in result.rows]
        self.assertEqual(dates, sorted(dates))


class TestMinBarsWarning(unittest.TestCase):
    def test_few_bars_warns(self):
        rows = _good_rows(10)
        result = validate_csv(_make_csv(rows))
        self.assertTrue(result.ok)
        self.assertTrue(any("minimum" in w.lower() for w in result.warnings))


class TestUnparseableDate(unittest.TestCase):
    def test_bad_date_format(self):
        text = "date,open,high,low,close,volume\nnotadate,10,11,9,10.5,100\n"
        result = validate_csv(text)
        self.assertFalse(result.ok)


class TestAdapterRealFallback(unittest.TestCase):
    def test_prefers_real_dir(self):
        base = tempfile.mkdtemp()
        real = os.path.join(base, "real")
        os.makedirs(real)

        with open(os.path.join(base, "TEST.csv"), "w") as f:
            f.write("ts,open,high,low,close,volume\n2023-01-01,1,2,1,1.5,10\n")
        with open(os.path.join(base, "TEST.meta.json"), "w") as f:
            json.dump({"source": "synthetic_random_walk", "synthetic": True,
                       "adjustment": "unadjusted"}, f)

        with open(os.path.join(real, "TEST.csv"), "w") as f:
            f.write("date,open,high,low,close,volume\n2023-06-01,50,51,49,50.5,9999\n")
        with open(os.path.join(real, "TEST.meta.json"), "w") as f:
            json.dump({"source": "yahoo_finance", "synthetic": False,
                       "adjustment": "adjusted"}, f)

        adapter = CsvAdapter(base, real_dir=real)
        bars = adapter.bars("TEST")
        self.assertEqual(bars[0]["close"], 50.5)
        meta = adapter.meta("TEST")
        self.assertFalse(meta.synthetic)
        self.assertEqual(meta.adjustment, "adjusted")

    def test_falls_back_to_synthetic(self):
        base = tempfile.mkdtemp()
        real = os.path.join(base, "real")
        os.makedirs(real)

        with open(os.path.join(base, "SYN.csv"), "w") as f:
            f.write("ts,open,high,low,close,volume\n2023-01-01,1,2,1,1.5,10\n")
        with open(os.path.join(base, "SYN.meta.json"), "w") as f:
            json.dump({"source": "synthetic_random_walk", "synthetic": True,
                       "adjustment": "unadjusted"}, f)

        adapter = CsvAdapter(base, real_dir=real)
        bars = adapter.bars("SYN")
        self.assertEqual(bars[0]["close"], 1.5)
        meta = adapter.meta("SYN")
        self.assertTrue(meta.synthetic)


class TestSyntheticLabelBehavior(unittest.TestCase):
    def test_synthetic_sidecar_marks_synthetic(self):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "X.csv"), "w") as f:
            f.write("ts,open,high,low,close,volume\n2023-01-01,1,1,1,1,1\n")
        with open(os.path.join(d, "X.meta.json"), "w") as f:
            json.dump({"source": "synthetic_random_walk", "synthetic": True,
                       "adjustment": "unadjusted"}, f)
        meta = CsvAdapter(d).meta("X")
        self.assertTrue(meta.synthetic)
        self.assertEqual(meta.evidence_grade(), "pipeline_validation_only")


class TestRealDataLabelBehavior(unittest.TestCase):
    def test_real_adjusted_gets_real_grade(self):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "Y.csv"), "w") as f:
            f.write("date,open,high,low,close,volume\n2023-01-01,1,1,1,1,1\n")
        with open(os.path.join(d, "Y.meta.json"), "w") as f:
            json.dump({"source": "manual", "synthetic": False,
                       "adjustment": "adjusted"}, f)
        meta = CsvAdapter(d).meta("Y")
        self.assertFalse(meta.synthetic)
        self.assertEqual(meta.evidence_grade(), "real")

    def test_real_unknown_adjustment_gets_downgraded(self):
        meta = DataMeta(source="manual", synthetic=False, adjustment="unknown")
        self.assertEqual(meta.evidence_grade(), "real_unverified_adjustment")


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
