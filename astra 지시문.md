첨부파일:
CODEX_ASTRA_CRYPTO_FUTURES_MASTER_BUILD_SPEC.md

아래 지시문에 따라 이 설계도를 독립적으로 감사하고,
실제 수익성·OOS 강건성·실전 실행 안정성 측면에서 더 좋은 구조가 있다면
근거와 검증 방법을 제시하여 수정안을 만들어라.

[제가 작성해준 Astra 마스터 설계 감사·업그레이드 지시문 전체 붙여넣기]

중요:
지금은 절대 코드를 작성하거나 기존 파일을 수정하지 마라.
PART 1~7의 감사 결과만 작성한 뒤 멈춰라.
내가 승인한 후에만 V1.1 명세 확정 및 구현 단계로 넘어가라.


# ASTRA — CHIEF QUANT RESEARCHER / SYSTEM ARCHITECT REVIEW DIRECTIVE

현재 프로젝트에는 다음 마스터 설계문서가 존재한다.

`CODEX_ASTRA_CRYPTO_FUTURES_MASTER_BUILD_SPEC.md`

이 문서는 내가 여러 AI의 독립적인 분석을 비교·취합하여 만든 Bitget USDT-M 코인선물 24시간 자동매매 시스템의 현재 기준 설계다.

그러나 이 문서를 “정답”이라고 가정하지 마라.

너의 첫 번째 임무는 코딩이 아니다.

너는 지금부터 이 프로젝트의:

**Chief Quant Researcher
Chief System Architect
Risk Officer
Execution Engineer
Adversarial Reviewer**

역할을 동시에 맡는다.

목표는 기존 설계도를 그대로 구현하는 것이 아니라,

> **기존 설계를 공격하고, 틀린 부분은 제거하고, 부족한 부분은 보완하고, 더 높은 실전 기대수익과 더 강한 생존성을 동시에 달성할 수 있는 설계로 업그레이드하는 것이다.**

단, “높은 수익”을 단순 백테스트 CAGR 최대화로 해석해서는 안 된다.

우리가 실제로 최적화하고 싶은 것은:

**비용 차감 후 장기 복리 성장률 + 높은 Expectancy + 높은 Profit Factor + 높은 Calmar/Sortino**

이면서 동시에:

**Max Drawdown / Tail Risk / Risk of Ruin / Liquidation Risk / Execution Risk / Parameter Sensitivity / Overfitting**

을 통제하는 시스템이다.

---

# 0. 가장 중요한 기본 원칙

현재 MASTER SPEC의 모든 규칙을 두 종류로 구분하라.

## A. 절대로 임의 변경하면 안 되는 Safety Constitution

다음은 Alpha가 아니라 자본 보호와 운영 안전에 관한 규칙이다.

명확한 더 나은 대안이 입증되지 않는 한 유지한다.

* LIVE 거래 기본 OFF
* Demo/Paper 검증 전 Live 활성화 금지
* 출금 API 권한 금지
* API Secret 코드/로그/Git 저장 금지
* Exchange-side protective stop 필수
* Protective stop 설치 실패 시 naked leveraged position 유지 금지
* Local/Exchange position reconciliation 필수
* 데이터 stale / position mismatch / API 장애 시 신규 진입 금지
* Kill Switch
* Risk limit
* Look-ahead 금지
* Incomplete candle 사용 금지
* 미래의 Funding/OI/Universe 정보 사용 금지
* Sealed Holdout을 보고 다시 튜닝하는 행위 금지
* 실제 거래비용을 제거한 수익률로 전략 평가 금지
* Martingale / 무제한 Grid / 손실 복구 목적의 배팅 증액 금지

## B. 변경 가능한 Research Hypothesis

다음은 현재의 가설일 뿐이다.

더 좋은 근거가 있다면 적극적으로 변경하거나 폐기하라.

예:

* 4H EMA200 방향 필터
* 24H Donchian breakout
* 5M execution
* 0.10 × ATR breakout buffer
* Turnover Z threshold
* OI filter
* Funding Z threshold
* Premium Z threshold
* ATR stop multiplier
* Channel trailing
* Maximum holding time
* Re-entry cooldown
* 0.35% risk/trade
* 3× leverage cap
* 1D RV percentile 기준
* BTC/ETH/SOL/XRP universe

