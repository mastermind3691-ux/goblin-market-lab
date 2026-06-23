"""Evidence-language guard.

Research output describes what was *measured*, never what *will* happen. This
module lists prediction/hype phrases that must never appear in a scorecard, and
a guard used by tests (and optionally at runtime) to enforce it.

Preferred evidence language: "historically tested", "shadow signal",
"not enough data", "positive expectancy after costs", "research-only",
"lags buy-and-hold".
"""

from __future__ import annotations

BANNED_PHRASES = [
    "will go up", "will go down", "will rise", "will fall", "will profit",
    "guaranteed", "safe trade", "risk-free", "can't lose", "cannot lose",
    "sure thing", "to the moon", "definitely", "always wins", "easy money",
    "buy now", "you should buy", "you should sell",
]


def find_prediction_language(text: str) -> list[str]:
    low = (text or "").lower()
    return [p for p in BANNED_PHRASES if p in low]


def assert_evidence_language(text: str) -> None:
    hits = find_prediction_language(text)
    if hits:
        raise AssertionError(f"Prediction/hype language found: {hits} in: {text!r}")
