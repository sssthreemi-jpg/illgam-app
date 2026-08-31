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

## 연도별 지분 데이터

지분율·기업규모·법인간 출자·§18 목록·세율은 해마다 바뀝니다. 그래서 데이터를 **연도 폴더**로
나눠 담고, 계산할 때 연도를 골라 씁니다.

```
backend/data/
  2025/  company_sizes.json  shareholder_holdings.json  intercompany_holdings.json
         params.json         section18_indirect_investors.json
  2026/  (같은 5개 파일)
```

새 연도를 추가하려면 **폴더를 하나 만들고 5개 파일을 넣으면 됩니다.** 5개가 모두 있는 폴더만
인식하며, 하나라도 빠지면 그 연도는 목록에 나타나지 않습니다. 코드 수정은 필요 없습니다.

각 연도의 `params.json` 에 있는 `기준시점` 문구가 화면과 결과 리포트에 그대로 표시되므로,
연도마다 정확히 적어두세요(예: `"2025.12.31 지분 / 25년 매출"`).

기본값은 **가장 최근 연도**입니다. 없는 연도를 요청하면 400 으로 거절합니다 — 사용자가 2025 로
계산했다고 믿는데 조용히 2026 데이터가 쓰이는 것이 최악이기 때문입니다.

연도 폴더 없이 `backend/data/*.json` 만 있는 **예전 구조도 그대로 동작합니다.** 이때 연도
이름표는 `기준시점` 에서 뽑고, 못 뽑으면 `기본` 이 됩니다.

| 엔드포인트 | 하는 일 |
| --- | --- |
| `GET /api/years` | 계산 가능한 연도와 각 연도의 기준시점 |

`year` 는 `/api/companies`, `/api/my-company`, `/api/admin/summary`, `/api/related-sales/*` 에서는
**쿼리스트링**으로, `/api/evaluate` 와 `/api/admin/evaluate-review` 에서는 **요청 본문**으로 받습니다.
어느 쪽이든 생략하면 기본 연도입니다.

### 데이터 백업과 복구

`backend/data/` 는 기밀이라 **git 에 없습니다.** 이 PC 에서 사라지면 저장소만으로는 복구되지
않으므로, 5개 파일 중 어디까지 되살릴 수 있는지 알아두어야 합니다.

| 파일 | 복구 방법 |
| --- | --- |
| `shareholder_holdings.json` | 지분율 엑셀에서 **재생성 가능** (아래 스크립트) |
| `intercompany_holdings.json` | 지분율 엑셀에서 **재생성 가능** (아래 스크립트) |
| `company_sizes.json` | **백업 필요.** 기업분류 엑셀이 연도별로 다르고 손으로 고친 값이 섞여 있습니다. |
| `params.json` | **백업 필요.** 세율·비율을 직접 관리합니다. |
| `section18_indirect_investors.json` | **백업 필요.** 세무 검토로 확정해 등재합니다. |

```powershell
# 미리보기(기본). 기존 파일과 무엇이 달라지는지만 보여준다.
python scripts\rebuild_year_data.py --year 2025 --holdings "...\25.12말 기준 일감 증여세 (지분율).xlsx"

# 실제로 덮어쓴다.
python scripts\rebuild_year_data.py --year 2025 --holdings "..." --write
```

스크립트는 같은 폴더의 `company_sizes.json` 을 **법인 목록의 정본**으로 읽습니다. 그래서
`company_sizes.json` 이 먼저 있어야 나머지 두 개를 만들 수 있습니다 — 백업에서 가장 중요한 파일입니다.

기본이 미리보기인 이유는 **손으로 고친 값이 조용히 덮이는 것을 막기 위해서**입니다
(예: 2026 대웅인베스트먼트를 중견 → 일반으로 보정한 이력).

### 구현 메모: 왜 전역을 갈아끼우지 않는가

`backend/calc.py` 는 연도별 데이터를 `Dataset` 객체로 만들어 기동 시 **전부 메모리에 올려두고**,
계산 함수가 그중 하나를 골라 씁니다. 요청마다 모듈 전역을 갈아끼우는 방식은 쓰면 안 됩니다 —
FastAPI 는 `def` 엔드포인트를 스레드풀에서 돌리므로, 두 사람이 동시에 다른 연도로 계산하면
서로의 데이터를 밟습니다. 예외 없이 세액만 조용히 틀리는 유형이라 특히 위험합니다.

