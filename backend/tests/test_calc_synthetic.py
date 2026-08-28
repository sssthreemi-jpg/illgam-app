"""합성 fixture 데이터로 도는 로직 테스트.

실제 지분 데이터(`backend/data/*.json`)는 기밀이라 저장소에 없다. 그래서 CI 에서는
`test_calc.py`(엑셀 검증본 골든 넘버)가 통째로 skip 된다 — 여기가 그 공백을 메운다.

검증 대상은 숫자 자체가 아니라 **계산 파이프라인·과세제외 우선순위·응답 노출면**이다.
`fixture_data` 픽스처(backend/conftest.py)가 실제 데이터 유무와 무관하게 항상
`backend/tests/fixtures/data/` 를 적재하므로, 로컬에서도 CI 와 같은 결과가 나온다.

fixture 구성은 backend/tests/fixtures/data/README.md 참조.
"""
import pytest
from fastapi.testclient import TestClient

from backend.auth import ADMIN_USERNAME, ADMIN_PASSWORD
from backend.main import app

client = TestClient(app)

SUBJECT = "가나전자"          # 일반, 마바물산에 30% 출자
COUNTERPARTY_10 = "마바물산"   # ⑩ 기본 과세제외
COUNTERPARTY_14 = "사아텍"     # ⑭ 지분율 상당액 (A=0.4 … B=0)
COUNTERPARTY_NONE = "자차산업"  # 지배주주 지분율 전무 → 과세제외 사유 없음

