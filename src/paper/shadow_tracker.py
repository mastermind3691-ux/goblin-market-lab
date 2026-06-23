"""Shadow / paper-forward tracker.

Records what a strategy WOULD do on each new completed bar, going forward, and
the outcome a few bars later. It never executes anything and never feeds a real
order. This is how you collect forward (out-of-sample) evidence to compare
against the backtest — the honest counterweight to curve-fitting.

For v0.1 this is a thin, persistable record. Wire it to a scheduled bar-close
job once the backtest loop is trusted.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ShadowTracker:
    records: list[dict] = field(default_factory=list)

    def observe(self, strategy: str, instrument: str, ts: str, signal: str, price: float) -> None:
        self.records.append({
            "strategy": strategy, "instrument": instrument,
            "ts": ts, "signal": signal, "price": price, "outcome": None,
        })

    def to_dict(self) -> dict:
        return {"records": list(self.records)}

    @classmethod
    def from_dict(cls, data: dict) -> "ShadowTracker":
        t = cls()
        t.records = list(data.get("records", []))
        return t
