"""Backtest engine — replay completed bars through a strategy.

Long-only, one position at a time, v0.1. Honest about fees: every round trip
pays ``fee_bps``. Also records a **buy-and-hold benchmark** over the same active
window, so a scorecard can ask the only question that matters for a long-only
equity strategy: did this beat simply holding the thing?

What must NOT belong here: live data, order placement, look-ahead (the strategy
only ever sees bars up to the current index).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..strategies.base import Signal, Strategy


@dataclass
class BacktestResult:
    strategy: str
    instrument: str
    n_bars: int
    returns: list[float] = field(default_factory=list)  # per closed trade, fee-adjusted
    trades: list[dict] = field(default_factory=list)
    buy_and_hold_return: float = 0.0                     # over the active window
    warmup: int = 0


def backtest(
    strategy: Strategy,
    instrument: str,
    bars: list[dict],
    fee_bps: float = 5.0,
    warmup: int = 100,
) -> BacktestResult:
    result = BacktestResult(strategy=strategy.name, instrument=instrument,
                            n_bars=len(bars), warmup=warmup)
    fee = fee_bps / 10_000.0
    position_open = False
    entry_price = 0.0

    if len(bars) > warmup:
        start_close = bars[warmup]["close"]
        end_close = bars[-1]["close"]
        if start_close:
            result.buy_and_hold_return = (end_close - start_close) / start_close

    for i in range(warmup, len(bars)):
        window = bars[: i + 1]                 # no look-ahead
        price = window[-1]["close"]
        sig = strategy.signal(window, position_open)

        if sig is Signal.BUY and not position_open:
            position_open = True
            entry_price = price
            result.trades.append({"ts": window[-1]["ts"], "side": "buy", "price": price})
        elif sig is Signal.SELL and position_open:
            gross = (price - entry_price) / entry_price
            net = gross - fee                  # round-trip cost charged on exit
            result.returns.append(net)
            result.trades.append({"ts": window[-1]["ts"], "side": "sell",
                                  "price": price, "return": net})
            position_open = False

    return result


def compounded_return(returns: list[float]) -> float:
    """Sequential, fully-allocated long-only compounding of closed-trade returns."""
    equity = 1.0
    for r in returns:
        equity *= (1 + r)
    return equity - 1
