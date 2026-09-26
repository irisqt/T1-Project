# Exploratory research findings — 2026-09-23

The current fixed candidates do not establish positive expectancy. Each candidate has negative aggregate model PnL across the three development folds, at both baseline and doubled fees/slippage. No strategy was selected or promoted. The final holdout remains unevaluated.

## Dataset and procedure

- Actual public Bitget UTA market-price 1H OHLC: 4 symbols, 4319 identical contiguous complete bars each.
- Symbols: BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT.
- Downloaded candle window: 2026-03-27 05:00 UTC through 2026-09-23 04:00 UTC.
- Warmup: 106 hours. Development folds: 1123, 1123 and 1124 hours, approximately 47 days each.
- Sealed holdout: 2026-08-19 01:00 UTC through 2026-09-23 04:00 UTC.
- Each fold starts with independent 10,000 USDT model capital; all four symbols share that capital and aggregate risk caps. Positions are closed at fold end.
- Baseline model: 6 bp fee and 4 bp adverse slippage on each side; cost stress doubles both before sizing. Funding is an adverse 1 bp per 8 hours estimate for either direction, not actual historical settlements.
- Primary report supplies observed current contract increments/minima. Historical contract changes are unmodeled; maintenance margin remains a fixed 1% assumption.

## Results

| Candidate | Cost multiple | Fold 1 / 2 / 3 net returns | Model trades | Pooled trade PF | Worst fold drawdown |
| --- | ---: | --- | ---: | ---: | ---: |
| breakout24 | 1 | -4.879% / -0.557% / -2.686% | 320 | 0.526 | 5.123% |
| breakout24 | 2 | -5.385% / -1.369% / -3.534% | 321 | 0.402 | 5.539% |
| breakout48 | 1 | -5.097% / +0.103% / -2.142% | 261 | 0.478 | 5.182% |
| breakout48 | 2 | -5.240% / -0.646% / -2.773% | 261 | 0.370 | 5.344% |
| momentum48 | 1 | -6.228% / -0.169% / -5.115% | 713 | 0.588 | 6.687% |
| momentum48 | 2 | -7.191% / -2.677% / -6.320% | 718 | 0.440 | 7.562% |

These fold returns must not be added and called a continuous portfolio return. Pooled PF is the sum of positive completed-trade net PnL divided by the absolute sum of negative completed-trade net PnL across independent folds. Doubled costs change position sizes and sometimes trade sets. Drawdown includes open/close marks and a conservative simultaneous intrabar adverse bound; it is not an observed synchronized tick path.

## Evidence and limits

- `artifacts/history_180d_20260923.json`: public dataset, source timestamp and availability notes.
- `artifacts/instruments_20260923.json`: current public contract snapshot.
- `artifacts/research_180d_current_rules_20260923.json`: primary report, all model trades/equity samples, SHA-256 input fingerprints and explicit limitations.
- `artifacts/research_180d_20260923.json`: separately retained default CLI report with assumed contract rules; do not confuse it with the primary report.
- `artifacts/research_summary_20260923.json`: compact table data.
- `artifacts/public_check_20260923.json` and `artifacts/public_recovery_data_check_20260923.json`: actual public quote/candle/funding smoke-check summaries. No authenticated access or orders occurred.

The current-universe selection, short development history, approximate hourly stop ordering, unavailable historic order books/mark triggers, estimated funding, current contract rules and excluded infrastructure expense prevent live-readiness claims. The three fixed development folds are not six walk-forward fitting/evaluation cycles or an independent 12-month OOS. Profit-factor and trade-count policy gates, long forward paper/demo evidence and execution recovery evidence remain unsatisfied.

Keep PAPER for software/operational evidence only. These results provide no basis for exposing account funds or claiming profit. Future hypotheses need a new preregistration and separate data policy; repeatedly testing variants on the sealed holdout would invalidate it.

## Offline reproduction

The primary report uses `run_research(dataset, load_settings("config/paper.toml"), instruments=snapshot)` with `Candle(**row)` dataset entries and `Instrument(**row)` entries from the saved snapshot. Do not pass `evaluate_holdout=True`. Input SHA-256 values are embedded in the primary report. The default CLI reproduction command is documented in API_CONTRACT.md and deliberately labels its assumed contract rules.