숫자가 기존 문서에 있다는 이유만으로 유지하지 마라.

모두 HYPOTHESIS다.

---

# 1. 기존 설계를 먼저 RED TEAM하라

코딩하기 전에 MASTER SPEC을 처음부터 끝까지 읽어라.

그리고 다음 질문으로 공격하라.

### Alpha

1. 현재 V1의 실제 Alpha는 무엇인가?
2. 단순한 Trend/Breakout beta를 Alpha라고 착각하고 있지 않은가?
3. 수익의 대부분이 BTC 장기 상승에 의존할 가능성은 없는가?
4. Short에서도 동일한 경제적 논리가 성립하는가?
5. 거래비용 이후에도 edge가 남을 가능성이 있는가?
6. 5M execution이 지나치게 noisy하지 않은가?
7. 15M/30M/1H execution이 오히려 Net Expectancy가 높을 가능성은 없는가?

### Feature

각 Feature를 다음 관점에서 다시 평가하라.

* 새로운 정보를 제공하는가?
* 다른 Feature와 정보가 중복되는가?
* prediction인가 risk filter인가?
* 시점 t에서 실제로 확보 가능한가?
* historical backtest 가능한가?
* 데이터 품질이 충분한가?
* live에서도 동일하게 계산 가능한가?
* 거래 수만 감소시키고 실제 expectancy는 못 높이는가?

다음 Feature는 특히 재평가한다.

* Price trend
* Breakout structure
* Realized volatility
* ATR
* Quote turnover
* Open Interest
* ΔOI
* OI acceleration
* Funding
* Funding Z
* ΔFunding
* Perpetual premium
* Basis
* Spread
* Liquidation
* Aggressive trade imbalance
* CVD
* Order-book imbalance
* Cross-sectional momentum
* BTC → Alt lead-lag
* Spot → Perpetual lead-lag
* Binance → Bitget lead-lag
* Trading session effect
* Weekend effect

---

# 2. 기존 전략보다 좋은 대안이 있다면 과감히 제안하라

현재 V1이:

**Higher-TF Trend → Breakout → Derivatives Filters → Risk Management**

구조라고 해서 이 구조를 보호하려고 하지 마라.

다음 후보들과 동일한 조건에서 경쟁시켜라.

### Candidate A

현재 Trend + Breakout V1

### Candidate B

Volatility Expansion Breakout

### Candidate C

Time-Series Momentum

### Candidate D

Cross-Sectional Momentum / Relative Strength

### Candidate E

Regime-specific Trend

### Candidate F

Range Mean-Reversion

단, Mean-Reversion은 Trend/Cascade 시장에서 반드시 차단되어야 한다.

### Candidate G

Price × OI × Funding state model

### Candidate H

Derivatives Crowding / Deleveraging model

### Candidate I

Lead-Lag model

### Candidate J

네가 발견한 더 좋은 구조

이 중 무엇이 가장 좋아 보이는지 말로 결정하지 마라.

동일한:

* Universe
* Data period
* Fee
* Slippage
* Funding
* Risk per trade
* Execution assumptions

을 사용하여 경쟁시키는 Research Plan을 설계하라.

---

# 3. “최고 수익률”을 찾지 마라

다음 방식은 금지한다.

> 수백 개 파라미터를 돌리고 가장 CAGR 높은 조합을 선택한다.

우리가 원하는 것은:

**Maximum Point가 아니라 Robust Plateau**

다.

예를 들어:

Donchian 24가 최고라도

20 / 22 / 24 / 26 / 28

전체가 비슷하게 양호하면 채택할 수 있다.

하지만:

23 = 손실
24 = 대박
25 = 손실

이면 24를 폐기하라.

ATR multiplier, timeframe, funding threshold, volume threshold 등 모든 핵심 파라미터에 이 원칙을 적용하라.

---

# 4. Alpha와 Risk를 절대로 섞지 마라

각 Feature를 반드시 아래 중 하나로 분류하라.

### ALPHA

미래 기대수익을 바꿀 가능성이 있는 정보.

### CONFIRMATION

기존 Alpha의 품질을 높이는 정보.

### RISK FILTER

