# Strategy loss audit — 2026-09-23

The existing candidates fail for both price selection and trading costs. Lower fees alone would not turn the recorded development trades into a profitable sample. Raising leverage or removing cash-risk limits does not repair this evidence.

## Evidence and scope

- Read-only analysis of `artifacts/research_180d_current_rules_20260923.json`, its development trade records, and the existing `strategy.py`, `research.py`, `engine.py`, `risk.py`, `exchange.py`, and `store.py` implementation.
- Report SHA-256: `af0886bb15530e4fc58ce3dd35702570edc3962cc9d784855102b9c07b763fa6`.
- Baseline costs: 6 bp fee and 4 bp adverse slippage per side, adverse funding estimate 1 bp per 8 hours.
- All figures below pool three development folds, each starting with an independent 10,000 USDT. Dollar PnL may be summed to diagnose losses; this is **not a continuous portfolio return**.
- The final holdout beginning 2026-08-19 01:00 UTC was not accessed or evaluated for this audit. The saved report has `holdout.evaluated=false` and an empty holdout result list.
- No parameter search, code changes, cloud changes, authenticated access, or orders were part of this audit. A separate, preregistered v2 study addresses the hypotheses described here.

## 1. Loss decomposition

USDT, rounded to cents:

| Candidate | Trades | Price PnL before modeled costs | Slippage drag | Fees | Funding debit | Net PnL |
|---|---:|---:|---:|---:|---:|---:|
| breakout24 | 320 | -338.03 | 173.56 | 260.34 | 40.32 | -812.25 |
| breakout48 | 261 | -348.76 | 133.31 | 199.96 | 31.59 | -713.62 |
| momentum48 | 713 | -217.20 | 347.14 | 520.71 | 66.16 | -1,151.21 |

The stored `gross_pnl` already includes adverse slippage. Its totals are -511.59, -482.07, and -564.34 respectively; calling these values frictionless gross alpha would be incorrect.

For a fixed recorded trade, reconstruct the unslipped model entry as `entry / (1 + side * 0.0004)` and the unslipped exit trigger as `exit / (1 - side * 0.0004)`. Price PnL is `side * (unslipped_exit - unslipped_entry) * qty`; the difference from stored gross is the modeled slippage drag. This is an accounting decomposition using the same trades, sizes, and stop paths, **not a fresh zero-cost backtest**. Different costs would change sizing and occasionally the trade set.

Costs explain much of the loss, especially for momentum48, but every candidate also loses on the reconstructed price component. Funding is comparatively small in this sample; removing the funding estimate alone cannot close the gap.

## 2. Losses are broad, not isolated to one coin or direction

Baseline pooled net USDT:

| Contribution | breakout24 | breakout48 | momentum48 |
|---|---:|---:|---:|
| BTCUSDT | -242.44 | -196.16 | -411.74 |
| ETHUSDT | -144.94 | -145.49 | -217.67 |
| SOLUSDT | -258.97 | -226.45 | -296.05 |
| XRPUSDT | -165.90 | -145.51 | -225.75 |
| Long | -378.50 | -438.88 | -571.09 |
| Short | -433.75 | -274.74 | -580.13 |

All four symbol contributions and both direction contributions are negative for all three candidates. Their reconstructed price components are also negative in each of these aggregates. Removing the worst coin, banning one direction, or treating this solely as an unfavorable directional market is not supported as a sufficient repair.

## 3. Winning trades do not compensate for stop losses

| Candidate | Observed win rate | Average net winner | Average net loser, absolute | Winner/loser ratio | Break-even win rate at observed payoff | Net expectancy/trade |
|---|---:|---:|---:|---:|---:|---:|
| breakout24 | 27.81% | 10.125 | 7.417 | 1.365 | 42.28% | -2.538 |
| breakout48 | 26.44% | 9.477 | 7.122 | 1.331 | 42.91% | -2.734 |
| momentum48 | 23.00% | 10.020 | 5.090 | 1.969 | 33.69% | -1.615 |

Break-even win rate is the descriptive ratio `average_loss / (average_win + average_loss)` on this sample, not a forecast.

Stops account for 304/320 breakout24 trades (-1,154.65 USDT), 249/261 breakout48 trades (-954.03), and 682/713 momentum48 trades (-1,699.84). Stop exits include profitable trailing exits and should not all be labeled losses.

