"""Market-data adapter contract + data provenance.

What belongs here: the *interface* every data source must satisfy (plain OHLCV
bars) AND a ``DataMeta`` that forces every source to declare its provenance:
- is it synthetic (sample/debug) or real?
- are prices adjusted or unadjusted for splits/dividends?

These labels are not optional. Synthetic data must never be presented as
evidence, and an unadjusted equity series silently distorts returns — so every
scorecard reads ``DataMeta`` and surfaces it.

What must NOT belong here: vendor-specific code, API keys, or anything that
could place an order. Adapters are read-only.

A "bar" is a dict: {"ts", "open", "high", "low", "close", "volume"}.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

ADJUSTMENT_VALUES = {"adjusted", "unadjusted", "unknown"}


@dataclass(frozen=True)
class DataMeta:
    source: str            # human-readable origin, e.g. "synthetic_random_walk"
    synthetic: bool        # True = sample/debug data, NEVER evidence
    adjustment: str        # "adjusted" | "unadjusted" | "unknown"

    def __post_init__(self) -> None:
        if self.adjustment not in ADJUSTMENT_VALUES:
            raise ValueError(f"adjustment must be one of {ADJUSTMENT_VALUES}")

    def evidence_grade(self) -> str:
        """How much trust this data's numbers deserve."""
        if self.synthetic:
            return "pipeline_validation_only"
        if self.adjustment == "unknown":
            return "real_unverified_adjustment"
        return "real"


class MarketDataAdapter(ABC):
    """Read-only source of historical/recent bars for one instrument."""

    @abstractmethod
    def bars(self, instrument: str, timeframe: str = "1d", limit: int = 500) -> list[dict]:
        """Return up to ``limit`` most-recent completed bars, oldest first.

        Must never return a partial/forming bar, never block on a live socket,
        never require trading credentials.
        """
        raise NotImplementedError

    @abstractmethod
    def meta(self, instrument: str) -> DataMeta:
        """Declare provenance for this instrument's data. Required, not optional."""
        raise NotImplementedError