나쁜 시장에서 거래를 막는 정보.

### EXECUTION FILTER

스프레드·유동성·슬리피지 문제를 방지하는 정보.

### PORTFOLIO FEATURE

종목선택/자본배분을 위한 정보.

### RESEARCH ONLY

현재 근거가 부족해 저장만 하는 정보.

예를 들어 Funding extreme이 실제 방향 Alpha가 아니라 crowding risk filter라면 그렇게 분류하라.

OI 역시 Long/Short 방향을 직접 알려준다고 가정하지 마라.

---

# 5. Feature를 추가하기보다 삭제하는 것을 우선하라

새 Feature를 넣을 때 다음 질문을 반드시 통과시켜라.

> 이것을 제거하면 OOS 성과가 실제로 나빠지는가?

Ablation을 수행한다.

예:

BASE

BASE + Volume

BASE + OI

BASE + Funding

BASE + Premium

BASE + OI + Funding

FULL

뿐 아니라 FULL에서:

* Volume 제거
* OI 제거
* Funding 제거
* Premium 제거
* Trend filter 제거
* RV filter 제거
* Spread filter 제거

도 시험한다.

Feature 제거 후:

* 수익 비슷함
* MDD 비슷함
* OOS 비슷함
* 거래 수 증가
* Parameter sensitivity 감소

라면 Feature를 삭제하라.

**더 단순한 전략이 같은 성능을 내면 단순한 전략이 승자다.**

---

# 6. Timeframe을 다시 최적화하라

현재:

1D = volatility risk
4H = direction
1H = structure
5M = execution

으로 되어 있다.

이 구조를 고정된 사실이라고 생각하지 마라.

다음과 같은 구조를 비교할 수 있다.

4H → 1H → 5M

4H → 30M → 5M

1H → 15M

1D → 4H → 15M

4H → 1H → 15M

단,

최고 수익 조합을 고르는 것이 아니라:

* Net expectancy / trade
* Profit / turnover
* Fee-to-gross-profit ratio
* OOS PF
* MDD
* Calmar
* parameter robustness

로 판단하라.

5M이 거래빈도만 늘리고 비용을 키운다면 과감히 버려라.

---

# 7. 거래빈도와 비용의 관계를 특히 분석하라

전략의 Gross Alpha가 아니라 Net Alpha를 측정한다.

반드시 포함:

* Maker fee
* Taker fee
* Bid/Ask spread
* Slippage
* Funding
* Partial fill
* Missed fill
* Latency
* Requote
* order rejection

다음을 반드시 계산하라.

`Gross PnL`

`Total Friction`

`Net PnL`

그리고:

`Friction / Gross Profit`

이 지나치게 높은 전략은 탈락시킨다.

---

# 8. Execution Alpha도 연구하라

전략 Alpha와 별도로 Execution을 개선하면 동일 전략의 Net Return을 높일 수 있다.

다음 비교를 설계하라.

Market

vs

Marketable Limit

vs

Post-only Limit + timeout + Market fallback

측정:

* fill probability
* missed trade cost
* adverse selection
* realized slippage
* fee difference
* final Net PnL

“Maker가 싸다”라는 이유만으로 선택하지 마라.

---

# 9. Position Sizing을 별도의 연구 문제로 취급하라

현재 0.35% fixed risk/trade가 기본이다.

다음과 비교하라.

* Fixed fractional risk
* Volatility targeting
* Drawdown adaptive risk
* ATR risk parity
* Portfolio volatility target
* correlation-adjusted allocation

Kelly는 연구 가능하지만 Production V1에 바로 사용하지 마라.

Full Kelly는 금지한다.

Sizing의 목적은 단순히 MDD를 줄이는 것이 아니다.

**동일한 전략 Alpha에서 장기 geometric growth를 최대화하면서 ruin 확률을 통제하는 것**이다.

---

# 10. Portfolio Layer가 단일 종목 전략보다 수익 개선에 기여하는지 확인하라

BTC / ETH / SOL / XRP를 단순히 각각 독립적으로 거래하지 마라.

다음을 연구하라.

* correlation cluster
* rolling beta to BTC
* volatility-normalized allocation
* signal ranking
* liquidity weighting
* cross-sectional momentum
* simultaneous signal selection

