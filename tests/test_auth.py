import base64
import os
import unittest

from src.web.app import app

PASSWORD = "s3cret-test-pw"


def _basic(user: str, pw: str) -> dict:
    token = base64.b64encode(f"{user}:{pw}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


class TestAuthDisabled(unittest.TestCase):
    """No DASHBOARD_PASSWORD set -> local/dev behavior unchanged."""

    def setUp(self):
        os.environ.pop("DASHBOARD_PASSWORD", None)
        self.client = app.test_client()

    def test_health_public(self):
        self.assertEqual(self.client.get("/health").status_code, 200)

    def test_root_open_in_dev(self):
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_status_open_in_dev(self):
        self.assertEqual(self.client.get("/api/status").status_code, 200)


class TestAuthEnabled(unittest.TestCase):
    """DASHBOARD_PASSWORD set -> protected routes require Basic Auth."""

    def setUp(self):
        os.environ["DASHBOARD_PASSWORD"] = PASSWORD
        self.client = app.test_client()

    def tearDown(self):
        os.environ.pop("DASHBOARD_PASSWORD", None)
        os.environ.pop("DASHBOARD_USERNAME", None)

    def test_health_remains_public(self):
        self.assertEqual(self.client.get("/health").status_code, 200)

    def test_root_requires_auth(self):
        self.assertEqual(self.client.get("/").status_code, 401)

    def test_status_requires_auth(self):
        self.assertEqual(self.client.get("/api/status").status_code, 401)

    def test_correct_password_returns_200(self):
        h = _basic("admin", PASSWORD)
        self.assertEqual(self.client.get("/", headers=h).status_code, 200)
        self.assertEqual(self.client.get("/api/status", headers=h).status_code, 200)

    def test_wrong_password_returns_401(self):
        h = _basic("admin", "wrong-password")
        self.assertEqual(self.client.get("/", headers=h).status_code, 401)
        self.assertEqual(self.client.get("/api/status", headers=h).status_code, 401)

    def test_wrong_username_returns_401(self):
        h = _basic("not-admin", PASSWORD)
        self.assertEqual(self.client.get("/", headers=h).status_code, 401)

    def test_missing_credentials_returns_401(self):
        self.assertEqual(self.client.get("/").status_code, 401)

    def test_custom_username(self):
        os.environ["DASHBOARD_USERNAME"] = "mary"
        self.assertEqual(self.client.get("/", headers=_basic("mary", PASSWORD)).status_code, 200)
        self.assertEqual(self.client.get("/", headers=_basic("admin", PASSWORD)).status_code, 401)

    def test_password_never_exposed_in_responses(self):
        h = _basic("admin", PASSWORD)
        for path in ("/", "/api/status", "/health"):
            body = self.client.get(path, headers=h).get_data(as_text=True)
            self.assertNotIn(PASSWORD, body)
        # the 401 challenge must not leak it either
        self.assertNotIn(PASSWORD, self.client.get("/").get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
