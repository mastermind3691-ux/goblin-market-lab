"""CLI: run shadow tracking in explicit historical or forward mode.

    python -m tools.run_shadow_tracking --mode historical-bootstrap
    python -m tools.run_shadow_tracking --mode forward

Historical bootstrap walks already-available bars and records
historical_bootstrap signals. Forward mode initializes a watermark on first run,
then records only signals from later completed bars as forward_observed.

Manual only: no scheduler, no dashboard polling, no orders.
"""

from __future__ import annotations

import argparse
import os

from src.data.csv_adapter import CsvAdapter
from src.instruments.registry import INSTRUMENTS
from src.paper.persistence import atomic_write_json, load_json
from src.paper.shadow_tracker import ShadowTracker, ORIGIN_HISTORICAL
from src.safety.gate import can_place_orders
from src.strategies.sma_dip import SmaDip
from src.strategies.trend_filter import TrendFilter

DATA_DIR = os.getenv("DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "data"))
SHADOW_PATH = os.getenv("SHADOW_STATE_PATH",
                         os.path.join(os.path.dirname(__file__), "..", "shadow_state.json"))

MODE_HISTORICAL = "historical-bootstrap"
MODE_FORWARD = "forward"


def _strategies():
    return [SmaDip(), TrendFilter()]


def _load_tracker() -> ShadowTracker:
    saved = load_json(SHADOW_PATH)
    return ShadowTracker.from_dict(saved) if saved else ShadowTracker()


def _available_bars(adapter: CsvAdapter) -> dict[str, list[dict]]:
    data = {}
    for symbol in INSTRUMENTS:
        try:
            bars = adapter.bars(symbol, limit=999_999)
        except FileNotFoundError:
            print(f"  {symbol}: no data, skipping")
            continue
        if bars:
            data[symbol] = bars
    return data


def run_historical_bootstrap() -> dict:
    adapter = CsvAdapter(DATA_DIR)
    tracker = _load_tracker()

    total_added = 0
    total_resolved = 0

    for symbol, bars in _available_bars(adapter).items():
        meta = adapter.meta(symbol)
        for strat in _strategies():
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
    summary["mode"] = MODE_HISTORICAL
    summary["added"] = total_added
    summary["resolved_now"] = total_resolved
    return summary


def run_forward_observation() -> dict:
    adapter = CsvAdapter(DATA_DIR)
    tracker = _load_tracker()
    bars_by_symbol = _available_bars(adapter)
    latest_by_symbol = {symbol: bars[-1]["ts"] for symbol, bars in bars_by_symbol.items()}

    if not tracker.forward_observation_started:
        tracker.initialize_forward_observation(latest_by_symbol)
        for symbol, bars in bars_by_symbol.items():
            tracker.resolve_outcomes(symbol, bars)
        atomic_write_json(SHADOW_PATH, tracker.to_dict())
        summary = tracker.summary()
        summary["path"] = SHADOW_PATH
        summary["mode"] = MODE_FORWARD
        summary["added"] = 0
        summary["resolved_now"] = 0
        return summary

    total_added = 0
    total_resolved = 0
    any_new_bar = False

    for symbol, bars in bars_by_symbol.items():
        meta = adapter.meta(symbol)
        observed_after = tracker.forward_observed_through.get(
            symbol,
            tracker.forward_started_after.get(symbol, ""),
        )
        latest = bars[-1]["ts"]
        if latest > observed_after:
            any_new_bar = True
            for strat in _strategies():
                total_added += tracker.observe_forward_bars(
                    strat, symbol, bars, observed_after,
                    warmup=100, data_source=meta.source, adjustment=meta.adjustment,
                )
            tracker.forward_observed_through[symbol] = latest

        resolved = tracker.resolve_outcomes(symbol, bars)
        total_resolved += resolved

    tracker.new_forward_records_last_run = total_added
    if any_new_bar and total_added:
        tracker.forward_last_message = f"Forward observation collected {total_added} new records."
    elif any_new_bar:
        tracker.forward_last_message = "New completed bars processed; no actionable BUY signals recorded."
    else:
        tracker.forward_last_message = "No new completed bars since last forward observation."

    atomic_write_json(SHADOW_PATH, tracker.to_dict())
    summary = tracker.summary()
    summary["path"] = SHADOW_PATH
    summary["mode"] = MODE_FORWARD
    summary["added"] = total_added
    summary["resolved_now"] = total_resolved
    return summary


def run_shadow_tracking(mode: str) -> dict:
    if mode == MODE_HISTORICAL:
        return run_historical_bootstrap()
    if mode == MODE_FORWARD:
        return run_forward_observation()
    raise ValueError(f"Unknown shadow mode: {mode}")


def _print_summary(s: dict) -> None:
    print(f"\nPersisted to {s['path']}")
    print(f"\n--- Shadow Summary ({s['mode']}) ---")
    print(f"  total records: {s['total']}")
    print(f"  historical bootstrap: {s['historical_bootstrap']}")
    print(f"  forward observed: {s['forward_observed']}")
    print(f"  forward observation started: {s['forward_observation_started']}")
    print(f"  forward started after: {s['forward_started_after']}")
    print(f"  forward observed through: {s['forward_observed_through']}")
    print(f"  new forward records last run: {s['new_forward_records_last_run']}")
    print(f"  pending: {s['pending']}")
    print(f"  resolved: {s['resolved']}")
    print(f"  resolved this run: {s['resolved_now']}")
    print(f"  historical sample size (5-bar): {s['historical_sample_size']}")
    print(f"  forward sample size (5-bar): {s['forward_sample_size']}")
    print(f"  enough forward data: {s['enough_forward_data']}")
    print(f"  verdict: {s['verdict']}")
    print(f"  forward message: {s['forward_message']}")
    print(f"  trade impact: {s['trade_impact']}")
    print(f"  paper portfolio impact: {s['paper_portfolio_impact']}")
    print(f"  can_place_orders: {can_place_orders()}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run shadow tracking.")
    parser.add_argument(
        "--mode",
        required=True,
        choices=[MODE_HISTORICAL, MODE_FORWARD],
        help="Use historical-bootstrap for backfill or forward for true forward observation.",
    )
    args = parser.parse_args()

    _print_summary(run_shadow_tracking(args.mode))


if __name__ == "__main__":
    main()
