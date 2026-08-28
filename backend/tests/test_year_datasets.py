"""연도별 데이터 세트 테스트.

지분·규모·세율은 해마다 바뀌므로 `backend/data/<연도>/` 로 나눠 담고, 계산 시점에
연도를 골라 쓴다. 여기서 지키려는 것은 세 가지다.

  1. 연도를 바꾸면 **실제로 다른 데이터로** 계산된다 (그냥 이름표만 바뀌는 게 아니다).
  2. 없는 연도를 요청하면 **조용히 기본 연도로 넘어가지 않고 실패**한다.
     사용자가 2025 로 계산했다고 믿는데 2026 데이터가 쓰이는 것이 최악이다.
  3. 연도 폴더가 없는 **예전 평면 구조도 그대로 동작**한다.

fixture 차이(backend/tests/fixtures/data_years/):
  2025 — 가나전자가 '중견', 지배주주 A 지분 0.1
  2026 — 가나전자가 '일반', 지배주주 A 지분 0.2
"""
import json
import os

import pytest
from fastapi.testclient import TestClient

from backend import calc
from backend.auth import ADMIN_USERNAME, ADMIN_PASSWORD
from backend.main import app

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
YEAR_DIR = os.path.join(FIXTURES, "data_years")
FLAT_DIR = os.path.join(FIXTURES, "data")

SUBJECT = "가나전자"
COUNTERPARTY_NONE = "자차산업"     # 과세제외 사유 없음
ARGS = (SUBJECT, 10_000_000_000, 0, 10_000_000_000, {COUNTERPARTY_NONE: 9_000_000_000})

client = TestClient(app)


@pytest.fixture
def years(monkeypatch):
    """연도 폴더 fixture 로 갈아끼운다."""
    monkeypatch.setenv("ILLGAM_DATA_DIR", YEAR_DIR)
    calc.load_data()
    yield calc
    monkeypatch.undo()
    calc.load_data()


@pytest.fixture
def flat(monkeypatch):
    """연도 폴더가 없는 예전 평면 구조."""
    monkeypatch.setenv("ILLGAM_DATA_DIR", FLAT_DIR)
    calc.load_data()
    yield calc
    monkeypatch.undo()
    calc.load_data()


