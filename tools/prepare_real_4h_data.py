"""Validate and import user-provided real 4H ETF CSV data.

    python tools/prepare_real_4h_data.py --symbol GLD --input path/to/GLD.csv \
        --source vendor_export --adjustment unknown --timezone America/New_York \
        --session-policy RTH
"""

from __future__ import annotations

import argparse
import json
import os
import sys


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from src.data.base import ADJUSTMENT_VALUES
from src.data.four_hour_csv import (
    SESSION_POLICIES,
    build_4h_metadata,
    normalized_4h_csv,
    validate_4h_csv_text,
    validate_real_4h_files,
)


DEFAULT_REAL_DIR = os.path.join(REPO_ROOT, "data", "real")


def four_hour_data_dir() -> str:
    real_dir = (os.getenv("REAL_DATA_DIR") or DEFAULT_REAL_DIR).strip()
    return os.path.join(real_dir, "4h")


def import_real_4h_csv(
    symbol: str,
    text: str,
    source: str,
    adjustment: str,
    timezone_name: str,
    session_policy: str,
    resampled_from: str | None = None,
    notes: str = "Imported from user-provided intraday CSV.",
    output_dir: str | None = None,
) -> dict:
    validation = validate_4h_csv_text(text)
    if not validation.ok:
        raise ValueError("; ".join(validation.errors))
    if adjustment not in ADJUSTMENT_VALUES:
        raise ValueError(f"adjustment must be one of {sorted(ADJUSTMENT_VALUES)}")
    if session_policy not in SESSION_POLICIES:
        raise ValueError(f"session_policy must be one of {sorted(SESSION_POLICIES)}")
    if not source.strip() or not timezone_name.strip():
        raise ValueError("source and timezone must be non-empty")

    symbol = symbol.upper()
    destination = output_dir or four_hour_data_dir()
    os.makedirs(destination, exist_ok=True)
    csv_path = os.path.join(destination, f"{symbol}.csv")
    meta_path = os.path.join(destination, f"{symbol}.meta.json")
    metadata = build_4h_metadata(
        symbol=symbol,
        bars=validation.bars,
        source=source,
        adjustment=adjustment,
        timezone_name=timezone_name,
        session_policy=session_policy,
        resampled_from=resampled_from,
        notes=notes,
    )
    _atomic_write_text(csv_path, normalized_4h_csv(validation.bars))
    _atomic_write_text(meta_path, json.dumps(metadata, indent=2, sort_keys=True) + "\n")

    written = validate_real_4h_files(csv_path, meta_path, symbol)
    if not written.ok:
        raise RuntimeError("written 4H data failed validation: " + "; ".join(written.errors))
    return {
        "symbol": symbol,
        "row_count": len(written.bars),
        "date_start": written.bars[0]["ts"],
        "date_end": written.bars[-1]["ts"],
        "csv_path": csv_path,
        "meta_path": meta_path,
        "warnings": list(written.warnings),
    }


def _atomic_write_text(path: str, text: str) -> None:
    temporary = f"{path}.tmp"
    with open(temporary, "w", newline="", encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(temporary, path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate and import user-provided real 4H ETF CSV data."
    )
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--adjustment", required=True, choices=sorted(ADJUSTMENT_VALUES))
    parser.add_argument("--timezone", required=True)
    parser.add_argument("--session-policy", required=True, choices=sorted(SESSION_POLICIES))
    parser.add_argument("--resampled-from")
    parser.add_argument("--notes", default="Imported from user-provided intraday CSV.")
    args = parser.parse_args()

    if not os.path.isfile(args.input):
        print(f"ERROR: input file not found: {args.input}", file=sys.stderr)
        raise SystemExit(1)
    with open(args.input, encoding="utf-8-sig") as fh:
        text = fh.read()
    try:
        imported = import_real_4h_csv(
            symbol=args.symbol,
            text=text,
            source=args.source,
            adjustment=args.adjustment,
            timezone_name=args.timezone,
            session_policy=args.session_policy,
            resampled_from=args.resampled_from,
            notes=args.notes,
        )
    except (ValueError, RuntimeError) as exc:
        print(f"VALIDATION FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(json.dumps(imported, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
