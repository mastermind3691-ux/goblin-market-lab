"""CLI: re-download and re-import market data for one or more symbols.

    python -m tools.refresh_market_data --symbols SPY GLD --start 2000-01-01

Calls the existing download + import pipeline. Manual/local only: never places
orders and never mutates lab state beyond updating the CSV files in
REAL_DATA_DIR when set, otherwise data/real/.
"""

from __future__ import annotations

import argparse
import os
from datetime import datetime

from src.data.completed_bars import yfinance_exclusive_end
from tools.download_market_data import dataframe_to_csv_result, fetch_bars
from tools.import_csv import import_csv_text, real_data_dir


def refresh_market_data(symbols: list[str], start: str, end: str | None = None,
                        adjustment: str = "unknown",
                        output_dir: str | None = None,
                        write_raw: bool = True,
                        now: datetime | None = None) -> dict:
    end = end or yfinance_exclusive_end(now)
    out_dir = output_dir or real_data_dir()
    root = os.path.join(os.path.dirname(__file__), "..")
    raw_dir = os.path.join(root, "data", "raw", "yfinance")
    if write_raw:
        os.makedirs(raw_dir, exist_ok=True)

    refreshed = []
    for symbol in symbols:
        symbol = symbol.upper()
        df = fetch_bars(symbol, start, end)
        converted = dataframe_to_csv_result(df)
        csv_text = converted["csv_text"]

        raw_path = None
        if write_raw:
            raw_path = os.path.join(raw_dir, f"{symbol}.csv")
            with open(raw_path, "w", encoding="utf-8") as fh:
                fh.write(csv_text)

        imported = import_csv_text(
            symbol, csv_text, source="yfinance",
            adjustment=adjustment, output_dir=out_dir,
        )
        imported["raw_path"] = raw_path
        imported["latest_vendor_row_date"] = converted["latest_vendor_row_date"]
        imported["excluded_vendor_rows"] = [
            {"symbol": symbol, **row}
            for row in converted["excluded_rows"]
        ]
        refreshed.append(imported)

    return {
        "symbols": [r["symbol"] for r in refreshed],
        "output_dir": out_dir,
        "download_end_exclusive": end,
        "latest_bar_date": {r["symbol"]: r["latest_bar_date"] for r in refreshed},
        "latest_vendor_row_date": {
            r["symbol"]: r["latest_vendor_row_date"] for r in refreshed
        },
        "excluded_vendor_rows": [
            row
            for item in refreshed
            for row in item["excluded_vendor_rows"]
        ],
        "refreshed": refreshed,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Re-download and re-import market data.",
    )
    parser.add_argument("--symbols", nargs="+", required=True, help="Symbols to refresh")
    parser.add_argument("--start", default="2000-01-01", help="Start date (default: 2000-01-01)")
    parser.add_argument(
        "--end",
        default=None,
        help="Exclusive end date (default: latest completed regular-session bar)",
    )
    parser.add_argument("--adjustment", default="unknown",
                        choices=["adjusted", "unadjusted", "unknown"],
                        help="Adjustment label (default: unknown)")
    args = parser.parse_args()

    result = refresh_market_data(args.symbols, args.start, args.end, args.adjustment)
    for item in result["refreshed"]:
        print(f"\n--- {item['symbol']} ---")
        print(f"OK: {item['bar_count']} bars refreshed.")
        print(f"    raw: {item['raw_path']}")
        print(f"    csv: {item['csv_path']}")
        print(f"    date range: {item['date_range'][0]} to {item['date_range'][1]}")
        print(f"    latest vendor row: {item['latest_vendor_row_date']}")
        for excluded in item["excluded_vendor_rows"]:
            print(f"    WARNING: {excluded['date']} {excluded['reason']}.")

    print("\nDone. Run 'python -m tools.run_backtest' to see updated scorecards.")


if __name__ == "__main__":
    main()
