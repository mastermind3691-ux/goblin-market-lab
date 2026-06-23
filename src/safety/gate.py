"""The single safety chokepoint for Goblin Market Lab.

Design contract (do not weaken without a human decision recorded in CLAUDE.md):

1. There is NO execution plane in this project. No module places orders.
   ``can_place_orders()`` therefore always returns ``False``. This is not a
   runtime flag that can flip to True — it is a structural fact. If you ever
   feel the need to make it return True, stop and re-read CLAUDE.md.

2. ``FORCE_PAPER_ONLY`` defaults to True and must stay True.

3. Strategy promotion is recommendation-only. ``candidate_status()`` always
   reports ``required_human_approval=True`` and ``ready_for_pilot=False``.
   A human reads the evidence and decides; the code never promotes anything.

Everything here is read-only and side-effect-free. It exists so the rest of the
app can ask "are we still safe?" and get an honest, un-overridable answer.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def force_paper_only() -> bool:
    """Paper-only is the default and the intended permanent state."""
    return _env_flag("FORCE_PAPER_ONLY", True)


def can_place_orders() -> bool:
    """Structural guarantee: this project has no order-placement code at all.

    Returns False unconditionally. The function exists so UI and tests can
    assert the guarantee, and so that any accidental future order code would
    have to first flip this to True in a visible, reviewed diff.
    """
    return False


@dataclass(frozen=True)
class SafetyState:
    force_paper_only: bool
    can_place_orders: bool
    real_trading_enabled: bool
    verdict: str


def safety_state() -> SafetyState:
    """A compact, human-readable snapshot of the safety posture."""
    fpo = force_paper_only()
    place = can_place_orders()
    # Read but intentionally never acted upon: surfaced only to make a
    # misconfiguration visible to a human, never to enable execution.
    real = _env_flag("REAL_TRADING_ENABLED", False)

    if place:
        verdict = "UNSAFE: order code exists — investigate immediately"
    elif not fpo:
        verdict = "WARNING: FORCE_PAPER_ONLY is off, but no order code exists so still paper"
    else:
        verdict = "Paper-only. No execution plane. Safe."

    return SafetyState(
        force_paper_only=fpo,
        can_place_orders=place,
        real_trading_enabled=real,
        verdict=verdict,
    )


@dataclass(frozen=True)
class CandidateStatus:
    """The promotion gate. Mirrors the BTC project's candidate_experiment_gate
    concept: it can *recommend*, it can never *promote*.
    """

    required_human_approval: bool
    ready_for_pilot: bool
    recommendation: str


def candidate_status(recommendation: str = "Keep collecting evidence.") -> CandidateStatus:
    """Always requires a human, never declares anything pilot-ready.

    ``recommendation`` is a plain-English note for a human to read. It does not
    and cannot change the gate: approval is always required, pilot is always
    False. This is deliberate and load-bearing.
    """
    return CandidateStatus(
        required_human_approval=True,
        ready_for_pilot=False,
        recommendation=recommendation,
    )
