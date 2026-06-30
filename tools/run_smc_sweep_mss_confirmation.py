"""Hostile confirmation report for one frozen Sweep -> MSS research candidate.

This is a research-only stress report, not a trade strategy and not a new
parameter search. It re-runs the single exploratory candidate already
identified by run_smc_sweep_mss_candidate_evaluation.py (pivot 5/2, MSS
expiry 16, target 2R, no FVG) and tries to break it: per-symbol splits,
long/short splits, per-year splits, outlier removal, flat cost penalties,
and a seeded permutation null test. It does not select a new winner and
does not change the frozen parameters.

    python tools/run_smc_sweep_mss_confirmation.py
    python tools/run_smc_sweep_mss_confirmation.py --symbol GLD --symbol QQQ
"""

from __future__ import annotations

import argparse
import json
import os
import random
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

DATA_DIR = os.getenv("DATA_DIR", os.path.join(REPO_ROOT, "data"))
REAL_DIR = os.path.join(DATA_DIR, "real")

# Frozen candidate under confirmation. Do not tune.
FROZEN_PIVOT_LEFT = 5
FROZEN_PIVOT_RIGHT = 2
FROZEN_MSS_EXPIRATION_BARS = 16
FROZEN_TARGET_R = 2.0

COST_PENALTIES_R = [0.05, 0.10, 0.20]
PERMUTATION_TRIALS = 2000
PERMUTATION_SEED = 1337


def _ordinary_r(results) -> list[float]:
    return [
        float(r.r_result) for r in results
        if r.status in {"WIN", "LOSS"} and r.r_result is not None
    ]


def _conservative_r(results) -> list[float]:
    ambiguous = sum(1 for r in results if r.status == "AMBIGUOUS_WORST_CASE")
    return _ordinary_r(results) + [-1.0] * ambiguous


def _remove_best_n(values: list[float], n: int) -> float:
    remaining = sorted(values, reverse=True)[n:]
    return sum(remaining)


def _outlier_removal(values: list[float]) -> dict[str, Any]:
    net = sum(values)
    after1 = _remove_best_n(values, 1)
    after2 = _remove_best_n(values, 2)
    after3 = _remove_best_n(values, 3)
    fragile = net > 0 and (after1 < 0 or after2 < 0 or after3 < 0)
    return {
        "net_r": net,
        "result_after_removing_best_1": after1,
        "result_after_removing_best_2": after2,
        "result_after_removing_best_3": after3,
        "fragile_outlier": fragile,
    }


def _cost_stress(values: list[float]) -> list[dict[str, Any]]:
    n = len(values)
    rows = []
    for penalty in COST_PENALTIES_R:
        adjusted_net = sum(values) - penalty * n
        rows.append({
            "penalty_r_per_trade": penalty,
            "adjusted_net_r": adjusted_net,
            "remains_positive": adjusted_net > 0,
        })
    return rows


def _permutation_test(values: list[float]) -> dict[str, Any]:
    """Seeded sign-shuffle null test: compare actual net R to a null
    distribution built by randomizing the sign of each resolved R outcome.

    This tests whether the observed net R could plausibly arise from a
    direction-agnostic process with the same magnitude of outcomes. It is
    a diagnostic, not a formal significance claim.
    """
    if len(values) < 2:
        return {
            "implemented": False,
            "reason": "fewer than 2 resolved outcomes; permutation test skipped.",
        }

    actual_net_r = sum(values)
    magnitudes = [abs(v) for v in values]
    rng = random.Random(PERMUTATION_SEED)
    null_nets = []
    for _ in range(PERMUTATION_TRIALS):
        signs = [rng.choice((-1.0, 1.0)) for _ in magnitudes]
        null_nets.append(sum(m * s for m, s in zip(magnitudes, signs)))

    at_or_above = sum(1 for n in null_nets if n >= actual_net_r)
    percentile = 1.0 - (at_or_above / PERMUTATION_TRIALS)

    return {
        "implemented": True,
        "trials": PERMUTATION_TRIALS,
        "seed": PERMUTATION_SEED,
        "actual_net_r": actual_net_r,
        "null_mean_net_r": sum(null_nets) / len(null_nets),
        "percentile_of_actual": percentile,
        "p_value_like_upper_tail": at_or_above / PERMUTATION_TRIALS,
        "note": (
            "Diagnostic only: fraction of sign-shuffled null trials whose net R "
            "matched or exceeded the actual net R. Not a formal hypothesis test."
        ),
    }


def _year_of(bars, setup) -> str | None:
    if not (0 <= setup.created_i < len(bars)):
        return None
    ts = (bars[setup.created_i].get("ts") or bars[setup.created_i].get("timestamp")
          or bars[setup.created_i].get("date"))
    if not ts:
        return None
    year = str(ts)[:4]
    return year if len(year) == 4 and year.isdigit() else None


def _year_stats(results) -> dict[str, Any]:
    ordinary = _ordinary_r(results)
    conservative = _conservative_r(results)
    wins = sum(1 for r in results if r.status == "WIN")
    losses = sum(1 for r in results if r.status == "LOSS")
    resolved = wins + losses
    return {
        "total_setups": len(results),
        "wins": wins,
        "losses": losses,
        "resolved_outcomes": resolved,
        "win_rate": wins / resolved if resolved else 0.0,
        "net_r": sum(ordinary),
        "conservative_net_r": sum(conservative),
        "expectancy_r": sum(ordinary) / len(ordinary) if ordinary else 0.0,
        "conservative_expectancy_r": (
            sum(conservative) / len(conservative) if conservative else 0.0
        ),
    }


