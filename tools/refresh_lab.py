"""One-shot Railway Cron command: refresh data and forward shadow evidence.

    python -m tools.refresh_lab --symbols SPY GLD --start 2000-01-01

This is a scheduled data/evidence refresh only. It exits when complete, places
no trades, and starts no in-app scheduler.
"""

from __future__ import annotations

import argparse
import os
import sys

from src.safety.gate import can_place_orders
from tools.refresh_market_data import refresh_market_data
from tools.run_shadow_tracking import run_forward_observation


def refresh_lab(symbols: list[str], start: str) -> dict:
    real_data_dir = (os.getenv("REAL_DATA_DIR") or "").strip()
    if not real_data_dir:
        raise RuntimeError("REAL_DATA_DIR is required. Set REAL_DATA_DIR=/mnt/data/real.")
    shadow_state_path = (os.getenv("SHADOW_STATE_PATH") or "").strip()
    if not shadow_state_path:
        raise RuntimeError(
            "SHADOW_STATE_PATH is required. Set SHADOW_STATE_PATH=/mnt/data/shadow_state.json."
        )

    refresh = refresh_market_data(
        symbols, start,
        output_dir=real_data_dir,
        write_raw=False,
    )
    shadow = run_forward_observation(
        real_data_dir=real_data_dir,
        state_path=shadow_state_path,
    )

    return {
        "primary_source": refresh["primary_source"],
        "symbols_refreshed": refresh["symbols"],
        "source_used": refresh["source_used"],
        "fallback_source_used": refresh["fallback_source_used"],
        "fallback_reason": refresh["fallback_reason"],
        "latest_bar_date": refresh["latest_bar_date"],
        "latest_vendor_row_date": refresh["latest_vendor_row_date"],
        "excluded_vendor_rows": refresh["excluded_vendor_rows"],
        "output_dir": refresh["output_dir"],
        "shadow_state_path": shadow["path"],
        "forward_observation_started": shadow["forward_observation_started"],
        "forward_observed_through": shadow["forward_observed_through"],
        "new_forward_records_last_run": shadow["new_forward_records_last_run"],
        "forward_sample_size": shadow["forward_sample_size"],
        "can_place_orders": can_place_orders(),
    }


def print_summary(summary: dict) -> None:
    print("Refresh Lab complete.")
    print(f"  primary source: {summary['primary_source']}")
    print(f"  symbols refreshed: {', '.join(summary['symbols_refreshed'])}")
    print(f"  source used: {summary['source_used']}")
    if summary["fallback_reason"]:
        print(f"  fallback source used: {summary['fallback_source_used']}")
        print(f"  fallback reason: {summary['fallback_reason']}")
    print(f"  latest accepted bar dates: {summary['latest_bar_date']}")
    print(f"  latest vendor row dates: {summary['latest_vendor_row_date']}")
    for excluded in summary["excluded_vendor_rows"]:
        print(
            f"  excluded vendor row: {excluded['symbol']} {excluded['date']} "
            f"{excluded['reason']}"
        )
    print(f"  output dir: {summary['output_dir']}")
    print(f"  forward_observation_started: {summary['forward_observation_started']}")
    print(f"  forward_observed_through: {summary['forward_observed_through']}")
    print(f"  new_forward_records_last_run: {summary['new_forward_records_last_run']}")
    print(f"  forward_sample_size: {summary['forward_sample_size']}")
    print(f"  can_place_orders: {summary['can_place_orders']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh market data and forward evidence once.")
    parser.add_argument("--symbols", nargs="+", required=True, help="Symbols to refresh")
    parser.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    args = parser.parse_args()

    try:
        print_summary(refresh_lab(args.symbols, args.start))
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
