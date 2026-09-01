import pytest

from backend.calc import evaluate

# 실제 법인명("이지메디컴")과 소유구조에 의존한다.
pytestmark = pytest.mark.realdata


def test_privacy_fields():
    r = evaluate("이지메디컴", 1_000_000, 0, 1_000_000, {"대웅제약": 100_000})
    allowed = {
        "company",
        "size",
        "taxable",
        "total_sales",
        "related_sales_total",
        "related_sales_ratio",
        "article10_total",
        "taxation_ratio",
        "dividend_deduction_total",
        "notices",
        "filing_credit_total",
        "gift_tax_payable_total",
        "normal_ratio",
        # 계산에 쓴 연도 이름표와 기준시점 문구. 지분 정보가 아니다.
        "year",
        "data_as_of",
        "deemed_gift_total",
        "gift_tax_total",
        "reason",
        # 요건별 판정 내역. 비교에 쓴 비율과 문턱(정상거래비율·한계보유비율)만 담는다.
        # 문턱은 params.json 의 규칙값이고, 보유요건은 '넘는 사람이 있는지'만 담는다
        # (인원수·코드는 admin=True 일 때만 붙는다).
        "criteria",
        # 과세제외 내역: 사유·조문과, 주주 무관하게 동일한 건(⑩/§18)의 적용률·금액만 담긴다.
        # ⑭ 지분율 상당액은 적용률·금액 모두 None 이며 어떤 합계도 함께 내보내지 않는다.
        "exclusion_details",
    }
    assert set(r.keys()) <= allowed, f"응답에 허용되지 않은 필드 존재: {set(r.keys()) - allowed}"
