# Illgam 내부용 일감몰아주기 증여세 판정기

로컬 개발 및 사내 배포용 FastAPI 백엔드 + 정적 프론트엔드 프로젝트입니다.

빠른 시작

1. `backend/data/`에 민감한 JSON 5개를 넣으세요: `company_sizes.json`, `shareholder_holdings.json`, `intercompany_holdings.json`, `params.json`, `section18_indirect_investors.json`. 절대 프론트엔드 폴더에 넣지 마세요.

   목록의 출처는 `backend/calc.py` 의 `DATA_FILES` 이고, **5개가 전부 있어야** `calc.data_available()` 이 참이 됩니다. 하나라도 빠지면 `backend/main.py` 의 `lifespan` 이 기동 시점에 `RuntimeError` 로 죽습니다(도커에서는 컨테이너가 그대로 종료됩니다 — `restart` 정책이 없습니다).

2. 개발환경(로컬 Python)

`backend` 는 파이썬 패키지입니다. **테스트·서버 모두 저장소 루트에서** 실행하세요
(`cd backend` 후에는 `from backend.calc import ...` 가 풀리지 않습니다).

```powershell
# 저장소 루트에서 실행한다. 경로는 클론한 위치 기준(예: C:\Users\you\Documents\GitHub\illgam-app).
python -m venv backend\.venv
.\backend\.venv\Scripts\Activate.ps1

# 런타임 의존성만: backend\requirements.txt
# 테스트까지: backend\requirements-dev.txt (pytest, httpx2, playwright 포함)
pip install -r backend\requirements-dev.txt

# 환경변수. backend/.env 에 적어두면 backend/__init__.py 가 읽으므로 매번 셸에
# 설정할 필요는 없다(scripts/setup.ps1 이 .env.example 을 복사해 만들어 준다).
# 아래처럼 셸에 직접 설정하면 .env 보다 우선한다.
#   우선순위: 셸 환경변수 > backend/.env > 코드 기본값
$env:ADMIN_USERNAME = "admin"
$env:ADMIN_PASSWORD = "change_this_password"
$env:JWT_SECRET = "change_this_secret"

python -m pytest backend -q

# 개발 서버
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

Windows 용 자동화 스크립트 (위 과정을 대신한다. 저장소 루트에서 실행)
```powershell
.\scripts\setup.ps1      # 가상환경 생성 + requirements-dev.txt 설치, backend/.env 생성
.\scripts\run_tests.ps1  # pytest 실행
.\scripts\run_server.ps1 # 개발 서버 실행
```

가상환경 폴백 안내
- 기본적으로 `scripts\setup.ps1` 은 프로젝트의 `backend\.venv` 에 가상환경을 생성합니다.
- 네트워크 드라이브나 권한 문제로 생성이 실패하면 `%LOCALAPPDATA%\illgam_venv` 에 자동으로 폴백되어 가상환경이 생성됩니다.
- 특정 경로의 venv 를 강제로 사용하려면 환경변수 `ILLGAM_VENV_PATH` 에 전체 경로를 설정하세요. (`run_tests.ps1`/`run_server.ps1` 는 이 변수를 우선 사용합니다.)

예: PowerShell 에서 강제 venv 경로 설정
```powershell
$env:ILLGAM_VENV_PATH = "C:\Users\you\venvs\illgam"
.\scripts\run_tests.ps1
```

3. 도커로 배포(사내망)
```powershell
# 저장소 루트에서
docker compose up -d --build
```
- 빌드 컨텍스트는 **저장소 루트**입니다(`backend/Dockerfile`, `docker-compose.yml`의 `context: .`). `backend` 를 패키지째 복사해야 `backend.main:app` 이 풀립니다.
- `backend/.env` 가 있어야 기동합니다(`docker-compose.yml` 의 `env_file`). 없으면 compose 가 거부합니다. `scripts\setup.ps1` 이 생성하며 양식은 `backend/.env.example` 참조.
- `backend/data/*.json` 은 `.dockerignore` 로 **이미지에서 제외**되고 런타임 볼륨(`/app/backend/data:ro`)으로만 붙습니다. 이미지 레이어에 구우면 `docker save` 로 그대로 새어나갑니다.

## 테스트와 CI

지분 데이터(`backend/data/*.json`)는 기밀이라 저장소에 커밋하지 않습니다. 그래서
`backend/conftest.py` 가 데이터 세트를 골라 씁니다.

| 상황 | 사용 데이터 | 결과 |
|---|---|---|
| `backend/data/` 에 5개 파일이 모두 있음 (로컬/사내 러너) | 실제 데이터 | 전체 통과 — 엑셀 검증본 골든 넘버 포함 |
| 파일 없음 (GitHub Actions 기본) | `backend/tests/fixtures/data/` 합성 데이터 | `@pytest.mark.realdata` 테스트는 skip, 나머지 전부 실행 |

- 합성 데이터로도 과세제외 우선순위(⑩ → ⑭)·누진세율·응답 노출면은 `backend/tests/test_calc_synthetic.py` 가 그대로 검증합니다.
- CI 에서 골든 넘버까지 돌리려면 저장소 시크릿 `ILLGAM_DATA_TAR_B64` 를 설정하세요.
  ```powershell
  tar -cz -C backend/data . | base64 -w0
  ```
- 임의 경로의 데이터를 쓰려면 `ILLGAM_DATA_DIR` 환경변수를 설정하세요.

보안 주의사항
- `backend/data/*.json`과 `.env`는 절대 git에 커밋하지 마세요. 배포 시에는 CI/CD에서 안전하게 주입하세요.
- 프로덕션에서는 `JWT_SECRET`을 안전한 시크릿으로 설정하고 HTTPS를 강제하세요. 미설정 시 `dev-secret` 으로 폴백해 토큰 위조가 가능합니다.
- ⑭ 지분율 상당액의 과세제외 금액·적용률·합계는 일반 응답에 싣지 않습니다. 매출액으로 나누면 지배주주 지분율이 그대로 역산되기 때문입니다(관리자 응답 전용).
