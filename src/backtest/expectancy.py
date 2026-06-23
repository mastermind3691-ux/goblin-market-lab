"""Honest expectancy reporting.

This is the pedagogical heart of the whole project. Most beginner trading tools
project confidence. This one's job is the opposite: to tell you, honestly,
whether a rule has shown any edge AND whether you even have enough data to say
anything at all.

Given a list of per-trade returns (e.g. percentage returns, or R-multiples),
``expectancy_report`` returns the numbers plus a plain-English verdict. The
verdict is conservative on purpose:

- Fewer than ``MIN_SAMPLES`` trades  -> "not enough data yet"
- Mean return within ~2 standard errors of zero -> "indistinguishable from zero"
- Otherwise -> reports the edge, while reminding you it's still paper evidence.

No part of this promotes anything. It only measures.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, asdict
from typing import Sequence

MIN_SAMPLES = 30  # Below this, decline to draw conclusions.


@dataclass(frozen=True)
class ExpectancyReport:
    n: int
    win_rate: float
    avg_win: float
    avg_loss: float
    expectancy: float          # mean per-trade return
    std: float
    standard_error: float
    enough_data: bool
    distinguishable_from_zero: bool
    verdict: str

    def to_dict(self) -> dict:
        return asdict(self)


def expectancy_report(returns: Sequence[float], min_samples: int = MIN_SAMPLES) -> ExpectancyReport:
    n = len(returns)
    if n == 0:
        return ExpectancyReport(
            n=0, win_rate=0.0, avg_win=0.0, avg_loss=0.0, expectancy=0.0,
            std=0.0, standard_error=0.0, enough_data=False,
            distinguishable_from_zero=False,
            verdict="No trades yet. Nothing to measure.",
        )

    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r < 0]
    mean = sum(returns) / n
    avg_win = (sum(wins) / len(wins)) if wins else 0.0
    avg_loss = (sum(losses) / len(losses)) if losses else 0.0
    win_rate = len(wins) / n

    if n > 1:
        variance = sum((r - mean) ** 2 for r in returns) / (n - 1)
        std = math.sqrt(variance)
        se = std / math.sqrt(n)
    else:
        std = 0.0
        se = 0.0

    enough = n >= min_samples
    # ~95% rule of thumb: is the mean more than 2 standard errors from zero?
    distinguishable = enough and se > 0 and abs(mean) > 2 * se

    if not enough:
        verdict = (
            f"Not enough data yet ({n} of {min_samples} trades). "
            "Any apparent edge here is noise. Keep collecting."
        )
    elif not distinguishable:
        verdict = (
            f"{n} trades, but the result is statistically indistinguishable "
            "from zero. No demonstrated edge."
        )
    elif mean > 0:
        verdict = (
            f"Positive paper expectancy of {mean:.4f} per trade over {n} trades. "
            "This is paper evidence only — not a proven live edge, not a reason to promote."
        )
    else:
        verdict = (
            f"Negative paper expectancy of {mean:.4f} per trade over {n} trades. "
            "This rule lost money in paper. Kill or revise it."
        )

    return ExpectancyReport(
        n=n, win_rate=win_rate, avg_win=avg_win, avg_loss=avg_loss,
        expectancy=mean, std=std, standard_error=se,
        enough_data=enough, distinguishable_from_zero=distinguishable,
        verdict=verdict,
    )
