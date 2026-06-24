"""Railway multi-service entrypoint with hardcoded safe roles."""

from __future__ import annotations

import os
import sys


ROLE_WEB = "web"
ROLE_CRON_TRIGGER = "cron-trigger"


def main() -> None:
    role = (os.getenv("GOBLIN_SERVICE_ROLE") or ROLE_WEB).strip() or ROLE_WEB
    if role == ROLE_WEB:
        from src.web.app import run_web
        run_web()
        return
    if role == ROLE_CRON_TRIGGER:
        from tools.trigger_admin_refresh import main as trigger_main
        trigger_main()
        return

    print(
        f"ERROR: unknown GOBLIN_SERVICE_ROLE '{role}'. "
        f"Allowed roles: {ROLE_WEB}, {ROLE_CRON_TRIGGER}.",
        file=sys.stderr,
    )
    sys.exit(1)


if __name__ == "__main__":
    main()
