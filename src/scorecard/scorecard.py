"""Scorecard — one honest verdict per (strategy, instrument).

Honesty rules enforced here:
1. Compares the strategy against buy-and-hold for the same instrument/window.
2. A profitable strategy that lags buy-and-hold says so plainly.
3. Flags concentration risk when most gross profit comes from one/few trades.
4. Synthetic data is gated: numbers are shown but NEVER labelled as evidence.
5. Surfaces data provenance: source, synthetic flag, split/dividend adjustment.
6. Evidence language only — no predictions (guarded by tests/language.py).
"""

from __future__ import annotations

from ..backtest.engine import BacktestResult, compounded_return
from ..backtest.expectancy import expectancy_report
from ..data.base import DataMeta
from ..safety.gate import candidate_status

CONCENTRATION_TOP1_LIMIT = 0.50   # one trade >50% of gross profit -> flag
CONCENTRATION_TOP3_LIMIT = 0.80   # top three >80% -> flag


def concentration(returns: list[float]) -> dict:
    """How much of the gross winning profit comes from the largest trade(s)."""
    winners = sorted((r for r in returns if r > 0), reverse=True)
    gross = sum(winners)
    if not winners or gross <= 0:
        return {"flagged": False, "winners": len(winners), "top1_share": 0.0,
                "top3_share": 0.0, "note": "No winning trades to concentrate."}
    top1 = winners[0] / gross
    top3 = sum(winners[:3]) / gross
    flagged = (top1 >= CONCENTRATION_TOP1_LIMIT) or (top3 >= CONCENTRATION_TOP3_LIMIT) or len(winners) < 5
    if flagged:
        note = (f"Concentration risk: {top1*100:.0f}% of gross profit came from one "
                f"trade ({len(winners)} winners total). One lucky winner is not proven edge.")
    else:
        note = "Profit is spread across multiple winning trades."
    return {"flagged": flagged, "winners": len(winners),
            "top1_share": round(top1, 3), "top3_share": round(top3, 3), "note": note}


def build_scorecard(result: BacktestResult, meta: DataMeta) -> dict:
    report = expectancy_report(result.returns)
    strat_return = compounded_return(result.returns)
    bh_return = result.buy_and_hold_return
    conc = concentration(result.returns)

    # Benchmark comparison (only meaningful with real data + some trades).
    if not result.returns:
        vs_benchmark = "n/a"
    elif strat_return > bh_return:
        vs_benchmark = "beats"
    else:
        vs_benchmark = "lags"

    grade = meta.evidence_grade()

    # Headline. Synthetic data can never read as evidence, whatever the numbers.
    if meta.synthetic:
        headline = "PIPELINE VALIDATION ONLY — synthetic data, not evidence"
    elif not report.enough_data:
        headline = "NO EDGE YET — not enough data"
    elif not report.distinguishable_from_zero:
        headline = "NO EDGE — indistinguishable from zero"
    elif report.expectancy > 0 and vs_benchmark == "lags":
        headline = "POSITIVE EXPECTANCY AFTER COSTS, BUT LAGS BUY-AND-HOLD"
    elif report.expectancy > 0:
        headline = "POSITIVE EXPECTANCY AFTER COSTS (research-only)"
    else:
        headline = "NEGATIVE — lost paper money after costs"

    # Verdict, in evidence language.
    parts: list[str] = []
    if meta.synthetic:
        parts.append("Synthetic sample data: these numbers validate the pipeline "
                     "only and are not evidence that anything works.")
    else:
        parts.append(report.verdict)
        if result.returns:
            cmp_word = "beat" if vs_benchmark == "beats" else "lagged"
            parts.append(f"Historically tested, the strategy {cmp_word} buy-and-hold "
                         f"({strat_return*100:.1f}% vs {bh_return*100:.1f}% over the window).")
        if grade == "real_unverified_adjustment":
            parts.append("Data adjustment for splits/dividends is unknown, so equity "
                         "returns may be distorted. Treat as research-only.")
    if conc["flagged"]:
        parts.append(conc["note"])

    gate = candidate_status(recommendation="Research-only. Keep collecting evidence.")

    return {
        "strategy": result.strategy,
        "instrument": result.instrument,
        "headline": headline,
        "verdict": " ".join(parts),
        # provenance
        "data_source": meta.source,
        "synthetic": meta.synthetic,
        "price_adjustment": meta.adjustment,
        "evidence_grade": grade,
        # evidence
        "trades": report.n,
        "win_rate": round(report.win_rate, 4),
        "expectancy_per_trade": round(report.expectancy, 6),
        "enough_data": report.enough_data and not meta.synthetic,
        "distinguishable_from_zero": report.distinguishable_from_zero and not meta.synthetic,
        # benchmark
        "strategy_return": round(strat_return, 4),
        "buy_and_hold_return": round(bh_return, 4),
        "vs_benchmark": vs_benchmark,
        # risk
        "concentration": conc,
        # gate
        "required_human_approval": gate.required_human_approval,
        "ready_for_pilot": gate.ready_for_pilot,
    }
