"""Run the frozen SMC candidate through CSV bars and print JSON statistics.

    python -m tools.run_smc_lsr_evaluation
    python -m tools.run_smc_lsr_evaluation --symbol SPY --timeframe 1d
"""

from __future__ import annotations

import argparse
import json
import os
import sys


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from src.backtest.judge import judge_setup
from src.backtest.research_report import build_research_report
from src.data.timeframe_csv_adapter import TimeframeCsvAdapter, normalize_timeframe
from src.instruments.registry import INSTRUMENTS
from src.strategies.smc_liquidity_sweep_reversion import (
    CANDIDATE_NAME,
    SMCLiquiditySweepReversionConfig,
    generate_smc_liquidity_sweep_setups,
)


DATA_DIR = os.getenv("DATA_DIR", os.path.join(REPO_ROOT, "data"))
REAL_DIR = os.path.join(DATA_DIR, "real")
def evaluate_symbol(
    adapter: TimeframeCsvAdapter,
    symbol: str,
    timeframe: str = "1d",
) -> dict:
    requested_timeframe = timeframe
    selection = adapter.select(symbol, requested_timeframe, limit=999_999)
    bars = selection.bars
    setups = generate_smc_liquidity_sweep_setups(
        bars, SMCLiquiditySweepReversionConfig()
    )
    results = [judge_setup(setup, bars) for setup in setups]
    report = build_research_report(
        symbol, selection.effective_timeframe, bars, setups, results
    )
    meta = selection.meta
    report["strategy"] = CANDIDATE_NAME
    report["requested_timeframe"] = requested_timeframe
    report["effective_timeframe"] = selection.effective_timeframe
    report["data"] = {
        "source": meta.source,
        "synthetic": meta.synthetic,
        "adjustment": meta.adjustment,
    }
    if meta.synthetic:
        report["warnings"].append(
            "PIPELINE_VALIDATION_ONLY: synthetic data is not research evidence."
        )
    if meta.adjustment != "adjusted":
        report["warnings"].append(
            f"PRICE_ADJUSTMENT_{meta.adjustment.upper()}: returns may be distorted."
        )
    if normalize_timeframe(requested_timeframe) != selection.effective_timeframe:
        report["warnings"].append(
            "REQUESTED_TIMEFRAME_UNAVAILABLE: "
            f"requested {requested_timeframe}; evaluated available "
            f"{selection.effective_timeframe} CSV bars."
        )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate the frozen SMC research candidate.")
    parser.add_argument("--symbol", action="append", choices=sorted(INSTRUMENTS))
    parser.add_argument(
        "--timeframe",
        default="1d",
        help="requested timeframe; uses verified real 4H data when available",
    )
    args = parser.parse_args()

    adapter = TimeframeCsvAdapter(
        DATA_DIR, real_dir=REAL_DIR if os.path.isdir(REAL_DIR) else None
    )
    symbols = args.symbol or sorted(INSTRUMENTS)
    reports = [evaluate_symbol(adapter, symbol, args.timeframe) for symbol in symbols]
    print(json.dumps(reports, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
