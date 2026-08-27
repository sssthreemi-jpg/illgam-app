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

# 상증령 §34의3 ⑱ 간접출자법인. {수혜법인: [간접출자법인, ...]}
# 밑줄로 시작하는 키는 파일 내 주석이므로 제외한다.
SECTION18 = {k: set(v) for k, v in _load("section18_indirect_investors.json").items()
             if not k.startswith("_")}

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

# --- 과세제외 판정 (상증령 §34의3) -------------------------------------------
# 적용 순서: ⑩ 기본 과세제외를 먼저 판정하고, 해당하지 않는 거래처만 ⑭ 추가 과세제외로 넘긴다.
ARTICLE_10 = "상증령 §34의3 ⑩"
ARTICLE_14_1 = "상증령 §34의3 ⑭1호 (§18 간접출자법인)"
ARTICLE_14_RATIO = "상증령 §34의3 ⑭ (지배주주 지분율 상당액)"
ARTICLE_NONE = "-"

REASON_10 = "수혜법인이 해당 거래처에 출자 (기본 과세제외)"
REASON_14_1 = "§18 간접출자법인과의 거래 (전액 제외)"
REASON_14_RATIO = "지배주주의 해당 거래처 지분율 상당액"
REASON_NONE = "과세제외 사유 없음"


def is_section18_indirect_investor(company, counterparty):
    """상증령 §34의3 ⑱ 간접출자법인 여부.

    data/section18_indirect_investors.json 에 등재된 관계만 인정한다.
    지분 경로가 연결돼 있다는 사실만으로는(단순 간접지분 관계) 간접출자법인으로 보지 않으며,
    그 경우 ⑭ 지배주주 지분율 상당액만 적용된다.

    사용자 입력을 받지 않는다. 이 판정이 서면 해당 거래처 매출이 전액 제외되어
    세액을 임의로 0 까지 낮출 수 있기 때문이다.
    """
    return counterparty in SECTION18.get(company, ())


def exclusion_for(company, counterparty, sales, shareholder):
    """거래처 1건 × 지배주주 1인의 과세제외를 판정한다.

    ⑩ 기본 과세제외가 성립하면 그것으로 끝내고 ⑭ 는 보지 않는다.
    ⑭ 안에서 사유가 겹치면 합산하지 않고 과세제외금액이 가장 큰 하나만 적용한다.

    반환: {"reason", "article", "rate", "excluded_sales"}
    """
    # ⑩ 기본 과세제외 — 수혜법인이 해당 거래처에 출자한 경우. 전액 제외.
    if INTER.get(company, {}).get(counterparty, 0) > 0:
        return {"reason": REASON_10, "article": ARTICLE_10,
                "rate": 1.0, "excluded_sales": float(sales)}

    # ⑭ 추가 과세제외 — 후보를 모두 세운 뒤 금액이 가장 큰 하나만 적용(합산하지 않는다).
    candidates = []
    if is_section18_indirect_investor(company, counterparty):
        candidates.append((REASON_14_1, ARTICLE_14_1, 1.0))
    ratio = HOLD.get(counterparty, {}).get(shareholder, 0)
    if ratio > 0:
        candidates.append((REASON_14_RATIO, ARTICLE_14_RATIO, ratio))
    if not candidates:
        return {"reason": REASON_NONE, "article": ARTICLE_NONE,
                "rate": 0.0, "excluded_sales": 0.0}
    reason, article, rate = max(candidates, key=lambda c: sales * c[2])
    return {"reason": reason, "article": article,
            "rate": rate, "excluded_sales": sales * rate}


def _ratio_exclusion_totals(details):
    """⑭ 지분율 상당액이 적용된 건들만 모은 지배주주별 과세제외 합계.

    거래처별 금액을 일반 사용자에게 주면 (금액 ÷ 매출액) 으로 지분율이 그대로 역산된다.
    여러 거래처가 섞인 합계는 개별 지분율로 분해되지 않으므로 이 값만 공개한다.
    """
    totals = {code: 0.0 for code in CODES}
    for d in details:
        if d["rate"] is not None:      # ⑩·§18 처럼 주주 무관하게 같은 율인 건은 대상 아님
            continue
        for entry in d["by_shareholder"]:
            totals[entry["code"]] += entry["excluded_sales"]
    return totals


def _public_detail(d):
    """일반 응답용 축약. ⑩·§18 은 적용률이 100% 라 지분율 정보가 없어 금액을 그대로 싣고,
    ⑭ 지분율 상당액은 거래처별 금액·범위를 모두 빼고 합계로만 제공한다."""
    return {k: d[k] for k in ("counterparty", "sales", "reason", "article",
                              "rate", "excluded_sales")}


