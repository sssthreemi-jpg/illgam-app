import backend.calc as calc
from backend.calc import evaluate, company_list, OTHER_COMPANY, SIZES

def test_ezmedicom():
    r = evaluate("이지메디컴", 10_000_000_000, 0, 10_000_000_000,
                 {"대웅제약": 9_000_000_000})
    assert r["gift_tax_total"] == 1_559_826_490, r["gift_tax_total"]
    assert r["taxable"] is True

def test_daewoongpet():
    r = evaluate("대웅펫", 5_000_000_000, 0, 8_000_000_000,
                 {"대웅제약": 5_000_000_000})
    assert r["gift_tax_total"] == 22_634_130, r["gift_tax_total"]

def test_general_company_over_100_billion_uses_20_percent_ratio():
    r = evaluate("대웅바이오", 1_000_000, 0, 200_000_000_000,
                 {"대웅제약": 100_000_000_001})
    assert r["size"] == "일반"
    assert r["normal_ratio"] == 0.2

def test_general_company_at_100_billion_keeps_default_ratio():
    r = evaluate("대웅바이오", 1_000_000, 0, 200_000_000_000,
                 {"대웅제약": 100_000_000_000})
    assert r["normal_ratio"] == 0.3

def test_tax_adjustments_are_added_to_operating_income():
    """세후영업이익 = 영업이익 ± 세무조정금액 - 법인세 상당액.

    영업이익 80억 + 가산 30억 - 차감 10억 = 100억 이므로,
    세무조정 없이 영업이익 100억을 넣은 결과와 정확히 같아야 한다.
    """
    base = evaluate("이지메디컴", 10_000_000_000, 0, 10_000_000_000,
                    {"대웅제약": 9_000_000_000})
    adjusted = evaluate("이지메디컴", 8_000_000_000, 0, 10_000_000_000,
                        {"대웅제약": 9_000_000_000},
                        tax_adjustments={"감가상각비": 3_000_000_000,
                                         "퇴직급여충당금": -1_000_000_000})
    assert adjusted["gift_tax_total"] == base["gift_tax_total"]
    assert adjusted["deemed_gift_total"] == base["deemed_gift_total"]


def test_corporate_tax_is_still_subtracted():
    """법인세 상당액 차감은 세무조정 도입 이후에도 유지된다."""
    base = evaluate("이지메디컴", 10_000_000_000, 0, 10_000_000_000,
                    {"대웅제약": 9_000_000_000})
    with_tax = evaluate("이지메디컴", 12_000_000_000, 2_000_000_000, 10_000_000_000,
                        {"대웅제약": 9_000_000_000})
    assert with_tax["gift_tax_total"] == base["gift_tax_total"]


def test_tax_adjustments_omitted_keeps_previous_behaviour():
    """세무조정을 넘기지 않으면 기존 계산과 동일해야 한다(회귀 방지)."""
    assert (evaluate("대웅펫", 5_000_000_000, 0, 8_000_000_000,
                     {"대웅제약": 5_000_000_000})["gift_tax_total"]
            == evaluate("대웅펫", 5_000_000_000, 0, 8_000_000_000,
                        {"대웅제약": 5_000_000_000}, {})["gift_tax_total"])


def test_company_list_ends_with_other_company_catch_all():
    """거래처 catch-all 이름은 서버가 정의해 목록에 실어 보낸다(프론트엔드가 만들지 않는다)."""
    companies = company_list()
    assert companies[-1] == OTHER_COMPANY
    assert companies.count(OTHER_COMPANY) == 1
    assert OTHER_COMPANY not in SIZES, "catch-all 은 판정 대상 법인이 될 수 없다"


def test_other_company_sales_count_as_related_without_exclusion():
    """기타법인 매출은 특관매출에 전액 잡히고, 지분 데이터가 없으므로 제외분은 생기지 않는다."""
    r = evaluate("이지메디컴", 10_000_000_000, 0, 10_000_000_000,
                 {OTHER_COMPANY: 4_000_000_000})
    assert r["related_sales_total"] == 4_000_000_000
    assert r["related_sales_ratio"] == 0.4


# --- 과세제외 판정 (상증령 §34의3) -------------------------------------------

def test_section10_takes_precedence_over_section14(monkeypatch):
    """⑩ 기본 과세제외가 성립하면 ⑭ 는 보지 않는다. §18 에 등재돼 있어도 마찬가지다."""
    monkeypatch.setitem(calc.SECTION18, "이지메디컴", {"에비슨케어"})
    verdict = calc.exclusion_for("이지메디컴", "에비슨케어", 1_000_000_000, "A")
    assert verdict["article"] == calc.ARTICLE_10
    assert verdict["rate"] == 1.0
    assert verdict["excluded_sales"] == 1_000_000_000


def test_plain_indirect_holding_is_not_fully_excluded():
    """단순 간접지분 관계는 전액 제외 대상이 아니다 — ⑭ 지분율 상당액만 적용된다."""
    verdict = calc.exclusion_for("이지메디컴", "대웅제약", 9_000_000_000, "A")
    assert verdict["article"] == calc.ARTICLE_14_RATIO
    assert 0 < verdict["rate"] < 1
    assert verdict["excluded_sales"] < 9_000_000_000


