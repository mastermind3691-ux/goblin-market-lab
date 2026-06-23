"""CLI: re-download and re-import market data for one or more symbols.

    python -m tools.refresh_market_data --symbols SPY GLD --start 2000-01-01

Calls the existing download + import pipeline. Manual/local only — never
touches the dashboard, never places orders, never mutates lab state beyond
updating the CSV files in data/real/.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import date


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Re-download and re-import market data.",
    )
    parser.add_argument("--symbols", nargs="+", required=True, help="Symbols to refresh")
    parser.add_argument("--start", default="2000-01-01", help="Start date (default: 2000-01-01)")
    parser.add_argument("--end", default=date.today().isoformat(), help="End date (default: today)")
    parser.add_argument("--adjustment", default="unknown",
                        choices=["adjusted", "unadjusted", "unknown"],
                        help="Adjustment label (default: unknown)")
    args = parser.parse_args()

    python = sys.executable
    root = os.path.join(os.path.dirname(__file__), "..")

    for symbol in args.symbols:
        symbol = symbol.upper()
        print(f"\n--- {symbol} ---")

        raw_path = os.path.join(root, "data", "raw", "yfinance", f"{symbol}.csv")

        print(f"Downloading {symbol}...")
        rc = subprocess.call([
            python, "-m", "tools.download_market_data",
            "--symbol", symbol,
            "--start", args.start,
            "--end", args.end,
        ], cwd=root)
        if rc != 0:
            print(f"ERROR: download failed for {symbol}", file=sys.stderr)
            continue

        print(f"Importing {symbol}...")
        rc = subprocess.call([
            python, "-m", "tools.import_csv",
            "--symbol", symbol,
            "--input", raw_path,
            "--source", "yfinance",
            "--adjustment", args.adjustment,
        ], cwd=root)
        if rc != 0:
            print(f"ERROR: import failed for {symbol}", file=sys.stderr)
            continue

        print(f"OK: {symbol} refreshed.")

    print("\nDone. Run 'python -m tools.run_backtest' to see updated scorecards.")


if __name__ == "__main__":
    main()