def _exclusions(company, related_sales):
    """거래처 전체를 훑어 (특관매출 합계, 지배주주별 과세제외 합계, 거래처별 내역)을 만든다."""
    teuk = 0.0
    excluded_by_code = {k: 0.0 for k in CODES}
    details = []
    for counterparty, sales in related_sales.items():
        sales = sales or 0
        if sales == 0:
            continue
        teuk += sales
        by_shareholder = []
        for code in CODES:
            verdict = exclusion_for(company, counterparty, sales, code)
            excluded_by_code[code] += verdict["excluded_sales"]
            by_shareholder.append(dict(verdict, code=code))
        # ⑩ 과 §18 은 지배주주와 무관하게 같은 율이 적용되므로 대표값 하나로 요약된다.
        rates = [v["rate"] for v in by_shareholder]
        amounts = [v["excluded_sales"] for v in by_shareholder]
        uniform = len(set(rates)) == 1
        head = by_shareholder[0]
        details.append({
            "counterparty": counterparty,
            "sales": sales,
            "reason": head["reason"] if uniform else REASON_14_RATIO,
            "article": head["article"] if uniform else ARTICLE_14_RATIO,
            # 주주마다 율이 다른 경우(⑭ 지분율 상당액) 단일 적용률을 낼 수 없어 None 이 된다.
            "rate": head["rate"] if uniform else None,
            "excluded_sales": round(head["excluded_sales"]) if uniform else None,
            # 그 경우를 위한 범위값. 주주별 내역(by_shareholder)과 달리 '누가 몇 %인지'는
            # 드러나지 않으므로 일반 응답에도 싣는다.
            "rate_min": min(rates),
            "rate_max": max(rates),
            "excluded_sales_min": round(min(amounts)),
            "excluded_sales_max": round(max(amounts)),
            "by_shareholder": by_shareholder,
        })
    return teuk, excluded_by_code, details


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
             related_sales=None, tax_adjustments=None):
    """집계 결과만 반환 (지분율·지배주주별 내역 미반환).

    간접출자 여부는 인자로 받지 않는다. 서버가 §18 등재 데이터로 판정한다.
    """
    related_sales = related_sales or {}
    tax_adjustments = tax_adjustments or {}
    if company not in SIZES:
        raise ValueError("알 수 없는 법인")
    size = SIZES[company]

    teuk, excluded_by_code, details = _exclusions(company, related_sales)
    ratio_totals = _ratio_exclusion_totals(details)

    after_tax_base = _after_tax_base(operating_income, corporate_tax, tax_adjustments)
    normal_ratio = _normal_ratio(size, teuk)
    myhold = HOLD.get(company, {})
    deemed_total = 0
    tax_total = 0
    for k in CODES:
        excl = excluded_by_code[k]
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
        # 거래처별 과세제외 사유·조문. 적용률·금액은 ⑩·§18(100%) 건만 채워지고
        # ⑭ 지분율 상당액 건은 None 이며, 아래 합계 범위로 대신 제공한다.
        "exclusion_details": [_public_detail(d) for d in details],
        "ratio_exclusion_total_min": round(min(ratio_totals.values())),
        "ratio_exclusion_total_max": round(max(ratio_totals.values())),
    }


def _normal_ratio(size, related_sales_total):
    if size == "일반" and related_sales_total > GENERAL_RELATED_SALES_THRESHOLD:
        return GENERAL_HIGH_RELATED_RATIO
    return NORMAL[size]


def evaluate_admin_review(company, operating_income, corporate_tax, total_sales,
                          related_sales=None, tax_adjustments=None):
    """관리자 검토 화면 전용 집계. 주주별 적용률(=지분율)까지 노출한다.

    과세제외 계산은 evaluate 와 같은 _exclusions 를 쓴다(두 경로가 어긋나지 않도록).
    """
    result = evaluate(company, operating_income, corporate_tax, total_sales,
                      related_sales, tax_adjustments)
    related_sales = related_sales or {}
    after_tax_base = _after_tax_base(operating_income, corporate_tax, tax_adjustments)
    teuk, excluded_by_code, details = _exclusions(company, related_sales)
    size = result["size"]

    # ⑩ 기본 과세제외분은 지배주주와 무관하게 모두에게 동일하게 빠지는 '공통' 제외분이다.
    common_exclusion = sum(d["sales"] for d in details if d["article"] == ARTICLE_10)

    exclusions = []
    adjusted_ratios = []
    shareholder_details = []
    for shareholder in CODES:
        excluded = excluded_by_code[shareholder]
        exclusions.append(excluded)
        denominator = total_sales - excluded
        adjusted_ratio = ((teuk - excluded) / denominator) if denominator else 0
        adjusted_ratios.append(adjusted_ratio)
        after = after_tax_base * (1 - excluded / total_sales) if total_sales else 0
        deemed = max(0, after) * max(0, adjusted_ratio - DED_R[size]) * max(0, HOLD.get(company, {}).get(shareholder, 0) - DED_H[size])
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
        # 주주별 적용률(=지분율)까지 담긴 전체 내역. 관리자 응답에만 싣는다.
        "exclusion_details": details,
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
