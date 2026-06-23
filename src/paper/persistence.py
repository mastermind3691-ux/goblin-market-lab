"""Atomic, migration-safe persistence for paper state.

Two disciplines carried over from the BTC project, re-implemented cleanly:

1. Atomic writes: write to a ``.tmp`` file, fsync, then ``os.replace`` so a
   crash mid-write can never corrupt the saved account.

2. Migration safety: if the saved state was built for a different instrument
   set than the one currently configured, we BACK IT UP rather than silently
   overwrite or reset it. Losing a human's research history is not allowed.

This module only knows how to read/write a JSON blob safely. It does not know
what is inside it — the portfolio/shadow modules own the schema.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Optional


def _fsync_parent_dir(path: str) -> None:
    parent = os.path.dirname(os.path.abspath(path)) or "."
    fd = os.open(parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    except OSError:
        pass  # Some filesystems (and Windows) don't support directory fsync.
    finally:
        os.close(fd)


def atomic_write_json(path: str, data: dict[str, Any]) -> None:
    """Write ``data`` as JSON to ``path`` atomically."""
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    _fsync_parent_dir(path)


def load_json(path: str) -> Optional[dict[str, Any]]:
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def save_paper_state(path: str, state: dict[str, Any], configured_instruments: list[str]) -> dict[str, Any]:
    """Save paper state, stamping it with the instruments it belongs to.

    Returns a small diagnostics dict (mirrors the BTC project's paper_memory
    diagnostics) so the UI can show what happened.
    """
    payload = dict(state)
    payload["_instruments"] = sorted(configured_instruments)
    payload["_saved_at"] = time.time()
    atomic_write_json(path, payload)
    return {"saved": True, "path": path, "instruments": payload["_instruments"]}


def restore_paper_state(path: str, configured_instruments: list[str]) -> tuple[Optional[dict[str, Any]], dict[str, Any]]:
    """Load paper state with migration safety.

    Rules:
    - File missing -> return (None, fresh diagnostics). Caller starts a new account.
    - Instrument set matches -> load normally.
    - Instrument set differs -> back up the old file as ``<path>.incompatible.<ts>.json``
      and return None so the caller starts fresh, WITHOUT destroying history.
    """
    diagnostics: dict[str, Any] = {
        "file_exists": os.path.exists(path),
        "migration_performed": False,
        "backup_path": None,
        "configured_instruments": sorted(configured_instruments),
        "saved_instruments": None,
    }

    saved = load_json(path)
    if saved is None:
        return None, diagnostics

    saved_instruments = saved.get("_instruments")
    diagnostics["saved_instruments"] = saved_instruments

    if saved_instruments is not None and saved_instruments != sorted(configured_instruments):
        backup = f"{path}.incompatible.{int(time.time())}.json"
        os.replace(path, backup)
        diagnostics["migration_performed"] = True
        diagnostics["backup_path"] = backup
        return None, diagnostics

    return saved, diagnostics
