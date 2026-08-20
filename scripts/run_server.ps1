Param()
$base = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location (Join-Path $base "..\backend")

$venvLocal = Join-Path (Get-Location) ".venv"
$venvFallback = Join-Path $env:LOCALAPPDATA "illgam_venv"
# allow overriding with env var
if ($env:ILLGAM_VENV_PATH) {
	$venv = $env:ILLGAM_VENV_PATH
} elseif (Test-Path $venvLocal) {
	$venv = $venvLocal
} elseif (Test-Path $venvFallback) {
	$venv = $venvFallback
} else {
	Write-Host "가상환경을 찾을 수 없습니다. 먼저 scripts\setup.ps1를 실행하세요. 또는 ILLGAM_VENV_PATH 환경변수를 설정하세요."
	exit 1
}

$activate = Join-Path $venv "Scripts\Activate.ps1"
if (-Not (Test-Path $activate)) { Write-Host "가상환경 활성화 스크립트를 찾을 수 없습니다: $activate"; exit 1 }
& $activate
uvicorn main:app --reload --host 0.0.0.0 --port 8000
