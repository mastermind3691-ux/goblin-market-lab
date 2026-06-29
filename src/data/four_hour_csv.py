"""Validation and normalization for user-provided real 4H OHLCV CSV data."""

from __future__ import annotations

import csv
import io
import json
import math
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .base import ADJUSTMENT_VALUES


REQUIRED_META_FIELDS = {
    "symbol", "timeframe", "source", "synthetic", "adjustment", "timezone",
    "session_policy", "generated_at", "row_count", "date_start", "date_end",
    "resampled_from", "notes",
}
SESSION_POLICIES = {"RTH", "extended", "unknown"}


@dataclass(frozen=True)
class FourHourCsvValidation:
    ok: bool
    bars: tuple[dict[str, Any], ...] = ()
    metadata: dict[str, Any] | None = None
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


def validate_4h_csv_text(text: str) -> FourHourCsvValidation:
    """Validate an oldest-first CSV and return normalized bars."""
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        return _failed("empty file or missing header")

    fields = {name.strip().lower(): name for name in reader.fieldnames}
    timestamp_key = next(
        (fields[name] for name in ("timestamp", "ts", "date") if name in fields),
        None,
    )
    missing = [name for name in ("open", "high", "low", "close") if name not in fields]
    if timestamp_key is None:
        missing.append("timestamp/date")
    if missing:
        return _failed(f"missing required columns: {', '.join(sorted(missing))}")

    bars: list[dict[str, Any]] = []
    errors: list[str] = []
    seen: set[datetime] = set()
    previous: datetime | None = None
    awareness: bool | None = None
    dates: set[str] = set()
    has_multiple_on_date = False

    for line_number, row in enumerate(reader, start=2):
        raw_timestamp = (row.get(timestamp_key) or "").strip()
        parsed = _parse_timestamp(raw_timestamp)
        if parsed is None:
            errors.append(f"row {line_number}: invalid intraday timestamp '{raw_timestamp}'")
            continue
        is_aware = parsed.utcoffset() is not None
        if awareness is None:
            awareness = is_aware
        elif awareness != is_aware:
            errors.append(f"row {line_number}: mixed timezone-aware and naive timestamps")
            continue
        comparable = parsed.astimezone(timezone.utc).replace(tzinfo=None) if is_aware else parsed
        if comparable in seen:
            errors.append(f"row {line_number}: duplicate timestamp {raw_timestamp}")
            continue
        if previous is not None and comparable < previous:
            errors.append(f"row {line_number}: timestamps are not sorted oldest first")
            continue
        seen.add(comparable)
        previous = comparable

        values: dict[str, float] = {}
        bad_value = False
        for name in ("open", "high", "low", "close"):
            try:
                value = float(row.get(fields[name], ""))
            except (TypeError, ValueError):
                errors.append(f"row {line_number}: {name} must be numeric")
                bad_value = True
                continue
            if not math.isfinite(value) or value <= 0:
                errors.append(f"row {line_number}: {name} must be positive and finite")
                bad_value = True
            values[name] = value
        if bad_value:
            continue
        if values["low"] > min(values["open"], values["close"]):
            errors.append(f"row {line_number}: low exceeds open or close")
            continue
        if values["high"] < max(values["open"], values["close"]):
            errors.append(f"row {line_number}: high is below open or close")
            continue

        volume = 0.0
        volume_key = fields.get("volume")
        if volume_key and (row.get(volume_key) or "").strip():
            try:
                volume = float(row[volume_key])
            except (TypeError, ValueError):
                errors.append(f"row {line_number}: volume must be numeric")
                continue
            if not math.isfinite(volume) or volume < 0:
                errors.append(f"row {line_number}: volume must be non-negative and finite")
                continue

        date = parsed.date().isoformat()
        if date in dates:
            has_multiple_on_date = True
        dates.add(date)
        bars.append({"ts": parsed.isoformat(), **values, "volume": volume})

    if not bars and not errors:
        errors.append("empty file: no data rows")
    if bars and not has_multiple_on_date:
        errors.append("timestamps show daily spacing, not intraday 4H data")
    return FourHourCsvValidation(
        ok=not errors,
        bars=tuple(bars) if not errors else (),
        errors=tuple(errors),
    )


