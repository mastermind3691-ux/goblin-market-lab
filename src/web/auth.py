"""Optional HTTP Basic Auth for the dashboard.

Behavior:
- If ``DASHBOARD_PASSWORD`` is set, protected routes require Basic Auth.
- If it is not set, auth is disabled and local/dev behavior is unchanged.
- ``/health`` is never protected (used for liveness checks).

The password is read from the environment at REQUEST time (not at import), so
enabling/disabling auth does not require recreating the app. It is never
returned in a response, never rendered, and never logged. ``hmac.compare_digest``
is used so credential checks are constant-time.

Username defaults to ``admin`` and can be overridden with ``DASHBOARD_USERNAME``.
"""

from __future__ import annotations

import hmac
import os
from functools import wraps

from flask import Response, request


def dashboard_password() -> str:
    return (os.getenv("DASHBOARD_PASSWORD") or "").strip()


def dashboard_username() -> str:
    return (os.getenv("DASHBOARD_USERNAME") or "admin").strip() or "admin"


def auth_enabled() -> bool:
    """Auth is on only when a non-empty password is configured."""
    return bool(dashboard_password())


def _credentials_ok(auth) -> bool:
    if auth is None:
        return False
    user_ok = hmac.compare_digest((auth.username or ""), dashboard_username())
    pass_ok = hmac.compare_digest((auth.password or ""), dashboard_password())
    return user_ok and pass_ok


def _challenge() -> Response:
    # Body intentionally generic — never echoes the configured credentials.
    return Response(
        "Authentication required.",
        401,
        {"WWW-Authenticate": 'Basic realm="Goblin Market Lab"'},
    )


def require_auth(view):
    """Decorator: enforce Basic Auth on a route, but only when auth is enabled."""

    @wraps(view)
    def wrapped(*args, **kwargs):
        if auth_enabled() and not _credentials_ok(request.authorization):
            return _challenge()
        return view(*args, **kwargs)

    return wrapped
