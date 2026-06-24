"""Offline CSV data adapter — the offline/debug path.

Runs the whole lab with zero API keys and reproducible numbers. Provenance is
declared per-instrument via an optional sidecar ``<instrument>.meta.json``:

    {"source": "synthetic_random_walk", "synthetic": true, "adjustment": "unadjusted"}

If no sidecar exists, the adapter falls back to ``default_meta`` (real, unknown
adjustment) — so a generic CSV someone drops in is treated as real data with an
*honest* "adjustment unknown" label, while the shipped sample files carry
sidecars marking them synthetic.

When ``REAL_DATA_DIR`` is set, the adapter checks it first for each instrument,
then any provided ``real_dir`` / repo ``data/real`` path. If a real CSV exists,
it is used instead of the synthetic sample. This lets manually imported real
data override demo data automatically.

Keep this as the offline/debug path. Add a real vendor adapter later behind the
same ``MarketDataAdapter`` interface — nothing downstream changes.

CSV format (header required): date,open,high,low,close,volume
Legacy format with ``ts`` instead of ``date`` is also accepted.
"""

from __future__ import annotations

import csv
import json
import os

from .base import DataMeta, MarketDataAdapter


class CsvAdapter(MarketDataAdapter):
    def __init__(self, data_dir: str, default_meta: DataMeta | None = None,
                 real_dir: str | None = None):
        self.data_dir = data_dir
        candidates = []
        env_real_dir = (os.getenv("REAL_DATA_DIR") or "").strip()
        if env_real_dir:
            candidates.append(env_real_dir)
        if real_dir:
            candidates.append(real_dir)
        default_real_dir = os.path.join(data_dir, "real")
        candidates.append(default_real_dir)
        self.real_dirs = list(dict.fromkeys(candidates))
        self.real_dir = self.real_dirs[0] if self.real_dirs else None
        self.default_meta = default_meta or DataMeta(
            source="csv", synthetic=False, adjustment="unknown"
        )

    def _resolve_path(self, instrument: str) -> str:
        for real_dir in self.real_dirs:
            real_path = os.path.join(real_dir, f"{instrument}.csv")
            if os.path.exists(real_path):
                return real_path
        fallback = os.path.join(self.data_dir, f"{instrument}.csv")
        if not os.path.exists(fallback):
            checked = ", ".join(self.real_dirs) if self.real_dirs else "no real dirs"
            raise FileNotFoundError(f"No data for {instrument} (checked "
                                    f"{checked} and {self.data_dir})")
        return fallback

    def _resolve_meta_dir(self, instrument: str) -> str:
        for real_dir in self.real_dirs:
            real_path = os.path.join(real_dir, f"{instrument}.csv")
            if os.path.exists(real_path):
                return real_dir
        return self.data_dir

    def bars(self, instrument: str, timeframe: str = "1d", limit: int = 500) -> list[dict]:
        path = self._resolve_path(instrument)
        rows: list[dict] = []
        with open(path, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                ts = row.get("date") or row.get("ts", "")
                rows.append({
                    "ts": ts,
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row.get("volume", 0) or 0),
                })
        rows.sort(key=lambda r: r["ts"])
        return rows[-limit:]

    def meta(self, instrument: str) -> DataMeta:
        meta_dir = self._resolve_meta_dir(instrument)
        sidecar = os.path.join(meta_dir, f"{instrument}.meta.json")
        if os.path.exists(sidecar):
            with open(sidecar, encoding="utf-8") as fh:
                d = json.load(fh)
            return DataMeta(
                source=d.get("source", "csv"),
                synthetic=bool(d.get("synthetic", False)),
                adjustment=d.get("adjustment", "unknown"),
            )
        return self.default_meta
