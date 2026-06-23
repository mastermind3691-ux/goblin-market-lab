"""Long only while price is above a long moving average. Another simple
HYPOTHESIS, useful as a contrast to sma_dip.
"""

from __future__ import annotations

from .base import Signal, Strategy


class TrendFilter(Strategy):
    name = "trend_filter"

    def __init__(self, window: int = 100):
        self.window = window

    def signal(self, bars: list[dict], position_open: bool) -> Signal:
        closes = self._closes(bars)
        sma = self._sma(closes, self.window)
        if sma is None:
            return Signal.HOLD
        price = closes[-1]
        if not position_open and price > sma:
            return Signal.BUY
        if position_open and price < sma:
            return Signal.SELL
        return Signal.HOLD