동시에 4개 코인이 Long이면 사실상 하나의 Crypto Beta position일 수 있다.

Portfolio level에서:

* gross exposure
* directional exposure
* cluster exposure
* total open risk

를 관리하라.

---

# 11. Market Regime을 더 잘 정의할 방법이 있는지 연구하라

현재 단순 EMA/RV보다 더 좋은 regime classification이 있는지 검토한다.

후보:

* Efficiency Ratio
* Variance Ratio
* rolling autocorrelation
* ADX
* realized volatility percentile
* trend slope / volatility normalized slope
* Donchian efficiency
* volume regime
* OI regime
* funding regime

하지만 Feature를 많이 넣어 Score model을 과최적화하지 마라.

처음에는 Rule-based 또는 매우 단순한 model을 선호한다.

ML을 사용하려면 반드시:

> ML이 없는 baseline보다 OOS에서 명확하게 개선되는가?

부터 증명하라.

---

# 12. Machine Learning은 자동으로 좋은 것이 아니다

XGBoost, neural network, Transformer 등을 사용한다는 이유만으로 더 좋은 시스템이라고 판단하지 마라.

ML은 다음 조건을 만족할 때만 후보로 올린다.

1. 충분한 표본
2. point-in-time Feature
3. leakage 없음
4. walk-forward
5. transaction cost 포함
6. simple baseline 대비 OOS improvement
7. explainable failure mode
8. stable calibration

복잡성에 비해 개선 폭이 작다면 폐기한다.

---

# 13. 새로운 Alpha 탐색 Branch를 따로 만들어라

Production V1과 Research를 분리하라.

### Production branch

검증을 통과한 전략만 포함.

### Research branch

다음을 연구한다.

* liquidation
* order flow
* CVD
* order book
* funding acceleration
* OI acceleration
* basis dynamics
* session effects
* lead-lag
* cross-sectional signals

Research 결과를 Production에 자동 반영하지 마라.

Research Acceptance Gate를 통과해야 한다.

---

# 14. 데이터부터 의심하라

백테스트 Alpha보다 먼저 Data Audit을 수행한다.

확인:

* timestamp alignment
* timezone
* candle completeness
* duplicate rows
* missing rows
* stale OI
* funding settlement alignment
* mark/index synchronization
* delisted contracts
* contract specification change
* symbol rename
* API maintenance gaps

잘못된 데이터로 높은 수익이 나오면 전략이 아니라 데이터 버그일 수 있다.

---

# 15. Research Pipeline을 엄격하게 유지하라

순서는:

Research Hypothesis

→ Train

→ Validation

→ Walk Forward

→ Sealed Holdout

→ Paper

→ Demo Cloud

→ Small Live

→ Scale

이다.

Holdout을 본 뒤:

“결과가 별로니까 threshold를 조금 바꾸자”

는 금지다.

그 순간 Holdout은 오염된다.

---

# 16. Multiple Testing을 관리하라

수십/수백 개 전략을 시험한 뒤 최고 Sharpe 하나를 고르면 안 된다.

모든 실험에:

* experiment ID
* hypothesis
* parameters
* tested universe
* date range
* result
* rejected/accepted
* reason

을 기록하라.

가능하면:

* Deflated Sharpe Ratio
* Probability of Backtest Overfitting
* Bootstrap
* parameter perturbation

등을 검토하라.

최소한 “몇 번의 전략/파라미터를 시험했는지”는 반드시 기록한다.

---

# 17. Stress Test를 더 강하게 하라

기본 백테스트 성과가 아무리 높아도 다음 테스트에서 무너지면 폐기한다.

* Fee ×1.5
* Fee ×2
* Slippage ×2
* Slippage ×3
* Spread shock
* adverse Funding
* execution 1 bar delay
* execution 2 bar delay
* random missed trades
* WebSocket downtime
* partial fill
* order rejection
* flash crash
* short squeeze
* correlation spike
* BTC crash / Alt cascade

우리가 원하는 것은:

**좋은 환경에서 많이 버는 전략**

보다

**환경이 나빠져도 edge가 완전히 사라지지 않는 전략**

이다.

---

# 18. Extreme Event Engine을 더욱 엄격히 검토하라

