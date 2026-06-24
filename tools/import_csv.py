"""CLI: validate and import a real CSV file into the real-data directory.

    python -m tools.import_csv --symbol SPY --input path/to/SPY.csv \
        --source manual --adjustment adjusted

Validates the CSV, normalizes columns, and writes the clean file plus a
meta.json sidecar into REAL_DATA_DIR when set, otherwise data/real/. Never
places orders, never touches the portfolio.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys

from src.data.base import ADJUSTMENT_VALUES
from src.data.csv_validator import validate_csv

REAL_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "real")


def real_data_dir() -> str:
    return (os.getenv("REAL_DATA_DIR") or REAL_DIR).strip()


def import_csv_text(symbol: str, text: str, source: str, adjustment: str,
                    output_dir: str | None = None) -> dict:
    result = validate_csv(text)

    if not result.ok:
        raise ValueError("; ".join(result.errors))

    out_dir = output_dir or real_data_dir()
    os.makedirs(out_dir, exist_ok=True)

    symbol = symbol.upper()
    out_csv = os.path.join(out_dir, f"{symbol}.csv")
    out_meta = os.path.join(out_dir, f"{symbol}.meta.json")

    with open(out_csv, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["date", "open", "high", "low", "close", "volume"])
        writer.writeheader()
        writer.writerows(result.rows)

    meta = {
        "source": source,
        "synthetic": False,
        "adjustment": adjustment,
    }
    with open(out_meta, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2)

    return {
        "symbol": symbol,
        "bar_count": result.bar_count,
        "date_range": result.date_range,
        "latest_bar_date": result.date_range[1],
        "csv_path": out_csv,
        "meta_path": out_meta,
        "warnings": result.warnings,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import and validate a CSV bar file into data/real/.",
    )
    parser.add_argument("--symbol", required=True, help="Instrument symbol (e.g. SPY)")
    parser.add_argument("--input", required=True, help="Path to input CSV file")
    parser.add_argument("--source", default="manual", help="Data source label (default: manual)")
    parser.add_argument(
        "--adjustment",
        required=True,
        choices=sorted(ADJUSTMENT_VALUES),
        help="Price adjustment status",
    )
    args = parser.parse_args()

    if not os.path.isfile(args.input):
        print(f"ERROR: input file not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    with open(args.input, encoding="utf-8") as fh:
        text = fh.read()

    result = validate_csv(text)

    for w in result.warnings:
        print(f"WARNING: {w}")

    if not result.ok:
        print("VALIDATION FAILED:")
        for e in result.errors:
            print(f"  {e}")
        sys.exit(1)

    imported = import_csv_text(args.symbol, text, args.source, args.adjustment)

    print(f"OK: {imported['bar_count']} bars written to {imported['csv_path']}")
    print(f"    date range: {imported['date_range'][0]} to {imported['date_range'][1]}")
    print(f"    meta: {imported['meta_path']} (source={args.source}, adjustment={args.adjustment})")


if __name__ == "__main__":
    main()