def test_section18_indirect_investor_excludes_full_sales(monkeypatch):
    """§14① §18 간접출자법인과의 거래는 매출액 100% 를 제외한다."""
    monkeypatch.setitem(calc.SECTION18, "이지메디컴", {"대웅제약"})
    r = evaluate("이지메디컴", 10_000_000_000, 0, 10_000_000_000,
                 {"대웅제약": 9_000_000_000})
    detail = next(d for d in r["exclusion_details"] if d["counterparty"] == "대웅제약")
    assert detail["article"] == calc.ARTICLE_14_1
    assert detail["rate"] == 1.0
    assert detail["excluded_sales"] == 9_000_000_000
    assert r["gift_tax_total"] == 0, "전액 제외되면 조정 후 특관비율이 0 이 된다"


def test_overlapping_reasons_apply_only_the_largest(monkeypatch):
    """사유가 겹치면 합산하지 않고 과세제외금액이 가장 큰 하나만 적용한다."""
    assert calc.HOLD["대웅제약"]["A"] > 0, "겹치는 ⑭ 지분율 사유가 실제로 존재해야 한다"
    monkeypatch.setitem(calc.SECTION18, "이지메디컴", {"대웅제약"})
    verdict = calc.exclusion_for("이지메디컴", "대웅제약", 9_000_000_000, "A")
    assert verdict["rate"] == 1.0
    assert verdict["excluded_sales"] == 9_000_000_000, "지분율 상당액이 더해지면 안 된다"


def test_exclusion_details_expose_reason_article_rate_and_amount():
    r = evaluate("이지메디컴", 10_000_000_000, 0, 10_000_000_000,
                 {"대웅제약": 9_000_000_000})
    detail = next(d for d in r["exclusion_details"] if d["counterparty"] == "대웅제약")
    assert set(detail) == {"counterparty", "sales", "reason", "article", "rate", "excluded_sales"}
    assert detail["reason"] == calc.REASON_14_RATIO


def test_ratio_exclusion_amounts_are_hidden_from_public_payload():
    """⑭ 지분율 상당액은 (금액 ÷ 매출액) 으로 지분율이 역산되므로 거래처별 값을 주지 않는다."""
    r = evaluate("이지메디컴", 10_000_000_000, 0, 10_000_000_000,
                 {"대웅제약": 9_000_000_000})
    detail = next(d for d in r["exclusion_details"] if d["counterparty"] == "대웅제약")
    assert detail["rate"] is None
    assert detail["excluded_sales"] is None
    for leaked in ("rate_min", "rate_max", "excluded_sales_min", "excluded_sales_max",
                   "by_shareholder"):
        assert leaked not in detail, leaked
    # 합계는 여러 거래처가 섞여 개별 지분율로 분해되지 않으므로 공개한다.
    assert r["ratio_exclusion_total_max"] > 0
    assert r["ratio_exclusion_total_min"] <= r["ratio_exclusion_total_max"]


def test_section10_amount_stays_visible_in_public_payload():
    """⑩ 은 적용률이 100% 라 지분율 정보가 없다 — 거래처별 금액을 그대로 노출한다."""
    r = evaluate("이지메디컴", 10_000_000_000, 0, 10_000_000_000,
                 {"에비슨케어": 1_000_000_000})
    detail = next(d for d in r["exclusion_details"] if d["counterparty"] == "에비슨케어")
    assert detail["article"] == calc.ARTICLE_10
    assert detail["rate"] == 1.0
    assert detail["excluded_sales"] == 1_000_000_000
    # ⑭ 건이 없으므로 합계는 0 이다.
    assert r["ratio_exclusion_total_max"] == 0


def test_admin_payload_keeps_ratio_ranges_and_shareholder_breakdown():
    """관리자 응답에만 거래처별 범위와 주주별 내역이 실린다."""
    r = calc.evaluate_admin_review("이지메디컴", 10_000_000_000, 0, 10_000_000_000,
                                   {"대웅제약": 9_000_000_000})
    detail = next(d for d in r["exclusion_details"] if d["counterparty"] == "대웅제약")
    assert 0 <= detail["rate_min"] < detail["rate_max"] < 1
    assert detail["excluded_sales_min"] < detail["excluded_sales_max"] < detail["sales"]
    assert len(detail["by_shareholder"]) == len(calc.CODES)


def test_no_registered_section18_keeps_golden_numbers():
    """§18 미등재 상태(기본값)에서는 엑셀 검증본 결과가 그대로 유지된다."""
    assert calc.SECTION18 == {}, "기본 데이터 파일에는 등재된 관계가 없어야 한다"
    r = evaluate("이지메디컴", 10_000_000_000, 0, 10_000_000_000,
                 {"대웅제약": 9_000_000_000})
    assert r["gift_tax_total"] == 1_559_826_490


if __name__ == "__main__":
    test_ezmedicom(); test_daewoongpet(); print("PASS")
