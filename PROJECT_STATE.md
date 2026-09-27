# PROJECT STATE — Bitget Auto Coin Trading

Updated: 2026-09-23 18:30 KST. Milestone: GCP continuous PAPER deployment verified.

## 사용자 요청과 작업 위치
- 모든 작업: C:/Users/irisq/Codex/Bitget Auto Coin_Trading. 초기 task cwd는 존재하지 않으므로 workdir를 명시한다.
- coin_trading/bitget_autotrader와 두 원본 참조 폴더는 수정하지 않는다.
- 설계·구현·검증·Google Cloud 24시간 운영 요청. 선택 프로젝트 t1-bitget-astra.
- 과거 단계별 승인/토큰 절약 지시는 적용하지 않는다.
- .env 값 출력·업로드 금지. 출금/이체 없음. 실제 주문 경로는 현재 미완성/미활성.

## 완료한 검증
- Google Cloud SDK 585.0.0 설치, ACTIVE 로그인, 프로젝트 ACTIVE 및 billingEnabled=true 확인.
- 전체 pytest 96개 + cloud_selftest 17개 통과. evidence: artifacts/validation-2026-09-23.json.
- 실제 BTC/ETH/SOL/XRP 공개 시세/1H봉/1m봉/funding API 점검 통과.
- 데이터 누락 시 HALT, 재시작 유지, 장부/수수료/funding, 거래 중복, 위험한도, 설정 검증 테스트 보완.
- 과거 봉 페이지 경계 누락 수정, history page limit=100으로 API 규격 일치.
- 조회 화면 JavaScript 문법 확인, cloud readiness 원장/heartbeat/현재 프로세스 일치 검사.

## 실제 배포 완료 (T1 프로젝트 이전)
- project: t1-bitget-astra
- instance: bitget-paper-v1
- zone: asia-northeast3-a (서울)
- machine: e2-small / Ubuntu 24.04 / STANDARD
- static outbound IP: 34.158.198.98
- SHA256: 20de617881ed36d84b2c48160893db0eac3a7d841cab194ac6e5318ee62f1f57
- 시작: 2026-09-27 새 T1 프로젝트로 서버 이전 및 재구동 완료. RUNNING 상태 확인.
- 전용 VPC와 IAP-only SSH. 웹/DB 공개 포트 없음. 기존 closebet-paper-01 변경 없음.
- bitget-bot/bitget-dashboard 서비스, health/backup timer 모두 active+enabled.
- /var/lib/bitget 별도 retained 20GB ext4 data disk. 원장 /var/lib/bitget/data/trader.sqlite3.
- 재시작 PID 변경 확인, 기존 started_ms/fingerprint/기록 보존, SQLite integrity=ok.
- GCS: gs://goldenpath-ai-bitget-paper-backups/bitget-paper/. 비공개, VM은 objectCreator만 부여.
- GCS 백업 실제 업로드 7개 확인. 최신 백업 다운로드/압축 복원/SQLite integrity=ok, 원장 동일성 확인.
- 30일 자동 삭제 lifecycle은 자동 승인 검토에서 거부되어 적용하지 않음. 버킷 자동 삭제 정책 없음.
- 증거: artifacts/cloud/deployment.json, acceptance.json, backup-restore-check.json, dashboard-check.json.
- 로컬 조회용 SSH tunnel session 31763, http://127.0.0.1:8765. 터널 종료/PC 종료는 서버 봇 작동과 무관.

