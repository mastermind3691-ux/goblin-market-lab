"""CLI: re-download and re-import market data for one or more symbols.

    python -m tools.refresh_market_data --symbols SPY GLD --start 2000-01-01

Calls the existing download + import pipeline. Manual/local only: never places
orders and never mutates lab state beyond updating the CSV files in
REAL_DATA_DIR when set, otherwise data/real/.
"""

from __future__ import annotations

import argparse
import csv
import io
import os
from datetime import datetime

from src.data.completed_bars import yfinance_exclusive_end
from src.data.tiingo_adapter import TiingoEodAdapter
from tools.download_market_data import dataframe_to_csv_result, fetch_bars
from tools.import_csv import import_csv_text, real_data_dir


PRIMARY_SOURCE = "tiingo"
FALLBACK_SOURCE = "yfinance"


def _bars_to_csv_text(bars: list[dict]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=["date", "open", "high", "low", "close", "volume"],
    )
    writer.writeheader()
    for bar in bars:
        writer.writerow({"date": bar["ts"], **{key: bar[key] for key in writer.fieldnames[1:]}})
    return output.getvalue()


def _tiingo_result(adapter: TiingoEodAdapter, symbol: str,
                   start: str, end: str) -> dict:
    result = adapter.fetch(symbol, start=start, end=end)
    if not result["bars"]:
        raise ValueError("Tiingo returned no accepted completed bars.")
    return {
        "csv_text": _bars_to_csv_text(result["bars"]),
        "source": result["meta"].source,
        "adjustment": result["meta"].adjustment,
        "latest_vendor_row_date": result["latest_vendor_row_date"],
        "excluded_vendor_rows": [
            {**row, "source": result["meta"].source}
            for row in result["excluded_vendor_rows"]
        ],
    }


def _yfinance_result(symbol: str, start: str, end: str) -> dict:
    converted = dataframe_to_csv_result(fetch_bars(symbol, start, end))
    return {
        "csv_text": converted["csv_text"],
        "source": FALLBACK_SOURCE,
        "adjustment": "unknown",
        "latest_vendor_row_date": converted["latest_vendor_row_date"],
        "excluded_vendor_rows": [
            {"symbol": symbol, **row, "source": FALLBACK_SOURCE}
            for row in converted["excluded_rows"]
        ],
    }


def refresh_market_data(symbols: list[str], start: str, end: str | None = None,
                        adjustment: str = "unknown",
                        output_dir: str | None = None,
                        write_raw: bool = True,
                        now: datetime | None = None,
                        tiingo_adapter: TiingoEodAdapter | None = None) -> dict:
    end = end or yfinance_exclusive_end(now)
    out_dir = output_dir or real_data_dir()
    root = os.path.join(os.path.dirname(__file__), "..")
    tiingo_key = (os.getenv("TIINGO_API_KEY") or "").strip()
    if tiingo_key and tiingo_adapter is None:
        tiingo_adapter = TiingoEodAdapter(api_key=tiingo_key, now=now)

    refreshed = []
    for symbol in symbols:
        symbol = symbol.upper()
        fallback_source = None
        fallback_reason = None
        if tiingo_adapter is not None:
            try:
                vendor = _tiingo_result(tiingo_adapter, symbol, start, end)
            except Exception as exc:
                fallback_source = FALLBACK_SOURCE
                fallback_reason = f"Tiingo unavailable ({type(exc).__name__})"
                diagnostics = tiingo_adapter.diagnostics(symbol)
                tiingo_exclusions = [
                    {**row, "source": PRIMARY_SOURCE}
                    for row in diagnostics.get("excluded_vendor_rows", [])
                ]
                vendor = _yfinance_result(symbol, start, end)
                vendor["excluded_vendor_rows"] = (
                    tiingo_exclusions + vendor["excluded_vendor_rows"]
                )
        else:
            fallback_source = FALLBACK_SOURCE
            fallback_reason = "TIINGO_API_KEY is not configured"
            vendor = _yfinance_result(symbol, start, end)

        csv_text = vendor["csv_text"]

        raw_path = None
        if write_raw:
            raw_dir = os.path.join(root, "data", "raw", vendor["source"])
            os.makedirs(raw_dir, exist_ok=True)
            raw_path = os.path.join(raw_dir, f"{symbol}.csv")
            with open(raw_path, "w", encoding="utf-8") as fh:
                fh.write(csv_text)

        imported = import_csv_text(
            symbol, csv_text, source=vendor["source"],
            adjustment=(vendor["adjustment"] if vendor["source"] == PRIMARY_SOURCE
                        else adjustment),
            output_dir=out_dir,
        )
        imported["raw_path"] = raw_path
        imported["source_used"] = vendor["source"]
        imported["fallback_source_used"] = fallback_source
        imported["fallback_reason"] = fallback_reason
        imported["latest_vendor_row_date"] = vendor["latest_vendor_row_date"]
        imported["excluded_vendor_rows"] = vendor["excluded_vendor_rows"]
        refreshed.append(imported)

    return {
        "primary_source": PRIMARY_SOURCE,
        "symbols": [r["symbol"] for r in refreshed],
        "output_dir": out_dir,
        "download_end_exclusive": end,
        "source_used": {r["symbol"]: r["source_used"] for r in refreshed},
        "fallback_source_used": {
            r["symbol"]: r["fallback_source_used"] for r in refreshed
        },
        "fallback_reason": {
            r["symbol"]: r["fallback_reason"] for r in refreshed
            if r["fallback_reason"]
        },
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
        print(f"    source used: {item['source_used']}")
        if item["fallback_source_used"]:
            print(f"    fallback: {item['fallback_source_used']} ({item['fallback_reason']})")
        print(f"    date range: {item['date_range'][0]} to {item['date_range'][1]}")
        print(f"    latest vendor row: {item['latest_vendor_row_date']}")
        for excluded in item["excluded_vendor_rows"]:
            print(f"    WARNING: {excluded['date']} {excluded['reason']}.")

    print("\nDone. Run 'python -m tools.run_backtest' to see updated scorecards.")


if __name__ == "__main__":
    main()
