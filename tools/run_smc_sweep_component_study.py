"""Component study: forward outcome tendency after confirmed pivot sweeps.

This is a forward observation study, not a trade strategy.  It measures what
happens over the next N bars after a liquidity sweep, without requiring MSS,
FVG, or any entry/exit logic.  No setups or orders are emitted.

Results are exploratory and must not be interpreted as evidence of
tradeable tendency.

    python tools/run_smc_sweep_component_study.py
    python tools/run_smc_sweep_component_study.py --symbol GLD --symbol QQQ
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from itertools import product
from math import isfinite
from statistics import median
from typing import Any, Mapping, Sequence

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from src.data.timeframe_csv_adapter import TimeframeCsvAdapter
from src.instruments.registry import INSTRUMENTS

DATA_DIR = os.getenv("DATA_DIR", os.path.join(REPO_ROOT, "data"))
REAL_DIR = os.path.join(DATA_DIR, "real")

PIVOT_PAIRS = [(5, 2), (8, 3), (13, 5)]
FORWARD_HORIZONS = [1, 2, 4, 8, 12]


@dataclass(frozen=True)
class Pivot:
    index: int
    level: float
    confirmed_i: int

    @property
    def usable_i(self) -> int:
        return self.confirmed_i + 1


@dataclass
class SweepObservation:
    symbol: str
    bar_index: int
    timestamp: str | None
    side: str
    swept_level: float
    close_at_signal: float
    ambiguous: bool
    forward_returns: dict[int, float | None]
    forward_directional_hit: dict[int, bool | None]
    max_favorable_excursion: dict[int, float | None]
    max_adverse_excursion: dict[int, float | None]


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


def _forward_metrics(
    bars: Sequence[Mapping[str, Any]],
    sweep_i: int,
    close_at_signal: float,
    side: str,
    horizons: Sequence[int],
) -> tuple[dict[int, float | None], dict[int, bool | None],
           dict[int, float | None], dict[int, float | None]]:
    returns: dict[int, float | None] = {}
    hits: dict[int, bool | None] = {}
    mfe: dict[int, float | None] = {}
    mae: dict[int, float | None] = {}
    last_i = len(bars) - 1

    for h in horizons:
        target_i = sweep_i + h
        if target_i > last_i:
            returns[h] = None
            hits[h] = None
            mfe[h] = None
            mae[h] = None
            continue

        fwd_close = float(bars[target_i]["close"])
        ret = (fwd_close - close_at_signal) / close_at_signal
        returns[h] = ret

        if side == "bullish":
            hits[h] = ret > 0
        else:
            hits[h] = ret < 0

        best = 0.0
        worst = 0.0
        for j in range(sweep_i + 1, target_i + 1):
            bar_high = float(bars[j]["high"])
            bar_low = float(bars[j]["low"])
            if side == "bullish":
                excursion_fav = (bar_high - close_at_signal) / close_at_signal
                excursion_adv = (close_at_signal - bar_low) / close_at_signal
            else:
                excursion_fav = (close_at_signal - bar_low) / close_at_signal
                excursion_adv = (bar_high - close_at_signal) / close_at_signal
            best = max(best, excursion_fav)
            worst = max(worst, excursion_adv)
        mfe[h] = best
        mae[h] = worst

    return returns, hits, mfe, mae


def detect_sweeps(
    bars: Sequence[Mapping[str, Any]],
    symbol: str,
    pivot_left: int,
    pivot_right: int,
    horizons: Sequence[int],
) -> list[SweepObservation]:
    _validate_bars(bars)
    observations: list[SweepObservation] = []
    known_high: Pivot | None = None
    known_low: Pivot | None = None

    for i, bar in enumerate(bars):
        close = float(bar["close"])
        high = float(bar["high"])
        low = float(bar["low"])

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
            ambiguous = bearish and bullish

            if ambiguous:
                side = "ambiguous"
            elif bearish:
                side = "bearish"
            else:
                side = "bullish"

            swept_level = (
                known_high.level if bearish and not ambiguous
                else known_low.level if bullish and not ambiguous
                else known_high.level
            )

            fwd_ret, fwd_hit, fwd_mfe, fwd_mae = _forward_metrics(
                bars, i, close, side if not ambiguous else "bullish",
                horizons,
            )

            ts = bar.get("ts") or bar.get("timestamp") or bar.get("date")

            observations.append(SweepObservation(
                symbol=symbol,
                bar_index=i,
                timestamp=str(ts) if ts else None,
                side=side,
                swept_level=swept_level,
                close_at_signal=close,
                ambiguous=ambiguous,
                forward_returns=fwd_ret,
                forward_directional_hit=fwd_hit,
                max_favorable_excursion=fwd_mfe,
                max_adverse_excursion=fwd_mae,
            ))

        pivot_i = i - pivot_right
        if pivot_i >= pivot_left:
            confirmed_high, confirmed_low = _confirmed_pivots(
                bars, pivot_i, i, pivot_left, pivot_right,
            )
            if confirmed_high is not None:
                known_high = confirmed_high
            if confirmed_low is not None:
                known_low = confirmed_low

    return observations


def _sample_status(n: int) -> str | None:
    if n < 30:
        return "INSUFFICIENT_SAMPLE"
    if n < 100:
        return "WEAK_SAMPLE"
    return None


def _horizon_stats(
    observations: list[SweepObservation],
    horizon: int,
    directional_only: bool = True,
) -> dict[str, Any]:
    if directional_only:
        obs = [o for o in observations if not o.ambiguous]
    else:
        obs = observations

    returns = [o.forward_returns[horizon] for o in obs
               if o.forward_returns.get(horizon) is not None]
    hits = [o.forward_directional_hit[horizon] for o in obs
            if o.forward_directional_hit.get(horizon) is not None]
    mfes = [o.max_favorable_excursion[horizon] for o in obs
            if o.max_favorable_excursion.get(horizon) is not None]
    maes = [o.max_adverse_excursion[horizon] for o in obs
            if o.max_adverse_excursion.get(horizon) is not None]

    n = len(returns)
    return {
        "horizon_bars": horizon,
        "observations": n,
        "average_forward_return": sum(returns) / n if n else 0.0,
        "median_forward_return": median(returns) if n else 0.0,
        "directional_hit_rate": sum(hits) / len(hits) if hits else 0.0,
        "average_max_favorable_excursion": sum(mfes) / len(mfes) if mfes else 0.0,
        "average_max_adverse_excursion": sum(maes) / len(maes) if maes else 0.0,
        "sample_status": _sample_status(n),
    }


def _aggregate_observations(
    observations: list[SweepObservation],
    horizons: Sequence[int],
) -> dict[str, Any]:
    directional = [o for o in observations if not o.ambiguous]
    bullish = [o for o in directional if o.side == "bullish"]
    bearish = [o for o in directional if o.side == "bearish"]
    ambiguous = [o for o in observations if o.ambiguous]

    return {
        "total_sweeps": len(observations),
        "bullish_sweeps": len(bullish),
        "bearish_sweeps": len(bearish),
        "ambiguous_sweeps": len(ambiguous),
        "directional_sweeps": len(directional),
        "sample_status": _sample_status(len(directional)),
        "per_horizon": [_horizon_stats(observations, h) for h in horizons],
    }


def evaluate_cell(
    pivot_left: int,
    pivot_right: int,
    horizons: Sequence[int],
    symbol_bars: dict[str, list[dict]],
) -> dict[str, Any]:
    all_observations: list[SweepObservation] = []
    per_symbol: dict[str, dict] = {}

    for symbol in sorted(symbol_bars):
        bars = symbol_bars[symbol]
        obs = detect_sweeps(bars, symbol, pivot_left, pivot_right, horizons)
        all_observations.extend(obs)
        per_symbol[symbol] = _aggregate_observations(obs, horizons)

    agg = _aggregate_observations(all_observations, horizons)

    return {
        "parameters": {
            "pivot_left": pivot_left,
            "pivot_right": pivot_right,
        },
        "aggregate": agg,
        "per_symbol": per_symbol,
    }


def run_sweep_component_study(
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
            "symbols_evaluated": [],
            "warnings": data_warnings + ["No symbols with verified 4H data."],
            "disclaimer": (
                "COMPONENT STUDY ONLY — measures forward tendency after pivot "
                "sweeps without MSS/FVG/entry logic.  Not a trade strategy.  "
                "Not research evidence."
            ),
        }

    cells = []
    for pl, pr in PIVOT_PAIRS:
        cell = evaluate_cell(pl, pr, FORWARD_HORIZONS, symbol_bars)
        cells.append(cell)

    cells.sort(
        key=lambda c: (
            c["aggregate"]["directional_sweeps"],
            c["aggregate"]["per_horizon"][0]["average_forward_return"]
            if c["aggregate"]["per_horizon"] else 0,
        ),
        reverse=True,
    )

    if len(symbol_bars) > 1:
        data_warnings.append(
            "CORRELATION_WARNING: ETF symbols may be correlated; aggregated "
            "counts are not independent observations."
        )

    return {
        "cells": cells,
        "grid_size": len(PIVOT_PAIRS),
        "symbols_evaluated": sorted(symbol_bars),
        "forward_horizons": list(FORWARD_HORIZONS),
        "warnings": data_warnings,
        "disclaimer": (
            "COMPONENT STUDY ONLY — measures forward tendency after pivot "
            "sweeps without MSS/FVG/entry logic.  Not a trade strategy.  "
            "Not research evidence."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Component study: forward outcome tendency after confirmed pivot "
            "sweeps.  Research-only observation study — not a trade strategy."
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
    result = run_sweep_component_study(symbols, adapter)
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
