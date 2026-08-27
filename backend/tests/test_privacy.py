from calc import evaluate


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
        # ⑭ 지분율 상당액은 거래처별 금액 대신 아래 합계 범위로만 제공한다.
        "exclusion_details",
        "ratio_exclusion_total_min",
        "ratio_exclusion_total_max",
    }
    assert set(r.keys()) <= allowed, f"응답에 허용되지 않은 필드 존재: {set(r.keys()) - allowed}"
