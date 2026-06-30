"""Long-only hostile confirmation report for the frozen Sweep -> MSS candidate.

Research-only, not a trade strategy. The combined long+short confirmation
report found the aggregate result was side-dependent: longs were positive,
shorts were negative. This report isolates the long side as its own
candidate stats block, and reports the short side as a rejected diagnostic
only (not a candidate). It reuses the same frozen parameters and the same
stress helpers as run_smc_sweep_mss_confirmation.py. It does not tune
parameters and does not select a new winner beyond the long/short split
already observed.

    python tools/run_smc_sweep_mss_long_only_confirmation.py
    python tools/run_smc_sweep_mss_long_only_confirmation.py --symbol GLD --symbol QQQ
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from src.backtest.judge import judge_setup
from src.backtest.research_report import build_research_report
from src.data.timeframe_csv_adapter import TimeframeCsvAdapter
from src.instruments.registry import INSTRUMENTS
from tools.run_smc_sweep_mss_candidate_evaluation import generate_sweep_mss_setups
from tools.run_smc_sweep_mss_confirmation import (
    FROZEN_MSS_EXPIRATION_BARS,
    FROZEN_PIVOT_LEFT,
    FROZEN_PIVOT_RIGHT,
    FROZEN_TARGET_R,
    _conservative_r,
    _cost_stress,
    _ordinary_r,
    _outlier_removal,
    _permutation_test,
    _year_of,
    _year_stats,
)

DATA_DIR = os.getenv("DATA_DIR", os.path.join(REPO_ROOT, "data"))
REAL_DIR = os.path.join(DATA_DIR, "real")


def _side_block(symbol: str, bars: list[dict], setups, results) -> dict[str, Any]:
    report = build_research_report(symbol, "4H", bars, setups, results)
    return {
        "total_setups": report["total_setups"],
        "filled_setups": report["filled_setups"],
        "wins": report["wins"],
        "losses": report["losses"],
        "ambiguous_worst_case": report["ambiguous_worst_case"],
        "pending": report["pending"],
        "resolved_win_rate": report["resolved_win_rate"],
        "net_r": report["net_r"],
        "conservative_net_r": report["conservative_net_r"],
        "expectancy_r": report["expectancy_r"],
        "conservative_expectancy_r": report["conservative_expectancy_r"],
        "sample_status": report["sample_status"],
    }


def _overall_block(setups, results, total_bars: int) -> dict[str, Any]:
    dummy_bars = [{"open": 1, "high": 1, "low": 1, "close": 1}] * total_bars
    report = build_research_report("ALL", "4H", dummy_bars, setups, results)
    resolved = report["wins"] + report["losses"]
    return {
        "total_setups": report["total_setups"],
        "filled_setups": report["filled_setups"],
        "resolved_outcomes": resolved,
        "wins": report["wins"],
        "losses": report["losses"],
        "ambiguous_worst_case": report["ambiguous_worst_case"],
        "pending": report["pending"],
        "win_rate": report["resolved_win_rate"],
        "net_r": report["net_r"],
        "expectancy_r": report["expectancy_r"],
        "conservative_net_r": report["conservative_net_r"],
        "conservative_expectancy_r": report["conservative_expectancy_r"],
        "profit_factor_r": report["profit_factor_r"],
        "sample_status": report["sample_status"],
    }


def run_long_only_confirmation(
    symbols: list[str], adapter: TimeframeCsvAdapter,
) -> dict[str, Any]:
    symbol_bars: dict[str, list[dict]] = {}
    data_warnings: list[str] = []

    for symbol in symbols:
        selection = adapter.select(symbol, "4H", limit=999_999)
        if selection.effective_timeframe != "4H":
            data_warnings.append(f"{symbol}: no verified 4H data, skipped")
            continue
        symbol_bars[symbol] = selection.bars
        data_warnings.extend(selection.warnings)

    if not symbol_bars:
        return {
            "warnings": data_warnings + ["No symbols with verified 4H data."],
            "disclaimer": (
                "LONG-ONLY HOSTILE CONFIRMATION REPORT — research-only. "
                "Not a trade strategy. Not evidence."
            ),
        }

    long_all_setups, long_all_results = [], []
    short_all_setups, short_all_results = [], []
    per_symbol_long: dict[str, Any] = {}
    long_by_year: dict[str, list] = {}

    for symbol in sorted(symbol_bars):
        bars = symbol_bars[symbol]
        setups, _ = generate_sweep_mss_setups(
            bars, FROZEN_PIVOT_LEFT, FROZEN_PIVOT_RIGHT,
            FROZEN_MSS_EXPIRATION_BARS, FROZEN_TARGET_R,
        )
        results = [judge_setup(s, bars) for s in setups]

        long_pairs = [(s, r) for s, r in zip(setups, results) if s.side == "long"]
        short_pairs = [(s, r) for s, r in zip(setups, results) if s.side == "short"]
        long_setups = [s for s, _ in long_pairs]
        long_results = [r for _, r in long_pairs]
        short_setups = [s for s, _ in short_pairs]
        short_results = [r for _, r in short_pairs]

        per_symbol_long[symbol] = _side_block(symbol, bars, long_setups, long_results)

        for setup, result in zip(long_setups, long_results):
            year = _year_of(bars, setup)
            if year:
                long_by_year.setdefault(year, []).append(result)

        long_all_setups.extend(long_setups)
        long_all_results.extend(long_results)
        short_all_setups.extend(short_setups)
        short_all_results.extend(short_results)

    total_bars = sum(len(b) for b in symbol_bars.values())
    long_block = _overall_block(long_all_setups, long_all_results, total_bars)
    short_block = _overall_block(short_all_setups, short_all_results, total_bars)
    short_block["label"] = "DIAGNOSTIC_REJECTED_BY_SPLIT"

    long_ordinary = _ordinary_r(long_all_results)
    long_conservative = _conservative_r(long_all_results)

    outlier_removal = {
        "ordinary": _outlier_removal(long_ordinary),
        "conservative": _outlier_removal(long_conservative),
    }
    cost_stress = _cost_stress(long_ordinary)
    permutation = _permutation_test(long_ordinary)
    per_year = {y: _year_stats(long_by_year[y]) for y in sorted(long_by_year)}

    comparison = {
        "combined_net_r": long_block["net_r"] + short_block["net_r"],
        "long_only_net_r": long_block["net_r"],
        "short_only_net_r": short_block["net_r"],
        "note": (
            "The combined long+short candidate result is side-dependent: "
            "the long side carries the positive aggregate while the short "
            "side is negative on its own."
        ),
    }

    warnings = list(data_warnings)
    resolved_count = long_block["resolved_outcomes"]
    if resolved_count < 100:
        warnings.append(
            "WEAK_SAMPLE: fewer than 100 unambiguous resolved long outcomes "
            f"({resolved_count})."
        )
    if len(symbol_bars) > 1:
        warnings.append(
            "CORRELATION_WARNING: ETF symbols may be correlated; aggregated "
            "counts are not independent observations."
        )
    warnings.append(
        "PRICE_ADJUSTMENT_UNKNOWN: yfinance-derived 4H data adjustment status "
        "is unknown."
    )
    warnings.append(
        "MULTIPLE_COMPARISONS_RISK: this long-only fork was chosen after "
        "seeing the long/short split in the combined confirmation report; "
        "the result has not been pre-registered or validated on independent "
        "data."
    )
    warnings.append(
        "RESEARCH_ONLY: this is a hostile confirmation report, not evidence "
        "of a tradeable result."
    )

    return {
        "long_only_candidate": {
            "parameters": {
                "pivot_left": FROZEN_PIVOT_LEFT,
                "pivot_right": FROZEN_PIVOT_RIGHT,
                "mss_expiration_bars": FROZEN_MSS_EXPIRATION_BARS,
                "target_r": FROZEN_TARGET_R,
                "side": "long",
            },
            **long_block,
        },
        "short_only_diagnostic": short_block,
        "per_symbol_long_only": per_symbol_long,
        "per_year_long_only": per_year,
        "outlier_removal_long_only": outlier_removal,
        "cost_slippage_stress_long_only": cost_stress,
        "permutation_null_test_long_only": permutation,
        "comparison_to_combined": comparison,
        "symbols_evaluated": sorted(symbol_bars),
        "warnings": warnings,
        "disclaimer": (
            "LONG-ONLY HOSTILE CONFIRMATION REPORT — research-only stress "
            "test isolating the long side of one frozen exploratory "
            "candidate (pivot 5/2, MSS expiry 16, target 2R, no FVG). The "
            "short side is reported only as a rejected diagnostic. Not a "
            "trade strategy. Not evidence."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Long-only hostile confirmation report for the frozen Sweep -> "
            "MSS research candidate. Research-only stress test — not a "
            "trade strategy."
        ),
    )
    parser.add_argument(
        "--symbol", action="append", choices=sorted(INSTRUMENTS),
        help="symbol to evaluate; repeat as needed (default: all registered)",
    )
    args = parser.parse_args()

    adapter = TimeframeCsvAdapter(
        DATA_DIR, real_dir=REAL_DIR if os.path.isdir(REAL_DIR) else None,
    )
    symbols = args.symbol or sorted(INSTRUMENTS)
    result = run_long_only_confirmation(symbols, adapter)
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