def _side_split(setups, results, side: str) -> dict[str, Any]:
    paired = [(s, r) for s, r in zip(setups, results) if s.side == side]
    sub_results = [r for _, r in paired]
    ordinary = _ordinary_r(sub_results)
    conservative = _conservative_r(sub_results)
    wins = sum(1 for r in sub_results if r.status == "WIN")
    losses = sum(1 for r in sub_results if r.status == "LOSS")
    resolved = wins + losses
    return {
        "count": len(paired),
        "wins": wins,
        "losses": losses,
        "resolved_outcomes": resolved,
        "win_rate": wins / resolved if resolved else 0.0,
        "net_r": sum(ordinary),
        "conservative_net_r": sum(conservative),
        "expectancy_r": sum(ordinary) / len(ordinary) if ordinary else 0.0,
        "conservative_expectancy_r": (
            sum(conservative) / len(conservative) if conservative else 0.0
        ),
    }


def run_confirmation(symbols: list[str], adapter: TimeframeCsvAdapter) -> dict[str, Any]:
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
                "HOSTILE CONFIRMATION REPORT — research-only stress test of one "
                "frozen exploratory candidate. Not a trade strategy. Not evidence."
            ),
        }

    all_setups = []
    all_results = []
    per_symbol: dict[str, Any] = {}
    by_year: dict[str, list] = {}

    for symbol in sorted(symbol_bars):
        bars = symbol_bars[symbol]
        setups, total_sweeps = generate_sweep_mss_setups(
            bars, FROZEN_PIVOT_LEFT, FROZEN_PIVOT_RIGHT,
            FROZEN_MSS_EXPIRATION_BARS, FROZEN_TARGET_R,
        )
        results = [judge_setup(s, bars) for s in setups]
        for setup, result in zip(setups, results):
            year = _year_of(bars, setup)
            if year:
                by_year.setdefault(year, []).append(result)
        report = build_research_report(symbol, "4H", bars, setups, results)
        per_symbol[symbol] = {
            "total_sweeps": total_sweeps,
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
        all_setups.extend(setups)
        all_results.extend(results)

    total_bars = sum(len(b) for b in symbol_bars.values())
    dummy_bars = [{"open": 1, "high": 1, "low": 1, "close": 1}] * total_bars
    overall = build_research_report("ALL", "4H", dummy_bars, all_setups, all_results)

    ordinary = _ordinary_r(all_results)
    conservative = _conservative_r(all_results)
    resolved_count = overall["wins"] + overall["losses"]

    overall_report = {
        "parameters": {
            "pivot_left": FROZEN_PIVOT_LEFT,
            "pivot_right": FROZEN_PIVOT_RIGHT,
            "mss_expiration_bars": FROZEN_MSS_EXPIRATION_BARS,
            "target_r": FROZEN_TARGET_R,
        },
        "total_setups": overall["total_setups"],
        "filled_setups": overall["filled_setups"],
        "resolved_outcomes": resolved_count,
        "wins": overall["wins"],
        "losses": overall["losses"],
        "ambiguous_worst_case": overall["ambiguous_worst_case"],
        "pending": overall["pending"],
        "win_rate": overall["resolved_win_rate"],
        "net_r": overall["net_r"],
        "expectancy_r": overall["expectancy_r"],
        "conservative_net_r": overall["conservative_net_r"],
        "conservative_expectancy_r": overall["conservative_expectancy_r"],
        "profit_factor_r": overall["profit_factor_r"],
        "sample_status": overall["sample_status"],
    }

    by_side = {
        "long": _side_split(all_setups, all_results, "long"),
        "short": _side_split(all_setups, all_results, "short"),
    }

    outlier_ordinary = _outlier_removal(ordinary)
    outlier_conservative = _outlier_removal(conservative)

    cost_stress = _cost_stress(ordinary)

    permutation = _permutation_test(ordinary)

    warnings = list(data_warnings)
    if resolved_count < 100:
        warnings.append(
            "WEAK_SAMPLE: fewer than 100 unambiguous resolved outcomes "
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
        "MULTIPLE_COMPARISONS_RISK: this candidate was selected after scanning "
        "a 27-cell parameter grid; the result has not been pre-registered or "
        "validated on independent data."
    )
    warnings.append(
        "RESEARCH_ONLY: this is a hostile confirmation report, not evidence "
        "of a tradeable result."
    )

    return {
        "frozen_candidate": overall_report,
        "per_symbol": per_symbol,
        "by_side": by_side,
        "per_year": {year: _year_stats(by_year[year]) for year in sorted(by_year)},
        "outlier_removal": {
            "ordinary": outlier_ordinary,
            "conservative": outlier_conservative,
        },
        "cost_slippage_stress": cost_stress,
        "permutation_null_test": permutation,
        "symbols_evaluated": sorted(symbol_bars),
        "warnings": warnings,
        "disclaimer": (
            "HOSTILE CONFIRMATION REPORT — research-only stress test of one "
            "frozen exploratory candidate (pivot 5/2, MSS expiry 16, target 2R, "
            "no FVG). Does not select a new winner. Not a trade strategy. "
            "Not evidence."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Hostile confirmation report for one frozen Sweep -> MSS research "
            "candidate. Research-only stress test — not a trade strategy, "
            "does not select a new winner."
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
    result = run_confirmation(symbols, adapter)
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
