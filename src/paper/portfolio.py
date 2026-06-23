"""Paper portfolio accounting. No real money. No orders. Ever.

A deliberately small, honest ledger:
- cash (paper)
- positions: instrument -> (quantity, average cost)
- closed-trade returns (used by the expectancy report)

It records simulated fills that come from the shadow tracker / backtest. It has
no path to a broker and imports nothing that could place an order. Field names
are currency-neutral on purpose (no legacy ``_eur`` confusion).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Position:
    quantity: float = 0.0
    avg_cost: float = 0.0


@dataclass
class PaperPortfolio:
    starting_cash: float = 10_000.0
    cash: float = field(default=0.0)
    positions: dict[str, Position] = field(default_factory=dict)
    closed_returns: list[float] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.cash == 0.0:
            self.cash = self.starting_cash

    def record_buy(self, instrument: str, quantity: float, price: float) -> None:
        cost = quantity * price
        if cost > self.cash:
            raise ValueError("Paper account cannot afford this simulated buy.")
        self.cash -= cost
        pos = self.positions.setdefault(instrument, Position())
        total_qty = pos.quantity + quantity
        if total_qty <= 0:
            self.positions.pop(instrument, None)
            return
        pos.avg_cost = (pos.avg_cost * pos.quantity + price * quantity) / total_qty
        pos.quantity = total_qty

    def record_sell(self, instrument: str, quantity: float, price: float) -> Optional[float]:
        """Record a simulated sell. Returns the trade's fractional return if it
        closes (part of) a position, else None.
        """
        pos = self.positions.get(instrument)
        if not pos or pos.quantity <= 0:
            raise ValueError("No paper position to sell.")
        quantity = min(quantity, pos.quantity)
        self.cash += quantity * price
        trade_return = (price - pos.avg_cost) / pos.avg_cost if pos.avg_cost else 0.0
        pos.quantity -= quantity
        if pos.quantity <= 1e-12:
            self.positions.pop(instrument, None)
        self.closed_returns.append(trade_return)
        return trade_return

    def mark_to_market(self, prices: dict[str, float]) -> float:
        equity = self.cash
        for instrument, pos in self.positions.items():
            equity += pos.quantity * prices.get(instrument, pos.avg_cost)
        return equity

    def to_dict(self) -> dict:
        return {
            "starting_cash": self.starting_cash,
            "cash": self.cash,
            "positions": {k: vars(v) for k, v in self.positions.items()},
            "closed_returns": list(self.closed_returns),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PaperPortfolio":
        port = cls(starting_cash=data.get("starting_cash", 10_000.0))
        port.cash = data.get("cash", port.starting_cash)
        port.positions = {
            k: Position(**v) for k, v in data.get("positions", {}).items()
        }
        port.closed_returns = list(data.get("closed_returns", []))
        return port
