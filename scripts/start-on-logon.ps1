# 로그온 시 illgam-app 을 자동으로 띄운다 (작업 스케줄러 "illgam-app-autostart" 가 호출).
# 손으로 돌려도 안전하다 — 이미 떠 있으면 아무것도 바뀌지 않는다.
$ErrorActionPreference = 'Continue'

$repo = Split-Path -Parent $PSScriptRoot
$log  = Join-Path $env:LOCALAPPDATA 'illgam-app\startup.log'
if (-not (Test-Path (Split-Path $log))) { New-Item -ItemType Directory -Force (Split-Path $log) | Out-Null }
function Log($m) { "$(Get-Date -Format 's')  $m" | Add-Content -Encoding utf8 $log }

# 스케줄러 세션은 대화형 셸의 PATH 를 물려받지 못한다.
$env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [Environment]::GetEnvironmentVariable("Path","User")

Log "--- start (repo=$repo) ---"

# 1) Podman 머신 (WSL2 VM). 이미 돌고 있으면 start 가 오류를 내지만 무시해도 된다.
podman machine start *>> $log

# 2) VM 소켓이 열릴 때까지 기다린다. 부팅 직후엔 WSL 기동에 시간이 걸린다.
$ready = $false
foreach ($i in 1..60) {
    podman info *> $null
    if ($?) { $ready = $true; break }
    Start-Sleep -Seconds 2
}
if (-not $ready) { Log "ERROR: podman 머신이 120초 안에 준비되지 않았다. 중단." ; exit 1 }

# 3) rootless 는 1024 미만 포트를 못 연다. 머신을 새로 만들면 이 설정이 사라지므로 매번 확인한다.
$portStart = (podman machine ssh 'cat /proc/sys/net/ipv4/ip_unprivileged_port_start' 2>$null)
if ("$portStart".Trim() -ne '80') {
    Log "특권 포트 설정이 없다(현재=$portStart). 다시 넣는다."
    podman machine ssh 'echo net.ipv4.ip_unprivileged_port_start=80 | sudo tee /etc/sysctl.d/99-unprivileged-ports.conf && sudo sysctl -p /etc/sysctl.d/99-unprivileged-ports.conf' *>> $log
}

# 4) 컨테이너 기동. 이미지는 다시 빌드하지 않는다 — 코드를 고쳤다면 사람이 직접
#    `podman compose up -d --build; podman compose restart frontend` 를 돌려야 한다.
Push-Location $repo
podman compose up -d *>> $log
Pop-Location

Log "--- done ---"
