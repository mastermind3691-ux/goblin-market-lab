# 🧪 Goblin Market Lab

A clean, **paper-only** research lab for non-crypto markets (ETFs, indices, gold;
stocks later). Sibling project to the Tiny Goblin BTC bot — **not a fork.**

Its job is to measure trading hypotheses honestly, not to trade. If a rule has
no edge or not enough data, the lab says so in plain English.

## Safety, in one line

There is **no order-placement code in this repo.** `can_place_orders()` returns
`False` structurally. Paper / shadow / backtest only. See `CLAUDE.md`.

## Quickstart (runs fully offline — no API key)

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env

# 1) Run the backtest + honest scorecards in the terminal
python -m tools.run_backtest

# 2) Run the dashboard
python -m src.web.app
# open http://127.0.0.1:5060
```

Sample CSV bars for SPY and GLD ship in `data/`, so everything works with no
network. Replace the `CsvAdapter` with a real vendor adapter later behind the
same `MarketDataAdapter` interface — nothing downstream changes.

## What v0.1 includes

- 2 instruments (SPY, GLD), 1 data adapter (offline CSV)
- 2 simple strategies (`sma_dip`, `trend_filter`) — hypotheses, not truths
- a fee-aware backtest engine (no look-ahead)
- honest expectancy + a scorecard that benchmarks vs buy-and-hold, flags
  concentration risk, labels data provenance (synthetic vs real, adjusted vs
  unadjusted), and says "NO EDGE YET" / "PIPELINE VALIDATION ONLY" when warranted
- atomic, migration-safe paper-state persistence
- a thin templated Flask dashboard

## What v0.1 deliberately excludes

Live trading, broker/order code, CFDs, leverage, Telegram, and a sprawling
research UI. Those are later (and most require an explicit human decision).

## Railway: shadow state persistence

The dashboard shows a "Shadow Replay / Forward Evidence" card. On a fresh
deploy it shows `total=0` because `shadow_state.json` is gitignored (it
contains generated data, not source).

To populate it on Railway:

1. **Create a Railway volume** and mount it at `/mnt/data`.
2. **Set the env vars**:
   ```bash
   REAL_DATA_DIR=/mnt/data/real
   SHADOW_STATE_PATH=/mnt/data/shadow_state.json
   ```
3. **Run the one-time bootstrap** (Railway shell or one-off command):
   ```bash
   python -m tools.run_shadow_tracking --mode historical-bootstrap
   ```
   This walks all historical bars and writes `historical_bootstrap` records.
   The dashboard will show them on the next page load.
4. **Initialize true forward observation**:
   ```bash
   python -m tools.run_shadow_tracking --mode forward
   ```
   The first forward run sets the watermark at the latest completed bar and
   creates 0 forward records. Later manual forward runs only record signals from
   newer completed bars. Historical bootstrap is replay, not true forward
   evidence -- the dashboard says so honestly.

**Safety:** `run_shadow_tracking` is record-only. No trades are placed, no
paper portfolio is mutated, no order/broker/execution code exists in this repo.
`can_place_orders()` remains `False`.

## Dashboard manual refresh

When `DASHBOARD_PASSWORD` is set and a Railway volume is mounted at `/mnt/data`,
the dashboard can run a protected manual refresh from the "Refresh Data +
Shadow" button. This calls `POST /admin/refresh` with a fixed action header,
fixed symbols (`SPY`, `GLD`), and fixed start date (`2000-01-01`).

The route requires:

```bash
REAL_DATA_DIR=/mnt/data/real
SHADOW_STATE_PATH=/mnt/data/shadow_state.json
```

It refreshes market CSV/meta files into `REAL_DATA_DIR`, then updates the shadow
ledger in forward observation mode. If no forward watermark exists, it
initializes one and waits for the next completed bar. It does not place trades,
create orders, run on a schedule, poll the dashboard, or mutate the paper
portfolio.

## Railway Cron refresh

To avoid forgetting manual refreshes, create a separate Railway Cron service
from the same repo if desired. Mount the same volume at `/mnt/data` and set:

```bash
REAL_DATA_DIR=/mnt/data/real
SHADOW_STATE_PATH=/mnt/data/shadow_state.json
FORCE_PAPER_ONLY=true
```

Use this command:

```bash
python -m tools.refresh_lab --symbols SPY GLD --start 2000-01-01
```

Suggested cron schedule:

```text
30 22 * * 1-5
```

Railway cron uses UTC. `22:30 UTC` is after the regular US market close during
typical market hours. This command is a one-shot data/evidence refresh: it
downloads SPY/GLD data into `REAL_DATA_DIR`, runs true forward observation, and
exits when complete. It is not an in-app scheduler, daemon, polling loop, or
trading process.

## Tests

```bash
python -m compileall -q src tests tools
python -m unittest discover -s tests
```
