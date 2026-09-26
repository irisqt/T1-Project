# Strategy research v2 — preregistration

Registered 2026-09-23 before running new candidate returns. User scope: strategy quality and net profitability. This is research, with unchanged cash-risk limits and no live promotion.

## Data and separation

Use BTCUSDT/ETHUSDT/SOLUSDT/XRPUSDT current-universe public hourly candles, extending to 720 days if available. The absolute original holdout starts **2026-08-19 01:00 UTC** and ends **2026-09-23 04:00 UTC**. Extending the dataset must never move that cutoff. Save source hashes and actual coverage. New hypotheses know the previous development failures; retrospective validation is not independent prospective evidence.

Development ends at the absolute holdout boundary. First 800 available hours are warmup. Divide the remaining development window into six chronological blocks. Compare the same fixed candidates in each block plus a continuous development simulation. All four assets share cash and the existing risk caps. Include the original breakout24 and an all-cash baseline. Do not increase risk or leverage to make returns larger.

## Fixed candidates (six, including baseline)

1. `baseline_breakout24`: original 1H breakout24/EMA100, 2 ATR initial stop, 12H channel trail, 48H maximum hold.
2. `trend4h_20`: UTC-complete 4H breakout20, EMA100 direction and 3-bar slope, efficiency ratio24 >= 0.25; 2.5 ATR14 initial stop; 3 ATR chandelier based on last 12 complete 4H highs/lows, activated only once closed-price profit reaches initial risk; 168H max hold.
3. `trend4h_40`: same, breakout40. This is the single preregistered slower neighbor.
4. `pullback4h`: 4H EMA20/EMA100 direction and EMA100 3-bar slope; efficiency24 >= 0.25; close crosses EMA20 back into the trend following a pullback; same stop/trail/hold as trend4h.
5. `range1h`: 1H close re-enters a 48H two-standard-deviation band; latest complete 4H efficiency24 <= 0.25 and EMA100 3-bar displacement <= 0.3 of 4H ATR14; target is next-open exit following a close at the 48H mean; 2 ATR14 initial stop, no trailing, 24H maximum hold.
6. `range4h`: corresponding 4H 24-bar band re-entry, efficiency24 <= 0.25 and same neutral slope condition; 2 ATR14 initial stop, next-open mean exit, no trailing, 72H maximum hold.

All new candidates: cooldown 8H; initial stop distance must be at least 4 times baseline modeled round-trip costs; mean-reversion target distance must also exceed 4 times baseline costs and initial stop distance. Baseline cost is fixed at 6bp fee + 4bp slippage per side for signal gating, even in cost-stress runs. No symbol/direction selection after looking at results. No additional parameter grid or candidate additions during this study.

## Causality and execution

Only complete UTC-aligned 4H groups containing all four consecutive hours count. Decisions use completed bars; fills use the following hourly open with adverse slippage. Stops are active before each execution bar. Closed-bar strategic exits wait for next open; gaps through stops take precedence. Trailing uses only completed bars and never loosens. Same initial cash-risk sizing for all candidates. Hourly stop ordering, current contract rules, 1% maintenance assumption, and adverse estimated funding are explicit limitations. Correct documented backtest/paper risk-halt mismatches before comparison, preserving original result artifacts.

## Evaluation and decision rule

Run each fixed candidate with baseline and doubled fees/slippage; do not retune signal hurdles in stress. Report continuous net return, gross price edge, fees/slippage/funding, PF, drawdown, turnover, holding time, symbol/direction contributions and all six block results. Original losses remain visible. Apply one-hour delayed-entry stress to any qualifying finalist.

A research finalist requires: positive continuous development net return; PF >= 1.15; at least 80 development trades; at least four of six blocks positive at baseline; positive continuous doubled-cost result and at least three of six stress blocks positive; continuous drawdown < 8%; removing the best-contributing symbol leaves positive aggregate trade PnL. Choose at most one passing candidate by median development-block net return (then smaller drawdown, then candidate name). Cash is preferred when none qualify.

Freeze the finalist configuration, source/data hashes and selection report before any holdout calculation. Only that finalist and baseline may receive one final holdout evaluation. No switching to another candidate using holdout results. If no finalist qualifies, leave holdout sealed and report failure honestly. A short holdout cannot establish live readiness. Optional shadow paper observation is distinct from replacing the active strategy.

For a finalist, report a deterministic 5,000-resample seven-day moving-block bootstrap interval of daily development return and a selection-aware family test across the fixed candidate return streams; these are diagnostics, not proofs of future profit. No candidate is automatically promoted to live.

## Primary methodological reference

[Bailey et al., The Probability of Backtest Overfitting](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf) motivates controlling the number of trials and separating selection from final evaluation. It does not validate these crypto strategies.
