"""CLI: run the backtest + scorecard for every instrument/strategy and print
the honest verdicts. Runs fully offline against /data CSVs.

    python -m tools.run_backtest
"""

from __future__ import annotations

import os

from src.backtest.engine import backtest
from src.data.csv_adapter import CsvAdapter
from src.instruments.registry import INSTRUMENTS
from src.scorecard.scorecard import build_scorecard
from src.strategies.sma_dip import SmaDip
from src.strategies.trend_filter import TrendFilter

DATA_DIR = os.getenv("DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "data"))
REAL_DIR = os.path.join(DATA_DIR, "real")


def main() -> None:
    real = REAL_DIR if os.path.isdir(REAL_DIR) else None
    adapter = CsvAdapter(DATA_DIR, real_dir=real)
    strategies = [SmaDip(), TrendFilter()]
    for symbol, inst in INSTRUMENTS.items():
        all_bars = adapter.bars(symbol, limit=999_999)
        bars = all_bars[-2000:]
        meta = adapter.meta(symbol)
        for strat in strategies:
            result = backtest(strat, symbol, bars, fee_bps=inst.fee_bps)
            card = build_scorecard(result, meta, bars=bars,
                                   available_bars=len(all_bars))
            print(f"\n[{card['strategy']} on {card['instrument']}] {card['headline']}")
            print(f"  {card['verdict']}")
            print(f"  data={card['data_source']} ({card['evidence_grade']}, "
                  f"adjustment={card['price_adjustment']})")
            print(f"  bars tested={card['bars_tested']} available={card['available_bars']} "
                  f"last_bar={card['last_bar_date']} "
                  f"stale={card['data_is_stale']} exposure={card['exposure_pct']}")
            print(f"  trades={card['trades']} win_rate={card['win_rate']} "
                  f"strat_return={card['strategy_return']} vs buy&hold={card['buy_and_hold_return']} "
                  f"({card['vs_benchmark']})")


if __name__ == "__main__":
    main()
