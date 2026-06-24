import base64
import io
import os
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch
from urllib.error import HTTPError

from src.safety.gate import can_place_orders
from tools import trigger_admin_refresh as trigger


PASSWORD = "cron-secret-password"


class FakeResponse:
    def __init__(self, status=200, body='{"ok": true}'):
        self.status = status
        self._body = body.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def getcode(self):
        return self.status

    def read(self):
        return self._body


class TestTriggerAdminRefresh(unittest.TestCase):
    def setUp(self):
        os.environ["DASHBOARD_URL"] = "https://example.test/"
        os.environ["DASHBOARD_USERNAME"] = "admin"
        os.environ["DASHBOARD_PASSWORD"] = PASSWORD

    def tearDown(self):
        os.environ.pop("DASHBOARD_URL", None)
        os.environ.pop("DASHBOARD_USERNAME", None)
        os.environ.pop("DASHBOARD_PASSWORD", None)

    def test_missing_env_fails_without_network(self):
        os.environ.pop("DASHBOARD_PASSWORD", None)
        opener_called = False

        def opener(*args, **kwargs):
            nonlocal opener_called
            opener_called = True
            return FakeResponse()

        with self.assertRaises(RuntimeError):
            trigger.trigger_admin_refresh(open_url=opener)
        self.assertFalse(opener_called)

    def test_success_sends_url_auth_and_header(self):
        seen = {}

        def opener(req, timeout):
            seen["url"] = req.full_url
            seen["timeout"] = timeout
            seen["headers"] = dict(req.header_items())
            return FakeResponse(body='{"ok": true, "can_place_orders": false}')

        payload = trigger.trigger_admin_refresh(open_url=opener)

        expected_token = base64.b64encode(f"admin:{PASSWORD}".encode()).decode()
        self.assertEqual(seen["url"], "https://example.test/admin/refresh")
        self.assertEqual(seen["timeout"], trigger.TIMEOUT_SECONDS)
        self.assertEqual(seen["headers"]["Authorization"], f"Basic {expected_token}")
        self.assertEqual(seen["headers"]["X-goblin-action"], "refresh-market-data")
        self.assertTrue(payload["ok"])

    def test_non_2xx_fails(self):
        def opener(req, timeout):
            return FakeResponse(status=500, body='{"ok": false}')

        with self.assertRaises(RuntimeError):
            trigger.trigger_admin_refresh(open_url=opener)

    def test_http_error_fails(self):
        def opener(req, timeout):
            body = io.BytesIO(b'{"ok": false}')
            exc = HTTPError(req.full_url, 403, "Forbidden", {}, body)
            exc.fp = body
            raise exc

        with self.assertRaises(RuntimeError):
            trigger.trigger_admin_refresh(open_url=opener)

    def test_ok_false_fails(self):
        def opener(req, timeout):
            return FakeResponse(body='{"ok": false, "error": "nope"}')

        with self.assertRaises(RuntimeError):
            trigger.trigger_admin_refresh(open_url=opener)

    def test_password_not_printed_in_error_output(self):
        def boom():
            raise RuntimeError(f"bad {PASSWORD}")

        err = io.StringIO()
        with patch.object(trigger, "trigger_admin_refresh", side_effect=boom), \
             redirect_stderr(err):
            with self.assertRaises(SystemExit):
                trigger.main()

        self.assertNotIn(PASSWORD, err.getvalue())
        self.assertIn("[redacted]", err.getvalue())

    def test_can_place_orders_false(self):
        self.assertFalse(can_place_orders())

    def test_no_forbidden_dirs(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for name in ("broker", "orders", "execution"):
            self.assertFalse(os.path.isdir(os.path.join(root, "src", name)))


if __name__ == "__main__":
    unittest.main()
