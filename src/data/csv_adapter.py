"""Offline CSV data adapter — the offline/debug path.

Runs the whole lab with zero API keys and reproducible numbers. Provenance is
declared per-instrument via an optional sidecar ``<instrument>.meta.json``:

    {"source": "synthetic_random_walk", "synthetic": true, "adjustment": "unadjusted"}

If no sidecar exists, the adapter falls back to ``default_meta`` (real, unknown
adjustment) — so a generic CSV someone drops in is treated as real data with an
*honest* "adjustment unknown" label, while the shipped sample files carry
sidecars marking them synthetic.

Keep this as the offline/debug path. Add a real vendor adapter later behind the
same ``MarketDataAdapter`` interface — nothing downstream changes.

CSV format (header required): ts,open,high,low,close,volume
"""

from __future__ import annotations

import csv
import json
import os

from .base import DataMeta, MarketDataAdapter


class CsvAdapter(MarketDataAdapter):
    def __init__(self, data_dir: str, default_meta: DataMeta | None = None):
        self.data_dir = data_dir
        self.default_meta = default_meta or DataMeta(
            source="csv", synthetic=False, adjustment="unknown"
        )

    def bars(self, instrument: str, timeframe: str = "1d", limit: int = 500) -> list[dict]:
        path = os.path.join(self.data_dir, f"{instrument}.csv")
        if not os.path.exists(path):
            raise FileNotFoundError(f"No sample data for {instrument} at {path}")
        rows: list[dict] = []
        with open(path, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                rows.append({
                    "ts": row["ts"],
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row.get("volume", 0) or 0),
                })
        rows.sort(key=lambda r: r["ts"])
        return rows[-limit:]

    def meta(self, instrument: str) -> DataMeta:
        sidecar = os.path.join(self.data_dir, f"{instrument}.meta.json")
        if os.path.exists(sidecar):
            with open(sidecar, encoding="utf-8") as fh:
                d = json.load(fh)
            return DataMeta(
                source=d.get("source", "csv"),
                synthetic=bool(d.get("synthetic", False)),
                adjustment=d.get("adjustment", "unknown"),
            )
        return self.default_meta
