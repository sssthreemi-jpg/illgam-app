# Illgam 내부용 일감몰아주기 증여세 판정기

로컬 개발 및 사내 배포용 FastAPI 백엔드 + 정적 프론트엔드 프로젝트입니다.

빠른 시작

1. `backend/data/`에 민감한 JSON 4개를 넣으세요: `company_sizes.json`, `shareholder_holdings.json`, `intercompany_holdings.json`, `params.json`. 절대 프론트엔드 폴더에 넣지 마세요.

2. 개발환경(로컬 Python)
```powershell
cd s:\illgam-app\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 환경변수 설정(예)
$env:ADMIN_USERNAME = "admin"
$env:ADMIN_PASSWORD = "change_this_password"
$env:JWT_SECRET = "change_this_secret"

cd ..
python -m pytest backend -q

# 개발 서버
cd backend
uvicorn main:app --reload --host 0.0.0.0 --port 8000

Windows용 자동화 스크립트
```powershell
cd s:\illgam-app
\.\scripts\setup.ps1    # 가상환경 생성 및 의존성 설치, backend/.env 생성
\.\scripts\run_tests.ps1  # pytest 실행
\.\scripts\run_server.ps1 # 개발 서버 실행
```

가상환경 폴백 안내
- 기본적으로 `scripts\setup.ps1`은 프로젝트의 `backend\.venv`에 가상환경을 생성합니다.
- 네트워크 드라이브나 권한 문제로 생성이 실패하면 `%LOCALAPPDATA%\illgam_venv`에 자동으로 폴백되어 가상환경이 생성됩니다.
- 특정 경로의 venv를 강제로 사용하려면 환경변수 `ILLGAM_VENV_PATH`에 전체 경로를 설정하세요. (`run_tests.ps1`/`run_server.ps1`는 이 변수를 우선 사용합니다.)

예: PowerShell에서 강제 venv 경로 설정
```powershell
$env:ILLGAM_VENV_PATH = "C:\Users\you\venvs\illgam"
.\scripts\run_tests.ps1
```
```

3. 도커로 배포(사내망)
```powershell
cd s:\illgam-app
docker compose up -d --build
```

보안 주의사항
- `backend/data/*.json`과 `.env`는 절대 git에 커밋하지 마세요. 배포 시에는 CI/CD에서 안전하게 주입하세요.
- 프로덕션에서는 `JWT_SECRET`을 안전한 시크릿으로 설정하고 HTTPS를 강제하세요.
