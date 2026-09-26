# API contract and verification evidence

Checked 2026-09-23. This release trades only in a local PAPER ledger. Public API success is not evidence of order execution, authenticated account access, exchange protection, profitability, or deployment.

## Public contract

Primary references: [Market Data](https://www.bitget.com/docs/catalog/market/market-data) and [Derivatives and Funding Rate](https://www.bitget.com/docs/catalog/market/derivatives).

| UTA v3 endpoint | Used contract |
| --- | --- |
| GET /api/v3/market/instruments | category=USDT-FUTURES; crypto perpetual contracts; quantityMultiplier and priceMultiplier are increments, while precision fields constrain decimals. listed is prelaunch; online is tradable. |
| GET /api/v3/market/tickers | Matching symbol/category, bid1Price, ask1Price, lastPrice, markPrice, indexPrice and millisecond ts. |
| GET /api/v3/market/candles | 1H and 1m market-price OHLC; documented page maximum 1000. |
| GET /api/v3/market/history-candles | Documented page maximum 100, endTime boundary, OHLC rows. |
| GET /api/v3/market/current-fund-rate | Matching symbol; decimal fundingRate and nextUpdate in milliseconds. |
| GET /api/v3/market/history-fund-rate | resultList with fundingRateTimestamp; numeric cursor pages 1..100 and limit <=100; documented retention 90 days. |

All listed endpoints are documented at 20 requests/second/IP. Pagination here is sequential. Request time spans, row continuity and funding coverage still require local validation.

## Observed public behavior and fixes

Actual unauthenticated public-check returned fresh quotes, supported instruments and 300 closed hourly bars for BTCUSDT, ETHUSDT, SOLUSDT and XRPUSDT. It sent no API key and no orders.

A public history probe compared three pages for each cursor rule. Setting the next endTime to the earliest returned bar timestamp gave a one-hour boundary gap (continuous data). Subtracting one millisecond gave a two-hour boundary gap (one missing bar). Both MarketClient internal pagination and CLI download now preserve the exact earliest timestamp. Completion is filtered against each call's original cutoff. Gap/duplicate checks remain mandatory; no missing bars are synthesized.

The implementation previously requested 200 historical rows; it now requests at most 100. Prelaunch listed status is no longer accepted by cash-risk sizing. Market metadata is a current snapshot. The fixed 1% maintenance-margin input is a conservative research assumption, not exchange risk-tier data or a liquidation guarantee.

## Authentication and execution boundary

[Quick Start](https://www.bitget.com/docs/uta/quick-start) defines Base64 HMAC-SHA256 over timestamp, uppercase method, path, optional encoded query, and transmitted body. Tests independently reconstruct signatures from the actual outgoing bytes. Production authenticated transport only permits GET account info/settings. Credentials have no printable fields, upstream error bodies are not echoed, redirects are rejected, and only the fixed Bitget HTTPS origin is allowed.

[Demo REST](https://www.bitget.com/docs/uta/demo-trading/rest-api) requires separately created demo keys and paptrading=1. DemoTransport is an opt-in transport primitive, disconnected from the paper engine. Its tests are mocked; no demo order was sent. POST is never automatically retried.

[Best Practices](https://www.bitget.com/docs/uta/best-practices-guide) distinguishes request acceptance from fill confirmation. A future execution engine must durably persist intent, reconcile ambiguous responses and partial fills, verify protective orders remotely, and recover after restart. Those requirements remain unimplemented; demo/live configuration stays blocked. No withdrawal/transfer paths exist.

## Reproduction

From the project directory in PowerShell:

```powershell
$env:PYTHONPATH=(Join-Path (Get-Location) 'src')
python -m pytest -q tests/test_exchange.py tests/test_risk.py tests/test_strategy.py tests/test_research.py -p no:cacheprovider
python -m bitget_bot public-check
python -m bitget_bot download --days 180 --output artifacts/history_180d_20260923.json
python -m bitget_bot research --input artifacts/history_180d_20260923.json --output artifacts/research_180d_20260923.json
```

Mocked regression evidence: 48 tests passed after contract fixes. Historical report conclusions and remaining data limitations are recorded separately in docs/RESEARCH_FINDINGS.md; no result automatically changes operating settings.
