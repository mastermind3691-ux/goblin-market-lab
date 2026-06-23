"""CSV validation and normalization for manually imported bar data.

Validates that a CSV file is safe to use as backtest input: required columns
present, dates parse and sort correctly, no corrupt OHLCV values.  Returns
either a cleaned list of rows ready for writing, or a list of errors.

This module is read-only with respect to the lab state — it never mutates
portfolio, never touches the network, never places orders.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import datetime

REQUIRED_COLUMNS = {"date", "open", "high", "low", "close"}
OPTIONAL_COLUMNS = {"volume", "adjusted_close"}
CANONICAL_ORDER = ["date", "open", "high", "low", "close", "volume"]
MIN_BARS_FOR_BACKTEST = 120


@dataclass
class ValidationResult:
    ok: bool
    rows: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    bar_count: int = 0
    date_range: tuple[str, str] | None = None


def _normalize_column_name(name: str) -> str:
    return name.strip().lower().replace(" ", "_")


def _parse_date(s: str) -> datetime | None:
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(s.strip(), fmt)
        except ValueError:
            continue
    return None


def validate_csv(text: str) -> ValidationResult:
    """Validate and normalize CSV content. Returns ValidationResult."""
    errors: list[str] = []
    warnings: list[str] = []

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        return ValidationResult(ok=False, errors=["Empty file or no header row."])

    normalized_fields = {_normalize_column_name(f): f for f in reader.fieldnames}
    mapped = {_normalize_column_name(f): f for f in reader.fieldnames}

    # ts is accepted as an alias for date
    if "date" not in mapped and "ts" in mapped:
        mapped["date"] = mapped["ts"]

    missing = REQUIRED_COLUMNS - set(mapped.keys())
    if missing:
        return ValidationResult(
            ok=False,
            errors=[f"Missing required columns: {', '.join(sorted(missing))}"],
        )

    raw_rows: list[dict] = []
    for lineno, row in enumerate(reader, start=2):
        parsed: dict = {}

        raw_date = row[mapped["date"]].strip()
        dt = _parse_date(raw_date)
        if dt is None:
            errors.append(f"Row {lineno}: cannot parse date '{raw_date}'.")
            continue
        parsed["date"] = dt.strftime("%Y-%m-%d")
        parsed["_dt"] = dt

        has_bad_ohlc = False
        for col in ("open", "high", "low", "close"):
            raw_val = row.get(mapped[col], "").strip()
            if not raw_val:
                errors.append(f"Row {lineno}: missing {col}.")
                has_bad_ohlc = True
                continue
            try:
                val = float(raw_val)
            except ValueError:
                errors.append(f"Row {lineno}: {col} is not a number ('{raw_val}').")
                has_bad_ohlc = True
                continue
            if val <= 0:
                errors.append(f"Row {lineno}: {col} must be positive ({val}).")
                has_bad_ohlc = True
                continue
            parsed[col] = val

        if has_bad_ohlc:
            continue

        if parsed["high"] < parsed["low"]:
            errors.append(
                f"Row {lineno}: high ({parsed['high']}) < low ({parsed['low']})."
            )
            continue

        vol_key = mapped.get("volume")
        if vol_key and row.get(vol_key, "").strip():
            try:
                v = float(row[vol_key].strip())
                if v < 0:
                    errors.append(f"Row {lineno}: negative volume ({v}).")
                    continue
                parsed["volume"] = v
            except ValueError:
                parsed["volume"] = 0.0
        else:
            parsed["volume"] = 0.0

        raw_rows.append(parsed)

    if errors:
        return ValidationResult(ok=False, errors=errors, warnings=warnings)

    if not raw_rows:
        return ValidationResult(ok=False, errors=["No valid data rows found."])

    # Check for unsorted input before sorting (warn but fix)
    original_dates = [r["date"] for r in raw_rows]
    raw_rows.sort(key=lambda r: r["_dt"])
    sorted_dates = [r["date"] for r in raw_rows]
    if original_dates != sorted_dates:
        warnings.append("Dates were not in ascending order; rows have been sorted.")

    # Check for duplicate dates
    seen_dates: set[str] = set()
    deduped: list[dict] = []
    for r in raw_rows:
        if r["date"] in seen_dates:
            errors.append(f"Duplicate date: {r['date']}.")
        else:
            seen_dates.add(r["date"])
            deduped.append(r)

    if errors:
        return ValidationResult(ok=False, errors=errors, warnings=warnings)

    if len(deduped) < MIN_BARS_FOR_BACKTEST:
        warnings.append(
            f"Only {len(deduped)} bars — minimum {MIN_BARS_FOR_BACKTEST} recommended for backtest."
        )

    clean_rows = []
    for r in deduped:
        clean_rows.append({
            "date": r["date"],
            "open": r["open"],
            "high": r["high"],
            "low": r["low"],
            "close": r["close"],
            "volume": r["volume"],
        })

    date_range = (clean_rows[0]["date"], clean_rows[-1]["date"])
    return ValidationResult(
        ok=True,
        rows=clean_rows,
        errors=[],
        warnings=warnings,
        bar_count=len(clean_rows),
        date_range=date_range,
    )