def _auth():
    r = client.post("/api/auth/login",
                    json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# --- 적재 ---------------------------------------------------------------------

def test_year_directories_are_all_loaded(years):
    assert years.available_years() == ["2026", "2025"], "최신순이어야 한다"
    assert years.DEFAULT_YEAR == "2026", "기본은 가장 최근 연도"


def test_year_options_carry_as_of_text(years):
    options = {o["year"]: o["as_of"] for o in years.year_options()}
    assert "2025" in options["2025"]
    assert "2026" in options["2026"]


def test_flat_layout_still_loads(flat):
    """연도 폴더를 안 만든 기존 배포도 그대로 돌아야 한다."""
    assert flat.DATA_LOADED
    assert len(flat.available_years()) == 1
    # 연도 이름표는 params.json 의 기준시점에서 뽑는다.
    year = flat.available_years()[0]
    assert year == flat.DEFAULT_YEAR
    assert flat.evaluate(*ARGS)["year"] == year


def test_flat_layout_year_label_falls_back_when_unparseable(tmp_path, monkeypatch):
    """기준시점에 연도가 없으면 '기본' 이라는 이름표를 쓴다(죽지 않는다)."""
    for name in calc.DATA_FILES:
        src = os.path.join(FLAT_DIR, name)
        with open(src, encoding="utf-8") as f:
            data = json.load(f)
        if name == "params.json":
            data["기준시점"] = "연도 없음"
        with open(tmp_path / name, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    monkeypatch.setenv("ILLGAM_DATA_DIR", str(tmp_path))
    calc.load_data()
    try:
        assert calc.available_years() == [calc.FALLBACK_YEAR]
    finally:
        monkeypatch.undo()
        calc.load_data()


# --- 연도가 실제로 계산을 바꾸는가 --------------------------------------------

def test_size_differs_by_year(years):
    assert years.dataset("2025").sizes[SUBJECT] == "중견"
    assert years.dataset("2026").sizes[SUBJECT] == "일반"


def test_evaluate_uses_the_requested_year(years):
    r25 = years.evaluate(*ARGS, year="2025")
    r26 = years.evaluate(*ARGS, year="2026")
    assert r25["year"] == "2025" and r26["year"] == "2026"
    assert r25["size"] == "중견" and r26["size"] == "일반"
    # 규모가 다르면 정상거래비율도 다르다(중견 40% / 일반 30%).
    assert r25["normal_ratio"] == 0.4
    assert r26["normal_ratio"] == 0.3
    # 지분·공제율이 모두 달라 세액이 같을 수 없다.
    assert r25["gift_tax_total"] != r26["gift_tax_total"]


def test_year_omitted_means_default_year(years):
    assert years.evaluate(*ARGS) == years.evaluate(*ARGS, year=years.DEFAULT_YEAR)


def test_result_carries_the_as_of_text(years):
    assert "2025" in years.evaluate(*ARGS, year="2025")["data_as_of"]


def test_admin_review_uses_the_requested_year(years):
    r = years.evaluate_admin_review(*ARGS, year="2025")
    assert r["year"] == "2025"
    a = next(d for d in r["shareholder_details"] if d["code"] == "A")
    assert a["holding_ratio"] == 0.1, "2025 의 A 지분"
    # 총계와 주주별 합계는 연도를 바꿔도 맞아야 한다.
    assert sum(d["gift_tax"] for d in r["shareholder_details"]) == r["gift_tax_total"]


def test_admin_review_and_evaluate_agree_within_a_year(years):
    for year in years.available_years():
        plain = years.evaluate(*ARGS, year=year)
        review = years.evaluate_admin_review(*ARGS, year=year)
        assert review["gift_tax_total"] == plain["gift_tax_total"], year
        assert review["deemed_gift_total"] == plain["deemed_gift_total"], year


def test_company_list_is_per_year(years):
    assert years.company_list("2025")[-1] == years.OTHER_COMPANY
    assert set(years.company_list("2025")) == set(years.company_list("2026"))


# --- 없는 연도는 조용히 넘어가지 않는다 ---------------------------------------

def test_unknown_year_raises_instead_of_falling_back(years):
    with pytest.raises(ValueError, match="2099"):
        years.evaluate(*ARGS, year="2099")


def test_unknown_year_message_lists_available_years(years):
    with pytest.raises(ValueError, match="2026"):
        years.dataset("2099")


# --- API ---------------------------------------------------------------------

def test_years_endpoint_lists_years_and_default(years):
    r = client.get("/api/years", headers=_auth())
    assert r.status_code == 200
    data = r.json()
    assert [o["year"] for o in data["years"]] == ["2026", "2025"]
    assert data["default"] == "2026"


def test_years_endpoint_requires_auth(years):
    assert client.get("/api/years").status_code == 401


def test_evaluate_endpoint_honours_year(years):
    body = {"company": SUBJECT, "operating_income": 10_000_000_000, "corporate_tax": 0,
            "total_sales": 10_000_000_000, "related_sales": {COUNTERPARTY_NONE: 9_000_000_000}}
    h = _auth()
    r25 = client.post("/api/admin/evaluate-review", json={**body, "year": "2025"}, headers=h)
    r26 = client.post("/api/admin/evaluate-review", json={**body, "year": "2026"}, headers=h)
    assert r25.status_code == 200 and r26.status_code == 200
    assert r25.json()["size"] == "중견"
    assert r26.json()["size"] == "일반"
    assert r25.json()["gift_tax_total"] != r26.json()["gift_tax_total"]


def test_evaluate_endpoint_rejects_unknown_year(years):
    body = {"company": SUBJECT, "year": "2099", "operating_income": 1,
            "corporate_tax": 0, "total_sales": 1, "related_sales": {}}
    r = client.post("/api/admin/evaluate-review", json=body, headers=_auth())
    assert r.status_code == 400
    assert "2099" in r.json()["detail"]


def test_companies_endpoint_honours_year(years):
    r = client.get("/api/companies?year=2025", headers=_auth())
    assert r.status_code == 200
    assert r.json()["year"] == "2025"


def test_companies_endpoint_rejects_unknown_year(years):
    r = client.get("/api/companies?year=2099", headers=_auth())
    assert r.status_code == 400


def test_template_endpoint_honours_year(years):
    r = client.get("/api/related-sales/template?year=2025", headers=_auth())
    assert r.status_code == 200
    assert len(r.content) > 0
