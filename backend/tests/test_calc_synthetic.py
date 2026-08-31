"""합성 fixture 데이터로 도는 로직 테스트.

실제 지분 데이터(`backend/data/*.json`)는 기밀이라 저장소에 없다. 그래서 CI 에서는
`test_calc.py`(엑셀 검증본 골든 넘버)가 통째로 skip 된다 — 여기가 그 공백을 메운다.

검증 대상은 숫자 자체가 아니라 **계산 파이프라인·과세제외 우선순위·응답 노출면**이다.
`fixture_data` 픽스처(backend/conftest.py)가 실제 데이터 유무와 무관하게 항상
`backend/tests/fixtures/data/` 를 적재하므로, 로컬에서도 CI 와 같은 결과가 나온다.

fixture 구성은 backend/tests/fixtures/data/README.md 참조.
"""
import json

import pytest
from fastapi.testclient import TestClient

from backend.auth import ADMIN_USERNAME, ADMIN_PASSWORD
from backend.main import app

client = TestClient(app)

SUBJECT = "가나전자"          # 일반, 마바물산에 30% 출자
COUNTERPARTY_10 = "마바물산"   # ⑩ 기본 과세제외
COUNTERPARTY_14 = "사아텍"     # ⑭ 지분율 상당액 (A=0.4 … B=0)
COUNTERPARTY_NONE = "자차산업"  # 지배주주 지분율 전무 → 과세제외 사유 없음
COUNTERPARTY_HC = "지주자회사"   # ⑭2호 (지주회사 지분율 70% > 지배주주 A 40%)

