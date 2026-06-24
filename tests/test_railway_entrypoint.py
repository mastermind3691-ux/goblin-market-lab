import os
import unittest
import io
from contextlib import redirect_stderr
from unittest.mock import patch

from src.safety.gate import can_place_orders
from tools import railway_entrypoint


class TestRailwayEntrypoint(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("GOBLIN_SERVICE_ROLE", None)

    def test_unset_role_defaults_to_web(self):
        os.environ.pop("GOBLIN_SERVICE_ROLE", None)
        with patch("src.web.app.run_web") as run_web, \
             patch("tools.trigger_admin_refresh.main") as trigger:
            railway_entrypoint.main()

        run_web.assert_called_once_with()
        trigger.assert_not_called()

    def test_web_role_uses_web_path(self):
        os.environ["GOBLIN_SERVICE_ROLE"] = "web"
        with patch("src.web.app.run_web") as run_web, \
             patch("tools.trigger_admin_refresh.main") as trigger:
            railway_entrypoint.main()

        run_web.assert_called_once_with()
        trigger.assert_not_called()

    def test_cron_trigger_role_uses_trigger_path(self):
        os.environ["GOBLIN_SERVICE_ROLE"] = "cron-trigger"
        with patch("src.web.app.run_web") as run_web, \
             patch("tools.trigger_admin_refresh.main") as trigger:
            railway_entrypoint.main()

        trigger.assert_called_once_with()
        run_web.assert_not_called()

    def test_unknown_role_exits_1(self):
        os.environ["GOBLIN_SERVICE_ROLE"] = "python -m something_else"
        err = io.StringIO()
        with redirect_stderr(err):
            with self.assertRaises(SystemExit) as cm:
                railway_entrypoint.main()

        self.assertEqual(cm.exception.code, 1)
        self.assertIn("unknown GOBLIN_SERVICE_ROLE", err.getvalue())

    def test_can_place_orders_false(self):
        self.assertFalse(can_place_orders())

    def test_no_forbidden_dirs(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for name in ("broker", "orders", "execution"):
            self.assertFalse(os.path.isdir(os.path.join(root, "src", name)))


if __name__ == "__main__":
    unittest.main()
