"""일감몰아주기 증여세 계산 엔진 (엑셀 검증본과 동일 로직).
지분율 등 민감 데이터는 이 모듈 내부에서만 사용하며, 집계 결과만 반환한다.
"""
import json, math, os

DATA = os.path.join(os.path.dirname(__file__), "data")

def _load(name):
    with open(os.path.join(DATA, name), encoding="utf-8") as f:
        return json.load(f)

SIZES = _load("company_sizes.json")            # {법인: 규모}
HOLD  = _load("shareholder_holdings.json")     # {법인: {A..C12, sum}}
INTER = _load("intercompany_holdings.json")    # {소유법인: {피소유법인: 지분}}
PARAMS = _load("params.json")

CODES = [s["code"] for s in PARAMS["shareholders"]]   # A,B,C,D,C1,C11,C12
NORMAL = PARAMS["정상거래비율"]
DED_R  = PARAMS["공제거래비율"]
DED_H  = PARAMS["공제보유비율"]
BRACKETS = PARAMS["누진세율"]                  # [[과표하한, 세율, 누진공제], ...]
EXEMPT = PARAMS["면세점"]
GENERAL_RELATED_SALES_THRESHOLD = 100_000_000_000
GENERAL_HIGH_RELATED_RATIO = 0.2

# 개별 법인으로 잡히지 않는 나머지 거래처를 담는 catch-all 이름.
# 프론트엔드가 별도로 만들어 쓰지 않도록 company_list() 에 포함해 내려보낸다.
OTHER_COMPANY = "기타법인"


def company_list():
    """거래처 선택용 법인명 목록(+기타법인). 규모/지분 등 부가정보는 반환하지 않음."""
    companies = sorted(SIZES.keys())
    if "대웅" in companies:
        companies.remove("대웅")
        companies.insert(0, "대웅")
    if "HR그룹" in companies:
        companies.remove("HR그룹")
        companies.append("HR그룹")
    return companies + [OTHER_COMPANY]

def _gift_tax(base):
    if base < EXEMPT:
        return 0
    rate, deduct = BRACKETS[0][1], BRACKETS[0][2]
    for low, r, d in BRACKETS:
        if base >= low:
            rate, deduct = r, d
    tax = base * rate - deduct
    return int(math.floor(tax / 10) * 10)   # 10원 미만 절사

def _after_tax_base(operating_income, corporate_tax, tax_adjustments):
    """세후영업이익 = 영업이익 ± 세무조정금액 - 법인세 상당액.

    세무조정 항목은 가산이면 양수, 차감이면 음수로 입력받아 그대로 합산한다.
    """
    return operating_income + sum((tax_adjustments or {}).values()) - corporate_tax


def evaluate(company, operating_income, corporate_tax, total_sales,
             related_sales=None, indirect_invest=None, tax_adjustments=None):
    """집계 결과만 반환 (지분율·지배주주별 내역 미반환)."""
    related_sales = related_sales or {}
    indirect_invest = indirect_invest or {}
    tax_adjustments = tax_adjustments or {}
    if company not in SIZES:
        raise ValueError("알 수 없는 법인")
    size = SIZES[company]
    owned = INTER.get(company, {})            # 이 법인이 보유한 거래처(제10항 판정)

    teuk = 0.0        # 특관매출
    je10 = 0.0        # 제10항 합계
    f14 = {k: 0.0 for k in CODES}   # 지배주주별 ⑭ 합계
    for g, sales in related_sales.items():
        sales = sales or 0
        if sales == 0:
            continue
        teuk += sales
        s10 = sales if owned.get(g, 0) > 0 else 0
        je10 += s10
        F = sales - s10
        indirect = bool(indirect_invest.get(g, False))
        gh = HOLD.get(g, {})
        for k in CODES:
            f14[k] += max(F if indirect else 0, F * gh.get(k, 0))

    after_tax_base = _after_tax_base(operating_income, corporate_tax, tax_adjustments)
    normal_ratio = _normal_ratio(size, teuk)
    myhold = HOLD.get(company, {})
    deemed_total = 0
    tax_total = 0
    for k in CODES:
        excl = je10 + f14[k]
        ratio = 0 if (total_sales - excl) == 0 else (teuk - excl) / (total_sales - excl)
        after = 0 if total_sales == 0 else after_tax_base * (1 - excl / total_sales)
        deemed = max(0, after) * max(0, ratio - DED_R[size]) * max(0, myhold.get(k, 0) - DED_H[size])
        deemed_total += deemed
        tax_total += _gift_tax(deemed)

    return {
        "company": company,
        "size": size,
        "taxable": tax_total > 0,
        "total_sales": total_sales,
        "related_sales_total": teuk,
        "related_sales_ratio": (teuk / total_sales) if total_sales else 0,
        "normal_ratio": normal_ratio,
        "deemed_gift_total": round(deemed_total),
        "gift_tax_total": tax_total,
        "reason": _reason(size, teuk, total_sales, normal_ratio, tax_total),
    }


