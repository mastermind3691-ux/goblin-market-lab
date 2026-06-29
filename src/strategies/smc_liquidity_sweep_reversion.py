"""Pure setup generator for the SMC liquidity-sweep reversion candidate.

This module generates research setups from completed OHLC bars.  It makes no
claim about edge; fills and outcomes belong to :mod:`src.backtest.judge`.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Mapping, Sequence

from ..backtest.judge import SetupEvent


CANDIDATE_NAME = "smc_liquidity_sweep_reversion_v1_0"


@dataclass(frozen=True)
class SMCLiquiditySweepReversionConfig:
    pivot_left: int = 8
    pivot_right: int = 3
    mss_expiration_bars: int = 8
    order_expiration_bars: int = 8
    entry_mode: str = "near"
    target_r: float = 2.0
    current_trend_filter: str = "with_trend"
    current_ema_len: int = 200

    def __post_init__(self) -> None:
        if self.pivot_left < 1 or self.pivot_right < 1:
            raise ValueError("pivot_left and pivot_right must be positive")
        if self.mss_expiration_bars < 1 or self.order_expiration_bars < 1:
            raise ValueError("expiration windows must be positive")
        if self.entry_mode not in {"near", "mid", "deep"}:
            raise ValueError("entry_mode must be 'near', 'mid', or 'deep'")
        if not isfinite(self.target_r) or self.target_r <= 0:
            raise ValueError("target_r must be a positive finite number")
        if self.current_trend_filter not in {"with_trend", "disabled"}:
            raise ValueError("current_trend_filter must be 'with_trend' or 'disabled'")
        if self.current_ema_len < 1:
            raise ValueError("current_ema_len must be positive")


@dataclass(frozen=True)
class _Pivot:
    index: int
    level: float
    confirmed_i: int

    @property
    def usable_i(self) -> int:
        return self.confirmed_i + 1


@dataclass(frozen=True)
class _Sequence:
    direction: str
    sweep_i: int
    sweep_extreme: float
    swept_pivot: _Pivot
    mss_pivot: _Pivot


def generate_smc_liquidity_sweep_setups(
    bars: Sequence[Mapping[str, Any]],
    config: SMCLiquiditySweepReversionConfig | None = None,
) -> list[SetupEvent]:
    """Generate causal research setups from oldest-first completed bars."""
    cfg = config or SMCLiquiditySweepReversionConfig()
    _validate_bars(bars)

    setups: list[SetupEvent] = []
    known_high: _Pivot | None = None
    known_low: _Pivot | None = None
    active: _Sequence | None = None
    ema: float | None = None
    ema_count = 0
    alpha = 2.0 / (cfg.current_ema_len + 1.0)

    for i, bar in enumerate(bars):
        close = float(bar["close"])
        ema_count += 1
        ema = close if ema is None else alpha * close + (1.0 - alpha) * ema
        usable_ema = ema if ema_count >= cfg.current_ema_len else None

        if active is not None:
            age = i - active.sweep_i
            if age > cfg.mss_expiration_bars:
                active = None
            elif _mss_hit(active, close):
                setup = _setup_from_mss(bars, i, active, cfg, usable_ema)
                if setup is not None:
                    setups.append(setup)
                active = None
        else:
            bearish = (
                known_high is not None
                and float(bar["high"]) > known_high.level
                and close < known_high.level
            )
            bullish = (
                known_low is not None
                and float(bar["low"]) < known_low.level
                and close > known_low.level
            )
            if bearish != bullish:
                if bearish and known_low is not None:
                    active = _Sequence(
                        direction="bearish",
                        sweep_i=i,
                        sweep_extreme=float(bar["high"]),
                        swept_pivot=known_high,
                        mss_pivot=known_low,
                    )
                elif bullish and known_high is not None:
                    active = _Sequence(
                        direction="bullish",
                        sweep_i=i,
                        sweep_extreme=float(bar["low"]),
                        swept_pivot=known_low,
                        mss_pivot=known_high,
                    )

        pivot_i = i - cfg.pivot_right
        if pivot_i >= cfg.pivot_left:
            confirmed_high, confirmed_low = _confirmed_pivots(bars, pivot_i, i, cfg)
            if confirmed_high is not None:
                known_high = confirmed_high
            if confirmed_low is not None:
                known_low = confirmed_low

    return setups


def _confirmed_pivots(
    bars: Sequence[Mapping[str, Any]],
    pivot_i: int,
    confirmed_i: int,
    cfg: SMCLiquiditySweepReversionConfig,
) -> tuple[_Pivot | None, _Pivot | None]:
    start = pivot_i - cfg.pivot_left
    end = pivot_i + cfg.pivot_right
    candidate_high = float(bars[pivot_i]["high"])
    candidate_low = float(bars[pivot_i]["low"])
    other_indices = [j for j in range(start, end + 1) if j != pivot_i]
    high = None
    low = None
    if all(candidate_high > float(bars[j]["high"]) for j in other_indices):
        high = _Pivot(pivot_i, candidate_high, confirmed_i)
    if all(candidate_low < float(bars[j]["low"]) for j in other_indices):
        low = _Pivot(pivot_i, candidate_low, confirmed_i)
    return high, low


def _mss_hit(active: _Sequence, close: float) -> bool:
    if active.direction == "bearish":
        return close < active.mss_pivot.level
    return close > active.mss_pivot.level


def _setup_from_mss(
    bars: Sequence[Mapping[str, Any]],
    i: int,
    active: _Sequence,
    cfg: SMCLiquiditySweepReversionConfig,
    ema: float | None,
) -> SetupEvent | None:
    if i <= active.sweep_i or i < 2:
        return None

    candle_1 = bars[i - 2]
    candle_3 = bars[i]
    close = float(candle_3["close"])
    if active.direction == "bearish":
        fvg_bottom = float(candle_3["high"])
        fvg_top = float(candle_1["low"])
        if fvg_bottom >= fvg_top or not _trend_allows("short", close, ema, cfg):
            return None
        side = "short"
        invalidation = max(active.sweep_extreme, active.swept_pivot.level)
    else:
        fvg_bottom = float(candle_1["high"])
        fvg_top = float(candle_3["low"])
        if fvg_bottom >= fvg_top or not _trend_allows("long", close, ema, cfg):
            return None
        side = "long"
        invalidation = min(active.sweep_extreme, active.swept_pivot.level)

    entry = _entry_for_mode(side, fvg_bottom, fvg_top, cfg.entry_mode)
    risk = abs(entry - invalidation)
    if risk == 0 or (side == "long" and invalidation >= entry):
        return None
    if side == "short" and invalidation <= entry:
        return None
    target = entry + risk * cfg.target_r if side == "long" else entry - risk * cfg.target_r
    metadata = {
        "strategy": CANDIDATE_NAME,
        "diagnostic_only": True,
        "sweep_i": active.sweep_i,
        "sweep_extreme": active.sweep_extreme,
        "swept_pivot_i": active.swept_pivot.index,
        "swept_pivot_level": active.swept_pivot.level,
        "swept_pivot_confirmed_i": active.swept_pivot.confirmed_i,
        "swept_pivot_usable_i": active.swept_pivot.usable_i,
        "mss_pivot_i": active.mss_pivot.index,
        "mss_pivot_level": active.mss_pivot.level,
        "mss_pivot_confirmed_i": active.mss_pivot.confirmed_i,
        "mss_pivot_usable_i": active.mss_pivot.usable_i,
        "fvg_bottom": fvg_bottom,
        "fvg_top": fvg_top,
        "entry_mode": cfg.entry_mode,
        "target_r": cfg.target_r,
        "current_trend_filter": cfg.current_trend_filter,
        "current_ema": ema,
    }
    return SetupEvent(
        side=side,
        created_i=i,
        valid_from_i=i + 1,
        entry=entry,
        invalidation=invalidation,
        target=target,
        expires_i=i + cfg.order_expiration_bars,
        metadata=metadata,
    )


def _entry_for_mode(side: str, bottom: float, top: float, mode: str) -> float:
    if mode == "mid":
        return (bottom + top) / 2.0
    if side == "long":
        return top if mode == "near" else bottom
    return bottom if mode == "near" else top


def _trend_allows(
    side: str,
    close: float,
    ema: float | None,
    cfg: SMCLiquiditySweepReversionConfig,
) -> bool:
    if cfg.current_trend_filter == "disabled":
        return True
    if ema is None:
        return False
    return close > ema if side == "long" else close < ema


def _validate_bars(bars: Sequence[Mapping[str, Any]]) -> None:
    required = ("open", "high", "low", "close")
    for i, bar in enumerate(bars):
        try:
            values = {key: float(bar[key]) for key in required}
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"bar {i} must contain numeric OHLC values") from exc
        if not all(isfinite(value) and value > 0 for value in values.values()):
            raise ValueError(f"bar {i} OHLC values must be positive and finite")
        if values["low"] > min(values["open"], values["close"]):
            raise ValueError(f"bar {i} low exceeds open or close")
        if values["high"] < max(values["open"], values["close"]):
            raise ValueError(f"bar {i} high is below open or close")
