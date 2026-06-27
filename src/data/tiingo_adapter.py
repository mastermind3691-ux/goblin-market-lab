"""Read-only Tiingo EOD adapter with explicit price-adjustment provenance."""

from __future__ import annotations

import json
import math
import os
from datetime import datetime
from urllib import parse, request

from .base import DataMeta, MarketDataAdapter
from .completed_bars import is_completed_daily_bar


TIINGO_EOD_URL = "https://api.tiingo.com/tiingo/daily/{symbol}/prices"
ADJUSTED_FIELDS = ("adjOpen", "adjHigh", "adjLow", "adjClose")
RAW_FIELDS = ("open", "high", "low", "close")


def _date_label(value) -> str:
    return str(value or "")[:10]


def _finite_number(value) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


class TiingoEodAdapter(MarketDataAdapter):
    def __init__(self, api_key: str | None = None, open_url=request.urlopen,
                 now: datetime | None = None, timeout: int = 30):
        self._api_key = (api_key or os.getenv("TIINGO_API_KEY") or "").strip()
        if not self._api_key:
            raise ValueError("TIINGO_API_KEY is required for Tiingo EOD data.")
        self._open_url = open_url
        self._now = now
        self._timeout = timeout
        self._meta_by_symbol: dict[str, DataMeta] = {}
        self._diagnostics_by_symbol: dict[str, dict] = {}

    def _request_rows(self, instrument: str, start: str,
                      end: str | None) -> list[dict]:
        params = {"startDate": start, "resampleFreq": "daily"}
        if end:
            params["endDate"] = end
        symbol = instrument.upper()
        url = TIINGO_EOD_URL.format(symbol=parse.quote(symbol, safe=""))
        req = request.Request(
            f"{url}?{parse.urlencode(params)}",
            headers={
                "Authorization": f"Token {self._api_key}",
                "Accept": "application/json",
                "User-Agent": "goblin-market-lab/1.0",
            },
        )
        with self._open_url(req, timeout=self._timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, list):
            raise ValueError("Tiingo EOD response must be a list of rows.")
        return payload

    @staticmethod
    def _price_fields(rows: list[dict]) -> tuple[tuple[str, ...], str]:
        if rows and all(all(field in row for field in ADJUSTED_FIELDS) for row in rows):
            return ADJUSTED_FIELDS, "adjusted"
        if rows and all(all(field in row for field in RAW_FIELDS) for row in rows):
            return RAW_FIELDS, "unadjusted"
        return (), "unknown"

    def fetch(self, instrument: str, start: str = "2000-01-01",
              end: str | None = None, limit: int = 999_999) -> dict:
        symbol = instrument.upper()
        rows = self._request_rows(symbol, start, end)
        rows.sort(key=lambda row: _date_label(row.get("date")))
        fields, adjustment = self._price_fields(rows)
        meta = DataMeta(source="tiingo", synthetic=False, adjustment=adjustment)
        self._meta_by_symbol[symbol] = meta

        latest_vendor_row_date = _date_label(rows[-1].get("date")) if rows else None
        bars = []
        excluded = []
        labels = ("Open", "High", "Low", "Close")
        for row in rows:
            row_date = _date_label(row.get("date"))
            if not fields:
                excluded.append({
                    "symbol": symbol,
                    "date": row_date or "unknown",
                    "reason": "excluded because a consistent OHLC field set was unavailable",
                })
                continue
            missing = [
                label for field, label in zip(fields, labels)
                if not _finite_number(row.get(field))
            ]
            if missing:
                excluded.append({
                    "symbol": symbol,
                    "date": row_date or "unknown",
                    "reason": f"excluded because {'/'.join(missing)} was NaN or incomplete",
                })
                continue
            if not is_completed_daily_bar(row_date, self._now):
                excluded.append({
                    "symbol": symbol,
                    "date": row_date or "unknown",
                    "reason": "excluded because the daily bar was not completed",
                })
                continue

            volume_field = "adjVolume" if adjustment == "adjusted" else "volume"
            volume = row.get(volume_field)
            if not _finite_number(volume):
                volume = row.get("volume", 0)
            bars.append({
                "ts": row_date,
                "open": float(row[fields[0]]),
                "high": float(row[fields[1]]),
                "low": float(row[fields[2]]),
                "close": float(row[fields[3]]),
                "volume": float(volume) if _finite_number(volume) else 0.0,
            })

        result = {
            "bars": bars[-limit:],
            "meta": meta,
            "latest_vendor_row_date": latest_vendor_row_date,
            "excluded_vendor_rows": excluded,
        }
        self._diagnostics_by_symbol[symbol] = result
        return result

    def bars(self, instrument: str, timeframe: str = "1d",
             limit: int = 500) -> list[dict]:
        if timeframe != "1d":
            raise ValueError("TiingoEodAdapter supports daily bars only.")
        return self.fetch(instrument, limit=limit)["bars"]

    def meta(self, instrument: str) -> DataMeta:
        return self._meta_by_symbol.get(
            instrument.upper(),
            DataMeta(source="tiingo", synthetic=False, adjustment="unknown"),
        )

    def diagnostics(self, instrument: str) -> dict:
        return dict(self._diagnostics_by_symbol.get(instrument.upper(), {}))
