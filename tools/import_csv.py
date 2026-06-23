"""CLI: validate and import a real CSV file into data/real/.

    python -m tools.import_csv --symbol SPY --input path/to/SPY.csv \
        --source manual --adjustment adjusted

Validates the CSV, normalizes columns, and writes the clean file plus a
meta.json sidecar into data/real/. Never places orders, never touches
the portfolio.
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

    os.makedirs(REAL_DIR, exist_ok=True)

    symbol = args.symbol.upper()
    out_csv = os.path.join(REAL_DIR, f"{symbol}.csv")
    out_meta = os.path.join(REAL_DIR, f"{symbol}.meta.json")

    with open(out_csv, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["date", "open", "high", "low", "close", "volume"])
        writer.writeheader()
        writer.writerows(result.rows)

    meta = {
        "source": args.source,
        "synthetic": False,
        "adjustment": args.adjustment,
    }
    with open(out_meta, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2)

    print(f"OK: {result.bar_count} bars written to {out_csv}")
    print(f"    date range: {result.date_range[0]} to {result.date_range[1]}")
    print(f"    meta: {out_meta} (source={args.source}, adjustment={args.adjustment})")


if __name__ == "__main__":
    main()
