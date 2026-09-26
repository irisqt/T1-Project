# Google Cloud 24시간 운영

이 배포는 **실시간 공개 시세를 사용하는 모의매매(paper)** 전용입니다. 배포 파일에는 Bitget 키와 `.env`가 포함되지 않습니다. 거래소 계좌에 주문을 넣지 않고 전략·비용·운영 상태를 관찰합니다. 실제 주문 기능은 별도 검증과 실행 설정이 완료되어야 활성화할 수 있습니다.

## 구성

- 프로젝트 `goldenpath-ai`, 기본 지역 서울 `asia-northeast3-a`.
- Ubuntu 24.04, Python 3.12 이상, 표준 Compute Engine `e2-small`. Spot VM을 사용하지 않습니다.
- 전용 VPC와 서브넷, 외부 고정 IPv4, SSH는 Google IAP의 `35.235.240.0/20`에서만 허용합니다. 인터넷으로 웹/DB 포트를 열지 않습니다.
- 부팅 디스크 20GB와 **자동 삭제하지 않는 별도 상태 디스크 20GB**. 상태는 `/var/lib/bitget/data`, SQLite DB는 `trader.sqlite3`입니다.
- VM의 전용 서비스 계정에는 프로젝트 권한을 부여하지 않습니다. 선택한 기존 GCS 백업 버킷에만 `roles/storage.objectCreator`를 줄 수 있습니다.
- systemd 프로세스 자동 재시작, 1분 간격 heartbeat 검사, 180초 이상 지연된 실행의 재시작. 사용자가 서비스를 중지하면 watchdog이 다시 켜지 않습니다.
- 매시간 SQLite online backup을 생성하고 로컬 최신 168개를 유지합니다. `-BackupBucket`을 지정하면 압축 백업을 GCS에도 저장합니다. GCS 삭제 권한은 없으므로 버킷 보관 주기는 버킷 수명 주기 규칙으로 관리합니다.

