"""Watch-only market context built from existing CSV data.

This module never downloads data, never mutates state, and never feeds
strategies or scorecards. It is display-only context for the dashboard/API.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from .csv_adapter import CsvAdapter
from ..instruments.registry import INSTRUMENTS

WATCH_SYMBOLS = ("SPY", "GLD")
RECENT_SERIES_LIMIT = 60
STALE_DATA_DAYS = 30
MARKET_TZ = "America/New_York"


def _parse_bar_date(ts: str) -> date | None:
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(ts.strip(), fmt).date()
        except (ValueError, AttributeError):
            continue
    return None


def _freshness(bars: list[dict], today: date | None = None) -> dict:
    today = today or date.today()
    if not bars:
        return {"latest_bar_date": None, "data_age_days": None, "data_is_stale": True}
    latest = bars[-1].get("ts", "")
    parsed = _parse_bar_date(latest)
    if parsed is None:
        return {"latest_bar_date": latest, "data_age_days": None, "data_is_stale": True}
    age = (today - parsed).days
    return {
        "latest_bar_date": parsed.isoformat(),
        "data_age_days": age,
        "data_is_stale": age > STALE_DATA_DAYS,
    }


def _next_weekday(d: date) -> date:
    candidate = d + timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate


def _iso_local(d: date, t: time, tz: ZoneInfo) -> str:
    return datetime.combine(d, t, tzinfo=tz).isoformat()


def market_clock(now: datetime | None = None) -> dict:
    tz = ZoneInfo(MARKET_TZ)
    current = now.astimezone(tz) if now else datetime.now(tz)
    open_t = time(9, 30)
    close_t = time(16, 0)
    today = current.date()

    is_weekend = current.weekday() >= 5
    open_dt = datetime.combine(today, open_t, tzinfo=tz)
    close_dt = datetime.combine(today, close_t, tzinfo=tz)

    if is_weekend:
        state = "weekend"
        market_open = False
        next_open_day = today
        while next_open_day.weekday() >= 5:
            next_open_day += timedelta(days=1)
        next_close_day = next_open_day
    elif open_dt <= current < close_dt:
        state = "open"
        market_open = True
        next_open_day = today
        next_close_day = today
    else:
        state = "closed"
        market_open = False
        next_open_day = today if current < open_dt else _next_weekday(today)
        next_close_day = today if current < close_dt else next_open_day

    return {
        "timezone": MARKET_TZ,
        "core_session": "09:30-16:00 ET",
        "market_open": market_open,
        "market_state": state,
        "next_open_est": _iso_local(next_open_day, open_t, tz),
        "next_close_est": _iso_local(next_close_day, close_t, tz),
        "holiday_calendar_accuracy": "not_implemented",
        "clock_note": "Regular-hours estimate only; US market holidays are not modeled.",
    }


def instrument_market_info(adapter: CsvAdapter, symbol: str,
                           today: date | None = None,
                           series_limit: int = RECENT_SERIES_LIMIT) -> dict:
    bars = adapter.bars(symbol, limit=999_999)
    meta = adapter.meta(symbol)
    latest = bars[-1] if bars else {}
    previous = bars[-2] if len(bars) >= 2 else {}
    latest_close = latest.get("close")
    previous_close = previous.get("close")

    day_change = None
    day_change_pct = None
    if latest_close is not None and previous_close not in (None, 0):
        day_change = round(latest_close - previous_close, 4)
        day_change_pct = round(day_change / previous_close, 6)

    freshness = _freshness(bars, today=today)
    inst = INSTRUMENTS[symbol]
    recent = [
        {"date": b["ts"], "close": b["close"]}
        for b in bars[-min(series_limit, RECENT_SERIES_LIMIT):]
    ]
    sparkline_points = _sparkline_points([p["close"] for p in recent])

    return {
        "symbol": symbol,
        "display_name": inst.label,
        "source": meta.source,
        "price_adjustment": meta.adjustment,
        "latest_bar_date": freshness["latest_bar_date"],
        "latest_close": latest_close,
        "previous_close": previous_close,
        "day_change": day_change,
        "day_change_pct": day_change_pct,
        "bars_available": len(bars),
        "data_is_stale": freshness["data_is_stale"],
        "data_age_days": freshness["data_age_days"],
        "status": "watch_only",
        "trade_impact": "none",
        "recent_close_series": recent,
        "sparkline_points": sparkline_points,
    }


def market_info_payload(data_dir: str, today: date | None = None) -> dict:
    adapter = CsvAdapter(data_dir)
    instruments = []
    for symbol in WATCH_SYMBOLS:
        try:
            instruments.append(instrument_market_info(adapter, symbol, today=today))
        except FileNotFoundError:
            continue

    return {
        "market_clock": market_clock(),
        "instruments": instruments,
        "trade_impact": "none",
    }


def _sparkline_points(closes: list[float], width: int = 100, height: int = 28) -> str:
    if not closes:
        return ""
    if len(closes) == 1:
        return f"0,{height / 2:.1f} {width},{height / 2:.1f}"
    low = min(closes)
    high = max(closes)
    span = high - low
    points = []
    for i, close in enumerate(closes):
        x = (i / (len(closes) - 1)) * width
        y = height / 2 if span == 0 else height - ((close - low) / span) * height
        points.append(f"{x:.1f},{y:.1f}")
    return " ".join(points)
