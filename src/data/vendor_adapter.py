"""Placeholder for a REAL market-data vendor adapter.

Build this later behind the same ``MarketDataAdapter`` interface. Two
non-negotiables when you do:

1. ``meta()`` MUST declare ``synthetic=False`` and a truthful ``adjustment``
   ("adjusted" or "unadjusted"). For equities/ETFs you usually want
   split/dividend-ADJUSTED closes; if the vendor returns unadjusted prices, say
   so — do not pretend.
2. No API key belongs in code. Read it from the environment inside this adapter
   only. Nothing here may place an order.
"""

from __future__ import annotations

from .base import DataMeta, MarketDataAdapter


class VendorAdapter(MarketDataAdapter):
    def __init__(self, *args, **kwargs):
        raise NotImplementedError(
            "Real vendor adapter not implemented yet. Use CsvAdapter for offline "
            "work. When you build this, declare truthful DataMeta (synthetic=False, "
            "adjustment='adjusted' or 'unadjusted')."
        )

    def bars(self, instrument, timeframe="1d", limit=500):
        raise NotImplementedError

    def meta(self, instrument):
        raise NotImplementedError