서울 VM·디스크·외부 IP·스토리지에는 사용 요금이 발생합니다. 이 구성을 무료 티어로 간주하지 않습니다. 실제 금액과 예산은 배포 계정의 [Google Cloud 가격 계산기](https://cloud.google.com/products/calculator)와 결제 화면에서 확인합니다. 예산 알림은 비용을 자동으로 중단시키는 장치가 아닙니다.

## 로그인과 사전 확인

[Windows 로그인 안내](GCP_LOGIN_WINDOWS.md)를 따릅니다. 배포 실행자는 프로젝트 리소스 생성 및 API 활성화 권한, VM OS Admin Login, IAP Tunnel Resource Accessor, 해당 VM 서비스 계정에 대한 Service Account User 권한이 필요합니다. 스크립트는 로그인한 사용자에게 관리자 역할을 임의로 부여하지 않습니다. 조직 정책·IAM 권한 오류가 생기면 해당 관리자와 필요한 권한만 확인합니다.

```powershell
Set-Location -LiteralPath 'C:\Users\irisq\Codex\Bitget Auto Coin_Trading'
python -B scripts\cloud_selftest.py
.\scripts\cloud_deploy.ps1 -ProjectId goldenpath-ai
```

기본 실행은 **로컬 압축 파일과 배포 계획만 생성**합니다. 새 프로그램의 `src/bitget_bot`, `config/paper.toml`, `infra/gcp`만 허용 목록으로 포함합니다. 이전 참고 폴더, `.env`, `data`, 로그, 캐시, 비밀 파일을 통째로 복사하지 않습니다. 파일별 SHA256 명세서와 전체 압축 SHA256을 함께 만듭니다.

## 실제 배포

```powershell
.\scripts\cloud_deploy.ps1 -ProjectId goldenpath-ai -Execute
```

기존 백업용 버킷을 사용하려면 `-BackupBucket 실제-버킷이름`을 추가합니다. 버킷을 지정하지 않으면 로컬 디스크 백업까지만 수행합니다. 같은 디스크의 백업만으로는 디스크 전체 손실에서 복구할 수 없으므로 장기 운영 전에는 GCS 복제 또는 디스크 스냅샷을 설정합니다.

스크립트는 결제·프로젝트 접근을 확인한 뒤 필요한 API, 전용 VPC, IAP SSH 규칙, 서비스 계정, 고정 IP, 상태 디스크, VM을 생성합니다. 기존 리소스는 이름뿐 아니라 소유 표시와 설정을 검사하며 예상하지 못한 리소스를 덮어쓰지 않습니다. 중단되면 오류 원인을 해결한 후 같은 명령으로 재시도합니다. 이미 만들어진 유료 리소스는 실패 후에도 남을 수 있습니다.

코드는 SHA256으로 구분된 `/opt/bitget/releases`에 설치되고 `/opt/bitget/current`가 활성 버전을 가리킵니다. 업데이트는 상태 디스크와 기존 `/etc/bitget/paper.toml`을 유지합니다. 설정 변경은 해당 서버 파일을 검토해서 반영합니다. 설치 완료 후 서비스 활성 상태와 heartbeat가 확인되어야 배포 성공으로 기록합니다. 결과는 로컬 `artifacts/cloud/deployment.json`에 남습니다.

## 운영 확인

VM 접속:

```powershell
gcloud compute ssh bitget-paper-v1 --project=goldenpath-ai --zone=asia-northeast3-a --tunnel-through-iap
```

VM에서:

```bash
sudo systemctl status bitget-bot.service --no-pager
sudo python3 /opt/bitget/current/infra/gcp/runtime_ops.py verify
sudo journalctl -u bitget-bot.service -n 100 --no-pager
sudo systemctl list-timers bitget-health.timer bitget-backup.timer
cd /opt/bitget/current
sudo -u bitget env PYTHONPATH=/opt/bitget/current/src python3 -m bitget_bot status --config /etc/bitget/paper.toml
```

heartbeat는 프로세스가 순환하고 있다는 뜻입니다. 수익성이나 시세의 정상성을 보장하지 않습니다. 상태가 halted/degraded라면 저널과 전략 상태를 확인합니다. Google VM 전체의 장애는 VM 내부 watchdog으로 감지할 수 없으므로 운영 확대 시 외부 가용성 감시도 추가합니다.

즉시 중지와 재개:

```bash
sudo systemctl stop bitget-bot.service
sudo systemctl start bitget-bot.service
```

재부팅 후에도 중지 상태를 유지하려면 `sudo systemctl disable --now bitget-bot.service`를 사용합니다. 다시 자동 실행하려면 `sudo systemctl enable --now bitget-bot.service`를 사용합니다.

수동 백업 확인:

```bash
sudo systemctl start bitget-backup.service
sudo journalctl -u bitget-backup.service -n 30 --no-pager
sudo ls -lh /var/lib/bitget/backups
```

## 복구와 롤백

서비스를 먼저 중지합니다. `trader.sqlite3`와 남아 있는 `-wal`, `-shm` 파일은 같은 시점의 한 세트로 취급합니다. 복구 전에 기존 파일을 별도 디렉터리로 보존하고, 선택한 검증된 백업 DB를 `/var/lib/bitget/data/trader.sqlite3`로 복사합니다. **기존 WAL/SHM 파일을 새 DB와 함께 사용하지 않습니다.** 소유권을 bitget:bitget, 권한을 0600으로 맞춘 뒤 SQLite `PRAGMA integrity_check`와 앱 상태를 확인하고 재시작합니다.

코드 롤백은 서비스를 중지한 상태에서 `/opt/bitget/current`를 기존 검증된 release 디렉터리로 바꿉니다. DB 스키마가 바뀌었다면 단순 코드 롤백이 호환되는지 먼저 확인합니다. 릴리스와 상태 디스크를 자동으로 삭제하는 작업은 포함하지 않습니다.

## 중단 후 재개

1. 루트의 `PROJECT_STATE.md`와 이 문서를 읽습니다.
2. `artifacts/cloud/deployment.json`이 있으면 해당 VM의 실제 상태를 조회합니다. 파일이 없더라도 리소스가 일부 생성되었을 수 있으므로 GCP를 확인합니다.
3. 최신 로컬 테스트 및 배포 압축 SHA를 확인합니다.
4. 인증이 유효하면 동일 배포 명령을 계속 수행합니다.
5. VM 서비스·heartbeat·백업을 실제 확인하기 전에는 “24시간 배포 완료”라고 기록하지 않습니다.

## 공식 근거

- [IAP TCP forwarding](https://docs.cloud.google.com/iap/docs/using-tcp-forwarding): IAP SSH의 소스 범위와 접근 방식.
- [OS Login 설정](https://docs.cloud.google.com/compute/docs/oslogin/set-up-oslogin): 사용자 및 서비스 계정 접근 권한.
- [비부팅 디스크 포맷과 마운트](https://docs.cloud.google.com/compute/docs/disks/format-mount-disk-linux): UUID 기반 부팅 시 재마운트.
- [Cloud Storage IAM](https://docs.cloud.google.com/storage/docs/access-control/iam): 버킷 범위 Object Creator 권한.
- [애플리케이션 일관성 스냅샷](https://docs.cloud.google.com/compute/docs/disks/creating-linux-application-consistent-pd-snapshots): 디스크 스냅샷 전후 일관성 처리. 이 프로그램은 우선 SQLite online backup을 사용합니다.

## 2026-09-23 운영 구성 보완

- 조회 전용 `bitget-dashboard.service`를 추가했습니다. 서버에서는 127.0.0.1:8765만 사용하며 SSH 터널로 접속합니다.
- 배포 readiness는 현재 프로세스가 시작된 이후의 heartbeat와 SQLite 원장이 모두 paper/RUNNING이며 일치할 때만 통과합니다. DEGRADED/HALTED 상태는 배포 완료 조건을 충족하지 못합니다.
- `goldenpath-ai-bitget-paper-backups` 비공개 서울 리전 버킷을 생성했습니다. public access prevention 및 uniform bucket-level access 적용. 자동 삭제 수명 주기는 적용하지 않았습니다.
- 실행 명령: `.\scripts\cloud_deploy.ps1 -ProjectId goldenpath-ai -GcloudPath gcloud.cmd -BackupBucket goldenpath-ai-bitget-paper-backups -Execute`.
- `scripts/cloud_acceptance.py --restart`는 해당 전용 paper VM에서 실행하는 검증 도구입니다. 서비스 재시작 전후 원장, 백업 무결성, 조회 화면, timer/자동 시작을 확인합니다.
- 테스트 증거: `artifacts/validation-2026-09-23.json`. 실제 원격 완료 결과는 배포 후 별도 기록합니다.
