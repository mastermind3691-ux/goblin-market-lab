# AGENTS.md — Goblin Market Lab

> Read this before touching anything. This is a **clean, paper-only research lab**
> for non-crypto markets (ETFs, indices, gold; stocks later). It is a *sibling*
> of the Tiny Goblin BTC bot — **not a fork, not an extension of it.** The whole
> point of this repo is to stay small and honest where the BTC bot grew crowded.

---

## Hard rules (never violate without an explicit human decision recorded here)

1. **Paper-only. No live trading.** There is no execution plane in this repo.
2. **Do not add broker or order-placement code.** Not gated, not "just in case",
   not behind a flag. `src/safety/gate.py:can_place_orders()` returns `False`
   structurally; if you ever want it to return `True`, stop and ask the human.
3. **No automatic strategy promotion.** `candidate_status()` always returns
   `required_human_approval=True` and `ready_for_pilot=False`. Code recommends;
   a human decides.
4. **No CFDs and no leverage** until a human explicitly approves it later. MVP is
   cash-equity paper math only.
5. **Honesty over confidence.** If a rule lacks data or edge, the system must say
   so plainly ("NO EDGE YET — not enough data"). Never manufacture confidence.
6. **`FORCE_PAPER_ONLY=true` is the default and stays the default.**

If a task seems to require breaking any of these, do not do it. Explain the
conflict and wait for the human.

---

## Architecture rules (how to keep it clean)

- **Keep modules small and single-purpose.** No file should accumulate unrelated
  responsibilities.
- **Never create a giant `dashboard.py` monolith.** The BTC bot's `dashboard.py`
  is ~32k lines doing everything; that is the anti-pattern this repo exists to
  avoid. The web layer (`src/web/app.py`) is presentation only and must stay thin.
  If it grows, split routes into separate modules — do not let it absorb logic.
- **No embedded giant HTML strings.** All markup lives in `src/web/templates/`.
  Do not render pages from Python string templates.
- **Strategies are pure functions** from price history to a signal. They never
  touch the portfolio, never persist, never call the network, never place orders.
- **Snapshot/analytics code is read-only.** It must not mutate portfolio or state.
- **Do not copy the BTC bot wholesale.** Reuse *concepts* (safety separation,
  evidence-first, atomic persistence, read-only notifications). Do not paste its
  code, its `*_eur` legacy field names, its 10 rooms, or its many overlapping
  research layers.
- **Currency-neutral naming.** No `*_eur` legacy labels. Say what you mean.
- **Optional auth lives in `src/web/auth.py`, not in `app.py`.** When
  `DASHBOARD_PASSWORD` is set, `/` and `/api/status` require HTTP Basic Auth;
  `/health` stays public; with no password set, dev behavior is unchanged. The
  password is read at request time, compared with `hmac.compare_digest`, and
  must never be rendered, returned, or logged.

---

## Evidence honesty rules (enforced in code + tests)

- **Benchmark everything.** Every scorecard compares the strategy against
  buy-and-hold for the same instrument and window. A strategy with positive
  expectancy that still lags buy-and-hold must say so plainly — the headline
  becomes "POSITIVE EXPECTANCY AFTER COSTS, BUT LAGS BUY-AND-HOLD".
- **Flag concentration.** If most of the gross profit comes from one or a few
  trades (top-1 ≥ 50%, top-3 ≥ 80%, or fewer than 5 winners), the scorecard
  flags it. One lucky winner is not proven edge.
- **Synthetic data is never evidence.** The sample CSVs carry
  `<symbol>.meta.json` sidecars marking them `synthetic: true`. Any scorecard
  built on synthetic data is headlined "PIPELINE VALIDATION ONLY" and has its
  `enough_data` / `distinguishable_from_zero` claims forced off. Do not remove
  this gate to make a demo "look better".
- **Label price adjustment.** Every `DataMeta` declares `adjustment`:
  `adjusted` | `unadjusted` | `unknown`. Unadjusted/unknown equity series
  distort returns, so the scorecard surfaces it and downgrades the evidence
  grade. A real vendor adapter must declare a truthful adjustment.
