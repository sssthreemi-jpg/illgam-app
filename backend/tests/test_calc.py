import pytest

import backend.calc as calc
from backend.calc import evaluate, company_list, OTHER_COMPANY

# 엑셀 검증본 골든 넘버와 실제 소유구조에 의존한다. 합성 fixture 로는 재현할 수 없으므로
# 실제 데이터가 없는 환경(CI)에서는 conftest 가 통째로 건너뛴다.
# 데이터에 의존하지 않는 로직 검증은 test_calc_synthetic.py 가 담당한다.
#
# 세액 골든 넘버는 요건③(한계보유비율) 도입으로 한 번 갱신됐다. 검증본 엑셀은 요건③ 을
# 반영하지 않아 한계보유비율 이하 주주에게도 세액을 매겼고, 그 값이 그대로 여기 박혀
# 있었다. 아래 값은 요건③ 을 적용한 결과이며, 세무 담당자가 과세대상 주주를 직접 확인해
# 확정했다(이지메디컴 C·C11, 대웅펫 C, 대웅바이오 A·C·D).
#   이지메디컴  1,559,826,490 -> 1,524,581,260  (D 1.12%, C1 1.11%, C12 1.57% 제외)
#   대웅펫         22,634,130 ->    18,887,560  (A 6.55%, D 5.32%, C1·C11·C12 제외)
#
# 두 번째 갱신은 절사 위치 변경이다. 산출세액에서 10원 미만을 깎던 것을 원 단위로 두고,
# 신고세액공제(3%)를 뺀 **납부세액에서** 10원 미만을 깎도록 실무 계산내역에 맞췄다.
# 그래서 gift_tax_total(산출세액)의 끝자리가 살아난다.
#   이지메디컴  1,524,581,260 -> 1,524,581,273   납부세액은 1,478,843,910
#   대웅펫         18,887,560 ->    18,887,566   납부세액은    18,320,940
#
# 세 번째 갱신은 ⑭2호 표(holding_company.json)를 그룹 전체로 채우면서 생겼다. 대웅펫은
# 대웅이 66.68% 를 가진 자회사라 대웅제약 향 매출에 ⑭2호가 붙는다. 이지메디컴은 대웅
# 지분이 없어 그대로다. 검증본 엑셀은 ⑭2호를 구현하지 않으므로 이 값은 검증본과 다르다 —
# 기준은 실무 계산내역(대웅바이오 25.4Q)이다.
#   대웅펫         18,887,566 ->     6,240,267   납부세액은     6,053,050
pytestmark = pytest.mark.realdata

def test_ezmedicom():
    r = evaluate("이지메디컴", 10_000_000_000, 0, 10_000_000_000,
                 {"대웅제약": 9_000_000_000})
    assert r["gift_tax_total"] == 1_524_581_273, r["gift_tax_total"]
    assert r["taxable"] is True

def test_daewoongpet():
    r = evaluate("대웅펫", 5_000_000_000, 0, 8_000_000_000,
                 {"대웅제약": 5_000_000_000})
    assert r["gift_tax_total"] == 6_240_267, r["gift_tax_total"]

def test_general_company_over_100_billion_uses_20_percent_ratio():
    r = evaluate("대웅바이오", 1_000_000, 0, 200_000_000_000,
                 {"대웅제약": 100_000_000_001})
    assert r["size"] == "일반"
    assert r["normal_ratio"] == 0.2

def test_general_company_exactly_at_100_billion_keeps_default_ratio():
    """문턱은 '1천억원 초과'라 정확히 1천억이면 아직 30% 다."""
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
    assert OTHER_COMPANY not in calc.SIZES, "catch-all 은 판정 대상 법인이 될 수 없다"


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
    # 합계도 주지 않는다. 거래처 1건만 넣어 호출하면 (합계 ÷ 매출) 이 곧 지분율이고,
    # 여러 건을 넣어도 요청을 쪼갠 차분으로 개별 몫이 복원되기 때문이다.
    for leaked in ("ratio_exclusion_total_min", "ratio_exclusion_total_max"):
        assert leaked not in r, leaked


def test_section10_amount_stays_visible_in_public_payload():
    """⑩ 은 적용률이 100% 라 지분율 정보가 없다 — 거래처별 금액을 그대로 노출한다."""
    r = evaluate("이지메디컴", 10_000_000_000, 0, 10_000_000_000,
                 {"에비슨케어": 1_000_000_000})
    detail = next(d for d in r["exclusion_details"] if d["counterparty"] == "에비슨케어")
    assert detail["article"] == calc.ARTICLE_10
    assert detail["rate"] == 1.0
    assert detail["excluded_sales"] == 1_000_000_000


def test_admin_payload_keeps_ratio_ranges_and_shareholder_breakdown():
    """관리자 응답에만 거래처별 범위와 주주별 내역이 실린다."""
    r = calc.evaluate_admin_review("이지메디컴", 10_000_000_000, 0, 10_000_000_000,
                                   {"대웅제약": 9_000_000_000})
    detail = next(d for d in r["exclusion_details"] if d["counterparty"] == "대웅제약")
    assert 0 <= detail["rate_min"] < detail["rate_max"] < 1
    assert detail["excluded_sales_min"] < detail["excluded_sales_max"] < detail["sales"]
    assert len(detail["by_shareholder"]) == len(calc.CODES)
    # ⑭ 합계 범위는 관리자 응답에만 남긴다.
    assert r["ratio_exclusion_total_max"] > 0
    assert r["ratio_exclusion_total_min"] <= r["ratio_exclusion_total_max"]