PUBLIC_FIELDS = {
    "company", "size", "taxable", "total_sales", "related_sales_total",
    "related_sales_ratio", "article10_total", "taxation_ratio",
    "normal_ratio", "deemed_gift_total", "gift_tax_total",
    # 계산에 쓴 연도 이름표와 기준시점 문구. 지분 정보가 아니다.
    "year", "data_as_of",
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
#   증여의제이익 = 100억 × 0.85 × (과세대상 주주 지분율 합)
#
# 과세대상 주주는 요건③ 으로 걸러진다 — 한계보유비율(일반 3%)을 **개인별로** 초과한
# A(20%)·C(10%)·D(5%) 만 남고 C1(2%)·C11(1%)·C12(0.5%) 는 빠진다. 지분율 합 0.385
# 에서 0.035 가 빠져 0.35 이므로 100억 × 0.85 × 0.35 = 29.75억.
# 요건③ 도입 전 값은 3,272,500,000(=0.385 전체) 이었다.
_PIPELINE_ARGS = (SUBJECT, 10_000_000_000, 0, 10_000_000_000, {COUNTERPARTY_NONE: 9_000_000_000})
_EXPECTED_DEEMED = 2_975_000_000
_EXPECTED_TAX = 790_000_000   # 요건③ 도입 전 826,750,000


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


# --- 한계보유비율 문턱(과세요건 ③) ------------------------------------------
# 보유비율에도 비율이 두 개다. 한계보유비율(일반 3%, 중견·중소 10%)은 과세대상인지
# 가르는 문턱이고, 공제보유비율(일반 0%, 중견 5%, 중소 10%)은 계산식에서 빼는 값이다.
# 정상거래비율에서 한 번 겪은 함정을 보유비율 쪽에서 그대로 반복해, 요건③ 이 통째로
# 빠져 있었다. 문턱은 합계가 아니라 **개인별**로 본다 — 한계보유비율을 넘긴 주주만
# 과세대상이다. 위 _PIPELINE_ARGS 의 가나전자가 이 구조를 그대로 보여준다(A·C·D 만
# 남고 C1·C11·C12 는 빠진다).
#
# 중소는 공제보유비율(10%)이 한계보유비율(10%)과 같아 우연히 맞았고, 일반·중견만
# 드러난다. 그래서 두 규모를 모두 세워 둔다.

GATE_GENERAL = "요건삼일반"   # 일반, A 2% <= 3%
GATE_MIDSIZE = "요건삼중견"   # 중견, A 8% <= 10%
GATE_ABOVE = "요건삼경계"     # 일반, A 4% > 3% (대조군)


def test_holding_at_or_below_limit_is_not_taxable_general(fixture_data):
    """일반 A 2% <= 3% → 거래비율을 넘겨도 과세대상이 아니다."""
    r = fixture_data.evaluate(GATE_GENERAL, 50_000_000_000, 0, 100_000_000_000,
                              {COUNTERPARTY_NONE: 90_000_000_000})
    assert r["size"] == "일반"
    assert r["related_sales_ratio"] == pytest.approx(0.9)   # 요건② 는 충족
    assert r["gift_tax_total"] == 0
    assert r["deemed_gift_total"] == 0
    assert r["taxable"] is False


def test_holding_at_or_below_limit_is_not_taxable_midsize(fixture_data):
    """중견 A 8% <= 10% → 공제보유비율(5%)은 넘지만 한계보유비율은 못 넘는다.

    게이트가 없으면 (8% - 5%) > 0 이라 세액이 생기던 조합이다.
    """
    r = fixture_data.evaluate(GATE_MIDSIZE, 50_000_000_000, 0, 100_000_000_000,
                              {COUNTERPARTY_NONE: 90_000_000_000})
    assert r["size"] == "중견"
    assert r["gift_tax_total"] == 0
    assert r["taxable"] is False


def test_holding_above_limit_stays_taxable(fixture_data):
    """A 4% > 3% → 문턱이 과하게 막지 않는다(대조군)."""
    r = fixture_data.evaluate(GATE_ABOVE, 50_000_000_000, 0, 100_000_000_000,
                              {COUNTERPARTY_NONE: 90_000_000_000})
    assert r["taxable"] is True
    assert r["gift_tax_total"] > 0


def test_reason_distinguishes_holding_shortfall_from_ratio_shortfall(fixture_data):
    """요건② 는 넘고 요건③ 만 미달인 경우 사유가 '보유요건' 을 짚어야 한다."""
    r = fixture_data.evaluate(GATE_GENERAL, 50_000_000_000, 0, 100_000_000_000,
                              {COUNTERPARTY_NONE: 90_000_000_000})
    # '보유요건' 만 보면 과세 문구("보유요건을 충족하여 과세대상")도 통과해 버린다.
    # 게이트를 지웠을 때 반드시 깨지도록 '미충족/해당없음' 까지 못박는다.
    assert "보유요건 미충족" in r["reason"], r["reason"]
    assert "해당없음" in r["reason"], r["reason"]
    assert "과세대상" not in r["reason"], r["reason"]
    assert "이하여서" not in r["reason"], r["reason"]   # 거래비율 미달 문구가 아니어야 한다


def test_admin_review_applies_the_same_holding_gate(fixture_data):
    """관리자 화면도 같은 게이트를 탄다 — 두 경로의 숫자가 갈리면 안 된다."""
    r = fixture_data.evaluate_admin_review(GATE_MIDSIZE, 50_000_000_000, 0,
                                           100_000_000_000,
                                           {COUNTERPARTY_NONE: 90_000_000_000})
    assert r["gift_tax_total"] == 0
    assert all(d["deemed_gift_income"] == 0 for d in r["shareholder_details"])
    assert all(d["taxable"] is False for d in r["shareholder_details"])


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


def test_general_company_exactly_at_100_billion_keeps_default_ratio(fixture_data):
    """문턱은 '1천억원 초과'라 정확히 1천억이면 아직 30% 다."""
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


SHAREHOLDER_DETAIL_FIELDS = {
    "code", "holding_ratio", "excluded_sales", "adjusted_related_ratio",
    "after_tax_operating_income", "deemed_gift_income", "gift_tax", "taxable",
}


def test_shareholder_details_never_carry_real_names(fixture_data):
    """지배주주 실명은 응답에 실리지 않는다.

    화면은 코드(A/B/C/D/C1/C11/C12)로만 표시하므로, 실명을 내보내면 개발자도구
    네트워크 탭에 그대로 노출될 뿐이다. params.json 의 이름은 서버 안에서만 쓴다.
    """
    calc = fixture_data
    r = calc.evaluate_admin_review(*_PIPELINE_ARGS)
    names = {s["name"] for s in calc.PARAMS["shareholders"]}
    assert names, "fixture params.json 에 이름이 있어야 이 테스트가 의미를 가진다"

    for detail in r["shareholder_details"]:
        assert set(detail.keys()) == SHAREHOLDER_DETAIL_FIELDS, set(detail.keys())
        assert detail["code"] in calc.CODES

    # 응답 전체를 훑어 이름이 어디에도 없는지 본다(다른 필드로 새는 경우까지).
    blob = json.dumps(r, ensure_ascii=False, default=str)
    leaked = sorted(n for n in names if n in blob)
    assert not leaked, f"응답에 지배주주 실명이 들어 있다: {leaked}"


def test_admin_endpoint_response_has_no_real_names(fixture_data):
    """HTTP 응답 본문 기준으로도 확인한다."""
    calc = fixture_data
    body = {"company": SUBJECT, "operating_income": 10_000_000_000, "corporate_tax": 0,
            "total_sales": 10_000_000_000, "related_sales": {COUNTERPARTY_NONE: 9_000_000_000}}
    r = client.post("/api/admin/evaluate-review", json=body, headers=_auth(_admin_token()))
    assert r.status_code == 200, r.text
    names = {s["name"] for s in calc.PARAMS["shareholders"]}
    leaked = sorted(n for n in names if n in r.text)
    assert not leaked, f"응답 본문에 지배주주 실명이 들어 있다: {leaked}"


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
    # year 는 어느 연도 목록인지 알려주는 이름표다. 규모·지분 정보는 여전히 없다.
    assert set(data) == {"companies", "year"}
    assert all(isinstance(name, str) for name in data["companies"])


# --- ⑭2호(지주회사 지분율 상당액)와 판정/계산 비율 분리 -------------------------

def test_section14_clause2_beats_clause3_when_larger(fixture_data):
    """⑭ 는 호별 금액 중 가장 큰 하나만 쓴다. 지주회사 지분율(70%)이 지배주주(40%)보다 크다."""
    calc = fixture_data
    verdict = calc.exclusion_for(SUBJECT, COUNTERPARTY_HC, 1_000_000_000, "A")
    assert verdict["article"] == calc.ARTICLE_14_2
    assert verdict["excluded_sales"] == pytest.approx(700_000_000)


def test_section14_clause2_needs_the_shareholder_to_own_the_counterparty(fixture_data):
    """지배주주가 그 거래처 지분을 전혀 안 가지면 ⑭2호도 성립하지 않는다."""
    calc = fixture_data
    verdict = calc.exclusion_for(SUBJECT, COUNTERPARTY_NONE, 1_000_000_000, "A")
    assert verdict["excluded_sales"] == 0
    assert verdict["article"] == calc.ARTICLE_NONE


def test_section14_clause2_needs_the_subject_under_the_same_holding_company(fixture_data):
    """수혜법인이 그 지주회사의 자·손자회사가 아니면 ⑭2호를 쓰지 않는다."""
    calc = fixture_data
    verdict = calc.exclusion_for("다라화학", COUNTERPARTY_HC, 1_000_000_000, "A")
    assert verdict["article"] == calc.ARTICLE_14_RATIO
    assert verdict["excluded_sales"] == pytest.approx(400_000_000)


def test_article10_amount_is_deducted_before_section14(fixture_data):
    """⑩ 을 먼저 빼고 남은 금액에 ⑭ 를 적용한다. 종전에는 ⑩ 이 있으면 ⑭ 를 아예 안 봤다."""
    calc = fixture_data
    verdict = calc.exclusion_for(SUBJECT, COUNTERPARTY_HC, 1_000_000_000, "A",
                                 article10=200_000_000)
    assert verdict["excluded_sales"] == pytest.approx(200_000_000 + 560_000_000)
    assert verdict["article10"] == 200_000_000


def test_section18_clause1_is_skipped_when_article10_exists(fixture_data, monkeypatch):
    """⑩ 이 있는 거래처에는 ⑭1호(전액 제외)를 적용하지 않는다."""
    calc = fixture_data
    monkeypatch.setitem(calc.dataset().section18, SUBJECT, {COUNTERPARTY_HC})
    full = calc.exclusion_for(SUBJECT, COUNTERPARTY_HC, 1_000_000_000, "A")
    assert full["article"] == calc.ARTICLE_14_1, "⑩ 이 없으면 1호가 전액 제외로 이긴다"
    partial = calc.exclusion_for(SUBJECT, COUNTERPARTY_HC, 1_000_000_000, "A",
                                 article10=200_000_000)
    assert partial["article"] == calc.ARTICLE_14_2
    assert partial["excluded_sales"] == pytest.approx(760_000_000)


def test_gate_uses_the_article10_only_ratio_not_the_adjusted_one(fixture_data):
    """과세요건 판정은 ⑩ 만 뺀 비율로 한다. ⑭ 까지 뺀 비율로 판정하면 과세대상이 사라진다.

    2025 대웅바이오가 정확히 이 모양이다 — 판정비율 22.42%(> 20%)로 과세대상인데
    계산비율은 13.55% 다. 둘을 같게 두면 세액이 통째로 0 이 된다.
    """
    calc = fixture_data
    r = calc.evaluate(SUBJECT, 1_000_000_000, 0, 1_000_000_000,
                      {COUNTERPARTY_HC: 400_000_000})
    assert r["taxation_ratio"] == pytest.approx(0.4), "판정비율은 40%"
    assert r["normal_ratio"] == 0.3
    assert r["gift_tax_total"] > 0, "⑭ 제외로 조정비율이 16.7% 가 되어도 과세대상이다"


def test_article10_input_lowers_the_taxation_ratio(fixture_data):
    """⑩ 은 판정비율 자체를 낮춘다. 40% → (4억−1억)/10억 = 30% 로 문턱과 같아져 비과세."""
    calc = fixture_data
    r = calc.evaluate(SUBJECT, 1_000_000_000, 0, 1_000_000_000,
                      {COUNTERPARTY_HC: 400_000_000},
                      article10_exclusions={COUNTERPARTY_HC: 100_000_000})
    assert r["article10_total"] == 100_000_000
    assert r["taxation_ratio"] == pytest.approx(0.3)
    assert r["gift_tax_total"] == 0, "문턱은 '초과'라 같으면 과세하지 않는다"
