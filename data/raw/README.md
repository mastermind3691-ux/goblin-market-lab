# data/raw/ — Downloaded Market Data (Local Only)

This directory holds raw CSV files fetched by helper scripts like
`tools/download_market_data.py`. These files are **not committed** to the repo
(`data/raw/` is in `.gitignore`).

## Workflow

1. Download raw bars:
   ```bash
   python -m tools.download_market_data --symbol SPY --start 2000-01-01 --end 2026-06-23
   ```

2. Import through the validator into `data/real/`:
   ```bash
   python -m tools.import_csv --symbol SPY --input data/raw/yfinance/SPY.csv --source yfinance --adjustment unknown
   ```

3. Run the backtest to see real-data scorecards:
   ```bash
   python -m tools.run_backtest
   ```

## Why not committed

Market data files can be large and may have redistribution restrictions.
Each developer downloads their own copy locally. The synthetic sample data
in `data/` provides a zero-dependency offline fallback.
