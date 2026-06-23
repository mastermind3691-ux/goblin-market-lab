import unittest
from src.safety.gate import can_place_orders, candidate_status, safety_state


class TestSafety(unittest.TestCase):
    def test_can_never_place_orders(self):
        # The structural guarantee. If this ever fails, an execution plane snuck in.
        self.assertFalse(can_place_orders())

    def test_safety_state_reports_paper_only(self):
        s = safety_state()
        self.assertFalse(s.can_place_orders)

    def test_candidate_gate_always_requires_human_and_blocks_pilot(self):
        g = candidate_status("anything")
        self.assertTrue(g.required_human_approval)
        self.assertFalse(g.ready_for_pilot)
