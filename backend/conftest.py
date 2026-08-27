"""테스트 데이터 세트 선택.

실제 지분 데이터(`backend/data/*.json`)는 기밀이라 `.gitignore` 대상이고, CI 체크아웃에는 없다.
그 상태에서 `backend/calc.py` 가 import 시점에 파일을 읽으면 수집 단계에서 전부 죽는다.

그래서 여기서:
  - `backend/data/` 에 5개 파일이 모두 있으면 그대로 쓴다(로컬 개발/사내 러너).
  - 없으면 `ILLGAM_DATA_DIR` 을 합성 fixture 로 돌려 재적재한다(CI).
    이때 엑셀 검증본 골든 넘버에 의존하는 테스트는 `@pytest.mark.realdata` 로 건너뛴다.
"""
import os

import pytest

from backend import calc

FIXTURE_DATA_DIR = os.path.join(os.path.dirname(__file__), "tests", "fixtures", "data")


def _use_fixture_data():
    if calc.data_available():
        return False
    os.environ["ILLGAM_DATA_DIR"] = FIXTURE_DATA_DIR
    if not calc.load_data():
        raise RuntimeError(f"합성 fixture 데이터도 찾을 수 없습니다: {FIXTURE_DATA_DIR}")
    return True


USING_FIXTURE_DATA = _use_fixture_data()

SKIP_REASON = (
    "실제 지분 데이터(backend/data/*.json)가 없어 합성 fixture 로 실행 중입니다. "
    "엑셀 검증본 골든 넘버 테스트는 건너뜁니다."
)


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "realdata: 실제 지분 데이터(backend/data/*.json)가 있어야만 통과하는 테스트",
    )


def pytest_collection_modifyitems(config, items):
    if not USING_FIXTURE_DATA:
        return
    skip = pytest.mark.skip(reason=SKIP_REASON)
    for item in items:
        if "realdata" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def fixture_data(monkeypatch):
    """이 테스트 동안 합성 fixture 데이터로 갈아끼운다(실제 데이터가 있는 환경에서도).

    덕분에 로직 테스트는 CI/로컬 어디서나 같은 데이터로 돈다.
    """
    monkeypatch.setenv("ILLGAM_DATA_DIR", FIXTURE_DATA_DIR)
    calc.load_data()
    yield calc
    monkeypatch.undo()
    calc.load_data()


def pytest_report_header(config):
    source = "합성 fixture" if USING_FIXTURE_DATA else "실제 데이터"
    return f"illgam data set: {source} ({calc.DATA})"
