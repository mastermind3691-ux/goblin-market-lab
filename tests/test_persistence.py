import os
import tempfile
import unittest
from src.paper.persistence import save_paper_state, restore_paper_state


class TestPersistence(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "paper_state.json")

    def test_save_then_restore(self):
        save_paper_state(self.path, {"cash": 123}, ["SPY", "GLD"])
        state, diag = restore_paper_state(self.path, ["SPY", "GLD"])
        self.assertEqual(state["cash"], 123)
        self.assertFalse(diag["migration_performed"])

    def test_missing_file_returns_none(self):
        state, diag = restore_paper_state(self.path, ["SPY"])
        self.assertIsNone(state)
        self.assertFalse(diag["file_exists"])

    def test_instrument_mismatch_backs_up_not_overwrites(self):
        save_paper_state(self.path, {"cash": 1}, ["SPY"])
        state, diag = restore_paper_state(self.path, ["SPY", "GLD"])
        self.assertIsNone(state)                       # fresh account
        self.assertTrue(diag["migration_performed"])
        self.assertTrue(os.path.exists(diag["backup_path"]))  # history preserved
