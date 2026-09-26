<#
.SYNOPSIS
Package or deploy the paper worker to a dedicated GCP VM.
.DESCRIPTION
Default is a local package and plan. -Execute provisions billable resources in the explicit project.
No .env, reference folders, or exchange credentials are uploaded.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][ValidatePattern('^[a-z][a-z0-9-]{4,61}[a-z0-9]$')][string]$ProjectId,
    [ValidatePattern('^[a-z]+-[a-z]+[0-9]-[a-z]$')][string]$Zone = 'asia-northeast3-a',
    [ValidatePattern('^[a-z][a-z0-9-]{1,22}$')][string]$Instance = 'bitget-paper-v1',
    [ValidatePattern('^[a-z0-9-]+$')][string]$MachineType = 'e2-small',
    [ValidatePattern('^$|^[a-z0-9][a-z0-9._-]{1,220}[a-z0-9]$')][string]$BackupBucket = '',
    [string]$GcloudPath = 'gcloud.cmd',
    [switch]$Execute
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$projectRoot = Split-Path -Parent $PSScriptRoot
$archive = Join-Path $projectRoot 'artifacts\cloud\bitget-paper.tar.gz'
$region = $Zone.Substring(0, $Zone.LastIndexOf('-'))
$network = "$Instance-net"
$subnet = "$Instance-subnet"
$disk = "$Instance-data"
$addressName = "$Instance-ip"
$serviceId = "$Instance-runner"
$serviceEmail = "$serviceId@$ProjectId.iam.gserviceaccount.com"

& python (Join-Path $PSScriptRoot 'cloud_bundle.py') --root $projectRoot --output $archive
if ($LASTEXITCODE -ne 0) { throw 'Deployment archive build failed.' }
$archiveHash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
Write-Output "Project=$ProjectId; zone=$Zone; VM=$Instance; type=$MachineType"
Write-Output 'Resources: dedicated VPC, IAP-only SSH, static IPv4, Ubuntu 24.04, 20GB boot disk, retained 20GB state disk.'
Write-Output "Archive SHA256=$archiveHash; mode=paper; credentials=excluded"
if (-not $Execute) {
    Write-Output 'Plan only. No Google Cloud resource was changed. Use -Execute after authentication and project/billing verification.'
    return
}

$gcloud = (Get-Command $GcloudPath -ErrorAction Stop).Source
function Invoke-Gcloud {
    param([string[]]$Arguments)
    & $gcloud @Arguments "--project=$ProjectId" --quiet
    if ($LASTEXITCODE -ne 0) { throw "gcloud command failed: $($Arguments[0..([Math]::Min(2,$Arguments.Count-1))] -join ' ')" }
}
function Get-GcloudJson {
    param([string[]]$Arguments)
    $raw = Invoke-Gcloud ($Arguments + '--format=json')
    return ($raw -join [Environment]::NewLine | ConvertFrom-Json)
}
function Assert-Owned {
    param($Resource, [string]$Description)
    if (-not $Resource.labels -or $Resource.labels.owner -ne 'bitget-paper-v1') {
        throw "Existing $Description lacks ownership label; refusing to adopt or modify it."
    }
}

$accounts = @(Get-GcloudJson @('auth','list','--filter=status:ACTIVE'))
if ($accounts.Count -ne 1) { throw 'Exactly one active gcloud account is required. Run gcloud auth login.' }
$project = Get-GcloudJson @('projects','describe',$ProjectId)
if ($project.lifecycleState -ne 'ACTIVE') { throw 'GCP project is not ACTIVE.' }
$billing = Get-GcloudJson @('billing','projects','describe',$ProjectId)
if (-not $billing.billingEnabled) { throw 'Billing is not enabled for this project.' }

