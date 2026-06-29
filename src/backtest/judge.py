"""Deterministic evaluation of already-created research setups against OHLC bars.

The judge does not generate setups.  It only walks forward from a setup's
eligibility index and records what the supplied bars can establish.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class SetupEvent:
    side: str
    created_i: int
    valid_from_i: int
    entry: float
    invalidation: float
    target: float
    expires_i: int
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.side not in {"long", "short"}:
            raise ValueError("side must be 'long' or 'short'")
        if min(self.created_i, self.valid_from_i, self.expires_i) < 0:
            raise ValueError("setup indices must be non-negative")
        if self.expires_i < self.valid_from_i:
            raise ValueError("expires_i must be at or after valid_from_i")

        if self.side == "long":
            if self.target <= self.entry:
                raise ValueError("long target must be above entry")
            if self.invalidation >= self.entry:
                raise ValueError("long invalidation must be below entry")
        else:
            if self.target >= self.entry:
                raise ValueError("short target must be below entry")
            if self.invalidation <= self.entry:
                raise ValueError("short invalidation must be above entry")


@dataclass(frozen=True)
class JudgeResult:
    status: str
    filled_i: int | None
    closed_i: int | None
    entry: float
    exit_price: float | None
    r_result: float | None
    reason: str
    bars_held: int
    metadata: dict[str, Any]


def judge_setup(setup: SetupEvent, bars: Sequence[Mapping[str, Any]]) -> JudgeResult:
    """Evaluate one setup against oldest-first OHLC bars.

    The creation bar is never eligible, even if ``valid_from_i`` points to it.
    With OHLC data, a bar touching both outcome levels has unknowable intrabar
    ordering, so it is recorded as a worst-case ambiguous loss.
    """
    metadata = dict(setup.metadata)
    first_eligible_i = max(setup.valid_from_i, setup.created_i + 1)
    last_available_i = len(bars) - 1
    last_entry_i = min(setup.expires_i, last_available_i)

    filled_i: int | None = None
    for i in range(first_eligible_i, last_entry_i + 1):
        if _entry_touched(setup, bars[i]):
            filled_i = i
            break

    if filled_i is None:
        if last_available_i >= setup.expires_i:
            return JudgeResult(
                status="NO_FILL",
                filled_i=None,
                closed_i=None,
                entry=setup.entry,
                exit_price=None,
                r_result=None,
                reason="Entry was not touched by setup expiry.",
                bars_held=0,
                metadata=metadata,
            )
        return JudgeResult(
            status="PENDING",
            filled_i=None,
            closed_i=None,
            entry=setup.entry,
            exit_price=None,
            r_result=None,
            reason="Setup has not filled and its expiry is beyond available bars.",
            bars_held=0,
            metadata=metadata,
        )

    for i in range(filled_i, len(bars)):
        target_hit, invalidation_hit = _outcomes_touched(setup, bars[i])
        bars_held = i - filled_i
        if target_hit and invalidation_hit:
            return JudgeResult(
                status="AMBIGUOUS_WORST_CASE",
                filled_i=filled_i,
                closed_i=i,
                entry=setup.entry,
                exit_price=setup.invalidation,
                r_result=-1.0,
                reason="Target and invalidation were touched in the same bar; worst case applied.",
                bars_held=bars_held,
                metadata=metadata,
            )
        if invalidation_hit:
            return JudgeResult(
                status="LOSS",
                filled_i=filled_i,
                closed_i=i,
                entry=setup.entry,
                exit_price=setup.invalidation,
                r_result=-1.0,
                reason="Invalidation was touched before target.",
                bars_held=bars_held,
                metadata=metadata,
            )
        if target_hit:
            return JudgeResult(
                status="WIN",
                filled_i=filled_i,
                closed_i=i,
                entry=setup.entry,
                exit_price=setup.target,
                r_result=_target_multiple(setup),
                reason="Target was touched before invalidation.",
                bars_held=bars_held,
                metadata=metadata,
            )

    return JudgeResult(
        status="PENDING",
        filled_i=filled_i,
        closed_i=None,
        entry=setup.entry,
        exit_price=None,
        r_result=None,
        reason="Simulated fill occurred, but no outcome was established by available bars.",
        bars_held=last_available_i - filled_i,
        metadata=metadata,
    )


def _entry_touched(setup: SetupEvent, bar: Mapping[str, Any]) -> bool:
    if setup.side == "long":
        return bar["low"] <= setup.entry
    return bar["high"] >= setup.entry


def _outcomes_touched(
    setup: SetupEvent, bar: Mapping[str, Any]
) -> tuple[bool, bool]:
    if setup.side == "long":
        return bar["high"] >= setup.target, bar["low"] <= setup.invalidation
    return bar["low"] <= setup.target, bar["high"] >= setup.invalidation


def _target_multiple(setup: SetupEvent) -> float:
    if setup.side == "long":
        return (setup.target - setup.entry) / (setup.entry - setup.invalidation)
    return (setup.entry - setup.target) / (setup.invalidation - setup.entry)
