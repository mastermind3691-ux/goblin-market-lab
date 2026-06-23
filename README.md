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

## Tests

```bash
python -m compileall -q src tests tools
python -m unittest discover -s tests
```