Invoke-Gcloud @('services','enable','compute.googleapis.com','iap.googleapis.com','oslogin.googleapis.com','iam.googleapis.com')
$networks = @(Get-GcloudJson @('compute','networks','list',"--filter=name=$network"))
if ($networks.Count -eq 0) {
    Invoke-Gcloud @('compute','networks','create',$network,'--subnet-mode=custom','--bgp-routing-mode=regional','--description=Dedicated Bitget paper network')
} elseif ($networks[0].description -ne 'Dedicated Bitget paper network' -or $networks[0].autoCreateSubnetworks) {
    throw 'Existing network is not owned by this deployment.'
}
$subnets = @(Get-GcloudJson @('compute','networks','subnets','list',"--filter=name=$subnet","--regions=$region"))
if ($subnets.Count -eq 0) {
    Invoke-Gcloud @('compute','networks','subnets','create',$subnet,"--network=$network","--region=$region",'--range=10.72.0.0/24','--enable-private-ip-google-access')
} elseif (-not $subnets[0].network.EndsWith("/$network") -or $subnets[0].ipCidrRange -ne '10.72.0.0/24') {
    throw 'Existing subnet does not match dedicated deployment network.'
}
$firewallName = "$Instance-iap-ssh"
$firewalls = @(Get-GcloudJson @('compute','firewall-rules','list',"--filter=network:$network"))
if ($firewalls.Count -eq 0) {
    Invoke-Gcloud @('compute','firewall-rules','create',$firewallName,"--network=$network",'--direction=INGRESS','--action=ALLOW','--rules=tcp:22','--source-ranges=35.235.240.0/20',"--target-tags=$Instance",'--description=IAP-only SSH for Bitget paper worker')
} elseif ($firewalls.Count -ne 1 -or $firewalls[0].name -ne $firewallName -or
          $firewalls[0].direction -ne 'INGRESS' -or
          (@($firewalls[0].targetTags) -join ',') -ne $Instance -or
          (@($firewalls[0].sourceRanges) -join ',') -ne '35.235.240.0/20' -or
          (@($firewalls[0].allowed).Count) -ne 1 -or $firewalls[0].allowed[0].IPProtocol -ne 'tcp' -or
          (@($firewalls[0].allowed[0].ports) -join ',') -ne '22') {
    throw 'Dedicated VPC has unexpected firewall rules. Inspect before continuing.'
}

$accounts = @(Get-GcloudJson @('iam','service-accounts','list',"--filter=email=$serviceEmail"))
if ($accounts.Count -eq 0) {
    Invoke-Gcloud @('iam','service-accounts','create',$serviceId,'--display-name=Bitget paper worker (no project roles)')
} elseif ($accounts[0].displayName -ne 'Bitget paper worker (no project roles)') {
    throw 'Existing service account does not belong to this deployment.'
}
$projectPolicy = Get-GcloudJson @('projects','get-iam-policy',$ProjectId)
$runnerRoles = @($projectPolicy.bindings | Where-Object { @($_.members) -contains "serviceAccount:$serviceEmail" })
if ($runnerRoles.Count -gt 0) { throw 'VM service account already has project-wide IAM roles. Review before using it for this deployment.' }
# No project-wide role is granted to the VM service account.
if ($BackupBucket) {
    Invoke-Gcloud @('storage','buckets','describe',"gs://$BackupBucket")
    Invoke-Gcloud @('storage','buckets','add-iam-policy-binding',"gs://$BackupBucket","--member=serviceAccount:$serviceEmail",'--role=roles/storage.objectCreator')
}
$addresses = @(Get-GcloudJson @('compute','addresses','list',"--filter=name=$addressName AND region:$region"))
if ($addresses.Count -eq 0) {
    Invoke-Gcloud @('compute','addresses','create',$addressName,"--region=$region",'--network-tier=PREMIUM','--description=Dedicated Bitget paper static outbound IP')
} elseif ($addresses[0].description -ne 'Dedicated Bitget paper static outbound IP') {
    throw 'Existing address is not owned by this deployment.'
}
$ip = (Get-GcloudJson @('compute','addresses','describe',$addressName,"--region=$region")).address
$disks = @(Get-GcloudJson @('compute','disks','list',"--filter=name=$disk AND zone:$Zone"))
if ($disks.Count -eq 0) {
    Invoke-Gcloud @('compute','disks','create',$disk,"--zone=$Zone",'--type=pd-balanced','--size=20GB','--labels=owner=bitget-paper-v1,role=state')
} else {
    Assert-Owned $disks[0] 'state disk'
}
$instances = @(Get-GcloudJson @('compute','instances','list',"--filter=name=$Instance AND zone:$Zone"))
if ($instances.Count -eq 0) {
    Invoke-Gcloud @(
        'compute','instances','create',$Instance,"--zone=$Zone","--machine-type=$MachineType",
        '--provisioning-model=STANDARD','--maintenance-policy=MIGRATE',
        '--image-family=ubuntu-2404-lts-amd64','--image-project=ubuntu-os-cloud',
        '--boot-disk-size=20GB','--boot-disk-type=pd-balanced','--no-boot-disk-auto-delete',
        "--disk=name=$disk,device-name=bitget-data,mode=rw,boot=no,auto-delete=no",
        "--subnet=$subnet","--address=$ip","--tags=$Instance",
        "--service-account=$serviceEmail",'--scopes=https://www.googleapis.com/auth/cloud-platform',
        '--metadata=enable-oslogin=TRUE,block-project-ssh-keys=TRUE',
        '--shielded-secure-boot','--shielded-vtpm','--shielded-integrity-monitoring',
        '--labels=owner=bitget-paper-v1,mode=paper'
    )
} else {
    Assert-Owned $instances[0] 'VM'
    if (-not $instances[0].networkInterfaces[0].subnetwork.EndsWith("/$subnet") -or
        $instances[0].serviceAccounts[0].email -ne $serviceEmail) {
        throw 'Existing VM network/service account does not match deployment.'
    }
    $attachedData = @($instances[0].disks | Where-Object { $_.deviceName -eq 'bitget-data' })
    if ($attachedData.Count -ne 1 -or -not $attachedData[0].source.EndsWith("/$disk") -or $attachedData[0].autoDelete) {
        throw 'Existing VM does not have the expected retained data disk.'
    }
    if ($instances[0].networkInterfaces[0].accessConfigs[0].natIP -ne $ip) {
        throw 'Existing VM external IP does not match the reserved deployment address.'
    }
    $osLogin = @($instances[0].metadata.items | Where-Object { $_.key -eq 'enable-oslogin' })
    if ($osLogin.Count -ne 1 -or $osLogin[0].value -ne 'TRUE') { throw 'Existing VM must have OS Login enabled.' }
    if ($instances[0].status -ne 'RUNNING') { throw 'Existing VM is not RUNNING; inspect it before continuing.' }
}
# The caller needs OS Admin Login, IAP Tunnel Resource Accessor, and Service Account User.
# The script intentionally does not grant the caller broad IAM roles.
$ready = $false
for ($attempt = 0; $attempt -lt 12; $attempt++) {
    & $gcloud compute ssh $Instance "--project=$ProjectId" "--zone=$Zone" --tunnel-through-iap --quiet --command='true'
    if ($LASTEXITCODE -eq 0) { $ready = $true; break }
    Start-Sleep -Seconds 10
}
if (-not $ready) { throw 'VM exists but IAP SSH is unavailable. Check OS Login/IAP/IAM permissions; rerun after correcting.' }