PUBLIC_FIELDS = {
    "company", "size", "taxable", "total_sales", "related_sales_total",
    "related_sales_ratio", "normal_ratio", "deemed_gift_total", "gift_tax_total",
    "reason", "exclusion_details",
}
PUBLIC_DETAIL_FIELDS = {"counterparty", "sales", "reason", "article", "rate", "excluded_sales"}


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _admin_token():
    r = client.post("/api/auth/login",
                    json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


# --- 과세제외 판정 (상증령 §34의3) -------------------------------------------

def test_section10_excludes_full_sales(fixture_data):
    """⑩ — 수혜법인이 거래처에 출자했으면 매출 전액 제외."""
    calc = fixture_data
    verdict = calc.exclusion_for(SUBJECT, COUNTERPARTY_10, 1_000_000_000, "A")
    assert verdict["article"] == calc.ARTICLE_10
    assert verdict["rate"] == 1.0
    assert verdict["excluded_sales"] == 1_000_000_000


def test_section10_takes_precedence_over_section18(fixture_data, monkeypatch):
    """⑩ 이 성립하면 ⑭ 는 아예 보지 않는다 — §18 에 등재돼 있어도 마찬가지."""
    calc = fixture_data
    monkeypatch.setitem(calc.SECTION18, SUBJECT, {COUNTERPARTY_10})
    verdict = calc.exclusion_for(SUBJECT, COUNTERPARTY_10, 1_000_000_000, "A")
    assert verdict["article"] == calc.ARTICLE_10


def test_ratio_exclusion_uses_that_shareholders_holding(fixture_data):
    """⑭ 지분율 상당액 — 지배주주마다 적용률이 다르다."""
    calc = fixture_data
    a = calc.exclusion_for(SUBJECT, COUNTERPARTY_14, 1_000_000_000, "A")
    b = calc.exclusion_for(SUBJECT, COUNTERPARTY_14, 1_000_000_000, "B")
    assert a["article"] == calc.ARTICLE_14_RATIO
    assert a["rate"] == 0.4
    assert a["excluded_sales"] == pytest.approx(400_000_000)
    # B 는 지분이 없어 제외 사유 자체가 없다.
    assert b["article"] == calc.ARTICLE_NONE
    assert b["rate"] == 0.0


def test_section18_excludes_full_sales_without_stacking(fixture_data, monkeypatch):
    """§18 등재 관계는 100% 제외. 지분율 상당액과 겹쳐도 합산하지 않고 큰 것 하나만 적용."""
    calc = fixture_data
    monkeypatch.setitem(calc.SECTION18, SUBJECT, {COUNTERPARTY_14})
    verdict = calc.exclusion_for(SUBJECT, COUNTERPARTY_14, 1_000_000_000, "A")
    assert verdict["article"] == calc.ARTICLE_14_1
    assert verdict["rate"] == 1.0
    assert verdict["excluded_sales"] == 1_000_000_000, "지분율 상당액 40% 가 더해지면 안 된다"


def test_no_exclusion_reason(fixture_data):
    calc = fixture_data
    verdict = calc.exclusion_for(SUBJECT, COUNTERPARTY_NONE, 1_000_000_000, "A")
    assert verdict["article"] == calc.ARTICLE_NONE
    assert verdict["rate"] == 0.0
    assert verdict["excluded_sales"] == 0.0


# --- 누진세율·면세점 ----------------------------------------------------------

@pytest.mark.parametrize("base,expected", [
    (400_000, 0),                    # 면세점(50만원) 미만
    (500_000, 50_000),               # 10%
    (200_000_000, 30_000_000),       # 20% - 1천만
    (700_000_000, 150_000_000),      # 30% - 6천만
    (2_000_000_000, 640_000_000),    # 40% - 1억6천만
    (4_000_000_000, 1_540_000_000),  # 50% - 4억6천만
])
def test_gift_tax_brackets(fixture_data, base, expected):
    assert fixture_data._gift_tax(base) == expected


# --- 계산 파이프라인 ----------------------------------------------------------

# 가나전자(일반, 공제거래비율 5%, 공제보유비율 0%), 총매출 100억, 세후영업이익 100억,
# 특관매출 90억(자차산업 — 과세제외 사유 없음) 기준 손계산값.
#   조정 후 특관비율 0.9, 초과분 0.85
#   증여의제이익 = 100억 × 0.85 × 지분율
_PIPELINE_ARGS = (SUBJECT, 10_000_000_000, 0, 10_000_000_000, {COUNTERPARTY_NONE: 9_000_000_000})
_EXPECTED_DEEMED = 3_272_500_000
_EXPECTED_TAX = 826_750_000


def test_pipeline_totals(fixture_data):
    r = fixture_data.evaluate(*_PIPELINE_ARGS)
    assert r["size"] == "일반"
    assert r["related_sales_ratio"] == 0.9
    assert r["deemed_gift_total"] == _EXPECTED_DEEMED
    assert r["gift_tax_total"] == _EXPECTED_TAX
    assert r["taxable"] is True


# --- 정상거래비율 문턱 -------------------------------------------------------
# 비율이 두 개인 것이 함정이다. 정상거래비율(일반 30%)은 과세 여부를 가르는 문턱이고,
# 공제거래비율(일반 5%)은 계산식에서 빼는 값이다. 종전에는 문턱을 아무 데서도 검사하지
# 않아, 조정비율 10.3% 인 일반법인이 (10.3% - 5%) > 0 이라는 이유로 과세로 나왔다.
# 골든 넘버 케이스는 전부 비율 60~90% 라 이 결함이 드러나지 않았다.

def test_below_normal_ratio_is_not_taxable(fixture_data):
    """일반 10.3% < 30% → 과세대상이 아니어야 한다(회귀 방지)."""
    r = fixture_data.evaluate(SUBJECT, 50_000_000_000, 0, 100_000_000_000,
                              {COUNTERPARTY_NONE: 10_300_000_000})
    assert r["size"] == "일반"
    assert r["normal_ratio"] == 0.3
    assert r["related_sales_ratio"] == pytest.approx(0.103)
    assert r["gift_tax_total"] == 0
    assert r["deemed_gift_total"] == 0
    assert r["taxable"] is False


def test_reason_states_ratio_shortfall_not_a_false_claim(fixture_data):
    """사유 문구가 '30%를 초과' 라고 단정하면 안 된다 — 실제로는 미달이다."""
    r = fixture_data.evaluate(SUBJECT, 50_000_000_000, 0, 100_000_000_000,
                              {COUNTERPARTY_NONE: 10_300_000_000})
    assert "초과하고" not in r["reason"], r["reason"]
    assert "이하" in r["reason"], r["reason"]


def test_ratio_exactly_at_normal_ratio_is_not_taxable(fixture_data):
    """'초과' 이므로 같은 값은 과세하지 않는다."""
    r = fixture_data.evaluate(SUBJECT, 50_000_000_000, 0, 100_000_000_000,
                              {COUNTERPARTY_NONE: 30_000_000_000})
    assert r["related_sales_ratio"] == pytest.approx(0.3)
    assert r["taxable"] is False
    assert r["gift_tax_total"] == 0


def test_just_over_normal_ratio_is_taxable(fixture_data):
    """문턱을 넘으면 정상적으로 과세된다 — 문턱이 과하게 막지 않는지 확인."""
    r = fixture_data.evaluate(SUBJECT, 50_000_000_000, 0, 100_000_000_000,
                              {COUNTERPARTY_NONE: 30_100_000_000})
    assert r["taxable"] is True
    assert r["gift_tax_total"] > 0
    assert "초과하고" in r["reason"]


def test_threshold_uses_ratio_after_exclusions(fixture_data):
    """판정 비율은 **과세제외 후** 값이다.

    ⑩ 거래처(마바물산)는 전액 과세제외되므로, 과세제외 전 비율이 90% 여도
    조정 후에는 0% 가 되어 과세대상이 아니다.
    """
    r = fixture_data.evaluate(SUBJECT, 10_000_000_000, 0, 10_000_000_000,
                              {COUNTERPARTY_10: 9_000_000_000})
    assert r["related_sales_ratio"] == pytest.approx(0.9), "집계 비율 자체는 90%"
    assert r["taxable"] is False
    assert "이하" in r["reason"], r["reason"]


def test_admin_review_agrees_with_evaluate_on_the_threshold(fixture_data):
    """관리자 화면이 식을 따로 계산하다 총계와 어긋나면 안 된다."""
    args = (SUBJECT, 50_000_000_000, 0, 100_000_000_000,
            {COUNTERPARTY_NONE: 10_300_000_000})
    plain = fixture_data.evaluate(*args)
    admin = fixture_data.evaluate_admin_review(*args)
    assert admin["gift_tax_total"] == plain["gift_tax_total"] == 0
    assert all(d["gift_tax"] == 0 for d in admin["shareholder_details"])
    assert all(d["taxable"] is False for d in admin["shareholder_details"])
    # 주주별 합계와 총계가 맞아야 한다.
    assert sum(d["gift_tax"] for d in admin["shareholder_details"]) == admin["gift_tax_total"]


def test_admin_shareholder_rows_are_consistent_when_taxable(fixture_data):
    """과세되는 경우에도 주주별 합계 = 총계 여야 한다."""
    args = (SUBJECT, 50_000_000_000, 0, 100_000_000_000,
            {COUNTERPARTY_NONE: 60_000_000_000})
    admin = fixture_data.evaluate_admin_review(*args)
    assert admin["gift_tax_total"] > 0
    assert sum(d["gift_tax"] for d in admin["shareholder_details"]) == admin["gift_tax_total"]
    # 문턱을 넘겼는데 지분이 0 인 주주(B)는 여전히 과세되지 않는다.
    b = next(d for d in admin["shareholder_details"] if d["code"] == "B")
    assert b["holding_ratio"] == 0 and b["gift_tax"] == 0


def test_tax_adjustments_are_added_to_operating_income(fixture_data):
    """세후영업이익 = 영업이익 ± 세무조정 - 법인세 상당액."""
    adjusted = fixture_data.evaluate(
        SUBJECT, 8_000_000_000, 0, 10_000_000_000, {COUNTERPARTY_NONE: 9_000_000_000},
        tax_adjustments={"감가상각비": 3_000_000_000, "퇴직급여충당금": -1_000_000_000})
    assert adjusted["gift_tax_total"] == _EXPECTED_TAX
    assert adjusted["deemed_gift_total"] == _EXPECTED_DEEMED


def test_corporate_tax_is_subtracted(fixture_data):
    with_tax = fixture_data.evaluate(
        SUBJECT, 12_000_000_000, 2_000_000_000, 10_000_000_000,
        {COUNTERPARTY_NONE: 9_000_000_000})
    assert with_tax["gift_tax_total"] == _EXPECTED_TAX


def test_section10_sales_drop_out_of_the_ratio(fixture_data):
    """⑩ 거래처 매출은 분자·분모에서 모두 빠져 세액에 잡히지 않는다."""
    r = fixture_data.evaluate(SUBJECT, 10_000_000_000, 0, 10_000_000_000,
                              {COUNTERPARTY_10: 9_000_000_000})
    assert r["related_sales_total"] == 9_000_000_000, "특관매출 집계에는 그대로 잡힌다"
    assert r["gift_tax_total"] == 0


def test_general_company_over_100_billion_uses_20_percent_ratio(fixture_data):
    r = fixture_data.evaluate(SUBJECT, 1_000_000, 0, 200_000_000_000,
                              {COUNTERPARTY_NONE: 100_000_000_001})
    assert r["size"] == "일반"
    assert r["normal_ratio"] == 0.2


def test_general_company_at_100_billion_keeps_default_ratio(fixture_data):
    r = fixture_data.evaluate(SUBJECT, 1_000_000, 0, 200_000_000_000,
                              {COUNTERPARTY_NONE: 100_000_000_000})
    assert r["normal_ratio"] == 0.3


def test_company_list_ends_with_catch_all(fixture_data):
    calc = fixture_data
    companies = calc.company_list()
    assert companies[-1] == calc.OTHER_COMPANY
    assert companies.count(calc.OTHER_COMPANY) == 1
    assert calc.OTHER_COMPANY not in calc.SIZES, "catch-all 은 판정 대상 법인이 될 수 없다"


# --- 응답 노출면 (명세 §0) ----------------------------------------------------

def test_public_payload_field_allowlist(fixture_data):
    r = fixture_data.evaluate(SUBJECT, 10_000_000_000, 0, 10_000_000_000,
                              {COUNTERPARTY_14: 1_000_000_000})
    assert set(r) <= PUBLIC_FIELDS, set(r) - PUBLIC_FIELDS
    for detail in r["exclusion_details"]:
        assert set(detail) == PUBLIC_DETAIL_FIELDS, detail
        # 0%(사유 없음)와 100%(⑩·§18) 외의 값은 곧 지배주주 지분율이므로 나가면 안 된다.
        assert detail["rate"] in (None, 0.0, 1.0), detail


def test_public_payload_hides_ratio_exclusion_amounts_and_totals(fixture_data):
    """⑭ 지분율 상당액은 거래처별 금액도, 합계도 주지 않는다.

    합계를 주면 거래처 1건짜리 요청의 (합계 ÷ 매출액) 이 곧 지분율이고,
    여러 건을 넣어도 요청을 쪼갠 차분으로 개별 몫이 복원된다.
    """
    r = fixture_data.evaluate(SUBJECT, 10_000_000_000, 0, 10_000_000_000,
                              {COUNTERPARTY_14: 1_000_000_000})
    detail = next(d for d in r["exclusion_details"] if d["counterparty"] == COUNTERPARTY_14)
    assert detail["rate"] is None
    assert detail["excluded_sales"] is None
    for leaked in ("rate_min", "rate_max", "excluded_sales_min", "excluded_sales_max",
                   "by_shareholder"):
        assert leaked not in detail, leaked
    for leaked in ("ratio_exclusion_total_min", "ratio_exclusion_total_max"):
        assert leaked not in r, leaked


def test_section10_amount_stays_visible(fixture_data):
    """⑩ 은 적용률이 100% 라 지분율 정보가 없다 — 금액을 그대로 노출한다."""
    r = fixture_data.evaluate(SUBJECT, 10_000_000_000, 0, 10_000_000_000,
                              {COUNTERPARTY_10: 1_000_000_000})
    detail = next(d for d in r["exclusion_details"] if d["counterparty"] == COUNTERPARTY_10)
    assert detail["rate"] == 1.0
    assert detail["excluded_sales"] == 1_000_000_000


def test_admin_payload_keeps_ranges_totals_and_breakdown(fixture_data):
    calc = fixture_data
    r = calc.evaluate_admin_review(SUBJECT, 10_000_000_000, 0, 10_000_000_000,
                                   {COUNTERPARTY_14: 1_000_000_000})
    detail = next(d for d in r["exclusion_details"] if d["counterparty"] == COUNTERPARTY_14)
    assert detail["rate_min"] == 0            # B (지분 없음)
    assert detail["rate_max"] == 0.4          # A
    assert len(detail["by_shareholder"]) == len(calc.CODES)
    assert r["ratio_exclusion_total_min"] == 0
    assert r["ratio_exclusion_total_max"] == pytest.approx(400_000_000)
    assert r["shareholder_details"]


def test_admin_and_public_totals_agree(fixture_data):
    calc = fixture_data
    plain = calc.evaluate(*_PIPELINE_ARGS)
    review = calc.evaluate_admin_review(*_PIPELINE_ARGS)
    assert review["gift_tax_total"] == plain["gift_tax_total"]
    assert review["deemed_gift_total"] == plain["deemed_gift_total"]
    assert sum(d["gift_tax"] for d in review["shareholder_details"]) == plain["gift_tax_total"]


# --- API 노출면·권한 ----------------------------------------------------------

def test_evaluate_endpoint_returns_only_public_fields(fixture_data):
    body = {"company": SUBJECT, "operating_income": 10_000_000_000, "corporate_tax": 0,
            "total_sales": 10_000_000_000, "related_sales": {COUNTERPARTY_14: 1_000_000_000}}
    r = client.post("/api/evaluate", json=body, headers=_auth(_admin_token()))
    assert r.status_code == 200, r.text
    data = r.json()
    assert set(data) <= PUBLIC_FIELDS, set(data) - PUBLIC_FIELDS
    for detail in data["exclusion_details"]:
        assert set(detail) == PUBLIC_DETAIL_FIELDS, detail
        assert detail["rate"] in (None, 0.0, 1.0), detail


def test_admin_review_rejects_anonymous():
    body = {"company": SUBJECT, "operating_income": 0, "corporate_tax": 0, "total_sales": 0}
    assert client.post("/api/admin/evaluate-review", json=body).status_code == 401


def test_admin_review_rejects_non_admin():
    r = client.post("/api/auth/login", json={"username": "이지메디컴", "password": "demo"})
    assert r.status_code == 200, r.text
    body = {"company": SUBJECT, "operating_income": 0, "corporate_tax": 0, "total_sales": 0}
    resp = client.post("/api/admin/evaluate-review", json=body,
                       headers=_auth(r.json()["access_token"]))
    assert resp.status_code == 403


def test_evaluate_rejects_other_company_for_non_admin(fixture_data):
    r = client.post("/api/auth/login", json={"username": "이지메디컴", "password": "demo"})
    body = {"company": SUBJECT, "operating_income": 0, "corporate_tax": 0, "total_sales": 0}
    resp = client.post("/api/evaluate", json=body, headers=_auth(r.json()["access_token"]))
    assert resp.status_code == 403


def test_companies_endpoint_returns_names_only(fixture_data):
    r = client.get("/api/companies", headers=_auth(_admin_token()))
    assert r.status_code == 200
    data = r.json()
    assert set(data) == {"companies"}
    assert all(isinstance(name, str) for name in data["companies"])
