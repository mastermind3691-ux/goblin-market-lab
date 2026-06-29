# data/real/ — Manually Imported Real Bar Data

This directory holds **real** (non-synthetic) daily CSV bars imported via
`python -m tools.import_csv`. These files take priority over the synthetic
sample data in `data/`.

## Optional verified 4H research data

The SMC evaluation CLI looks for genuine 4H files at:

```text
data/real/4h/GLD.csv
data/real/4h/GLD.meta.json
data/real/4h/SPY.csv
data/real/4h/SPY.meta.json
```

The CSV must use the normal OHLCV columns and full timestamps (for example,
`2024-01-02T09:30:00`). At least one date must contain multiple bars. The
sidecar must explicitly declare the timeframe and provenance:

```json
{
  "source": "vendor_name",
  "synthetic": false,
  "adjustment": "adjusted",
  "timeframe": "4H"
}
```

Missing, synthetic, daily-timestamped, or incorrectly labelled files are not
treated as 4H data. The CLI falls back to available daily data and emits
`REQUESTED_TIMEFRAME_UNAVAILABLE`. It never constructs 4H bars from daily bars.

## Expected CSV format

**Required columns:** `date`, `open`, `high`, `low`, `close`
**Optional columns:** `volume`

```csv
date,open,high,low,close,volume
2020-01-02,323.54,324.89,322.53,324.87,27765900
2020-01-03,321.16,323.64,321.09,322.41,31039600
```

- `date`: YYYY-MM-DD (also accepts M/D/YYYY, YYYY/MM/DD)
- `open`, `high`, `low`, `close`: positive numbers
- `high` must be >= `low`
- `volume`: non-negative integer or float (optional; defaults to 0)
- The header `ts` is accepted as an alias for `date`

## Import command

```bash
python -m tools.import_csv --symbol SPY --input path/to/SPY.csv --source manual --adjustment adjusted
```

The `--adjustment` flag is required. Use:
- `adjusted` — prices include split/dividend adjustments (recommended)
- `unadjusted` — raw exchange prices
- `unknown` — when you're not sure (scorecard will flag this)

## What happens on import

1. The CSV is validated (dates, OHLC ranges, duplicates, sort order).
2. A normalized `<SYMBOL>.csv` is written here.
3. A `<SYMBOL>.meta.json` sidecar is created with `synthetic: false`.
4. The backtest engine and scorecards will automatically prefer this file.

## Scorecards with real data

When real data is present, scorecard headlines reflect actual evidence quality
instead of showing "PIPELINE VALIDATION ONLY". The adjustment status is always
surfaced — unadjusted or unknown data gets a downgraded evidence grade.
