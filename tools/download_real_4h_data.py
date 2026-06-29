"""Manually download real 1H ETF bars and import validated 4H aggregates.

This one-shot research helper requests regular-session 1H bars, groups
consecutive bars within each session in chunks of up to four, and records the
derivation as ``resampled_from: 1H``. Daily bars are never used.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from src.data.four_hour_csv import validate_4h_csv_text
from tools.prepare_real_4h_data import four_hour_data_dir, import_real_4h_csv


SUPPORTED_SYMBOLS = ("GLD", "SPY")
MARKET_TIMEZONE = "America/New_York"


def fetch_1h_bars(symbol: str, period: str = "730d") -> pd.DataFrame:
    import yfinance as yf

    frame = yf.download(
        symbol,
        period=period,
        interval="1h",
        auto_adjust=False,
        prepost=False,
        actions=False,
        progress=False,
        threads=False,
        timeout=30,
    )
    if frame is None or frame.empty:
        raise ValueError(f"No 1H data returned for {symbol}.")
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = frame.columns.get_level_values(0)
    return frame


def resample_rth_1h_to_4h_csv(
    frame: pd.DataFrame,
    now: datetime | None = None,
) -> str:
    """Convert verified, sorted RTH 1H rows into session-anchored 4H CSV text."""
    if frame.empty:
        raise ValueError("Downloaded 1H data is empty.")
    data = frame.copy()
    data.columns = [str(column).strip().lower().replace(" ", "_") for column in data.columns]
    missing = [name for name in ("open", "high", "low", "close") if name not in data.columns]
    if missing:
        raise ValueError(f"Downloaded 1H data is missing columns: {', '.join(missing)}")
    if not isinstance(data.index, pd.DatetimeIndex):
        raise ValueError("Downloaded 1H data must use a DatetimeIndex.")
    if data.index.has_duplicates:
        raise ValueError("Downloaded 1H data contains duplicate timestamps.")
    if not data.index.is_monotonic_increasing:
        raise ValueError("Downloaded 1H data is not sorted oldest first.")

    market_zone = ZoneInfo(MARKET_TIMEZONE)
    if data.index.tz is None:
        data.index = data.index.tz_localize(market_zone)
    else:
        data.index = data.index.tz_convert(market_zone)
    current = now or datetime.now(market_zone)
    current = (
        current.replace(tzinfo=market_zone)
        if current.tzinfo is None
        else current.astimezone(market_zone)
    )
    data = data[data.index <= current - timedelta(hours=1)]
    minute_of_day = data.index.hour * 60 + data.index.minute
    data = data[(minute_of_day >= 9 * 60 + 30) & (minute_of_day < 16 * 60)]
    if data.empty:
        raise ValueError("No completed RTH 1H bars remain after filtering.")

    rows: list[dict] = []
    for _, session in data.groupby(data.index.date, sort=False):
        deltas = session.index.to_series().diff().dropna()
        if not deltas.empty and not (deltas == pd.Timedelta(hours=1)).all():
            raise ValueError("Downloaded 1H data has gaps inside a trading session.")
        for start in range(0, len(session), 4):
            chunk = session.iloc[start:start + 4]
            volume = float(chunk["volume"].sum()) if "volume" in chunk else 0.0
            rows.append({
                "timestamp": chunk.index[0].isoformat(),
                "open": float(chunk["open"].iloc[0]),
                "high": float(chunk["high"].max()),
                "low": float(chunk["low"].min()),
                "close": float(chunk["close"].iloc[-1]),
                "volume": volume,
            })

    output = pd.DataFrame(rows).to_csv(index=False)
    validation = validate_4h_csv_text(output)
    if not validation.ok:
        raise ValueError("Generated 4H data failed validation: " + "; ".join(validation.errors))
    return output


def download_and_import(
    symbol: str,
    period: str = "730d",
    output_dir: str | None = None,
    now: datetime | None = None,
) -> dict:
    symbol = symbol.upper()
    if symbol not in SUPPORTED_SYMBOLS:
        raise ValueError(f"symbol must be one of {SUPPORTED_SYMBOLS}")
    source = fetch_1h_bars(symbol, period=period)
    csv_text = resample_rth_1h_to_4h_csv(source, now=now)
    return import_real_4h_csv(
        symbol=symbol,
        text=csv_text,
        source="yfinance_1h",
        adjustment="unknown",
        timezone_name=MARKET_TIMEZONE,
        session_policy="RTH",
        resampled_from="1H",
        notes=(
            "Manual yfinance 1H download with prepost=false. Consecutive RTH bars "
            "are grouped per session in chunks of up to four; the final session "
            "bucket may be shorter because US ETF RTH is 6.5 hours."
        ),
        output_dir=output_dir or four_hour_data_dir(),
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download real ETF 1H bars and import validated 4H research data."
    )
    parser.add_argument(
        "--symbol", action="append", choices=SUPPORTED_SYMBOLS,
        help="symbol to download; repeat as needed (default: GLD and SPY)",
    )
    parser.add_argument(
        "--period", default="730d",
        help="yfinance intraday lookback (default: 730d; vendor availability applies)",
    )
    parser.add_argument("--output-dir", default=four_hour_data_dir())
    args = parser.parse_args()

    results = []
    for symbol in args.symbol or list(SUPPORTED_SYMBOLS):
        try:
            results.append(download_and_import(
                symbol, period=args.period, output_dir=args.output_dir
            ))
        except (ValueError, RuntimeError) as exc:
            print(f"ERROR: {symbol}: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
    print(json.dumps(results, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
