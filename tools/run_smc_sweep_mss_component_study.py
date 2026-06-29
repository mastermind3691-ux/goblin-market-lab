"""Component study: forward outcome tendency after Sweep then MSS confirmation.

This is a forward observation study, not a trade strategy.  It measures what
happens over the next N bars after a liquidity sweep is confirmed by a Market
Structure Shift (MSS), without requiring FVG or any entry/exit logic.
No setups or orders are emitted.

Results are exploratory and must not be interpreted as tradeable tendency.

    python tools/run_smc_sweep_mss_component_study.py
    python tools/run_smc_sweep_mss_component_study.py --symbol GLD --symbol QQQ
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
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
MSS_EXPIRATION_VALUES = [4, 8, 12, 16]
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
class MssObservation:
    symbol: str
    sweep_side: str
    sweep_bar_index: int
    sweep_timestamp: str | None
    mss_bar_index: int
    mss_timestamp: str | None
    swept_level: float
    frozen_mss_level: float
    bars_sweep_to_mss: int
    close_at_mss: float
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
    signal_i: int,
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
        target_i = signal_i + h
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
        for j in range(signal_i + 1, target_i + 1):
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


@dataclass
class _ActiveSweep:
    direction: str
    sweep_i: int
    swept_level: float
    frozen_mss_level: float
    ambiguous: bool


def detect_sweep_mss(
    bars: Sequence[Mapping[str, Any]],
    symbol: str,
    pivot_left: int,
    pivot_right: int,
    mss_expiration_bars: int,
    horizons: Sequence[int],
) -> tuple[list[MssObservation], int]:
    """Return (observations, total_sweeps_detected)."""
    _validate_bars(bars)
    observations: list[MssObservation] = []
    known_high: Pivot | None = None
    known_low: Pivot | None = None
    active: _ActiveSweep | None = None
    total_sweeps = 0

    for i, bar in enumerate(bars):
        close = float(bar["close"])
        high = float(bar["high"])
        low = float(bar["low"])

        if active is not None:
            age = i - active.sweep_i
            if age > mss_expiration_bars:
                active = None
            elif age >= 1 and not active.ambiguous:
                mss_hit = False
                if active.direction == "bearish" and close < active.frozen_mss_level:
                    mss_hit = True
                elif active.direction == "bullish" and close > active.frozen_mss_level:
                    mss_hit = True

                if mss_hit:
                    sweep_bar = bars[active.sweep_i]
                    sweep_ts = (sweep_bar.get("ts") or sweep_bar.get("timestamp")
                                or sweep_bar.get("date"))
                    mss_ts = bar.get("ts") or bar.get("timestamp") or bar.get("date")

                    fwd_ret, fwd_hit, fwd_mfe, fwd_mae = _forward_metrics(
                        bars, i, close, active.direction, horizons,
                    )

                    observations.append(MssObservation(
                        symbol=symbol,
                        sweep_side=active.direction,
                        sweep_bar_index=active.sweep_i,
                        sweep_timestamp=str(sweep_ts) if sweep_ts else None,
                        mss_bar_index=i,
                        mss_timestamp=str(mss_ts) if mss_ts else None,
                        swept_level=active.swept_level,
                        frozen_mss_level=active.frozen_mss_level,
                        bars_sweep_to_mss=age,
                        close_at_mss=close,
                        ambiguous=False,
                        forward_returns=fwd_ret,
                        forward_directional_hit=fwd_hit,
                        max_favorable_excursion=fwd_mfe,
                        max_adverse_excursion=fwd_mae,
                    ))
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

                if ambiguous:
                    pass
                elif bearish and known_low is not None:
                    active = _ActiveSweep(
                        direction="bearish",
                        sweep_i=i,
                        swept_level=known_high.level,
                        frozen_mss_level=known_low.level,
                        ambiguous=False,
                    )
                elif bullish and known_high is not None:
                    active = _ActiveSweep(
                        direction="bullish",
                        sweep_i=i,
                        swept_level=known_low.level,
                        frozen_mss_level=known_high.level,
                        ambiguous=False,
                    )

        pivot_i = i - pivot_right
        if pivot_i >= pivot_left:
            ch, cl = _confirmed_pivots(
                bars, pivot_i, i, pivot_left, pivot_right,
            )
            if ch is not None:
                known_high = ch
            if cl is not None:
                known_low = cl

    return observations, total_sweeps


def _sample_status(n: int) -> str | None:
    if n < 30:
        return "INSUFFICIENT_SAMPLE"
    if n < 100:
        return "WEAK_SAMPLE"
    return None


def _horizon_stats(
    observations: list[MssObservation],
    horizon: int,
) -> dict[str, Any]:
    returns = [o.forward_returns[horizon] for o in observations
               if o.forward_returns.get(horizon) is not None]
    hits = [o.forward_directional_hit[horizon] for o in observations
            if o.forward_directional_hit.get(horizon) is not None]
    mfes = [o.max_favorable_excursion[horizon] for o in observations
            if o.max_favorable_excursion.get(horizon) is not None]
    maes = [o.max_adverse_excursion[horizon] for o in observations
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
    observations: list[MssObservation],
    total_sweeps: int,
    horizons: Sequence[int],
) -> dict[str, Any]:
    bullish = [o for o in observations if o.sweep_side == "bullish"]
    bearish = [o for o in observations if o.sweep_side == "bearish"]
    mss_count = len(observations)

    return {
        "total_sweeps": total_sweeps,
        "sweeps_reaching_mss": mss_count,
        "mss_conversion_rate": mss_count / total_sweeps if total_sweeps else 0.0,
        "bullish_mss": len(bullish),
        "bearish_mss": len(bearish),
        "sample_status": _sample_status(mss_count),
        "per_horizon": [_horizon_stats(observations, h) for h in horizons],
    }


def evaluate_cell(
    pivot_left: int,
    pivot_right: int,
    mss_expiration_bars: int,
    horizons: Sequence[int],
    symbol_bars: dict[str, list[dict]],
) -> dict[str, Any]:
    all_observations: list[MssObservation] = []
    total_sweeps_all = 0
    per_symbol: dict[str, dict] = {}

    for symbol in sorted(symbol_bars):
        bars = symbol_bars[symbol]
        obs, sweeps = detect_sweep_mss(
            bars, symbol, pivot_left, pivot_right, mss_expiration_bars, horizons,
        )
        all_observations.extend(obs)
        total_sweeps_all += sweeps
        per_symbol[symbol] = _aggregate_observations(obs, sweeps, horizons)

    agg = _aggregate_observations(all_observations, total_sweeps_all, horizons)

    return {
        "parameters": {
            "pivot_left": pivot_left,
            "pivot_right": pivot_right,
            "mss_expiration_bars": mss_expiration_bars,
        },
        "aggregate": agg,
        "per_symbol": per_symbol,
    }


def run_sweep_mss_study(
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
                "COMPONENT STUDY ONLY — measures forward tendency after "
                "Sweep then MSS confirmation without FVG/entry logic.  "
                "Not a trade strategy.  Not research evidence."
            ),
        }

    cells = []
    for (pl, pr) in PIVOT_PAIRS:
        for mss_exp in MSS_EXPIRATION_VALUES:
            cell = evaluate_cell(pl, pr, mss_exp, FORWARD_HORIZONS, symbol_bars)
            cells.append(cell)

    cells.sort(
        key=lambda c: (
            c["aggregate"]["sweeps_reaching_mss"],
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
        "grid_size": len(PIVOT_PAIRS) * len(MSS_EXPIRATION_VALUES),
        "symbols_evaluated": sorted(symbol_bars),
        "forward_horizons": list(FORWARD_HORIZONS),
        "warnings": data_warnings,
        "disclaimer": (
            "COMPONENT STUDY ONLY — measures forward tendency after "
            "Sweep then MSS confirmation without FVG/entry logic.  "
            "Not a trade strategy.  Not research evidence."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Component study: forward outcome tendency after Sweep then MSS.  "
            "Research-only observation study — not a trade strategy."
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
    result = run_sweep_mss_study(symbols, adapter)
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