모듈 전역(`calc.SIZES` 등)은 연도 개념이 없던 시절 호출부와 테스트를 위해 남아 있고 **기본 연도
스냅샷**일 뿐입니다. 계산 경로에서는 쓰지 마세요.

## 특수관계자 매출 엑셀 업로드

거래처가 수십 개라 한 줄씩 입력하기 번거로우므로, 파일로 표를 채울 수 있습니다.
화면 "2. 특수관계자 세부매출" 의 **양식 다운로드** / **엑셀 업로드** 버튼입니다.

| 엔드포인트 | 하는 일 |
| --- | --- |
| `GET /api/related-sales/template` | 거래처명이 채워진 빈 xlsx 양식. 사용자는 B열 금액만 채운다. |
| `POST /api/related-sales/import` | 업로드 파일을 읽어 거래처별 금액을 돌려준다. |

**업로드는 아무것도 저장하지 않고 계산도 하지 않습니다.** 파일을 표로 바꿔주는 읽기 전용
변환일 뿐이고, 계산은 종전대로 사용자가 표를 확인하고 `확인` 을 눌러야 돕니다.

받는 형식은 `.xlsx` / `.xlsm` / `.csv`(UTF-8·cp949·탭 구분 포함)입니다. 구형 `.xls` 는
읽지 못하며 xlsx 로 저장하라는 안내를 돌려줍니다.

파싱은 `backend/excel_import.py` 에 있고, 우리 양식과 회계·ERP 추출본을 모두 받습니다.
ERP 추출본은 제목·기간 행이 위에 붙고 코드/비고 열이 섞이며 거래처명도 `(주)대웅제약` 처럼
적히므로, 헤더 행과 열 위치를 찾고 법인격 표기를 걷어내 맞춰봅니다.

설계상 중요한 규칙이 하나 있습니다. **확신이 없으면 매칭하지 않습니다.** 금액이 엉뚱한
법인에 붙는 것이 못 찾는 것보다 훨씬 나쁩니다. 못 맞춘 거래처는 버리지도, `기타법인` 에
임의로 합치지도 않고 화면에 그대로 띄워 사용자가 넣을 곳을 직접 고르게 합니다.
합계 행 제외, 같은 법인 여러 줄 합산, 잘라 읽은 행 수 보고도 같은 이유로 들어가 있습니다.

### 이름이 다르게 적히는 거래처

`(주)대웅제약`, `대웅제약(주)`, `주식회사 대웅제약` 처럼 **법인격 표기만 다른 것**은
`normalize_name()` 이 알아서 걷어내므로 따로 등록할 필요가 없습니다.

철자가 아예 다른 것은 `excel_import.NAME_ALIASES` 에 등록합니다. 실제로 파일에는 `기타`,
서버 목록에는 `기타법인` 으로 적혀 매칭이 안 되던 건이 있어 catch-all 동의어들을 넣어
두었습니다. 새 별칭이 필요하면 여기에 한 줄 추가하면 됩니다.

```python
NAME_ALIASES = {
    "기타": OTHER_COMPANY,      # 키는 normalize_name() 을 거친 형태
    ...
}
```

별칭은 **실제 법인명을 덮지 않고**(`setdefault`), 가리키는 법인이 서버 목록에 없으면
무시됩니다. 별칭 때문에 존재하지 않는 법인이 생기면 안 되기 때문입니다. 화면에서는
"파일과 이름이 다르게 연결된 N건" 을 펼쳐 무엇이 무엇으로 이어졌는지 확인할 수 있습니다.

의존성은 `openpyxl`(xlsx 읽기·쓰기)과 `python-multipart`(FastAPI 업로드 파싱)이며 둘 다
`backend/requirements.txt` 에 있습니다. `python-multipart` 가 빠지면 업로드 요청이 500 이 됩니다.

업로드 상한은 5MB(`backend/excel_import.py` 의 `MAX_UPLOAD_BYTES`)이고 최대 5000행을 읽습니다.
**도커 배포에서는 `frontend/nginx.conf` 의 `client_max_body_size` 도 함께 봐야 합니다.**
nginx 기본값이 1m 이라 그냥 두면 1MB 넘는 파일이 백엔드에 닿기도 전에 413 으로 잘리고,
로컬 개발에서는 nginx 를 거치지 않아 이 증상이 드러나지 않습니다. 상한 판단은 백엔드가
하도록 nginx 쪽을 6m 으로 조금 크게 잡아 두었습니다.

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
