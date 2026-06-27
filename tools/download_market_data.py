"""CLI: download daily bars via yfinance and save as raw CSV.

This is a manual data-fetch helper, not a live vendor system. It writes a raw
CSV that you then import through ``tools.import_csv`` for validation and
normalization.

    python -m tools.download_market_data --symbol SPY --start 2000-01-01 --end 2026-06-23

The output lands in ``data/raw/yfinance/<SYMBOL>.csv``. After downloading,
import into the lab:

    python -m tools.import_csv --symbol SPY --input data/raw/yfinance/SPY.csv \\
        --source yfinance --adjustment unknown

yfinance returns unadjusted OHLC when ``auto_adjust=False``; adjustment should
be declared ``unknown`` at import time unless you verify the source's policy.

Never places orders, never touches the portfolio, never mutates lab state.
"""

from __future__ import annotations

import argparse
import os
import sys

import pandas as pd

RAW_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "raw", "yfinance")


def fetch_bars(symbol: str, start: str, end: str) -> pd.DataFrame:
    import yfinance as yf
    df = yf.download(symbol, start=start, end=end, auto_adjust=False, progress=False)
    if df.empty:
        raise ValueError(f"No data returned for {symbol}.")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


def dataframe_to_csv_text(df: pd.DataFrame) -> str:
    df = df.copy()
    df.index.name = "date"
    df.columns = [c.lower().replace(" ", "_") for c in df.columns]
    df = df.sort_index(ascending=True)
    expected = ["open", "high", "low", "close", "volume"]
    cols = [c for c in expected if c in df.columns]
    required_price_cols = [c for c in ("open", "high", "low", "close") if c in df.columns]
    df = df.dropna(subset=required_price_cols)
    return df[cols].to_csv()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download daily bars via yfinance and save as raw CSV.",
    )
    parser.add_argument("--symbol", required=True, help="Instrument symbol (e.g. SPY)")
    parser.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="End date YYYY-MM-DD")
    parser.add_argument("--output-dir", default=RAW_DIR, help="Output directory")
    args = parser.parse_args()

    symbol = args.symbol.upper()
    print(f"Fetching {symbol} via yfinance ({args.start} to {args.end})...")

    try:
        df = fetch_bars(symbol, args.start, args.end)
    except Exception as exc:
        print(f"ERROR: failed to fetch data: {exc}", file=sys.stderr)
        sys.exit(1)

    os.makedirs(args.output_dir, exist_ok=True)
    out_path = os.path.join(args.output_dir, f"{symbol}.csv")

    csv_text = dataframe_to_csv_text(df)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(csv_text)

    bar_count = len(df)
    date_min = df.index.min().strftime("%Y-%m-%d")
    date_max = df.index.max().strftime("%Y-%m-%d")
    print(f"OK: {bar_count} bars written to {out_path}")
    print(f"    date range: {date_min} to {date_max}")
    print(f"\nNext step -- import into the lab:")
    print(f"    python -m tools.import_csv --symbol {symbol} "
          f"--input {out_path} --source yfinance --adjustment unknown")


if __name__ == "__main__":
    main()