def test_no_registered_section18_keeps_golden_numbers():
    """§18 미등재 상태(기본값)에서는 엑셀 검증본 결과가 그대로 유지된다."""
    assert calc.SECTION18 == {}, "기본 데이터 파일에는 등재된 관계가 없어야 한다"
    r = evaluate("이지메디컴", 10_000_000_000, 0, 10_000_000_000,
                 {"대웅제약": 9_000_000_000})
    assert r["gift_tax_total"] == 1_524_581_273


if __name__ == "__main__":
    test_ezmedicom(); test_daewoongpet(); print("PASS")


# --- 실무 계산내역(S: 드라이브 대웅바이오_25.4Q_계산내역.xlsx) 대조 ------------------
#
# 2025 대웅바이오 신고 기준 정답이다. 세후영업이익과 증여의제이익이 **원 단위까지** 맞아야 한다.
# 세액은 아직 다르다 — 정답은 배당소득 공제와 신고세액공제 3% 를 더 반영하는데
# 앱에는 그 두 단계가 없다(별건).

DWBIO_2025_SALES = {
    "대웅": 452_730, "IDS": 318_185, "대웅제약": 119_571_363_317, "대웅개발": 44_545,
    "한올바이오파마": 23_855_010_314, "힐리언스": 181_820, "아피셀테라퓨틱스": 90_000,
    "대웅이엔지": 544_550, "이지메디컴": 590_005, "엠서클": 558_182, "유와이즈원": 135_455,
    "시지바이오": 1_884_706_839, "페이지원": 44_545, "더편한샵": 45_455,
    "디엔컴퍼니": 4_204_544, "힐리언스코어운동": 90_910, "기타법인": 187_600_000,
}
DWBIO_2025_ARTICLE10 = {"대웅제약": 1_713_784_230}
# 계산내역의 지배주주별 (세후영업이익, 증여의제이익)
DWBIO_2025_EXPECTED = {
    "A": (85_139_901_786, 715_119_801),
    "C": (85_051_838_580, 1_371_573_033),
    "D": (85_139_866_285, 580_625_997),
}


def _dwbio_2025():
    return calc.evaluate_admin_review(
        "대웅바이오", 116_207_012_131, 20_999_171_475, 641_338_729_689,
        DWBIO_2025_SALES, year="2025", article10_exclusions=DWBIO_2025_ARTICLE10)


def test_dwbio_2025_taxation_ratio_matches_the_worksheet():
    """판정비율은 ⑩ 만 뺀 22.4206% 다. ⑭ 까지 뺀 13.55% 로 판정하면 비과세가 되어버린다."""
    r = _dwbio_2025()
    assert r["article10_total"] == 1_713_784_230
    assert r["taxation_ratio"] == pytest.approx(0.2242063211, abs=1e-9)
    assert r["normal_ratio"] == 0.2, "특관매출 1천억 초과 → 20%"
    assert r["taxable"] is True


def test_dwbio_2025_matches_the_worksheet_per_shareholder():
    r = _dwbio_2025()
    got = {d["code"]: d for d in r["shareholder_details"]}
    for code, (after, deemed) in DWBIO_2025_EXPECTED.items():
        assert got[code]["after_tax_operating_income"] == pytest.approx(after, abs=1), code
        assert got[code]["deemed_gift_income"] == pytest.approx(deemed, abs=1), code
    for code in ("B", "C1", "C11", "C12"):
        assert got[code]["gift_tax"] == 0, f"{code} 는 요건③(한계보유비율 3%) 미달"


def test_dwbio_2025_exclusion_total_matches_the_worksheet():
    """계산내역의 ⑭ MAX 합계 66,105,831,055 + ⑩ 1,713,784,230 = 앱의 과세제외 합계."""
    r = _dwbio_2025()
    a = [d for d in r["shareholder_details"] if d["code"] == "A"][0]
    assert a["excluded_sales"] == pytest.approx(66_105_831_055 + 1_713_784_230, abs=1)


# 배당소득 공제까지 얹으면 계산내역의 납부세액과 원 단위까지 맞아야 한다.
DWBIO_2025_DIVIDEND = {"A": 815_251_400, "C": 1_354_031_200, "D": 630_662_000}
DWBIO_2025_DISTRIBUTABLE = 401_825_672_130
# 계산내역의 지배주주별 (배당소득 공제, 산출세액, 신고세액공제, 납부세액)
DWBIO_2025_FINAL = {
    "A": (8_141_967, 152_093_350, 4_562_800, 147_530_550),
    "C": (15_615_988, 382_382_817, 11_471_484, 370_911_330),
    "D": (6_610_693, 112_204_591, 3_366_137, 108_838_450),
}


def _dwbio_2025_full():
    return calc.evaluate_admin_review(
        "대웅바이오", 116_207_012_131, 20_999_171_475, 641_338_729_689,
        DWBIO_2025_SALES, year="2025", article10_exclusions=DWBIO_2025_ARTICLE10,
        dividend_income=DWBIO_2025_DIVIDEND,
        distributable_income=DWBIO_2025_DISTRIBUTABLE)


def test_dwbio_2025_full_chain_matches_the_worksheet():
    r = _dwbio_2025_full()
    got = {d["code"]: d for d in r["shareholder_details"]}
    for code, (deduction, tax, credit, payable) in DWBIO_2025_FINAL.items():
        d = got[code]
        assert d["dividend_deduction"] == pytest.approx(deduction, abs=1), code
        assert d["gift_tax"] == tax, code
        assert d["filing_credit"] == credit, code
        assert d["gift_tax_payable"] == payable, code
    assert r["gift_tax_payable_total"] == 627_280_330
