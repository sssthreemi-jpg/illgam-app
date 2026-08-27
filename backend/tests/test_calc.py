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
                        {"대웅제약": 5_000_000_000}, None, {})["gift_tax_total"])


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


if __name__ == "__main__":
    test_ezmedicom(); test_daewoongpet(); print("PASS")
