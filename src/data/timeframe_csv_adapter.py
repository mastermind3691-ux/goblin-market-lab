"""Read-only selection of verified timeframe-specific CSV research data."""

from __future__ import annotations

import csv
import json
import os
from dataclasses import dataclass

from .base import DataMeta
from .csv_adapter import CsvAdapter


@dataclass(frozen=True)
class CsvDataSelection:
    bars: list[dict]
    meta: DataMeta
    effective_timeframe: str


class TimeframeCsvAdapter:
    """Select genuine 4H CSVs when present, otherwise use daily CSV data.

    A 4H file is eligible only at ``<real_dir>/4h/<SYMBOL>.csv`` with a sidecar
    declaring ``timeframe: 4H`` and ``synthetic: false``. Timestamps must include
    time-of-day values, with multiple bars present on at least one date.
    """

    def __init__(self, data_dir: str, real_dir: str | None = None):
        self.daily = CsvAdapter(data_dir, real_dir=real_dir)

    def select(
        self,
        instrument: str,
        requested_timeframe: str,
        limit: int = 500,
    ) -> CsvDataSelection:
        if normalize_timeframe(requested_timeframe) == "4H":
            selection = self._select_real_4h(instrument, limit)
            if selection is not None:
                return selection
        return CsvDataSelection(
            bars=self.daily.bars(instrument, timeframe="1d", limit=limit),
            meta=self.daily.meta(instrument),
            effective_timeframe="1D",
        )

    def _select_real_4h(
        self, instrument: str, limit: int
    ) -> CsvDataSelection | None:
        for real_dir in self.daily.real_dirs:
            timeframe_dir = os.path.join(real_dir, "4h")
            csv_path = os.path.join(timeframe_dir, f"{instrument}.csv")
            meta_path = os.path.join(timeframe_dir, f"{instrument}.meta.json")
            if not os.path.isfile(csv_path) or not os.path.isfile(meta_path):
                continue
            meta_payload = _read_meta_payload(meta_path)
            if (
                normalize_timeframe(str(meta_payload.get("timeframe", ""))) != "4H"
                or bool(meta_payload.get("synthetic", True))
            ):
                continue
            bars = _read_bars(csv_path, limit)
            if not _has_intraday_timestamps(bars):
                continue
            try:
                meta = DataMeta(
                    source=meta_payload.get("source", "csv_4h"),
                    synthetic=False,
                    adjustment=meta_payload.get("adjustment", "unknown"),
                )
            except ValueError:
                continue
            return CsvDataSelection(bars=bars, meta=meta, effective_timeframe="4H")
        return None


def normalize_timeframe(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"1d", "d", "day", "daily"}:
        return "1D"
    if normalized in {"4h", "4hr", "4hour", "4hours"}:
        return "4H"
    return value.strip().upper()


def _read_meta_payload(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_bars(path: str, limit: int) -> list[dict]:
    rows: list[dict] = []
    try:
        with open(path, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                rows.append({
                    "ts": row.get("ts") or row.get("date", ""),
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row.get("volume", 0) or 0),
                })
    except (OSError, KeyError, TypeError, ValueError):
        return []
    rows.sort(key=lambda row: row["ts"])
    return rows[-limit:]


def _has_intraday_timestamps(bars: list[dict]) -> bool:
    dates: set[str] = set()
    has_multiple_bars_on_one_date = False
    for bar in bars:
        timestamp = str(bar.get("ts", ""))
        if "T" not in timestamp and " " not in timestamp:
            return False
        date = timestamp[:10]
        if date in dates:
            has_multiple_bars_on_one_date = True
        dates.add(date)
    return has_multiple_bars_on_one_date