The small groups reaching the 48-hour maximum holding time made +312.56, +208.46, and +515.06 USDT respectively. Trades lasting 25–48 hours contributed +647.42, +454.52, and +1,264.31, while all trades observed to last at most 12 hours lost money. Duration is determined after entry and is affected by the exit rules. These observations motivate testing different entry/exit mechanics; they do **not** justify a hindsight rule that keeps only long-lived trades, removing protective stops, or assuming longer holds will be profitable.

## 4. Momentum re-entry churn is a concrete weakness

The momentum signal tests whether the current close is more than one ATR above/below the close 48 hours earlier, alongside EMA direction and slope. This is a persistent state, not a new crossing. After a stop and the two-hour cooldown, the same stale directional condition can generate another trade.

Counting consecutive trades within the same symbol and development fold:

| Candidate | Same-direction re-entries within 3 hours of preceding exit | Their net PnL | Other trades' net PnL |
|---|---:|---:|---:|
| breakout24 | 11 / 320 | -2.80 | -809.45 |
| breakout48 | 7 / 261 | -38.06 | -675.56 |
| momentum48 | 401 / 713 | -720.37 | -430.84 |

Momentum48's rapid same-direction re-entries represent 56.2% of trades and 62.6% of its net loss. An entry that requires a fresh state transition, pullback recovery, or a slower completed-bar signal is a testable repair. These retrospective buckets cannot establish that simply deleting the repeated trades would produce the same subsequent portfolio path; the remaining momentum trades are negative as well.

## 5. Backtest versus forward-paper discrepancies

These are findings in the **original implementation before v2 parity corrections**. They should be addressed or disclosed in the new study while preserving the original artifacts.

| Area | Original historical simulation | Existing forward paper | Consequence |
|---|---|---|---|
| Drawdown/rolling-loss HALT | Force-closes every position, sometimes at a simultaneous adverse hourly bound | Prevents new entries; continues each open position's stop/time management | Different exit rules, outcomes, and trade durations once a halt occurs |
| Risk pause | Extends pause expiry on every hourly observation above threshold | Arms a new pause only after the preceding pause expires | Different entry eligibility during a persistent loss episode |
| Entry market quality | Next hourly open plus modeled slippage; no historical spread, basis, or extreme-funding filter | Fresh ask/bid plus slippage; spread, basis, and funding checks | Backtest cannot certify executable entries or measured transaction cost |
| Stop execution | Hourly range and gap trigger; stop time stamped at the hour end | Minute replay and current quotes; first partial entry minute is not reconstructed | Exit sequence and realized price can diverge; neither is an exchange fill |
| Funding | Adverse estimate on both directions without supplied settlements | Actual public settlement rates with a price proxy | Cost decomposition is model evidence, not actual historical funding PnL |
| Startup indicator history | Earliest fold begins with only 106 warmup hours | Normal operation requests 300 complete hours | Different SMA-seeded EMA histories near the beginning of the first fold |

All nine baseline development runs have zero refused entries and no permanent halt. Thus the main original losses are not explained by leverage refusal, portfolio capacity, or the forced-halt discrepancy. Pause incidence is not recorded in the old artifact and should not be inferred as zero. The discrepancies matter to future research and its comparability with paper.

The original trailing channel deliberately excludes the newest completed bar and activates later; both implementations share this rule. It is a documented one-bar lag, not a discovered look-ahead bug. Changing it should be a declared strategy variant, not silently relabeling a favorable result as a bug fix.

## 6. Highest-value next work

1. Preserve risk limits and correct simulation/paper exit and pause parity before comparing new candidates. Add explicit economic and execution diagnostics so a higher return cannot hide changed assumptions.
2. Reduce stale-signal churn through preregistered fresh-transition or slower-horizon entries, with a fixed cost-versus-stop/target hurdle. Compare both normal and doubled costs without tuning the entry hurdle to the test result.
3. Test a bounded set of distinct hypotheses: slower trend capture, trend pullback recovery, and mean reversion confined to a causally identified range regime. Evaluate the trade-off between early exits and profit retention without eliminating protective stops.
4. Extend development history backward and use several chronological blocks; preserve the original absolute holdout cutoff. No coin/direction cherry-picking or open-ended parameter sweep.
5. Require positive net evidence under costs and concentration checks before nominating a research finalist. If none qualifies, report that result and preserve cash as the benchmark.

The independent follow-on specification is `docs/STRATEGY_RESEARCH_V2_PROTOCOL.md`. This audit establishes why the existing candidates need replacement research; it does not establish that any proposed replacement has positive expected return.
