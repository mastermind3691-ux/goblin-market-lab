"""Honest aggregate statistics for deterministic research Judge results."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping, Sequence

from .judge import JudgeResult, SetupEvent


def build_research_report(
    symbol: str,
    timeframe: str,
    bars: Sequence[Mapping[str, Any]],
    setups: Sequence[SetupEvent],
    results: Sequence[JudgeResult],
) -> dict[str, Any]:
    """Build JSON-safe research statistics without making evidence claims."""
    if len(setups) != len(results):
        raise ValueError("setups and results must have the same length")

    report = {
        "symbol": symbol,
        "timeframe": timeframe,
        "bars_evaluated": len(bars),
        **_summarize(results),
    }
    resolved = report["wins"] + report["losses"]
    if resolved < 30:
        sample_status = "INSUFFICIENT_SAMPLE"
        warning = "INSUFFICIENT_SAMPLE: fewer than 30 unambiguous resolved outcomes."
    elif resolved < 100:
        sample_status = "WEAK_SAMPLE"
        warning = "WEAK_SAMPLE: fewer than 100 unambiguous resolved outcomes."
    else:
        sample_status = None
        warning = None
    report["sample_status"] = sample_status
    report["warnings"] = [warning] if warning else []
    report["per_year"] = _per_year(bars, setups, results)
    return report


def _summarize(results: Sequence[JudgeResult]) -> dict[str, Any]:
    counts = {status: 0 for status in (
        "WIN", "LOSS", "NO_FILL", "AMBIGUOUS_WORST_CASE", "PENDING"
    )}
    for result in results:
        if result.status not in counts:
            raise ValueError(f"unknown Judge status: {result.status}")
        counts[result.status] += 1

    total = len(results)
    filled = sum(result.filled_i is not None for result in results)
    ordinary = [
        float(result.r_result)
        for result in results
        if result.status in {"WIN", "LOSS"} and result.r_result is not None
    ]
    conservative = ordinary + [-1.0] * counts["AMBIGUOUS_WORST_CASE"]
    wins = counts["WIN"]
    losses = counts["LOSS"]
    ambiguous = counts["AMBIGUOUS_WORST_CASE"]
    ordinary_resolved = wins + losses
    conservative_resolved = ordinary_resolved + ambiguous
    gross_wins = sum(value for value in ordinary if value > 0)
    gross_losses = abs(sum(value for value in ordinary if value < 0))

    return {
        "total_setups": total,
        "filled_setups": filled,
        "fill_rate": _ratio(filled, total),
        "wins": wins,
        "losses": losses,
        "no_fills": counts["NO_FILL"],
        "ambiguous_worst_case": ambiguous,
        "pending": counts["PENDING"],
        "resolved_win_rate": _ratio(wins, ordinary_resolved),
        "conservative_win_rate": _ratio(wins, conservative_resolved),
        "expectancy_r": _mean(ordinary),
        "conservative_expectancy_r": _mean(conservative),
        "profit_factor_r": (
            gross_wins / gross_losses if gross_losses else None
        ),
        "net_r": sum(ordinary),
        "conservative_net_r": sum(conservative),
        "average_r": _mean(ordinary),
        "conservative_average_r": _mean(conservative),
        "largest_winning_trade_contribution": _largest_win_contribution(ordinary),
        "result_after_removing_best_trade": _remove_best(ordinary, 1),
        "result_after_removing_best_two_trades": _remove_best(ordinary, 2),
        "conservative_result_after_removing_best_trade": _remove_best(conservative, 1),
        "conservative_result_after_removing_best_two_trades": _remove_best(conservative, 2),
    }


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _largest_win_contribution(values: Sequence[float]) -> float:
    wins = [value for value in values if value > 0]
    return max(wins) / sum(wins) if wins else 0.0


def _remove_best(values: Sequence[float], count: int) -> float:
    remaining = sorted(values, reverse=True)[count:]
    return sum(remaining)


def _per_year(
    bars: Sequence[Mapping[str, Any]],
    setups: Sequence[SetupEvent],
    results: Sequence[JudgeResult],
) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[JudgeResult]] = defaultdict(list)
    for setup, result in zip(setups, results):
        if not (0 <= setup.created_i < len(bars)):
            continue
        timestamp = bars[setup.created_i].get("ts") or bars[setup.created_i].get("date")
        if timestamp is None:
            continue
        year = str(timestamp)[:4]
        if len(year) == 4 and year.isdigit():
            grouped[year].append(result)
    return {year: _summarize(grouped[year]) for year in sorted(grouped)}
