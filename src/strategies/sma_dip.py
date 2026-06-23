"""Buy-the-dip below a moving average. A deliberately simple HYPOTHESIS.

It is not claimed to be good. Its only job is to be measurable. If the
scorecard says it has no edge, that is a successful, honest result.
"""

from __future__ import annotations

from .base import Signal, Strategy


class SmaDip(Strategy):
    name = "sma_dip"

    def __init__(self, window: int = 20, dip_pct: float = 0.03):
        self.window = window
        self.dip_pct = dip_pct

    def signal(self, bars: list[dict], position_open: bool) -> Signal:
        closes = self._closes(bars)
        sma = self._sma(closes, self.window)
        if sma is None:
            return Signal.HOLD
        price = closes[-1]
        if not position_open and price < sma * (1 - self.dip_pct):
            return Signal.BUY
        if position_open and price > sma:
            return Signal.SELL
        return Signal.HOLD
