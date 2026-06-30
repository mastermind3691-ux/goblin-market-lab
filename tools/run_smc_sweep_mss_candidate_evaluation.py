"""Research candidate evaluation: Sweep -> MSS with simulated Judge mechanics.

This is a research candidate evaluation, not a trade strategy.  It tests
whether a simulated Sweep -> MSS setup (no FVG requirement) survives
Judge-style stop/target mechanics.  Entry is simulated as a next-bar
market-style fill: the setup's entry level is set to the next bar's open,
which the Judge's existing limit-touch logic always fills immediately
because a bar's low/high always contains its own open.  No real broker,
order, or execution code is involved; nothing here recommends or promotes
a strategy.

    python tools/run_smc_sweep_mss_candidate_evaluation.py
    python tools/run_smc_sweep_mss_candidate_evaluation.py --symbol GLD --symbol QQQ
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from math import isfinite
from typing import Any, Mapping, Sequence

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from src.backtest.judge import JudgeResult, SetupEvent, judge_setup
from src.backtest.research_report import build_research_report
from src.data.timeframe_csv_adapter import TimeframeCsvAdapter
from src.instruments.registry import INSTRUMENTS

DATA_DIR = os.getenv("DATA_DIR", os.path.join(REPO_ROOT, "data"))
REAL_DIR = os.path.join(DATA_DIR, "real")

CANDIDATE_NAME = "smc_sweep_mss_research_candidate"

PIVOT_PAIRS = [(5, 2), (8, 3), (13, 5)]
MSS_EXPIRATION_VALUES = [8, 12, 16]
TARGET_R_VALUES = [1.0, 1.5, 2.0]


@dataclass(frozen=True)
class Pivot:
    index: int
    level: float
    confirmed_i: int

    @property
    def usable_i(self) -> int:
        return self.confirmed_i + 1


@dataclass(frozen=True)
class _ActiveSweep:
    direction: str  # "bearish" or "bullish"
    sweep_i: int
    sweep_extreme: float  # high at sweep bar (bearish) / low at sweep bar (bullish)
    frozen_mss_level: float
    swept_level: float


def _validate_bars(bars: Sequence[Mapping[str, Any]]) -> None:
    required = ("open", "high", "low", "close")
    for i, bar in enumerate(bars):
        try:
            values = {k: float(bar[k]) for k in required}
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"bar {i} must contain numeric OHLC values") from exc
        if not all(isfinite(v) and v > 0 for v in values.values()):
            raise ValueError(f"bar {i} OHLC values must be positive and finite")


def _confirmed_pivots(
    bars: Sequence[Mapping[str, Any]],
    pivot_i: int,
    confirmed_i: int,
    pivot_left: int,
    pivot_right: int,
) -> tuple[Pivot | None, Pivot | None]:
    start = pivot_i - pivot_left
    end = pivot_i + pivot_right
    candidate_high = float(bars[pivot_i]["high"])
    candidate_low = float(bars[pivot_i]["low"])
    others = [j for j in range(start, end + 1) if j != pivot_i]
    high = None
    low = None
    if all(candidate_high > float(bars[j]["high"]) for j in others):
        high = Pivot(pivot_i, candidate_high, confirmed_i)
    if all(candidate_low < float(bars[j]["low"]) for j in others):
        low = Pivot(pivot_i, candidate_low, confirmed_i)
    return high, low


def _build_setup(
    bars: Sequence[Mapping[str, Any]],
    mss_i: int,
    active: _ActiveSweep,
    target_r: float,
    last_i: int,
) -> SetupEvent | None:
    """Build a simulated next-bar market-style setup from a confirmed MSS.

    Entry uses the next bar's open as a simulated market-style fill level;
    documented here because Judge itself only understands limit-touch entries.
    Since a bar's open always lies within its own [low, high], Judge will
    always fill this setup on the very next bar, which simulates immediate
    market entry without changing Judge logic.
    """
    created_i = mss_i
    valid_from_i = created_i + 1
    if valid_from_i > last_i:
        return None

    next_bar = bars[valid_from_i]
    entry = float(next_bar["open"])

    if active.direction == "bullish":
        side = "long"
        invalidation = active.sweep_extreme
    else:
        side = "short"
        invalidation = active.sweep_extreme

    risk = abs(entry - invalidation)
    if risk == 0:
        return None
    if side == "long" and invalidation >= entry:
        return None
    if side == "short" and invalidation <= entry:
        return None

    target = entry + risk * target_r if side == "long" else entry - risk * target_r

    metadata = {
        "candidate": CANDIDATE_NAME,
        "diagnostic_only": True,
        "sweep_i": active.sweep_i,
        "sweep_side": active.direction,
        "mss_bar_i": mss_i,
        "swept_level": active.swept_level,
        "frozen_mss_level": active.frozen_mss_level,
        "target_r": target_r,
        "entry_mode": "next_bar_open_market_style",
    }

    return SetupEvent(
        side=side,
        created_i=created_i,
        valid_from_i=valid_from_i,
        entry=entry,
        invalidation=invalidation,
        target=target,
        expires_i=valid_from_i,
        metadata=metadata,
    )


def generate_sweep_mss_setups(
    bars: Sequence[Mapping[str, Any]],
    pivot_left: int,
    pivot_right: int,
    mss_expiration_bars: int,
    target_r: float,
) -> tuple[list[SetupEvent], int]:
    """Return (setups, total_sweeps_detected) from oldest-first completed bars."""
    _validate_bars(bars)
    setups: list[SetupEvent] = []
    known_high: Pivot | None = None
    known_low: Pivot | None = None
    active: _ActiveSweep | None = None
    total_sweeps = 0
    last_i = len(bars) - 1

    for i, bar in enumerate(bars):
        close = float(bar["close"])
        high = float(bar["high"])
        low = float(bar["low"])

        if active is not None:
            age = i - active.sweep_i
            if age > mss_expiration_bars:
                active = None
            elif age >= 1:
                mss_hit = False
                if active.direction == "bearish" and close < active.frozen_mss_level:
                    mss_hit = True
                elif active.direction == "bullish" and close > active.frozen_mss_level:
                    mss_hit = True

                if mss_hit:
                    setup = _build_setup(bars, i, active, target_r, last_i)
                    if setup is not None:
                        setups.append(setup)
                    active = None
                    pivot_i = i - pivot_right
                    if pivot_i >= pivot_left:
                        ch, cl = _confirmed_pivots(
                            bars, pivot_i, i, pivot_left, pivot_right,
                        )
                        if ch is not None:
                            known_high = ch
                        if cl is not None:
                            known_low = cl
                    continue

        if active is None:
            bearish = (
                known_high is not None
                and high > known_high.level
                and close < known_high.level
            )
            bullish = (
                known_low is not None
                and low < known_low.level
                and close > known_low.level
            )

            if bearish or bullish:
                total_sweeps += 1
                ambiguous = bearish and bullish
                if not ambiguous:
                    if bearish and known_low is not None:
                        active = _ActiveSweep(
                            direction="bearish",
                            sweep_i=i,
                            sweep_extreme=high,
                            frozen_mss_level=known_low.level,
                            swept_level=known_high.level,
                        )
                    elif bullish and known_high is not None:
                        active = _ActiveSweep(
                            direction="bullish",
                            sweep_i=i,
                            sweep_extreme=low,
                            frozen_mss_level=known_high.level,
                            swept_level=known_low.level,
                        )

        pivot_i = i - pivot_right
        if pivot_i >= pivot_left:
            ch, cl = _confirmed_pivots(bars, pivot_i, i, pivot_left, pivot_right)
            if ch is not None:
                known_high = ch
            if cl is not None:
                known_low = cl

    return setups, total_sweeps


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
    pivot_left: int,
    pivot_right: int,
    mss_expiration_bars: int,
    target_r: float,
    symbol_bars: dict[str, list[dict]],
) -> dict[str, Any]:
    per_symbol: dict[str, dict] = {}
    all_setups: list[SetupEvent] = []
    all_results: list[JudgeResult] = []
    total_sweeps_all = 0

    for symbol in sorted(symbol_bars):
        bars = symbol_bars[symbol]
        setups, total_sweeps = generate_sweep_mss_setups(
            bars, pivot_left, pivot_right, mss_expiration_bars, target_r,
        )
        results = [judge_setup(s, bars) for s in setups]
        report = build_research_report(symbol, "4H", bars, setups, results)
        per_symbol[symbol] = {
            "total_sweeps": total_sweeps,
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
        all_setups.extend(setups)
        all_results.extend(results)
        total_sweeps_all += total_sweeps

    total_bars = sum(len(bars) for bars in symbol_bars.values())
    dummy_bars = [{"open": 1, "high": 1, "low": 1, "close": 1}] * total_bars
    agg = build_research_report("ALL", "4H", dummy_bars, all_setups, all_results)

    row: dict[str, Any] = {
        "parameters": {
            "pivot_left": pivot_left,
            "pivot_right": pivot_right,
            "mss_expiration_bars": mss_expiration_bars,
            "target_r": target_r,
        },
        "total_sweeps": total_sweeps_all,
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


def run_candidate_evaluation(
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
            "disclaimer": (
                "RESEARCH CANDIDATE EVALUATION ONLY — simulated Sweep -> MSS "
                "setups run through Judge stop/target mechanics, no FVG "
                "requirement.  Not a trade strategy.  Not research evidence."
            ),
        }

    cells = []
    for pl, pr in PIVOT_PAIRS:
        for mss_exp in MSS_EXPIRATION_VALUES:
            for target_r in TARGET_R_VALUES:
                cells.append(evaluate_cell(pl, pr, mss_exp, target_r, symbol_bars))

    cells.sort(key=lambda c: c["conservative_expectancy_r"], reverse=True)

    if len(symbol_bars) > 1:
        data_warnings.append(
            "CORRELATION_WARNING: ETF symbols may be correlated; aggregated "
            "counts are not independent observations."
        )

    return {
        "cells": cells,
        "grid_size": len(PIVOT_PAIRS) * len(MSS_EXPIRATION_VALUES) * len(TARGET_R_VALUES),
        "symbols_evaluated": sorted(symbol_bars),
        "warnings": data_warnings,
        "disclaimer": (
            "RESEARCH CANDIDATE EVALUATION ONLY — simulated Sweep -> MSS "
            "setups run through Judge stop/target mechanics, no FVG "
            "requirement.  Not a trade strategy.  Not research evidence.  "
            "Sorted by conservative expectancy for inspection only; this "
            "is exploratory and does not select or recommend a winner."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Research candidate evaluation: Sweep -> MSS setups run through "
            "Judge stop/target mechanics, no FVG requirement.  Research-only "
            "— not a trade strategy."
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
    result = run_candidate_evaluation(symbols, adapter)
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
