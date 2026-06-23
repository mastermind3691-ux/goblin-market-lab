"""Instrument registry / watchlist.

What belongs here: a small, explicit list of what the lab watches, with the
metadata that actually differs between non-crypto markets — asset class, whether
it trades continuously or has sessions/gaps, and a realistic round-trip cost
assumption in basis points. What must NOT belong here: strategy logic, crypto
24/7 assumptions, or anything BTC-specific.

Start with TWO instruments. Resist adding more until the loop is proven.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Instrument:
    symbol: str            # internal symbol used for the CSV file name
    label: str             # human-friendly name
    asset_class: str       # "etf" | "index" | "gold" | "stock"
    continuous: bool       # False for things with sessions/overnight gaps
    fee_bps: float         # assumed round-trip cost in basis points (honesty)


INSTRUMENTS: dict[str, Instrument] = {
    "SPY": Instrument("SPY", "S&P 500 ETF", "etf", continuous=False, fee_bps=5.0),
    "GLD": Instrument("GLD", "Gold ETF", "gold", continuous=False, fee_bps=8.0),
}


def watchlist() -> list[str]:
    return list(INSTRUMENTS.keys())