## 연구 결과와 미완료 범위
- 180일 실제 공개 1H 데이터: 4개 종목 각각 4,319개 연속 확정 봉.
- 현재 계약 규칙을 반영한 3개 후보 × 2개 비용 × 3개 개발 구간 분석 완료.
- 모든 V1 후보의 개발 구간 합산 모형 PnL 음수. 실거래 승격 근거 없음. 최종 20% holdout은 미평가.
- **[2026-09-27 V2 전략 분석 결과]** `strategy_v2.py`의 신규 로직 백테스트 결과, `trend4h_20` (4시간 추세 돌파 20기간) 모듈이 모든 fold에서 우수한 우상향 성과(총 Net PnL +217.87)를 기록하여 최종 전략으로 선정됨 (`docs/ASTRA_ADVICE_LOG.md` 참고).
- **[2026-09-27 V2 GCP 24시간 실가동 이식 완료]** `trend4h_20` 전략을 포함한 봇을 기존 `goldenpath-ai`에서 완전히 독립된 새로운 새 프로젝트 `t1-bitget-astra`로 이전하여 클린 배포 완료. 봇 정상 가동 중.
- **[2026-09-27 T3 MTF 전략 백테스트 및 배포]** 4시간봉 거시추세와 5분봉 정밀타점을 결합한 `t3_trend4h_5m` 전략을 백테스트(총 PnL +21.96, PF 1.94) 후 실거래 환경(`aggressive_live.toml`)에 적용하고 GCP 서버에 펌웨어 업데이트 완료.
- docs/RESEARCH_FINDINGS.md와 artifacts/research_summary_20260923.json 참조.
- 운영 성공은 전략 수익성 또는 실거래 준비 완료가 아니다. 현재 설정은 paper만 허용한다.
- 실제 주문 엔진의 durable intent, 부분 체결 보호, remote stop 대조, 재시작 주문 복구, demo 검증은 아직 미완성.
- 장기 paper 성과, 외부 장애 알림 채널, 독립 OOS/새 전략 검증은 남아 있다. 현재 VM 내부 health와 GCS 백업만 실제 제공.
- 첫 부분 분봉/봉 내부 경로/funding 정산 가격/청산 margin tier는 모형 한계가 있다.

## 다음에 이어서 작업할 순서
1. 이 파일 → docs/BLUEPRINT.md → docs/RESEARCH_FINDINGS.md → docs/CLOUD_RUNBOOK.md를 읽는다.
2. 기존 VM을 먼저 조회한다. 중복 VM/새 프로젝트를 만들지 않는다.
3. `gcloud.cmd compute ssh bitget-paper-v1 --project=t1-bitget-astra --zone=asia-northeast3-a --tunnel-through-iap --quiet --command='sudo python3 /opt/bitget/current/infra/gcp/runtime_ops.py verify'`
4. 원장/최근 이벤트/백업을 확인하고 현재 paper 운영을 유지한다. 실계좌 거래가 이루어졌다고 주장하지 않는다.
5. 대시보드 업데이트(`trade.goldenpath.kr`): SQLite 라이브 DB(`trader.sqlite3`)를 직접 조회하도록 `dashboard.py` 수정 완료. 포트폴리오(가용잔고, 총자산), 포지션 뷰, BTC/ETH/SOL/XRP 종목별 트레이딩뷰 차트 변경 기능 구현. **최종적으로 노안 배려용 폰트 확대(24px) 및 한글화, 80포트 리다이렉트를 통한 접속 편의성 개선 배포 완료.**
6. V2 전략(`trend4h_20`)이 성공적인 PnL을 보였으므로, `engine.py` 등 실제 라이브 모듈에 `strategy_v2.py`를 통합(Integration)하고 `config`를 업데이트하는 작업을 진행한다. (완료)
7. T3 MTF 전략 적용: `run_live_bot.py`를 5분봉 지원 및 `strategy_t3.py` 통합 구조로 변경 후 GCP 실서버 배포. (완료)
8. 사용자 요청에 따른 리스크 검증: Full-Margin 올인 매매법의 위험성(15% 단일 거래 최대 손실)을 백테스트로 입증하고, 기존 Fixed Fractional Risk 모델의 방어력을 확인. (완료)
9. 기존 V1에 맞춰진 테스트 코드(`tests/test_engine.py` 등)의 Mock을 V2/T3 Policy 구조에 맞게 교체/업데이트하여 `pytest`가 모두 통과하도록 복원한다. (현재 보류/이후 ASTRA 복귀 시 과제)
10. 현재 상태: 사용자가 백테스트보다 **실시간 실전 모니터링**을 지켜보기 원함. 봇은 paper trading으로 T3 엔진 구동 중이며 대시보드로 실시간 관찰.

## 주요 파일
- README.md: 사용자 실행/조회 안내
- docs/BLUEPRINT.md: 설계 및 실거래 완료 조건
- src/bitget_bot/: 새 구현, tests/: 96개 테스트
- scripts/cloud_deploy.ps1: 배포/업데이트, scripts/cloud_acceptance.py: 원격 검증
- infra/gcp/: install/systemd/heartbeat/SQLite+GCS backup
- artifacts/: 실제 테스트/공개 API/연구/배포 증거