현재 설계에서 Extreme Event Engine은 Alpha generator가 아니다.

생존 시스템이다.

가격 충격 + OI 변화 + Spread 확대 + Mark/Index 괴리 + API 이상 등을 이용하여:

SAFE

DEGRADED

NO_NEW_ENTRY

HALTED

상태를 관리한다.

다만 기존 포지션을 “항상 즉시 시장가 청산”하는 것이 정말 최선인지도 연구하라.

Flash crash에서는 시장가 청산 자체가 극단적인 slippage를 만들 수 있기 때문이다.

상황별:

* hold with exchange stop
* reduce
* close
* no action

정책을 비교하라.

Safety logic도 백테스트/시뮬레이션 가능한 부분은 검증하라.

---

# 19. 성과 평가 순서를 바꾸지 마라

전략을 평가할 때 우선순위는:

1. Data validity
2. Look-ahead 없음
3. Net Expectancy > 0
4. OOS robustness
5. Parameter stability
6. Risk of Ruin
7. MDD / Tail Risk
8. Profit Factor
9. Calmar / Sortino
10. CAGR

이다.

CAGR이 높다는 이유로 앞의 항목들을 무시하지 마라.

---

# 20. 기존 V1보다 업그레이드된 V1.1을 제시하라

Audit가 끝난 후:

`MASTER STRATEGY V1.1`

을 작성한다.

반드시 다음을 포함한다.

DATA UNIVERSE

TIMEFRAMES

FEATURES

REGIME

LONG ENTRY

SHORT ENTRY

NO-TRADE

INITIAL STOP

TRAILING

TAKE PROFIT

TIME EXIT

RE-ENTRY

POSITION SIZING

LEVERAGE

PORTFOLIO RISK

CORRELATION LIMIT

EXECUTION METHOD

OI RULE

FUNDING RULE

PREMIUM/BASIS RULE

SPREAD RULE

EXTREME MARKET RULE

API FAILURE RULE

KILL SWITCH

RESTART RULE

각 항목은:

**KEEP / MODIFY / REMOVE / ADD**

중 하나로 표시하라.

그리고 반드시:

**기존 V1과 무엇이 달라졌는가**

를 설명하라.

---

# 21. 변경사항마다 증명 방법을 붙여라

“이게 더 좋아 보인다”는 이유는 인정하지 않는다.

예:

변경:

5M → 15M execution 제안

그렇다면 반드시:

### WHY

왜 더 나을 수 있는가.

### TEST

어떤 A/B Test를 할 것인가.

### PASS

어떤 결과가 나오면 채택할 것인가.

### FAIL

어떤 결과가 나오면 기존 5M을 유지할 것인가.

모든 주요 변경을 이 형식으로 작성하라.

---

# 22. Architecture도 검토하라

기존:

Python 3.12
Docker Compose
PostgreSQL
Google Compute Engine
Bitget REST + WS

구조가 적절한지 검토한다.

단, 기술 유행 때문에 Kubernetes, Kafka, Redis, Microservices 등을 무조건 추가하지 마라.

추가 기술은:

* 장애 복구
* 데이터 안정성
* latency
* observability
* maintainability

중 적어도 하나를 실질적으로 개선할 때만 채택한다.

1인 프로젝트라는 사실도 고려한다.

가장 단순하면서 안정적인 구조를 선호한다.

---

# 23. 24시간 운영 구조를 공격하라

다음 상황에서 시스템이 어떻게 살아남는지 확인하라.

* Python process crash
* Docker crash
* VM reboot
* Google maintenance
* Internet interruption
* Bitget maintenance
* Public WS disconnect
* Private WS disconnect
* REST timeout
* DB temporarily unavailable
* duplicate order request
* unknown order state
* position mismatch
* system clock drift
* stale market data

각 사건에 대해:

DETECTION

STATE TRANSITION

ACTION

RECOVERY

를 정의하라.

---

# 24. 코드 작성 전에 반드시 산출할 문서

아직 코딩하지 마라.

우선 다음 문서를 생성하라.

`docs/ASTRA_MASTER_AUDIT.md`

내용:

