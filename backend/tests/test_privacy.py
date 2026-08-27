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
        "normal_ratio",
        "deemed_gift_total",
        "gift_tax_total",
        "reason",
        # 과세제외 내역: 사유·조문과, 주주 무관하게 동일한 건(⑩/§18)의 적용률·금액만 담긴다.
        # ⑭ 지분율 상당액은 적용률·금액 모두 None 이며 어떤 합계도 함께 내보내지 않는다.
        "exclusion_details",
    }
    assert set(r.keys()) <= allowed, f"응답에 허용되지 않은 필드 존재: {set(r.keys()) - allowed}"
