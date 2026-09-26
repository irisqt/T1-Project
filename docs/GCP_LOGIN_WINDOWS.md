# Windows Google Cloud 로그인

확인된 프로젝트 ID: `goldenpath-ai`. Google Cloud 콘솔에 로그인하는 것과 PC의 `gcloud` 로그인은 별개입니다.

1. [Google 공식 Windows 설치 안내](https://docs.cloud.google.com/sdk/docs/install-sdk#windows)를 열고 **Google Cloud CLI installer**를 다운로드합니다.
2. 설치 파일을 실행합니다. 기본 구성과 PATH 등록 옵션을 사용합니다. 기존 Python 선택을 강제하지 않고 설치 프로그램의 기본값을 사용해도 됩니다.
3. 설치가 끝나면 **새 PowerShell 창** 또는 **Google Cloud SDK Shell**을 엽니다. 이미 열려 있던 터미널은 PATH 변경을 모를 수 있습니다.
4. 아래 명령을 한 줄씩 실행합니다.

```powershell
gcloud version
gcloud auth login
```

5. 열린 브라우저에서 `goldenpath-ai` 프로젝트에 접근 가능한 Google 계정을 고릅니다. Google 로그인과 권한 동의를 직접 완료합니다.
6. 터미널에 로그인이 완료되었다는 메시지가 나오면 다음을 실행합니다.

```powershell
gcloud config set project goldenpath-ai
gcloud auth list --filter=status:ACTIVE --format="table(account,status)"
gcloud projects describe goldenpath-ai --format="value(projectId,lifecycleState)"
gcloud billing projects describe goldenpath-ai --format="value(billingEnabled)"
```

정상 결과는 활성 계정 1개, `goldenpath-ai ACTIVE`, 결제 상태 `True`입니다. 계정 이메일 외에 토큰이나 인증 코드를 채팅에 붙여 넣을 필요가 없습니다. 로그인 후 Codex에 **“gcloud 로그인 완료, 이어서 배포해”**라고 말하면 이 상태를 확인하고 배포를 계속할 수 있습니다.

`gcloud`를 찾지 못하면 먼저 새 창을 엽니다. 그래도 안 되면 아래 기본 설치 위치를 확인합니다.

```powershell
& "$env:LOCALAPPDATA\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd" version
```

이 경로에서만 실행되면 배포 스크립트의 `-GcloudPath`에 같은 경로를 전달할 수 있습니다. 설치 디렉터리를 다른 곳으로 지정했다면 실제 `gcloud.cmd` 경로를 사용합니다.

브라우저가 자동으로 열리지 않는 환경에서는 `gcloud auth login --no-launch-browser`를 실행하고 터미널에 표시되는 Google URL을 직접 엽니다. 이 프로젝트에는 `gcloud auth application-default login`이나 서비스 계정 JSON 키 발급이 필요하지 않습니다. 로그인 세부 동작은 [공식 gcloud auth login 문서](https://docs.cloud.google.com/sdk/gcloud/reference/auth/login)를 따릅니다.

프로젝트 접근 오류나 결제 `False`가 나오면 [프로젝트 결제 상태](https://console.cloud.google.com/billing/linkedaccount?project=goldenpath-ai)를 확인합니다. 명령의 출력은 [공식 결제 확인 명령](https://docs.cloud.google.com/sdk/gcloud/reference/billing/projects/describe)에 정의되어 있습니다.