- **Evidence language only.** No prediction/hype words ("will go up", "safe
  trade", "guaranteed", etc.). Use "historically tested", "shadow signal",
  "not enough data", "positive expectancy after costs", "research-only",
  "lags buy-and-hold". `src/scorecard/language.py` lists the banned phrases and
  `tests/test_scorecard.py` fails if any appear in scorecard output. Keep them out.
- **CsvAdapter stays the offline/debug path.** Real data goes through a new
  adapter behind the same `MarketDataAdapter` interface (see
  `src/data/vendor_adapter.py`), which must return truthful `DataMeta`.

## Testing rules

- Tests focus on **math, accounting, and evidence logic** — expectancy,
  portfolio fills, fee handling, persistence/migration, the safety guarantee.
- **Do not write brittle UI-substring tests.** The BTC bot's suite asserts on
  rendered HTML substrings and exact `/api/status` keys, which makes every UI
  tweak break tests. Test behavior and numbers, not page text.
- Every evidence/expectancy result must be **honest about sample size and fees**:
  below `MIN_SAMPLES` trades it must report "not enough data"; fees must be
  charged in the backtest (`fee_bps`), never assumed away.
- Run before and after changes:
  ```
  python -m compileall -q src tests tools
  python -m unittest discover -s tests
  ```

---

## Repository map

```
goblin-market-lab/
├── AGENTS.md, README.md, requirements.txt, .env.example, Procfile, railway.json
├── data/                      # sample CSV bars (offline v0.1 runs with no API key)
├── src/
│   ├── safety/                # the single safety chokepoint (gate.py)
│   ├── data/                  # read-only market-data adapters (interface + CSV)
│   ├── instruments/           # watchlist + per-instrument metadata (fees, sessions)
│   ├── strategies/            # pure signal functions (hypotheses, not truths)
│   ├── backtest/              # replay engine + honest expectancy report
│   ├── paper/                 # paper portfolio, shadow tracker, atomic persistence
│   ├── scorecard/             # one honest verdict per (strategy, instrument)
│   └── web/                   # thin Flask app + templates (presentation only)
├── tools/                     # run_backtest.py (offline CLI)
└── tests/                     # math/accounting/evidence/safety tests
```

There is **deliberately no `execution/`, `broker/`, or `orders/` folder.** Its
absence is a feature.

---

## What each folder is for (and what must NOT go in it)

- **`src/safety/`** — the only place that answers "are we still safe?". Read-only.
  Must not import anything that could trade.
- **`src/data/`** — read-only bar adapters behind one interface. No API keys in
  the interface; no order code; no look-ahead.
- **`src/instruments/`** — explicit watchlist + honest cost/session metadata. No
  strategy logic, no crypto 24/7 assumptions.
- **`src/strategies/`** — pure functions producing BUY/SELL/HOLD. No side effects.
- **`src/backtest/`** — deterministic replay with fees; honest expectancy. No
  live data, no look-ahead.
- **`src/paper/`** — simulated accounting + forward shadow records + atomic,
  migration-safe persistence. No real money, no orders.
- **`src/scorecard/`** — beginner-readable verdicts. Says "no edge yet" loudly.
- **`src/web/`** — thin presentation. Templates only; no business logic; never a
  monolith.

---

## Roadmap gates (each stage must be honestly done before the next)

0. Plumbing: data adapter + instruments, no strategy. ✅ (CSV adapter in place)
1. Backtest + honest expectancy. ✅
2. Shadow / paper-forward tracking (record what a rule *would* do; never execute).
3. Paper portfolio simulation + scorecards over time.
4. *(Much later, human-approved only)* anything beyond paper. Live stays a wall.

Telegram is **not in MVP.** If added later, it is **outbound and read-only only**
(notifications), and can never mutate state from chat.

---

## Definition of done for a change

1. Modules stayed small; no monolith formed; no HTML in Python.
2. No order/broker/leverage code added.
3. Tests cover the math/accounting you touched; no brittle UI-substring tests.
4. Evidence output stays honest about sample size and fees.
5. `compileall` + `unittest` pass.
6. Do not commit or push unless the human explicitly says to.