def _normal_ratio(size, related_sales_total):
    if size == "일반" and related_sales_total > GENERAL_RELATED_SALES_THRESHOLD:
        return GENERAL_HIGH_RELATED_RATIO
    return NORMAL[size]


def evaluate_admin_review(company, operating_income, corporate_tax, total_sales,
                          related_sales=None, indirect_invest=None, tax_adjustments=None):
    """Return aggregate exclusion metrics for the admin review screen only."""
    result = evaluate(company, operating_income, corporate_tax, total_sales,
                      related_sales, indirect_invest, tax_adjustments)
    related_sales = related_sales or {}
    indirect_invest = indirect_invest or {}
    after_tax_base = _after_tax_base(operating_income, corporate_tax, tax_adjustments)
    owned = INTER.get(company, {})
    # 제10항 제외분은 지배주주와 무관하게 모두에게 동일하게 빠지는 '공통' 제외분이다.
    common_exclusion = sum((sales or 0) for name, sales in related_sales.items()
                           if owned.get(name, 0) > 0)
    exclusions = []
    adjusted_ratios = []
    shareholder_details = []
    for shareholder in CODES:
        excluded = 0.0
        for name, sales in related_sales.items():
            sales = sales or 0
            section10 = sales if owned.get(name, 0) > 0 else 0
            F = sales - section10
            holdings = HOLD.get(name, {})
            excluded += section10 + max(F if indirect_invest.get(name, False) else 0,
                                         F * holdings.get(shareholder, 0))
        exclusions.append(excluded)
        denominator = total_sales - excluded
        adjusted_ratio = ((result["related_sales_total"] - excluded) / denominator
                          if denominator else 0)
        adjusted_ratios.append(adjusted_ratio)
        after = after_tax_base * (1 - excluded / total_sales) if total_sales else 0
        deemed = max(0, after) * max(0, adjusted_ratio - DED_R[result["size"]]) * max(0, HOLD.get(company, {}).get(shareholder, 0) - DED_H[result["size"]])
        shareholder_details.append({
            "code": shareholder,
            "name": next((item["name"] for item in PARAMS["shareholders"] if item["code"] == shareholder), shareholder),
            "holding_ratio": HOLD.get(company, {}).get(shareholder, 0),
            "excluded_sales": round(excluded),
            "adjusted_related_ratio": adjusted_ratio,
            "after_tax_operating_income": after,
            "deemed_gift_income": deemed,
            "gift_tax": _gift_tax(deemed),
            "taxable": _gift_tax(deemed) > 0,
        })

    result.update({
        "excluded_sales_common": round(common_exclusion),
        "excluded_sales_min": round(min(exclusions) if exclusions else 0),
        "excluded_sales_max": round(max(exclusions) if exclusions else 0),
        "adjusted_related_ratio_min": min(adjusted_ratios) if adjusted_ratios else 0,
        "adjusted_related_ratio_max": max(adjusted_ratios) if adjusted_ratios else 0,
        "shareholder_details": shareholder_details,
    })
    return result

def _reason(size, teuk, total, normal, tax):
    if total == 0:
        return "총매출액이 0이라 판정 불가 (총매출 입력 필요)."
    if tax > 0:
        return f"특관거래비율이 정상거래비율({int(normal*100)}%)을 초과하고 보유요건을 충족하여 과세대상입니다."
    return f"정상거래비율({int(normal*100)}%) 미달 또는 보유요건 미충족으로 해당없음입니다."