1. Existing architecture summary
2. Major strengths
3. Major weaknesses
4. Dangerous assumptions
5. Unnecessary complexity
6. Missing features
7. KEEP / MODIFY / REMOVE / ADD table
8. Alpha research candidates
9. A/B Test matrix
10. V1.1 proposal
11. Expected advantages
12. New risks introduced
13. Research priority

그리고:

`docs/STRATEGY_V1_1_SPEC.md`

를 생성하라.

이 파일은 코드로 직접 옮길 수 있을 정도로 구체적이어야 한다.

---

# 25. V1을 무조건 바꾸려고 하지 마라

매우 중요하다.

새로운 모델이 더 복잡하다는 이유만으로 우월한 것이 아니다.

Audit 결과:

> 기존 V1이 가장 합리적이다.

라는 결론도 허용한다.

변경은 **증명 가능한 개선 가설**이 있을 때만 한다.

---

# 26. 내가 원하는 최종 목표

나는 하루 수익률이 가장 높은 카지노식 시스템을 원하는 것이 아니다.

나는:

**여러 시장 국면을 지나면서 실제 비용을 지불하고도 양의 기대값이 유지되고, 자본을 점진적으로 키울 수 있는 완전자동 시스템**

을 원한다.

궁극적인 목표함수는:

> **Maximum sustainable geometric growth subject to controlled drawdown and very low probability of ruin.**

이다.

높은 CAGR 때문에 MDD 50~70%를 감수하는 설계는 거부한다.

반대로 너무 보수적이어서 Alpha를 거의 사용하지 않는 시스템도 목표가 아니다.

**Alpha와 생존성 사이의 최적점을 찾아라.**

---

# 27. 첫 응답 형식

이 지시를 받은 즉시 코드를 수정하지 마라.

먼저 나에게 다음 순서로 보고하라.

## PART 1 — 현재 설계 평가

현재 설계에서 가장 뛰어난 부분 10개.

## PART 2 — 가장 위험한 부분

실전 성과를 악화시킬 가능성이 가장 높은 부분 10개.

## PART 3 — 삭제 후보

복잡도만 높이고 Alpha 기여가 의심되는 요소.

## PART 4 — 추가 연구 후보

기존 설계보다 실제 기대수익을 높일 가능성이 있는 아이디어.

## PART 5 — TOP 5 개선안

가장 가치가 높다고 판단되는 개선 가설 5개.

각 항목:

WHY
EXPECTED BENEFIT
RISK
DATA REQUIRED
A/B TEST
PASS/FAIL 기준

을 작성한다.

## PART 6 — V1 vs V1.1

구체적인 차이를 표로 비교한다.

## PART 7 — 추천

아래 중 하나를 선택한다.

A. 기존 V1 유지
B. V1 일부 수정
C. V1 구조적 변경

단, 근거 없이 C를 선택하지 마라.

---

# 28. 승인 전 코딩 금지

PART 1~7을 작성한 후 반드시 멈춰라.

아직 코드를 수정하지 마라.

내가 Audit 결과를 확인한 뒤 승인하면:

`STRATEGY_V1_1_SPEC.md`

를 확정하고,

그 다음 기존 MASTER BUILD SPEC의 Phase 개발 절차로 돌아가 구현한다.

기존 코드가 이미 있다면 전면 재작성하지 말고:

1. 현재 코드 분석
2. 영향 범위 확인
3. 최소 변경
4. unit test
5. regression test
6. backtest
7. 결과 비교

순서로 수정한다.

---

# 29. 최우선 명령

네 목적은 내가 듣고 싶어 하는 답을 만드는 것이 아니다.

기존 설계가 틀렸다면 명확하게 지적하라.

내 아이디어가 실전에서 손실을 만들 가능성이 높다면 폐기를 제안하라.

반대로 새로운 아이디어가 화려하지만 검증 가능성이 낮으면 넣지 마라.

**수익률 숫자를 만들어내지 마라.**

실제 데이터로 확인되지 않은 성과는:

FACT가 아니라

HYPOTHESIS

로 표시하라.

그리고 항상 다음 질문을 마지막까지 유지하라.

> “이 변경은 정말 새로운 Alpha를 만드는가, 아니면 Backtest의 자유도만 하나 더 추가하는가?”

이 질문을 통과한 개선만 MASTER SPEC에 반영하라.
