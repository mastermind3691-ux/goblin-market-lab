"""Compatibility import for the primary read-only market-data vendor."""

from .tiingo_adapter import TiingoEodAdapter


VendorAdapter = TiingoEodAdapter

__all__ = ["VendorAdapter", "TiingoEodAdapter"]