def validate_real_4h_files(
    csv_path: str,
    meta_path: str,
    expected_symbol: str,
) -> FourHourCsvValidation:
    """Validate a 4H CSV and its required provenance sidecar together."""
    errors: list[str] = []
    if not os.path.isfile(csv_path):
        errors.append("4H CSV is missing")
    if not os.path.isfile(meta_path):
        errors.append("4H metadata sidecar is missing")
    if errors:
        return FourHourCsvValidation(ok=False, errors=tuple(errors))

    try:
        with open(csv_path, encoding="utf-8-sig") as fh:
            csv_result = validate_4h_csv_text(fh.read())
    except OSError as exc:
        return _failed(f"cannot read 4H CSV: {exc}")
    errors.extend(csv_result.errors)

    try:
        with open(meta_path, encoding="utf-8") as fh:
            metadata = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        return _failed(f"cannot read 4H metadata: {exc}")
    if not isinstance(metadata, dict):
        return _failed("4H metadata must be a JSON object")

    missing = sorted(REQUIRED_META_FIELDS - set(metadata))
    if missing:
        errors.append(f"metadata missing required fields: {', '.join(missing)}")
    if str(metadata.get("symbol", "")).upper() != expected_symbol.upper():
        errors.append("metadata symbol does not match requested symbol")
    if str(metadata.get("timeframe", "")).upper() != "4H":
        errors.append("metadata timeframe must be 4H")
    if metadata.get("synthetic") is not False:
        errors.append("metadata synthetic must be false")
    if metadata.get("adjustment") not in ADJUSTMENT_VALUES:
        errors.append(f"metadata adjustment must be one of {sorted(ADJUSTMENT_VALUES)}")
    if metadata.get("session_policy") not in SESSION_POLICIES:
        errors.append(f"metadata session_policy must be one of {sorted(SESSION_POLICIES)}")
    for name in ("source", "timezone", "generated_at"):
        if not isinstance(metadata.get(name), str) or not metadata[name].strip():
            errors.append(f"metadata {name} must be a non-empty string")
    generated_at = metadata.get("generated_at")
    if isinstance(generated_at, str) and generated_at.strip():
        try:
            datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        except ValueError:
            errors.append("metadata generated_at must be an ISO-8601 timestamp")
    if not isinstance(metadata.get("notes"), str):
        errors.append("metadata notes must be a string")
    resampled_from = metadata.get("resampled_from")
    if resampled_from is not None and (
        not isinstance(resampled_from, str) or not resampled_from.strip()
    ):
        errors.append("metadata resampled_from must be null or a non-empty string")

    bars = csv_result.bars
    if bars:
        if metadata.get("row_count") != len(bars):
            errors.append("metadata row_count does not match CSV")
        if metadata.get("date_start") != bars[0]["ts"]:
            errors.append("metadata date_start does not match CSV")
        if metadata.get("date_end") != bars[-1]["ts"]:
            errors.append("metadata date_end does not match CSV")

    warnings: list[str] = []
    if metadata.get("adjustment") == "unknown":
        warnings.append("4H price adjustment is unknown")
    if metadata.get("session_policy") == "unknown":
        warnings.append("4H session policy is unknown")
    return FourHourCsvValidation(
        ok=not errors,
        bars=bars if not errors else (),
        metadata=metadata,
        errors=tuple(errors),
        warnings=tuple(warnings),
    )


def build_4h_metadata(
    symbol: str,
    bars: tuple[dict[str, Any], ...],
    source: str,
    adjustment: str,
    timezone_name: str,
    session_policy: str,
    resampled_from: str | None,
    notes: str,
) -> dict[str, Any]:
    return {
        "symbol": symbol.upper(),
        "timeframe": "4H",
        "source": source,
        "synthetic": False,
        "adjustment": adjustment,
        "timezone": timezone_name,
        "session_policy": session_policy,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "row_count": len(bars),
        "date_start": bars[0]["ts"],
        "date_end": bars[-1]["ts"],
        "resampled_from": resampled_from,
        "notes": notes,
    }


def normalized_4h_csv(bars: tuple[dict[str, Any], ...]) -> str:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output, fieldnames=["timestamp", "open", "high", "low", "close", "volume"]
    )
    writer.writeheader()
    for bar in bars:
        writer.writerow({"timestamp": bar["ts"], **{k: bar[k] for k in (
            "open", "high", "low", "close", "volume"
        )}})
    return output.getvalue()


def _parse_timestamp(value: str) -> datetime | None:
    if not value or ("T" not in value and " " not in value):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _failed(message: str) -> FourHourCsvValidation:
    return FourHourCsvValidation(ok=False, errors=(message,))
