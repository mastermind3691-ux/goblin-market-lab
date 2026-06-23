"""Strategy contract.

A strategy is a PURE FUNCTION from price history to a signal. It produces
opinions; it never touches the portfolio, never persists, never places orders.
This separation is the whole point — strategies are cheap to add and cheap to
kill, and nothing they do can move money.

What must NOT belong in a strategy: order code, portfolio mutation, persistence,
network calls, or any "auto-promote myself" logic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum


class Signal(str, Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


class Strategy(ABC):
    name: str = "unnamed"

    @abstractmethod
    def signal(self, bars: list[dict], position_open: bool) -> Signal:
        """Return BUY / SELL / HOLD given bars (oldest first) and whether a
        paper position is currently open. Long-only for v0.1.
        """
        raise NotImplementedError

    @staticmethod
    def _closes(bars: list[dict]) -> list[float]:
        return [b["close"] for b in bars]

    @staticmethod
    def _sma(values: list[float], n: int) -> float | None:
        if len(values) < n:
            return None
        return sum(values[-n:]) / n
