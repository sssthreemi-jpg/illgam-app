Param()
$base = Split-Path -Parent $MyInvocation.MyCommand.Path
# backend 는 패키지이므로 저장소 루트에서 실행해야 `import backend.*` 가 해결된다.
$root = (Resolve-Path (Join-Path $base "..")).Path
Set-Location $root

# 디렉터리 존재만으로는 부족하다. 생성하다 만 venv 껍데기가 정상 venv 를 가리는 것을 막기 위해
# Activate.ps1 까지 있는 경우에만 사용 가능한 것으로 본다.
function Test-UsableVenv($path) {
    if (-Not $path) { return $false }
    return (Test-Path (Join-Path $path "Scripts\Activate.ps1"))
}

$candidates = @(
    $env:ILLGAM_VENV_PATH,
    (Join-Path $root "backend\.venv"),
    (Join-Path $env:LOCALAPPDATA "illgam_venv")
)

$venv = $candidates | Where-Object { Test-UsableVenv $_ } | Select-Object -First 1

if (-Not $venv) {
    Write-Host "사용 가능한 가상환경이 없습니다. 먼저 scripts\setup.ps1 를 실행하세요."
    Write-Host "확인한 경로:"
    foreach ($c in $candidates) {
        if ($c) {
            if (Test-Path $c) {
                Write-Host "  - $c  (폴더는 있으나 Scripts\Activate.ps1 없음 — 생성 실패한 venv)"
            } else {
                Write-Host "  - $c  (없음)"
            }
        }
    }
    exit 1
}

$python = Join-Path $venv "Scripts\python.exe"
if (-Not (Test-Path $python)) { Write-Host "가상환경의 python.exe 를 찾을 수 없습니다: $python"; exit 1 }

Write-Host "가상환경: $venv"
Write-Host "주소: http://localhost:8000/"
& $python -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
