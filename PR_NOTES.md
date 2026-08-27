# PR notes — `chore/backend-package-ci`

## 1. CI 가 데이터 없이도 의미 있게 돈다

`.gitignore` 가 `backend/data/*.json`(기밀)을 제외하는데 `backend/calc.py` 는 **import 시점**에
그 파일들을 읽었다. 그래서 GitHub Actions 체크아웃에서는 수집 단계에서 `FileNotFoundError` 로
모든 테스트가 죽었다 — 워크플로가 처음부터 통과할 수 없는 상태였다.

- `calc.load_data()` / `calc.data_available()` / `ILLGAM_DATA_DIR` 로 데이터 적재를 분리했다.
  import 는 더 이상 실패하지 않고, 테스트가 데이터 세트를 갈아끼울 수 있다.
- `backend/main.py` 는 `SIZES` 를 이름으로 import 하지 않고 `calc.SIZES` 로 참조한다
  (재적재 시 stale 바인딩이 남지 않도록). 대신 lifespan 에서 데이터 미적재면 기동을 실패시킨다.
- `backend/tests/fixtures/data/` — 실제 소유구조와 무관한 **합성 데이터**를 추가했다.
- `backend/conftest.py` — 실제 데이터가 있으면 그대로, 없으면 합성 fixture 로 폴백한다.
  엑셀 검증본 골든 넘버에 의존하는 테스트는 `@pytest.mark.realdata` 로 skip 된다.
- `backend/tests/test_calc_synthetic.py` — 그 공백을 메우는 로직 테스트(과세제외 우선순위,
  누진세율, 세무조정, 응답 노출면, 권한). 실제 데이터 유무와 무관하게 항상 돈다.
- `.github/workflows/ci.yml` — 시크릿 `ILLGAM_DATA_TAR_B64` 가 있으면 주입해 골든 넘버까지 돌린다.
- `pytest.ini` — rootdir 을 저장소 루트로 고정.

## 2. 의존성

- `requirements.txt` 에 `fastapi.testclient.TestClient` 가 요구하는 HTTP 클라이언트가
  없어서 API 테스트가 CI 에서 돌 수 없었다. **`httpx2`** 를 테스트 의존성으로 넣는다.
  (`starlette` 1.6 부터 `testclient` 는 `httpx2` 를 먼저 import 하고, `httpx` 로 폴백하면
  `StarletteDeprecationWarning` 을 낸다.)
- 테스트 전용 의존성(`pytest`, `httpx2`, `playwright`)을 `requirements-dev.txt` 로 분리했다.
  프로덕션 이미지에 playwright 가 딸려 들어가지 않는다.
- `passlib[bcrypt]` → `passlib`. 해시는 `pbkdf2_sha256` 이라 bcrypt extra 가 필요 없다.

## 3. ⑭ 지분율 상당액 합계 노출 제거 (기밀)

일반 응답의 `ratio_exclusion_total_min`/`_max` 를 관리자 응답 전용으로 옮겼다.

"여러 거래처가 섞인 합계는 개별 지분율로 분해되지 않는다"는 전제가 틀렸다 —
**합계의 구성을 정하는 쪽이 클라이언트**다.

- 거래처를 1건만 넣어 호출하면 `합계 ÷ 그 거래처 매출` 이 곧 `max_k 지분율` 이다.
  `exclusion_details[].article` 로 어느 건이 ⑭ 인지도 구분된다.
- 여러 건을 넣어도 `{A,B}` 호출과 `{A}` 호출의 차분으로 B 의 몫이 정확히 복원된다.
- 실제 데이터에서 지배주주 B 의 지분율이 전 법인 0 이라 `_min` 은 항상 0 이었다.
  즉 실질적으로 `_max` 단일값만 나갔고, 그게 곧 지분율이었다.

거래처 건수 임계값이나 버킷화로는 차분 공격을 막지 못해 아예 내보내지 않는다.
프론트엔드는 일반 사용자에게 "비공개 (지분율 역산 방지)" 로 표시한다.

## 4. 이미지에 기밀이 구워지던 문제 (기밀)

`.dockerignore` 가 없어 `COPY . /app` 이 `backend/.env`, `backend/data/*.json`, `backend/.venv`
를 전부 이미지 레이어에 넣었다. 런타임 볼륨 마운트는 이미 구워진 레이어를 덮을 뿐이라
`docker save` / `docker history` 로 원본이 그대로 나온다.

- 저장소 루트에 `.dockerignore` 추가 — `.env`, `backend/data/`, `.venv`, 테스트, 프론트엔드 제외.

## 5. 도커 배포 정상화

`Dockerfile` 은 컨텍스트 `./backend` 를 `/app` 에 복사한 뒤 `uvicorn main:app` 을 띄웠는데,
`backend/main.py` 는 `from backend.calc import ...` 를 한다 → `ModuleNotFoundError`.
패키지화 이후 한 번도 뜨지 못하는 상태였다.

- 빌드 컨텍스트를 저장소 루트로 올리고 `COPY backend/ backend/` + `uvicorn backend.main:app`.
- `docker-compose.yml`: 데이터 볼륨 경로를 `/app/backend/data` 로 맞추고,
  `env_file: backend/.env` 로 `ADMIN_USERNAME`/`ADMIN_PASSWORD` 도 전달한다.
  (전에는 `JWT_SECRET` 만 넘겨 컨테이너 관리자 비밀번호가 항상 기본값 `adminpass` 였다.)
- 이제는 쓰지 않는 `version:` 키 제거, `depends_on` 추가.
- `README.md` / `README_먼저읽기.md` 의 `cd backend && uvicorn main:app` 도 같은 이유로 틀렸다 —
  저장소 루트에서 `uvicorn backend.main:app` 으로 정정.

## 남은 항목 (이 PR 범위 밖)

- `JWT_SECRET` / `ADMIN_PASSWORD` 의 하드코딩 폴백(`dev-secret`, `adminpass`) — 미설정 시
  기동 실패로 바꿔야 한다. `auth.py` 의 `sub` 미등록 시 `company = username` 폴백과 결합하면
  기본 시크릿 환경에서 관리자 토큰 위조가 가능하다.
- `.env.example` 의 `ALLOWED_ORIGINS` 가 죽은 설정 — `main.py` 는 localhost 를 하드코딩한다.
- `/api/admin/summary` 가 `evaluate(c, 0, 0, 0, {})` 를 호출해 항상 `taxable=False` 를 반환한다.
- `auth.py` 의 `datetime.utcnow()` (Python 3.12+ deprecated).
- `EvaluateRequest` 에 음수 방어(`ge=0`) 없음.
- `calc.py:149` — 7인 지분율이 모두 같고 0 이 아닌 행이 생기면 일반 응답의 `rate` 에
  실제 지분율이 실린다. 현재 데이터로는 도달 불가(전 법인 B=0)지만 코드 가드가 없다.
- 루트 shim `calc.py` / `models.py` / `auth.py` 는 이제 아무도 import 하지 않는다(삭제 후보).
  `main.py` shim 만 저장소 루트 `uvicorn main:app` 진입점으로 살아 있다.

## 검증

셸 도구 장애로 이 브랜치에서는 `pytest` 를 실행하지 못했다. 머지 전 반드시 확인할 것:

```powershell
python -m pytest backend -q -ra
docker compose config          # env_file / 볼륨 경로 확인
docker compose build backend
```
