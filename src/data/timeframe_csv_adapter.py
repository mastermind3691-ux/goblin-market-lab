"""Read-only selection of verified timeframe-specific CSV research data."""

from __future__ import annotations

import os
from dataclasses import dataclass

from .base import DataMeta
from .csv_adapter import CsvAdapter
from .four_hour_csv import validate_real_4h_files


@dataclass(frozen=True)
class CsvDataSelection:
    bars: list[dict]
    meta: DataMeta
    effective_timeframe: str
    warnings: tuple[str, ...] = ()


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
            selection, warnings = self._select_real_4h(instrument, limit)
            if selection is not None:
                return selection
        else:
            warnings = ()
        return CsvDataSelection(
            bars=self.daily.bars(instrument, timeframe="1d", limit=limit),
            meta=self.daily.meta(instrument),
            effective_timeframe="1D",
            warnings=warnings,
        )

    def _select_real_4h(
        self, instrument: str, limit: int
    ) -> tuple[CsvDataSelection | None, tuple[str, ...]]:
        rejection_warnings: list[str] = []
        for real_dir in self.daily.real_dirs:
            timeframe_dir = os.path.join(real_dir, "4h")
            csv_path = os.path.join(timeframe_dir, f"{instrument}.csv")
            meta_path = os.path.join(timeframe_dir, f"{instrument}.meta.json")
            if not os.path.isfile(csv_path) and not os.path.isfile(meta_path):
                continue
            validation = validate_real_4h_files(csv_path, meta_path, instrument)
            if not validation.ok:
                rejection_warnings.append(
                    "FOUR_HOUR_DATA_REJECTED: " + "; ".join(validation.errors)
                )
                continue
            metadata = validation.metadata or {}
            meta = DataMeta(
                source=metadata["source"],
                synthetic=False,
                adjustment=metadata["adjustment"],
            )
            warnings = rejection_warnings + [
                f"FOUR_HOUR_DATA_WARNING: {warning}"
                for warning in validation.warnings
            ]
            return CsvDataSelection(
                bars=list(validation.bars[-limit:]),
                meta=meta,
                effective_timeframe="4H",
                warnings=tuple(warnings),
            ), tuple(warnings)
        return None, tuple(rejection_warnings)


def normalize_timeframe(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"1d", "d", "day", "daily"}:
        return "1D"
    if normalized in {"4h", "4hr", "4hour", "4hours"}:
        return "4H"
    return value.strip().upper()
