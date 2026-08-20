Param()
Write-Host "Setting up Illgam app (Windows)"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")
$backend = Join-Path $repoRoot "backend"
if (-Not (Test-Path $backend)) {
    Write-Error "Backend folder not found at $backend. 실행 경로를 확인하세요."
    exit 1
}
Set-Location $backend

$venvPath = Join-Path $backend ".venv"
Write-Host "Using backend path: $backend"

if (-Not (Test-Path $venvPath)) {
    Write-Host "Creating virtual environment at $venvPath..."
    $created = $false
    try {
        if (Get-Command python -ErrorAction SilentlyContinue) {
            & python -m venv $venvPath
            $created = $true
        } elseif (Get-Command py -ErrorAction SilentlyContinue) {
            & py -3 -m venv $venvPath
            $created = $true
        } else {
            Write-Error "Python 실행파일을 찾을 수 없습니다. Python 3.8+를 설치하고 'python' 또는 'py' 명령이 PATH에 있는지 확인하세요."
            exit 1
        }
    } catch {
        Write-Warning "가상환경 생성 중 오류 발생: $($_.Exception.Message)"
    }

    if (-not $created) {
        # fallback: create venv in user's local appdata
        $fallbackDir = Join-Path $env:LOCALAPPDATA "illgam_venv"
        Write-Host "원격/권한 문제로 인해 백엔드 폴더에 가상환경 생성 실패, 로컬 경로로 대체합니다: $fallbackDir"
        if (-Not (Test-Path $fallbackDir)) { New-Item -ItemType Directory -Path $fallbackDir | Out-Null }
        if (Get-Command python -ErrorAction SilentlyContinue) {
            & python -m venv $fallbackDir
        } elseif (Get-Command py -ErrorAction SilentlyContinue) {
            & py -3 -m venv $fallbackDir
        } else {
            Write-Error "Python 실행파일을 찾을 수 없습니다. venv 생성 불가."
            exit 1
        }
        # point to fallback venv
        $venvPath = $fallbackDir
        Write-Host "가상환경을 로컬 경로에 생성했습니다: $venvPath"
    }
}

$activate = Join-Path $venvPath "Scripts\Activate.ps1"
if (Test-Path $activate) {
    Write-Host "Activating virtual environment..."
    & $activate
} else {
    Write-Error "가상환경 활성화 스크립트를 찾을 수 없습니다: $activate"
    exit 1
}

$pythonExe = Join-Path $venvPath "Scripts\python.exe"
if (-Not (Test-Path $pythonExe)) { Write-Error "가상환경의 python.exe를 찾을 수 없습니다: $pythonExe"; exit 1 }

Write-Host "Upgrading pip and installing requirements..."
& $pythonExe -m pip install --upgrade pip
& $pythonExe -m pip install -r requirements.txt

# Create .env from example if missing
if (-Not (Test-Path ".env")) {
  if (Test-Path ".env.example") {
    Copy-Item .env.example .env
    Write-Host ".env created from .env.example with example values. Edit backend/.env to set real secrets."
  } else {
    Write-Host "No .env.example found; creating minimal .env"
    @"
ADMIN_USERNAME=admin
ADMIN_PASSWORD=change_this_password
JWT_SECRET=change_this_secret
"@ | Out-File -Encoding utf8 .env
  }
}

Write-Host "Setup complete. To run tests: .\scripts\run_tests.ps1  To start server: .\scripts\run_server.ps1"
