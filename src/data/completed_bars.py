"""Daily-bar completion rules for US-listed watch instruments."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo


MARKET_TZ = ZoneInfo("America/New_York")
REGULAR_CLOSE = time(16, 0)


def market_time(now: datetime | None = None) -> datetime:
    if now is None:
        return datetime.now(MARKET_TZ)
    if now.tzinfo is None:
        return now.replace(tzinfo=MARKET_TZ)
    return now.astimezone(MARKET_TZ)


def parse_daily_bar_date(value: str) -> date | None:
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except (AttributeError, ValueError):
            continue
    return None


def is_completed_daily_bar(value: str, now: datetime | None = None) -> bool:
    """Return whether a dated daily bar is complete at the regular US close."""
    bar_date = parse_daily_bar_date(value)
    if bar_date is None:
        return False

    current = market_time(now)
    if bar_date < current.date():
        return True
    if bar_date > current.date() or current.weekday() >= 5:
        return False
    return current.time().replace(tzinfo=None) >= REGULAR_CLOSE


def completed_daily_bars(bars: list[dict], now: datetime | None = None) -> list[dict]:
    """Discard current-session and future daily bars."""
    return [bar for bar in bars if is_completed_daily_bar(bar.get("ts", ""), now)]


def yfinance_exclusive_end(now: datetime | None = None) -> str:
    """Choose an exclusive yfinance end date that includes today's closed bar."""
    current = market_time(now)
    end = current.date()
    if current.weekday() < 5 and current.time().replace(tzinfo=None) >= REGULAR_CLOSE:
        end += timedelta(days=1)
    return end.isoformat()
