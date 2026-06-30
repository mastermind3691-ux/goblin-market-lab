# Research Note: Machine Learning - Lorentzian Classification

**Indicator Name:** Machine Learning: Lorentzian Classification (by @jdehorty)
**TradingView URL:** https://www.tradingview.com/script/WhBzgfDu-Machine-Learning-Lorentzian-Classification/
**Review Date:** 2026-06-30

---

## 1. Summary
* **What it claims to do:** It uses a machine learning approach—specifically a k-Nearest Neighbors (k-NN) algorithm—to classify market data into bullish or bearish states by finding historical similarities. 
* **Market/timeframe:** It is a general-purpose indicator designed to work across various markets (crypto, forex, equities). The indicator page describes default feature settings as optimized for 4H to 12H for most charts.
* **Type:** It functions as a signal generator and classifier, often used as a core component of a full strategy or a sophisticated confluence filter.

## 2. Mechanism
* **Lorentzian Distance / Nearest-Neighbor:** In plain English, the script compares the current market conditions against thousands of historical data points. Instead of using traditional straight-line (Euclidean) distance to find the "closest" historical matches, it uses Lorentzian distance. This metric handles extreme market outliers (fat tails) and noise much better, allowing it to accurately cluster similar past price action to project potential future moves.
* **Features:** The classifier is fed by multiple customizable technical features, including RSI, WaveTrend, CCI, and ADX. It also employs various filters like EMA, SMA, and volatility/regime filters, alongside kernel regression for smoothing.
* **Bar-Close Confirmation:** The script evaluates its logic continuously, meaning signals can flicker intrabar. However, confirmed signals rely strictly on the **bar close**.

## 3. Repainting / Lookahead Risk
* **Repainting:** The author and community confirm that the indicator **does not repaint** once a bar has fully closed. Signals generated on historical closed bars will remain fixed.
* **Confirmation:** Signals must only be confirmed and acted upon after the bar close. Intrabar signals are preliminary.
* **Lookahead Risk:** Standard Pine Script features used in the indicator appear causal. However, advanced smoothing techniques like kernel regression can sometimes inadvertently introduce centered-window or lookahead biases depending on how they are implemented. Since a full line-by-line audit of the raw Pine Script wasn't fully executable here, we must clearly state: **A strict no-lookahead audit of the source code is required before trusting it in any forward simulation.**

## 4. Overfitting Risk
* **Knobs/Settings:** The indicator has numerous configurable settings, including the number of neighbors (k), the choice and weighting of features (RSI, ADX, etc.), and the lengths of various filters (EMA, volatility).
* **Curve-Fitting Risk:** With so many multidimensional knobs, it is extremely easy to tweak the settings until the indicator perfectly predicts past data (curve-fitting). 
* **ML Illusion:** Despite the "Machine Learning" label, it is fundamentally a distance-based nearest-neighbor algorithm. It possesses no inherent magic to predict the future and still absolutely requires rigorous out-of-sample and walk-forward validation to prove any true edge.
* **Update / New Knob:** The script has been upgraded to Pine Script v6. It now includes an “Include Full History” option for neighbor selection. Treat this as another parameter/behavior knob that must be included in overfitting and robustness review.

## 5. Trade Stats Caveat
* **Not a backtest substitute:** Built-in Trade Stats are not a substitute for proper backtesting.
* **Entry assumption risk:** Default stats may estimate performance from mid-bar entries, which is unrealistic.
* **Goblin standard:** Any Goblin test must strictly use a confirmed bar-close signal and a next-bar-open fill.
* **Costs:** Must include proper fees and slippage.

## 6. Tiny Goblin / Goblin Market Lab Safe Use
* **Classification:** research-only watchlist
* **Safe Use Cases:** 
  * It could be highly useful as a **context/regime feature** or a **confluence filter** to augment other simpler strategies.
  * It may serve as an interesting **shadow signal** for a purely paper/forward-tracking lab experiment to gather live out-of-sample data.
* **Why it shouldn't be trusted directly:** The sheer number of parameters means any historical edge could just be an overfit mirage. It should never be trusted blindly for active trading without overwhelming, multi-regime, out-of-sample evidence.

## 7. Suggested Safe Test Plan
If we decide to test this further, it must follow this strict structure:
* **Asset:** BTC first.
* **Timeframe:** 4H first.
* **Mode:** research-only.
* **Fill assumption:** Next bar open after a confirmed signal (strictly post-close).
* **Include:** Full fees and slippage in all accounting.
* **Compare against:**
  * Buy-and-hold BTC
  * S2 Bollinger Regime 4H (if available in project notes)
  * Simple EMA/RSI baseline
  * Random/baseline holdout (if easy)
* **Required Validation:**
  * Out-of-sample / walk-forward testing.
  * Regime split (bull vs. bear vs. crab market performance).
  * One-lucky-trade concentration check (ensuring edge isn't from 2 huge trades).
  * Parameter robustness / jitter (does changing `k` by 1 ruin the strategy?).
  * Drawdown check.
  * Trade count minimum (requires statistical significance).
  * No-lookahead audit.
  * No-repaint audit.

## 8. Final Verdict
`RESEARCH_ONLY_WATCHLIST`

**Goblin Verdict:** Has interesting math and handles noise well, but it has way too many shiny knobs. It might be useful as a context filter, but it needs a paranoid out-of-sample test to prove it isn't just curve-fitting the past. Do not trade it live.
