import ast
import unittest
from pathlib import Path

from src.backtest.judge import SetupEvent, judge_setup


def bar(low, high):
    return {"open": (low + high) / 2, "high": high, "low": low, "close": (low + high) / 2}


class TestResearchJudge(unittest.TestCase):
    def long_setup(self, **changes):
        values = dict(
            side="long", created_i=0, valid_from_i=1, entry=100,
            invalidation=95, target=110, expires_i=2,
        )
        values.update(changes)
        return SetupEvent(**values)

    def short_setup(self, **changes):
        values = dict(
            side="short", created_i=0, valid_from_i=1, entry=100,
            invalidation=105, target=90, expires_i=2,
        )
        values.update(changes)
        return SetupEvent(**values)

    def test_long_cannot_fill_on_creation_bar(self):
        result = judge_setup(self.long_setup(expires_i=1), [bar(99, 101), bar(101, 102)])
        self.assertEqual("NO_FILL", result.status)
        self.assertIsNone(result.filled_i)

    def test_short_cannot_fill_on_creation_bar(self):
        result = judge_setup(self.short_setup(expires_i=1), [bar(99, 101), bar(98, 99)])
        self.assertEqual("NO_FILL", result.status)
        self.assertIsNone(result.filled_i)

    def test_long_no_fill_before_expiry(self):
        result = judge_setup(self.long_setup(), [bar(101, 103), bar(101, 104), bar(102, 105)])
        self.assertEqual("NO_FILL", result.status)

    def test_short_no_fill_before_expiry(self):
        result = judge_setup(self.short_setup(), [bar(97, 99), bar(96, 99), bar(95, 99)])
        self.assertEqual("NO_FILL", result.status)

    def test_long_win(self):
        bars = [bar(101, 102), bar(99, 103), bar(101, 110)]
        result = judge_setup(self.long_setup(), bars)
        self.assertEqual(("WIN", 1, 2, 2.0), (result.status, result.filled_i, result.closed_i, result.r_result))
        self.assertEqual(1, result.bars_held)

    def test_long_loss(self):
        result = judge_setup(self.long_setup(), [bar(101, 102), bar(99, 103), bar(95, 104)])
        self.assertEqual(("LOSS", -1.0, 95), (result.status, result.r_result, result.exit_price))

    def test_short_win(self):
        result = judge_setup(self.short_setup(), [bar(98, 99), bar(97, 101), bar(90, 99)])
        self.assertEqual(("WIN", 2.0, 90), (result.status, result.r_result, result.exit_price))

    def test_short_loss(self):
        result = judge_setup(self.short_setup(), [bar(98, 99), bar(97, 101), bar(98, 105)])
        self.assertEqual(("LOSS", -1.0, 105), (result.status, result.r_result, result.exit_price))

    def test_same_bar_both_outcomes_is_ambiguous_worst_case(self):
        result = judge_setup(self.long_setup(), [bar(101, 102), bar(94, 111)])
        self.assertEqual("AMBIGUOUS_WORST_CASE", result.status)
        self.assertEqual(-1.0, result.r_result)
        self.assertEqual(0, result.bars_held)

    def test_filled_but_unresolved_is_pending(self):
        result = judge_setup(self.long_setup(), [bar(101, 102), bar(99, 104), bar(97, 106)])
        self.assertEqual("PENDING", result.status)
        self.assertEqual(1, result.filled_i)
        self.assertIsNone(result.closed_i)

    def test_unfilled_before_expiry_is_pending(self):
        setup = self.long_setup(expires_i=5)
        result = judge_setup(setup, [bar(101, 102), bar(101, 103)])
        self.assertEqual("PENDING", result.status)
        self.assertIsNone(result.filled_i)

    def test_invalid_long_geometry_is_rejected(self):
        with self.assertRaises(ValueError):
            self.long_setup(target=100)
        with self.assertRaises(ValueError):
            self.long_setup(invalidation=100)

    def test_invalid_short_geometry_is_rejected(self):
        with self.assertRaises(ValueError):
            self.short_setup(target=100)
        with self.assertRaises(ValueError):
            self.short_setup(invalidation=100)

    def test_result_preserves_metadata(self):
        metadata = {"strategy": "example", "symbol": "SPY", "timeframe": "1d", "score": 7, "grade": "B"}
        result = judge_setup(self.long_setup(metadata=metadata), [bar(101, 102), bar(99, 103), bar(101, 110)])
        self.assertEqual(metadata, result.metadata)
        self.assertIsNot(metadata, result.metadata)

    def test_judge_imports_only_research_dependencies(self):
        source = (Path(__file__).parents[1] / "src" / "backtest" / "judge.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        imported.update(
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        )
        forbidden_roots = {"broker", "orders", "execution", "live"}
        self.assertTrue(forbidden_roots.isdisjoint({name.split(".")[0] for name in imported if name}))


if __name__ == "__main__":
    unittest.main()
