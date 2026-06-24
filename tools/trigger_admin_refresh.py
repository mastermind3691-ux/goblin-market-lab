"""One-shot Railway Cron trigger for the dashboard admin refresh endpoint.

    python -m tools.trigger_admin_refresh

This service does not need a volume. It calls the dashboard service, which owns
the mounted volume and runs the protected refresh.
"""

from __future__ import annotations

import base64
import json
import os
import sys
from urllib import error, request

ACTION_HEADER = "refresh-market-data"
TIMEOUT_SECONDS = 120


def _required_env() -> dict[str, str]:
    values = {
        "DASHBOARD_URL": (os.getenv("DASHBOARD_URL") or "").strip().rstrip("/"),
        "DASHBOARD_USERNAME": (os.getenv("DASHBOARD_USERNAME") or "").strip(),
        "DASHBOARD_PASSWORD": os.getenv("DASHBOARD_PASSWORD") or "",
    }
    missing = [k for k, v in values.items() if not v]
    if missing:
        raise RuntimeError(f"Missing required env vars: {', '.join(missing)}")
    return values


def _redact(text: str, password: str) -> str:
    return text.replace(password, "[redacted]") if password else text


def trigger_admin_refresh(open_url=request.urlopen) -> dict:
    env = _required_env()
    url = f"{env['DASHBOARD_URL']}/admin/refresh"
    token = base64.b64encode(
        f"{env['DASHBOARD_USERNAME']}:{env['DASHBOARD_PASSWORD']}".encode("utf-8")
    ).decode("ascii")
    req = request.Request(
        url,
        data=b"",
        method="POST",
        headers={
            "Authorization": f"Basic {token}",
            "X-Goblin-Action": ACTION_HEADER,
            "Accept": "application/json",
        },
    )

    try:
        with open_url(req, timeout=TIMEOUT_SECONDS) as resp:
            status = getattr(resp, "status", resp.getcode())
            raw = resp.read().decode("utf-8", errors="replace")
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Refresh request failed with HTTP {exc.code}: {_redact(body, env['DASHBOARD_PASSWORD'])}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Refresh request failed: {_redact(str(exc.reason), env['DASHBOARD_PASSWORD'])}") from exc

    if status < 200 or status >= 300:
        raise RuntimeError(f"Refresh request failed with HTTP {status}: {_redact(raw, env['DASHBOARD_PASSWORD'])}")

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Refresh response was not valid JSON: {_redact(raw[:500], env['DASHBOARD_PASSWORD'])}") from exc

    if not payload.get("ok"):
        raise RuntimeError(f"Refresh returned ok=false: {_redact(json.dumps(payload, sort_keys=True), env['DASHBOARD_PASSWORD'])}")
    return payload


def main() -> None:
    try:
        payload = trigger_admin_refresh()
    except Exception as exc:
        password = os.getenv("DASHBOARD_PASSWORD") or ""
        print(f"ERROR: {_redact(str(exc), password)}", file=sys.stderr)
        sys.exit(1)

    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