Invoke-Gcloud @('compute','scp',$archive,"${Instance}:/tmp/bitget-paper.tar.gz","--zone=$Zone",'--tunnel-through-iap')
$installerSource = Join-Path $projectRoot 'infra\gcp\install.sh'
$installer = Join-Path $projectRoot 'artifacts\cloud\bitget-install.sh'
[IO.File]::WriteAllText($installer, [IO.File]::ReadAllText($installerSource).Replace("`r`n", "`n"), [Text.UTF8Encoding]::new($false))
Invoke-Gcloud @('compute','scp',$installer,"${Instance}:/tmp/bitget-install.sh","--zone=$Zone",'--tunnel-through-iap')
$bucketArg = if ($BackupBucket) { " '$BackupBucket'" } else { '' }
$command = "sudo bash /tmp/bitget-install.sh /tmp/bitget-paper.tar.gz $archiveHash$bucketArg"
Invoke-Gcloud @('compute','ssh',$Instance,"--zone=$Zone",'--tunnel-through-iap',"--command=$command")
$healthy = $false
for ($attempt = 0; $attempt -lt 18; $attempt++) {
    & $gcloud compute ssh $Instance "--project=$ProjectId" "--zone=$Zone" --tunnel-through-iap --quiet --command='sudo python3 /opt/bitget/current/infra/gcp/runtime_ops.py verify'
    if ($LASTEXITCODE -eq 0) { $healthy = $true; break }
    Start-Sleep -Seconds 10
}
if (-not $healthy) { throw 'Worker did not produce a fresh heartbeat. Inspect journalctl before marking deployment complete.' }
$record = [ordered]@{ project=$ProjectId; zone=$Zone; instance=$Instance; ip=$ip; mode='paper'; sha256=$archiveHash; deployedAt=(Get-Date).ToUniversalTime().ToString('o') }
$record | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $projectRoot 'artifacts\cloud\deployment.json') -Encoding UTF8
Write-Output "Deployment commands completed: $Instance ($ip). Verify heartbeat freshness and status before marking healthy."
