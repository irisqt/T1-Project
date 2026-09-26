# Bitget Auto Coin Trading

실제 Bitget 선물 시세를 사용해 가상 자금으로 동작하는 자동 모의매매 프로그램입니다.
현재 릴리스에는 실계좌 주문 기능이 연결되지 않았습니다. 레버리지 5~30배는 모의 포지션의 증거금 설정이며, 거래당 손실 예산과 주문 수량은 별도로 제한합니다.

## 현재 확인된 상태

2026-09-23: Google Cloud SDK 설치·인증 및 `goldenpath-ai` 접근 확인. 프로그램 테스트 96개와 운영 테스트 17개 통과. 네 종목 공개 시세 연결과 로컬 원장 재시작 확인. 서울 리전 `bitget-paper-v1` 배포 후 서비스 재시작·원장 유지·조회 화면·GCS 백업 복원까지 검증했습니다. 현재 모의매매로 실행 중입니다. 클라우드의 실제 배포 결과는 `artifacts/cloud/deployment.json` 및 `artifacts/cloud/acceptance.json`과 `PROJECT_STATE.md`에서 확인합니다. 파일이 없으면 해당 검증을 완료한 것으로 간주하지 않습니다.

## 로컬 실행

PowerShell에서:

```powershell
Set-Location -LiteralPath 'C:\Users\irisq\Codex\Bitget Auto Coin_Trading'
$env:PYTHONPATH=Join-Path (Get-Location) 'src'
python -m bitget_bot public-check
python -m bitget_bot run
```

실행 중 `Ctrl+C`로 종료합니다. 모의 원장은 `data/trader.sqlite3`에 저장됩니다. 같은 원장을 사용하면 이전 포지션·수수료·중단 상태를 이어갑니다. 별도 PowerShell에서 `python -m bitget_bot status` 또는 `python -m bitget_bot dashboard`로 조회할 수 있습니다.

## 클라우드 조회 화면

배포 완료 후 다음 명령을 실행하고 창을 유지합니다.

```powershell
gcloud.cmd compute ssh bitget-paper-v1 --project=goldenpath-ai --zone=asia-northeast3-a --tunnel-through-iap --quiet --command='sleep 86400' -- -L 8765:127.0.0.1:8765
```

브라우저에서 http://127.0.0.1:8765 를 엽니다. 조회 화면과 SSH 터널을 닫아도 서버의 모의매매는 계속 동작합니다. 서버 상태 확인·중단·백업·복구 명령은 [운영 안내](docs/CLOUD_RUNBOOK.md)에 있습니다.

## 자료

- [설계도](docs/BLUEPRINT.md)
- [이어서 작업하기](PROJECT_STATE.md)
- [Google Cloud 운영 안내](docs/CLOUD_RUNBOOK.md)
- [거래소 API 검증](docs/API_CONTRACT.md)
- [전략 연구 결과: 현재 후보 모두 실거래 기준 미충족](docs/RESEARCH_FINDINGS.md)
- `artifacts/`: 테스트, 과거 데이터, 탐색 연구, 배포 증거

모의매매 및 탐색 연구 결과는 실거래 수익을 입증하지 않습니다. 현재 한계와 실거래 완료 조건은 설계도 7~8절에 기록돼 있습니다. `.env`와 기존 참조 프로그램은 배포 파일에 포함하지 않습니다.
