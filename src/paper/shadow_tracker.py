"""Shadow / paper-forward tracker.

Records what a strategy WOULD signal on each completed bar and the outcome a
few bars later. It never executes anything, never feeds a real order, and never
mutates a portfolio.

Two record origins are distinguished honestly:

- ``historical_bootstrap``: created by walking already-available historical data.
  Useful for pipeline validation and baseline measurement, but NOT true
  out-of-sample forward evidence.
- ``forward_observed``: reserved for signals observed on newly arrived bars
  after forward observation has been initialized.

No portfolio, no compounding, no order simulation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..strategies.base import Signal, Strategy

HORIZONS = (5, 20)
MIN_SHADOW_SAMPLES = 20

ORIGIN_HISTORICAL = "historical_bootstrap"
ORIGIN_FORWARD = "forward_observed"


@dataclass
class ShadowRecord:
    key: str
    strategy: str
    instrument: str
    signal_date: str
    signal_type: str
    entry_price: float
    origin: str = ORIGIN_HISTORICAL
    data_source: str = ""
    adjustment: str = "unknown"
    outcomes: dict[str, Any] = field(default_factory=dict)

    def is_fully_resolved(self) -> bool:
        return all(f"h{h}" in self.outcomes for h in HORIZONS)

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "strategy": self.strategy,
            "instrument": self.instrument,
            "signal_date": self.signal_date,
            "signal_type": self.signal_type,
            "entry_price": self.entry_price,
            "origin": self.origin,
            "data_source": self.data_source,
            "adjustment": self.adjustment,
            "outcomes": dict(self.outcomes),
        }

    @classmethod
    def from_dict(cls, d: dict) -> ShadowRecord:
        return cls(
            key=d["key"],
            strategy=d["strategy"],
            instrument=d["instrument"],
            signal_date=d["signal_date"],
            signal_type=d["signal_type"],
            entry_price=d["entry_price"],
            origin=d.get("origin", ORIGIN_HISTORICAL),
            data_source=d.get("data_source", ""),
            adjustment=d.get("adjustment", "unknown"),
            outcomes=dict(d.get("outcomes", {})),
        )


def _make_key(strategy: str, instrument: str, ts: str) -> str:
    return f"{strategy}:{instrument}:{ts}"


@dataclass
class ShadowTracker:
    records: list[ShadowRecord] = field(default_factory=list)
    forward_observation_started: bool = False
    forward_started_after: dict[str, str] = field(default_factory=dict)
    forward_observed_through: dict[str, str] = field(default_factory=dict)
    new_forward_records_last_run: int = 0
    forward_last_message: str = "Forward observation not started"
    _index: dict[str, int] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self._rebuild_index()

    def _rebuild_index(self) -> None:
        self._index = {r.key: i for i, r in enumerate(self.records)}

    def observe(self, strategy: str, instrument: str, ts: str,
                signal: str, price: float,
                origin: str = ORIGIN_HISTORICAL,
                data_source: str = "", adjustment: str = "unknown") -> bool:
        key = _make_key(strategy, instrument, ts)
        if key in self._index:
            return False
        rec = ShadowRecord(
            key=key,
            strategy=strategy,
            instrument=instrument,
            signal_date=ts,
            signal_type=signal,
            entry_price=price,
            origin=origin,
            data_source=data_source,
            adjustment=adjustment,
        )
        self._index[key] = len(self.records)
        self.records.append(rec)
        return True

    def observe_bars(self, strat: Strategy, instrument: str,
                     bars: list[dict], warmup: int = 100,
                     origin: str = ORIGIN_HISTORICAL,
                     data_source: str = "", adjustment: str = "unknown") -> int:
        """Walk bars and record BUY signals. No look-ahead."""
        added = 0
        position_open = False
        for i in range(warmup, len(bars)):
            window = bars[:i + 1]
            sig = strat.signal(window, position_open)
            if sig is Signal.BUY and not position_open:
                ts = window[-1]["ts"]
                price = window[-1]["close"]
                if self.observe(strat.name, instrument, ts, "BUY", price,
                                origin, data_source, adjustment):
                    added += 1
                position_open = True
            elif sig is Signal.SELL and position_open:
                position_open = False
        return added

    def initialize_forward_observation(self, latest_by_symbol: dict[str, str]) -> None:
        """Start forward mode at current latest bars without backfilling."""
        self.forward_observation_started = True
        self.forward_started_after = dict(latest_by_symbol)
        self.forward_observed_through = dict(latest_by_symbol)
        self.new_forward_records_last_run = 0
        self.forward_last_message = "Forward observation initialized - waiting for next completed bar."

    def observe_forward_bars(self, strat: Strategy, instrument: str,
                             bars: list[dict], observed_after: str,
                             warmup: int = 100,
                             data_source: str = "",
                             adjustment: str = "unknown") -> int:
        """Replay state and record each strategy output after the watermark."""
        added = 0
        position_open = False
        for i in range(warmup, len(bars)):
            window = bars[:i + 1]
            sig = strat.signal(window, position_open)
            ts = window[-1]["ts"]
            if ts > observed_after:
                price = window[-1]["close"]
                if self.observe(strat.name, instrument, ts, sig.name, price,
                                ORIGIN_FORWARD, data_source, adjustment):
                    added += 1
            if sig is Signal.BUY and not position_open:
                position_open = True
            elif sig is Signal.SELL and position_open:
                position_open = False
        return added

    def resolve_outcomes(self, instrument: str, bars: list[dict]) -> int:
        """Resolve pending outcomes for records matching this instrument."""
        ts_to_idx = {b["ts"]: i for i, b in enumerate(bars)}

        resolved = 0
        for rec in self.records:
            if rec.instrument != instrument:
                continue
            if rec.is_fully_resolved():
                continue
            bar_idx = ts_to_idx.get(rec.signal_date)
            if bar_idx is None:
                continue
            for h in HORIZONS:
                h_key = f"h{h}"
                if h_key in rec.outcomes:
                    continue
                future_idx = bar_idx + h
                if future_idx < len(bars):
                    future_close = bars[future_idx]["close"]
                    ret = (future_close / rec.entry_price) - 1.0 if rec.entry_price else 0.0
                    rec.outcomes[h_key] = {
                        "horizon": h,
                        "future_date": bars[future_idx]["ts"],
                        "future_close": future_close,
                        "return_pct": round(ret, 6),
                    }
                    resolved += 1
        return resolved

    def summary(self) -> dict:
        total = len(self.records)
        resolved = sum(1 for r in self.records if r.is_fully_resolved())
        pending = total - resolved

        n_historical = sum(1 for r in self.records if r.origin == ORIGIN_HISTORICAL)
        n_forward = sum(1 for r in self.records if r.origin == ORIGIN_FORWARD)

        def _h_returns(origin_filter: str | None) -> dict[str, list[float]]:
            h_ret: dict[str, list[float]] = {f"h{h}": [] for h in HORIZONS}
            for rec in self.records:
                if origin_filter and rec.origin != origin_filter:
                    continue
                if rec.signal_type != "BUY":
                    continue
                for h in HORIZONS:
                    h_key = f"h{h}"
                    if h_key in rec.outcomes:
                        h_ret[h_key].append(rec.outcomes[h_key]["return_pct"])
            return h_ret

        all_h = _h_returns(None)
        fwd_h = _h_returns(ORIGIN_FORWARD)
        hist_h = _h_returns(ORIGIN_HISTORICAL)

        fwd_h5 = fwd_h["h5"]
        hist_h5 = hist_h["h5"]
        all_h5 = all_h["h5"]
        all_h20 = all_h["h20"]

        forward_enough = n_forward >= MIN_SHADOW_SAMPLES and len(fwd_h5) >= MIN_SHADOW_SAMPLES

        hit_rate = round(sum(1 for r in all_h5 if r > 0) / len(all_h5), 4) if all_h5 else None
        avg_h5 = round(sum(all_h5) / len(all_h5), 6) if all_h5 else None
        avg_h20 = round(sum(all_h20) / len(all_h20), 6) if all_h20 else None

        if n_forward == 0:
            if self.forward_observation_started:
                verdict = "Forward observation initialized - waiting for next completed bar"
            else:
                verdict = "Historical shadow replay available - forward evidence not started"
        elif not forward_enough:
            verdict = "Forward shadow evidence collecting - not enough data"
        else:
            verdict = "Forward shadow evidence available - review only"

        return {
            "total": total,
            "historical_bootstrap": n_historical,
            "forward_observed": n_forward,
            "forward_observation_started": self.forward_observation_started,
            "forward_started_after": dict(self.forward_started_after),
            "forward_observed_through": dict(self.forward_observed_through),
            "new_forward_records_last_run": self.new_forward_records_last_run,
            "pending": pending,
            "resolved": resolved,
            "historical_sample_size": len(hist_h5),
            "forward_sample_size": len(fwd_h5),
            "hit_rate_5bar": hit_rate,
            "avg_return_5bar": avg_h5,
            "avg_return_20bar": avg_h20,
            "enough_data": forward_enough,
            "enough_forward_data": forward_enough,
            "verdict": verdict,
            "forward_message": self.forward_last_message,
            "trade_impact": "none",
            "paper_portfolio_impact": "none",
            "required_human_approval": True,
            "ready_for_pilot": False,
        }

    def to_dict(self) -> dict:
        return {
            "records": [r.to_dict() for r in self.records],
            "forward_observation_started": self.forward_observation_started,
            "forward_started_after": dict(self.forward_started_after),
            "forward_observed_through": dict(self.forward_observed_through),
            "new_forward_records_last_run": self.new_forward_records_last_run,
            "forward_last_message": self.forward_last_message,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ShadowTracker:
        t = cls()
        t.records = [ShadowRecord.from_dict(d) for d in data.get("records", [])]
        t.forward_observation_started = bool(data.get("forward_observation_started", False))
        t.forward_started_after = dict(data.get("forward_started_after", {}))
        t.forward_observed_through = dict(data.get("forward_observed_through", {}))
        t.new_forward_records_last_run = int(data.get("new_forward_records_last_run", 0))
        t.forward_last_message = data.get("forward_last_message", "Forward observation not started")
        t._rebuild_index()
        return t
