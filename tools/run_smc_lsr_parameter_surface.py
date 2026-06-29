"""Evaluate SMC LSR across a parameter grid and report the full surface.

Research-only.  Every cell is reported — the tool does not select or recommend
a winner.  Sorting by conservative expectancy is for inspection convenience
only.  This is exploratory, not evidence.

    python tools/run_smc_lsr_parameter_surface.py
    python tools/run_smc_lsr_parameter_surface.py --symbol GLD --symbol SPY
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from itertools import product
from typing import Any, Mapping, Sequence

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from src.backtest.judge import judge_setup
from src.backtest.research_report import build_research_report
from src.data.timeframe_csv_adapter import TimeframeCsvAdapter
from src.instruments.registry import INSTRUMENTS
from src.strategies.smc_liquidity_sweep_reversion import (
    CANDIDATE_NAME,
    SMCLiquiditySweepReversionConfig,
    generate_smc_liquidity_sweep_setups,
)


DATA_DIR = os.getenv("DATA_DIR", os.path.join(REPO_ROOT, "data"))
REAL_DIR = os.path.join(DATA_DIR, "real")

PIVOT_PAIRS = [(5, 2), (8, 3), (13, 5)]
TREND_FILTERS = ["off", "with_trend", "countertrend_only"]
ENTRY_MODES = ["near", "mid"]
MSS_EXPIRATION_VALUES = [8, 12, 16]
ORDER_EXPIRATION_VALUES = [8, 12]
TARGET_R_VALUES = [1.5, 2.0]

_TREND_FILTER_MAP = {
    "off": "disabled",
    "with_trend": "with_trend",
}

_UNSUPPORTED_TREND_FILTERS = {"countertrend_only"}


def build_parameter_grid() -> list[dict[str, Any]]:
    cells: list[dict[str, Any]] = []
    for (pl, pr), tf, em, mss, oe, tr in product(
        PIVOT_PAIRS, TREND_FILTERS, ENTRY_MODES,
        MSS_EXPIRATION_VALUES, ORDER_EXPIRATION_VALUES, TARGET_R_VALUES,
    ):
        cells.append({
            "pivot_left": pl,
            "pivot_right": pr,
            "trend_filter": tf,
            "entry_mode": em,
            "mss_expiration_bars": mss,
            "order_expiration_bars": oe,
            "target_r": tr,
        })
    return cells


def _rejection_labels(row: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    resolved = row["wins"] + row["losses"]
    if resolved < 30:
        labels.append("INSUFFICIENT_SAMPLE")
    elif resolved < 100:
        labels.append("WEAK_SAMPLE")
    if row["conservative_expectancy_r"] <= 0:
        labels.append("NEGATIVE_EXPECTANCY")
    if row["fill_rate"] < 0.30:
        labels.append("LOW_FILL_RATE")
    best1 = row["result_after_removing_best_trade"]
    best2 = row["result_after_removing_best_two_trades"]
    if row["net_r"] > 0 and (best1 < 0 or best2 < 0):
        labels.append("FRAGILE_OUTLIER")
    return labels


def evaluate_cell(
    params: dict[str, Any],
    symbol_bars: dict[str, list[dict]],
) -> dict[str, Any]:
    internal_tf = _TREND_FILTER_MAP.get(params["trend_filter"])
    if internal_tf is None:
        return {
            "parameters": params,
            "skipped": True,
            "skip_reason": (
                f"trend_filter '{params['trend_filter']}' is not supported "
                "by the frozen SMC config; would require strategy logic changes."
            ),
        }

    config = SMCLiquiditySweepReversionConfig(
        pivot_left=params["pivot_left"],
        pivot_right=params["pivot_right"],
        mss_expiration_bars=params["mss_expiration_bars"],
        order_expiration_bars=params["order_expiration_bars"],
        entry_mode=params["entry_mode"],
        target_r=params["target_r"],
        current_trend_filter=internal_tf,
    )

    per_symbol: dict[str, dict] = {}
    all_results = []
    all_setups = []
    total_bars = 0

    for symbol in sorted(symbol_bars):
        bars = symbol_bars[symbol]
        setups = generate_smc_liquidity_sweep_setups(bars, config)
        results = [judge_setup(s, bars) for s in setups]
        report = build_research_report(symbol, "4H", bars, setups, results)
        per_symbol[symbol] = {
            "bars_evaluated": report["bars_evaluated"],
            "total_setups": report["total_setups"],
            "filled_setups": report["filled_setups"],
            "fill_rate": report["fill_rate"],
            "wins": report["wins"],
            "losses": report["losses"],
            "no_fills": report["no_fills"],
            "ambiguous_worst_case": report["ambiguous_worst_case"],
            "pending": report["pending"],
            "net_r": report["net_r"],
            "conservative_net_r": report["conservative_net_r"],
            "expectancy_r": report["expectancy_r"],
            "conservative_expectancy_r": report["conservative_expectancy_r"],
            "sample_status": report["sample_status"],
        }
        all_results.extend(results)
        all_setups.extend(setups)
        total_bars += len(bars)

    agg = build_research_report("ALL", "4H", [{"open": 1, "high": 1, "low": 1, "close": 1}] * total_bars, all_setups, all_results)

    row: dict[str, Any] = {
        "parameters": params,
        "skipped": False,
        "total_setups": agg["total_setups"],
        "filled_setups": agg["filled_setups"],
        "fill_rate": agg["fill_rate"],
        "wins": agg["wins"],
        "losses": agg["losses"],
        "no_fills": agg["no_fills"],
        "ambiguous_worst_case": agg["ambiguous_worst_case"],
        "pending": agg["pending"],
        "resolved_outcomes": agg["wins"] + agg["losses"],
        "resolved_win_rate": agg["resolved_win_rate"],
        "conservative_win_rate": agg["conservative_win_rate"],
        "net_r": agg["net_r"],
        "conservative_net_r": agg["conservative_net_r"],
        "expectancy_r": agg["expectancy_r"],
        "conservative_expectancy_r": agg["conservative_expectancy_r"],
        "profit_factor_r": agg["profit_factor_r"],
        "result_after_removing_best_trade": agg["result_after_removing_best_trade"],
        "result_after_removing_best_two_trades": agg["result_after_removing_best_two_trades"],
        "sample_status": agg["sample_status"],
        "per_symbol": per_symbol,
    }
    row["rejection_labels"] = _rejection_labels(row)
    return row


def run_parameter_surface(
    symbols: list[str],
    adapter: TimeframeCsvAdapter,
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
            "cells": [],
            "grid_size": 0,
            "symbols_evaluated": [],
            "warnings": data_warnings + ["No symbols with verified 4H data."],
            "disclaimer": "EXPLORATORY ONLY — not research evidence.",
        }

    grid = build_parameter_grid()
    cells = [evaluate_cell(params, symbol_bars) for params in grid]

    evaluated = [c for c in cells if not c.get("skipped")]
    evaluated.sort(key=lambda c: c.get("conservative_expectancy_r", 0), reverse=True)
    skipped = [c for c in cells if c.get("skipped")]

    return {
        "cells": evaluated + skipped,
        "grid_size": len(grid),
        "evaluated_count": len(evaluated),
        "skipped_count": len(skipped),
        "symbols_evaluated": sorted(symbol_bars),
        "warnings": data_warnings,
        "disclaimer": "EXPLORATORY ONLY — not research evidence.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate SMC LSR parameter surface across real 4H ETF data. "
            "Research-only — reports full grid, does not select a winner."
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
    result = run_parameter_surface(symbols, adapter)
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
