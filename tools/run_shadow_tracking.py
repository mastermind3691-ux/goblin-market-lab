"""CLI: run shadow tracking (historical bootstrap) for all instruments and strategies.

    python -m tools.run_shadow_tracking

Loads bar data, walks each strategy over completed bars, records BUY signals
into the shadow ledger as historical_bootstrap records, resolves pending
outcomes, persists, and prints a summary. These are historical replay records,
NOT true forward evidence.

Manual only — no scheduler, no dashboard polling, no orders.
"""

from __future__ import annotations

import os

from src.data.csv_adapter import CsvAdapter
from src.instruments.registry import INSTRUMENTS
from src.paper.persistence import atomic_write_json, load_json
from src.paper.shadow_tracker import ShadowTracker, ORIGIN_HISTORICAL
from src.strategies.sma_dip import SmaDip
from src.strategies.trend_filter import TrendFilter

DATA_DIR = os.getenv("DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "data"))
SHADOW_PATH = os.getenv("SHADOW_STATE_PATH",
                         os.path.join(os.path.dirname(__file__), "..", "shadow_state.json"))


def run_shadow_tracking() -> dict:
    adapter = CsvAdapter(DATA_DIR)
    strategies = [SmaDip(), TrendFilter()]

    saved = load_json(SHADOW_PATH)
    tracker = ShadowTracker.from_dict(saved) if saved else ShadowTracker()

    total_added = 0
    total_resolved = 0

    for symbol in INSTRUMENTS:
        try:
            bars = adapter.bars(symbol, limit=999_999)
        except FileNotFoundError:
            print(f"  {symbol}: no data, skipping")
            continue

        meta = adapter.meta(symbol)

        for strat in strategies:
            added = tracker.observe_bars(
                strat, symbol, bars, warmup=100,
                origin=ORIGIN_HISTORICAL,
                data_source=meta.source, adjustment=meta.adjustment,
            )
            total_added += added
            if added:
                print(f"  {strat.name} on {symbol}: {added} new signals (historical bootstrap)")

        resolved = tracker.resolve_outcomes(symbol, bars)
        total_resolved += resolved
        if resolved:
            print(f"  {symbol}: {resolved} outcomes resolved")

    atomic_write_json(SHADOW_PATH, tracker.to_dict())

    summary = tracker.summary()
    summary["path"] = SHADOW_PATH
    summary["added"] = total_added
    summary["resolved_now"] = total_resolved
    return summary


def main() -> None:
    s = run_shadow_tracking()
    print(f"\nPersisted to {s['path']}")

    print(f"\n--- Shadow Summary ---")
    print(f"  total records: {s['total']}")
    print(f"  historical bootstrap: {s['historical_bootstrap']}")
    print(f"  forward observed: {s['forward_observed']}")
    print(f"  pending: {s['pending']}")
    print(f"  resolved: {s['resolved']}")
    print(f"  historical sample size (5-bar): {s['historical_sample_size']}")
    print(f"  forward sample size (5-bar): {s['forward_sample_size']}")
    print(f"  hit rate (5-bar, all): {s['hit_rate_5bar']}")
    print(f"  avg return (5-bar, all): {s['avg_return_5bar']}")
    print(f"  avg return (20-bar, all): {s['avg_return_20bar']}")
    print(f"  enough forward data: {s['enough_data']}")
    print(f"  verdict: {s['verdict']}")
    print(f"  trade impact: {s['trade_impact']}")
    print(f"  paper portfolio impact: {s['paper_portfolio_impact']}")


if __name__ == "__main__":
    main()
