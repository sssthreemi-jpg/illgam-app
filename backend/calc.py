"""일감몰아주기 증여세 계산 엔진 (엑셀 검증본과 동일 로직).
지분율 등 민감 데이터는 이 모듈 내부에서만 사용하며, 집계 결과만 반환한다.
"""
import json, math, os, re

DEFAULT_DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

# 적재 대상 파일. 전부 .gitignore 대상(기밀)이라 저장소에는 없으며,
# 배포 파이프라인이 주입하거나 테스트가 ILLGAM_DATA_DIR 로 fixture 를 가리킨다.
DATA_FILES = (
    "company_sizes.json",
    "shareholder_holdings.json",
    "intercompany_holdings.json",
    "params.json",
    "section18_indirect_investors.json",
)

# 특수관계법인 매출액이 이 금액을 **초과**하는 일반기업은 정상거래비율이 20% 로 내려간다.
# 문턱은 '이상'이 아니라 '초과'다 — 경영진 이슈보고(2026-07-08)와 `대웅바이오 현황정리v2`
# 모두 "1천억원 초과" 로 적는다. 상증법 §45의3①1호 나목도 같다.
# (2026-08-31 에 '이상'으로 바꿨다가 두 문서를 확인하고 되돌렸다.)
# 상증령 §34의3 ⑭2호 판정에 쓰는 지주회사 정보. 연도 폴더의 이 파일에서 읽으며,
# **없으면 ⑭2호를 적용하지 않는다**(보수적으로 종전 동작 유지).
#
# 여기 지분율은 지주회사의 **직·간접** 지분율이며 자기주식을 반영한 값이다.
# intercompany_holdings.json(직접지분율)을 체인으로 전개해도 이 값이 나오지 않는다 —
# 중간 법인의 자기주식 때문이다(2025 대웅제약 경유분은 계수 0.983956 만큼 차이가 났다).
# 그래서 도출하지 않고 지분율 엑셀/계산내역에서 받아 적는다.
HOLDING_COMPANY_FILE = "holding_company.json"

GENERAL_RELATED_SALES_THRESHOLD = 100_000_000_000
GENERAL_HIGH_RELATED_RATIO = 0.2

# 신고세액공제율 (상증법 §69②). 산출세액의 3% 를 빼고 납부한다.
FILING_CREDIT_RATE = 0.03

# 과세요건 ③ 의 한계보유비율. params.json 의 "한계보유비율" 이 정본이고, 이 값은
# 키가 없는 예전 스냅샷(배포 시크릿의 tar 등)을 위한 폴백이다. 법정 비율이라
# 연도별로 달라지는 값이 아니어서 폴백을 둬도 조용히 틀릴 여지가 없다.
#
# **공제보유비율(params.json "공제보유비율", 일반 0%·중견 5%·중소 10%) 과 다른 값이다.**
#   - 한계보유비율: 이 사람이 과세대상 주주인지 가르는 **문턱**
#   - 공제보유비율: 증여의제이익 계산식에서 보유비율에서 **빼는 값**
# 검토 실무자료의 '직·간접 주식보유비율' 표가 일반기업의 차감값을 0.00% 로 적는 것은
# 후자를 가리킨다. 이름이 비슷해 한동안 문턱이 통째로 빠져 있었다.
#
# 문턱은 지배주주등 **합계가 아니라 개인별**로 본다. 상증법 §45의3 ① 이 납세의무자를
# "한계보유비율을 초과하여 보유한 주주에 한정" 하기 때문이다. 검증본의 '직·간접
# 주식보유비율' 표가 이를 그대로 보여준다 — 대웅바이오(일반, 2025) 표에는 3% 를
# 넘는 A·C·D 만 있고 0.45%/0.75%/0.30% 인 C1·C11·C12 는 아예 등재되지 않는다.
# 합계로 보면 이 셋에도 세액이 붙어 검증본과 어긋난다.
DEFAULT_HOLDING_LIMIT = {"일반": 0.03, "중견": 0.1, "중소": 0.1}

# 개별 법인으로 잡히지 않는 나머지 거래처를 담는 catch-all 이름.
# 프론트엔드가 별도로 만들어 쓰지 않도록 company_list() 에 포함해 내려보낸다.
OTHER_COMPANY = "기타법인"


# 연도 폴더 이름. backend/data/2025/, backend/data/2026/ …
YEAR_DIR_RE = re.compile(r"^\d{4}$")
# 연도 폴더도 없고 기준시점에서 연도를 못 뽑았을 때 쓰는 이름표.
FALLBACK_YEAR = "기본"


def resolve_data_dir(path=None):
    """사용할 데이터 디렉터리. ILLGAM_DATA_DIR 환경변수로 덮어쓸 수 있다."""
    return path or os.environ.get("ILLGAM_DATA_DIR") or DEFAULT_DATA_DIR


def _has_all_files(base):
    return all(os.path.isfile(os.path.join(base, name)) for name in DATA_FILES)


def _year_dirs(base):
    """base 아래 연도 폴더 중 5개 파일이 모두 갖춰진 것만 {연도: 경로} 로."""
    if not os.path.isdir(base):
        return {}
    found = {}
    for name in sorted(os.listdir(base)):
        sub = os.path.join(base, name)
        if YEAR_DIR_RE.match(name) and os.path.isdir(sub) and _has_all_files(sub):
            found[name] = sub
    return found


def data_available(path=None):
    """연도 폴더 구조든, 예전 평면 구조든 하나라도 온전하면 참."""
    base = resolve_data_dir(path)
    return bool(_year_dirs(base)) or _has_all_files(base)


class Dataset:
    """한 연도치 데이터 묶음. 적재 후에는 바꾸지 않는다.

    연도별 계산은 **이 객체를 골라 쓰는 방식**이어야 한다. 요청마다 모듈 전역을
    갈아끼우는 방식은 쓰면 안 된다 — FastAPI 는 `def` 엔드포인트를 스레드풀에서
    돌리므로, 두 사람이 동시에 다른 연도로 계산하면 서로의 데이터를 밟는다.
    예외가 나지 않고 세액만 조용히 틀리는 유형이라 특히 위험하다.
    """

    def __init__(self, year, base):
        def _load(name):
            with open(os.path.join(base, name), encoding="utf-8") as f:
                return json.load(f)

        self.year = year
        self.base = base
        self.sizes = _load("company_sizes.json")          # {법인: 규모}
        self.hold = _load("shareholder_holdings.json")    # {법인: {A..C12, sum}}
        self.inter = _load("intercompany_holdings.json")  # {소유법인: {피소유법인: 지분}}
        self.params = _load("params.json")
        # 상증령 §34의3 ⑱ 간접출자법인. {수혜법인: [간접출자법인, ...]}
        # 밑줄로 시작하는 키는 파일 내 주석이므로 제외한다.
        self.section18 = {k: set(v)
                          for k, v in _load("section18_indirect_investors.json").items()
                          if not k.startswith("_")}

        # ⑭2호용 지주회사 정보. 파일이 없어도 계산은 되며, 그 경우 ⑭2호만 적용되지 않는다.
        hc = {}
        hc_path = os.path.join(base, HOLDING_COMPANY_FILE)
        if os.path.isfile(hc_path):
            with open(hc_path, encoding="utf-8") as f:
                hc = json.load(f)
        self.holding_company = hc.get("지주회사")
        self.holding_ratio = {k: float(v) for k, v in (hc.get("지분율") or {}).items()
                              if not k.startswith("_")}
        # 배당소득 공제(간접출자 배당 이중과세 조정)용.
        # 직접보유비율은 지주회사에 대한 **직접** 지분율이다(shareholder_holdings 의 합계와 다르다).
        self.holding_direct = {k: float(v)
                               for k, v in (hc.get("지배주주직접보유비율") or {}).items()
                               if not k.startswith("_")}
        self.holding_distributable = float(hc.get("배당가능이익") or 0)

        self.codes = [s["code"] for s in self.params["shareholders"]]  # A,B,C,D,C1,C11,C12
        self.normal = self.params["정상거래비율"]
        self.ded_r = self.params["공제거래비율"]
        self.ded_h = self.params["공제보유비율"]
        self.limit_h = self.params.get("한계보유비율", DEFAULT_HOLDING_LIMIT)
        self.brackets = self.params["누진세율"]           # [[과표하한, 세율, 누진공제], ...]
        self.exempt = self.params["면세점"]
        # "2026.06.30 지분 / 26년 상반기 매출(연환산)" 같은 자유 문구. 결과 리포트에 찍는다.
        self.as_of = self.params.get("기준시점", "")


DATASETS = {}        # {연도: Dataset}
DEFAULT_YEAR = None  # 연도를 지정하지 않았을 때 쓰는 연도(가장 최근)
DATA = DEFAULT_DATA_DIR
DATA_LOADED = False


def _flat_year_label(params):
    """평면 구조에는 연도 폴더가 없다. 기준시점 문자열에서 연도를 뽑아 이름표로 쓴다."""
    m = re.search(r"(19|20)\d{2}", str(params.get("기준시점", "")))
    return m.group(0) if m else FALLBACK_YEAR


def _bind_legacy_globals():
    """모듈 전역을 기본 연도 데이터로 맞춘다.

    **연도별 계산에 쓰면 안 된다** — 기본 연도 스냅샷일 뿐이다. 계산 경로는
    dataset(year) 로 받은 Dataset 만 본다. 이 전역들은 연도 개념이 없던 시절의
    호출부(main.py 의 법인 존재 확인, 테스트)를 위해 남겨둔 것이다.
    """
    global SIZES, HOLD, INTER, PARAMS, SECTION18
    global CODES, NORMAL, DED_R, DED_H, LIMIT_H, BRACKETS, EXEMPT
    if DEFAULT_YEAR is None:
        SIZES, HOLD, INTER, PARAMS, SECTION18 = {}, {}, {}, {}, {}
        CODES, NORMAL, DED_R, DED_H, LIMIT_H = [], {}, {}, {}, {}
        BRACKETS, EXEMPT = [], 0
        return
    ds = DATASETS[DEFAULT_YEAR]
    SIZES, HOLD, INTER = ds.sizes, ds.hold, ds.inter
    PARAMS, SECTION18 = ds.params, ds.section18
    CODES, NORMAL, DED_R, DED_H = ds.codes, ds.normal, ds.ded_r, ds.ded_h
    LIMIT_H = ds.limit_h
    BRACKETS, EXEMPT = ds.brackets, ds.exempt


def load_data(path=None):
    """데이터 세트를 (재)적재한다. 연도 폴더가 있으면 전부 메모리에 올린다.

    import 시점에 곧바로 파일을 읽지 않고 이 함수로 분리한 이유는 두 가지다.
    - 데이터가 없는 환경(CI 등)에서 import 자체가 FileNotFoundError 로 죽지 않게 한다.
    - 테스트가 ILLGAM_DATA_DIR 로 합성 fixture 를 끼워 넣고 다시 적재할 수 있게 한다.

    반환값: 적재 성공 여부(bool).
    """
    global DATA, DATA_LOADED, DATASETS, DEFAULT_YEAR

    base = resolve_data_dir(path)
    DATA = base

    datasets = {year: Dataset(year, sub) for year, sub in _year_dirs(base).items()}
    if not datasets and _has_all_files(base):
        # 하위호환: 연도 폴더 없이 파일만 있는 예전 배포도 그대로 돈다.
        ds = Dataset(FALLBACK_YEAR, base)
        ds.year = _flat_year_label(ds.params)
        datasets[ds.year] = ds

    DATASETS = datasets
    DEFAULT_YEAR = max(datasets) if datasets else None
    DATA_LOADED = bool(datasets)
    _bind_legacy_globals()
    return DATA_LOADED


load_data()


def available_years():
    """계산 가능한 연도 목록(최신순)."""
    return sorted(DATASETS, reverse=True)


def year_options():
    """화면 드롭다운용. 연도와 그 연도 데이터의 기준시점."""
    return [{"year": y, "as_of": DATASETS[y].as_of} for y in available_years()]


def dataset(year=None):
    """연도에 해당하는 Dataset. year 가 없으면 기본 연도.

    없는 연도를 받으면 조용히 기본 연도로 넘어가지 않고 실패한다 — 사용자가 2025 로
    계산했다고 믿는데 2026 데이터가 쓰이는 것이 최악이다.
    """
    if not DATASETS:
        raise ValueError("지분 데이터가 적재되지 않았습니다.")
    if year in (None, ""):
        return DATASETS[DEFAULT_YEAR]
    key = str(year)
    if key not in DATASETS:
        raise ValueError(
            f"{key}년 지분 데이터가 없습니다. 계산 가능한 연도: {', '.join(available_years())}")
    return DATASETS[key]


def company_list(year=None):
    """거래처 선택용 법인명 목록(+기타법인). 규모/지분 등 부가정보는 반환하지 않음."""
    companies = sorted(dataset(year).sizes.keys())
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
ARTICLE_14_2 = "상증령 §34의3 ⑭2호 (지주회사 지분율 상당액)"
ARTICLE_14_RATIO = "상증령 §34의3 ⑭ (지배주주 지분율 상당액)"
ARTICLE_NONE = "-"

REASON_10 = "수혜법인이 해당 거래처에 출자 (기본 과세제외)"
REASON_14_1 = "§18 간접출자법인과의 거래 (전액 제외)"
REASON_14_2 = "수혜법인·거래처가 모두 지주회사의 자·손자회사 (지주회사 지분율 상당액)"
REASON_14_RATIO = "지배주주의 해당 거래처 지분율 상당액"
REASON_NONE = "과세제외 사유 없음"


def is_section18_indirect_investor(company, counterparty, ds=None):
    """상증령 §34의3 ⑱ 간접출자법인 여부.

    data/section18_indirect_investors.json 에 등재된 관계만 인정한다.
    지분 경로가 연결돼 있다는 사실만으로는(단순 간접지분 관계) 간접출자법인으로 보지 않으며,
    그 경우 ⑭ 지배주주 지분율 상당액만 적용된다.

    사용자 입력을 받지 않는다. 이 판정이 서면 해당 거래처 매출이 전액 제외되어
    세액을 임의로 0 까지 낮출 수 있기 때문이다.
    """
    ds = ds or dataset()
    return counterparty in ds.section18.get(company, ())


def holding_company_ratio(company, counterparty, ds=None):
    """⑭2호에 쓰는 지주회사 지분율. 요건을 못 갖추면 0.

    ⑭2호는 **수혜법인과 특수관계법인이 모두 같은 지주회사의 자·손자회사**일 때만
    성립한다. 그래서 둘 다 지주회사 지분율 표에 있어야 하고, 거래처가 지주회사
    자신이면 적용하지 않는다(자기 자신에 대한 지분율이란 것이 없다).
    """
    ds = ds or dataset()
    if not ds.holding_company or counterparty == ds.holding_company:
        return 0.0
    if company not in ds.holding_ratio:
        return 0.0
    return ds.holding_ratio.get(counterparty, 0.0)


def exclusion_for(company, counterparty, sales, shareholder, ds=None, article10=0):
    """거래처 1건 × 지배주주 1인의 과세제외를 판정한다.

    두 단계다. **⑩ 을 먼저 빼고, 남은 금액에 ⑭ 를 적용한다.**
    종전에는 ⑩ 이 있으면 거기서 끝내고 ⑭ 를 보지 않았는데, 실무 계산내역
    (`대웅바이오_25.4Q_계산내역.xlsx`)은 ⑩ 을 뺀 잔액에 다시 ⑭ 를 적용한다.

    ⑭ 는 1~4호 중 **금액이 가장 큰 하나만** 적용한다(합산하지 않는다).
      - 1호: §18 간접출자법인과의 거래 → 전액. 단 ⑩ 이 있는 거래처에는 적용하지 않는다.
      - 2호: 수혜법인·거래처가 모두 지주회사의 자·손자회사 → (매출−⑩) × 지주회사 지분율
      - 3호: (매출−⑩) × 지배주주의 그 거래처 지분율
      - 4호: 간접출자법인의 다른 자법인 → 실무상 2호와 같은 율이라 2호에 흡수된다.
    2호·3호 모두 **지배주주가 그 거래처 지분을 조금이라도 가져야** 성립한다.

    article10 은 신고서에서 확정한 ⑩ 과세제외금액이다. 지분 데이터로 도출되는 값이
    아니라(수출목적 매출 등) 호출자가 넘겨준다. 수혜법인이 거래처에 출자한 관계면
    그 인자와 무관하게 전액이 ⑩ 이다.

    반환: {"reason", "article", "rate", "excluded_sales", "article10"}
    """
    ds = ds or dataset()
    sales = float(sales)
    # ⑩ 기본 과세제외 — 수혜법인이 해당 거래처에 출자한 경우. 전액 제외.
    if ds.inter.get(company, {}).get(counterparty, 0) > 0:
        return {"reason": REASON_10, "article": ARTICLE_10,
                "rate": 1.0, "excluded_sales": sales, "article10": sales}

    a10 = min(max(float(article10 or 0), 0.0), sales)
    base = sales - a10

    candidates = []
    if a10 == 0 and is_section18_indirect_investor(company, counterparty, ds):
        candidates.append((REASON_14_1, ARTICLE_14_1, 1.0, sales))
    mine = ds.hold.get(counterparty, {}).get(shareholder, 0)
    if mine > 0:
        hc = holding_company_ratio(company, counterparty, ds)
        if hc > 0:
            candidates.append((REASON_14_2, ARTICLE_14_2, hc, min(base, base * hc)))
        candidates.append((REASON_14_RATIO, ARTICLE_14_RATIO, mine, min(base, base * mine)))

    if not candidates:
        if a10 > 0:
            return {"reason": REASON_10, "article": ARTICLE_10,
                    "rate": a10 / sales if sales else 0.0,
                    "excluded_sales": a10, "article10": a10}
        return {"reason": REASON_NONE, "article": ARTICLE_NONE,
                "rate": 0.0, "excluded_sales": 0.0, "article10": 0.0}

    reason, article, rate, amount = max(candidates, key=lambda c: c[3])
    return {"reason": reason, "article": article, "rate": rate,
            "excluded_sales": a10 + amount, "article10": a10}


def _ratio_exclusion_totals(details, ds):
    """⑭ 지분율 상당액이 적용된 건들만 모은 지배주주별 과세제외 합계.

    **관리자 응답에만 싣는다.** 한때 "여러 거래처가 섞인 합계는 개별 지분율로 분해되지 않는다"는
    이유로 일반 응답에도 범위(min/max)를 실었지만, 합계의 구성을 정하는 쪽이 클라이언트다:
      - 거래처를 1건만 넣어 호출하면 (합계 ÷ 그 거래처 매출) 이 곧 지분율이다.
      - 여러 건을 넣어도 {A,B} 호출과 {A} 호출의 차분으로 B 의 몫이 정확히 복원된다.
    거래처 건수 임계값이나 버킷화로는 이 차분 공격을 막지 못하므로 아예 내보내지 않는다.
    """
    totals = {code: 0.0 for code in ds.codes}
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


def _exclusions(company, related_sales, ds, article10=None):
    """거래처 전체를 훑어 (특관매출 합계, 주주별 과세제외 합계, 거래처별 내역, ⑩ 합계)를 만든다.

    ⑩ 합계를 따로 돌려주는 이유는 **과세요건 판정에 쓰는 비율이 ⑩ 만 반영한 비율**이기 때문이다
    (⑭ 는 증여의제이익 계산에만 반영한다). evaluate 가 그 값을 문턱과 비교한다.
    """
    article10 = article10 or {}
    teuk = 0.0
    article10_total = 0.0
    excluded_by_code = {k: 0.0 for k in ds.codes}
    details = []
    for counterparty, sales in related_sales.items():
        sales = sales or 0
        if sales == 0:
            continue
        teuk += sales
        by_shareholder = []
        for code in ds.codes:
            verdict = exclusion_for(company, counterparty, sales, code, ds,
                                    article10=article10.get(counterparty, 0))
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
        # ⑩ 은 지배주주와 무관하게 같은 금액이라 대표값 하나면 된다.
        article10_total += by_shareholder[0]["article10"]
    return teuk, excluded_by_code, details, article10_total


def _gift_tax(base, ds=None):
    """산출세액(신고세액공제 전). **원 단위 절사**다.

    종전에는 여기서 10원 미만을 절사했는데, 실무 계산내역은 산출세액을 원 단위로 두고
    신고세액공제를 뺀 **납부세액에서** 10원 미만을 절사한다. 먼저 10원으로 깎으면
    공제액이 달라져 납부세액이 10원씩 어긋난다.
    """
    ds = ds or dataset()
    if base < ds.exempt:
        return 0
    rate, deduct = ds.brackets[0][1], ds.brackets[0][2]
    for low, r, d in ds.brackets:
        if base >= low:
            rate, deduct = r, d
    return int(math.floor(base * rate - deduct))


def _filing_credit(tax):
    """신고세액공제 (상증법 §69②). 산출세액의 3%, 원 단위 절사."""
    return int(math.floor(tax * FILING_CREDIT_RATE))


def _payable(tax, credit):
    """납부할 증여세. 10원 미만 절사는 여기서 한 번만 한다."""
    return int(math.floor(max(tax - credit, 0) / 10) * 10)


def _dividend_deduction(company, code, deemed, distributable_income, dividend_income, ds):
    """간접출자 배당 이중과세 조정액 (증여의제이익에서 뺀다).

        공제액 = 배당소득 × 증여의제이익 ÷ ((수혜법인 배당가능이익 × 간접출자법인의
                 수혜법인 지분율 + 간접출자법인 배당가능이익) × 지배주주의 간접출자법인 직접보유비율)

    지배주주가 간접출자법인(지주회사)에서 이미 배당으로 과세된 몫을 덜어내는 계산이다.
    입력(배당소득·수혜법인 배당가능이익)이 없거나 지주회사 데이터가 없으면 0 이다.
    """
    dividend = float((dividend_income or {}).get(code, 0) or 0)
    if dividend <= 0 or deemed <= 0:
        return 0.0
    if ds.holding_distributable <= 0:
        # 지주회사 배당가능이익이 없으면 계산하지 않는다. 0 으로 두고 계산하면 분모가
        # 작아져 공제가 과대계상되고, 그만큼 세액이 조용히 줄어든다.
        return 0.0
    company_ratio = ds.holding_ratio.get(company, 0.0)
    direct = ds.holding_direct.get(code, 0.0)
    denom = ((float(distributable_income or 0) * company_ratio)
             + ds.holding_distributable) * direct
    if denom <= 0:
        return 0.0
    return dividend * deemed / denom


def _after_tax_base(operating_income, corporate_tax, tax_adjustments):
    """세후영업이익 = 영업이익 ± 세무조정금액 - 법인세 상당액.

    세무조정 항목은 가산이면 양수, 차감이면 음수로 입력받아 그대로 합산한다.
    """
    return operating_income + sum((tax_adjustments or {}).values()) - corporate_tax


def evaluate(company, operating_income, corporate_tax, total_sales,
             related_sales=None, tax_adjustments=None, year=None,
             article10_exclusions=None, dividend_income=None,
             distributable_income=0):
    """집계 결과만 반환 (지분율·지배주주별 내역 미반환).

    간접출자 여부는 인자로 받지 않는다. 서버가 §18 등재 데이터로 판정한다.
    year 를 주면 그 연도 지분·규모·세율로 계산한다. 없으면 기본(최신) 연도.
    """
    related_sales = related_sales or {}
    tax_adjustments = tax_adjustments or {}
    ds = dataset(year)
    if company not in ds.sizes:
        raise ValueError(f"{ds.year}년 데이터에 없는 법인입니다: {company}")
    size = ds.sizes[company]

    teuk, excluded_by_code, details, a10_total = _exclusions(
        company, related_sales, ds, article10_exclusions)

    after_tax_base = _after_tax_base(operating_income, corporate_tax, tax_adjustments)
    # 과세요건 판정에 쓰는 비율·금액은 ⑩ 만 반영한다(⑭ 는 계산에만 반영).
    taxable_sales = teuk - a10_total
    gate_ratio = (taxable_sales / total_sales) if total_sales else 0
    normal_ratio = _normal_ratio(size, taxable_sales, ds)
    over_threshold = gate_ratio > normal_ratio
    myhold = ds.hold.get(company, {})
    deemed_total = 0
    deduction_total = 0
    tax_total = 0
    credit_total = 0
    payable_total = 0
    for k in ds.codes:
        excl = excluded_by_code[k]
        ratio = 0 if (total_sales - excl) == 0 else (teuk - excl) / (total_sales - excl)
        after = 0 if total_sales == 0 else after_tax_base * (1 - excl / total_sales)
        deemed = _deemed_gift(size, after, ratio, myhold.get(k, 0), normal_ratio, ds,
                              gate_ratio=gate_ratio)
        deduction = _dividend_deduction(company, k, deemed, distributable_income,
                                        dividend_income, ds)
        base = max(deemed - deduction, 0)
        tax = _gift_tax(base, ds)
        credit = _filing_credit(tax)
        deemed_total += deemed
        deduction_total += deduction
        tax_total += tax
        credit_total += credit
        payable_total += _payable(tax, credit)

    return {
        "company": company,
        "size": size,
        # 어느 연도 데이터로 계산했는지 결과에 남긴다. 화면 리포트에도 찍는다.
        "year": ds.year,
        "data_as_of": ds.as_of,
        "taxable": tax_total > 0,
        "total_sales": total_sales,
        "related_sales_total": teuk,
        "related_sales_ratio": (teuk / total_sales) if total_sales else 0,
        # 과세요건 판정에 실제로 쓴 값들. 화면이 '왜 과세인지'를 설명하려면 이 비율이어야 한다.
        "article10_total": round(a10_total),
        "taxation_ratio": gate_ratio,
        "normal_ratio": normal_ratio,
        "deemed_gift_total": round(deemed_total),
        # 배당소득 공제(간접출자 배당 이중과세 조정)와 신고세액공제(3%).
        # gift_tax_total 은 종전대로 **산출세액**이고, 실제 납부액은 gift_tax_payable_total 이다.
        "dividend_deduction_total": round(deduction_total),
        "gift_tax_total": tax_total,
        "filing_credit_total": credit_total,
        "gift_tax_payable_total": payable_total,
        "reason": _reason(size, taxable_sales, total_sales, normal_ratio, tax_total,
                          over_threshold),
        # 거래처별 과세제외 사유·조문. 적용률·금액은 ⑩·§18(100%) 건만 채워지고
        # ⑭ 지분율 상당액 건은 None 이다. 합계도 내보내지 않는다(_ratio_exclusion_totals 주석 참조).
        "exclusion_details": [_public_detail(d) for d in details],
    }


def _normal_ratio(size, related_sales_total, ds=None):
    ds = ds or dataset()
    if size == "일반" and related_sales_total > GENERAL_RELATED_SALES_THRESHOLD:
        return GENERAL_HIGH_RELATED_RATIO
    return ds.normal[size]


def _deemed_gift(size, after, ratio, holding, normal_ratio, ds=None, gate_ratio=None):
    """지배주주 1인의 증여의제이익. 과세요건 문턱도 여기서 함께 본다.

    비율이 네 개라 이름만 보고 고르면 틀린다. 요건별로 쓰는 값이 다르다.
      - 정상거래비율(NORMAL, 일반 30%):   요건② 거래비율 **문턱**
      - 공제거래비율(DED_R, 일반 5%):     계산식에서 거래비율에서 **빼는 값**
      - 한계보유비율(LIMIT_H, 일반 3%):   요건③ 보유비율 **문턱**. 개인별로 본다.
      - 공제보유비율(DED_H, 일반 0%):     계산식에서 보유비율에서 **빼는 값**

    종전에는 계산식의 공제거래비율만 쓰고 문턱을 어디에서도 검사하지 않아,
    조정비율이 10.3% 인 일반법인도 (10.3% - 5%) > 0 이라는 이유로 세액이 생겼다.
    같은 함정을 보유비율 쪽에서 한 번 더 밟아, 요건③ 이 통째로 빠져 있었다.
    공제보유비율이 중소는 한계보유비율과 같은 10% 라 중소만 우연히 맞고,
    일반은 공제보유비율이 0% 라 0.3% 를 가진 주주에게도 세액이 붙었다.
    문턱은 둘 다 '초과'(>)여야 하며, 같으면 과세하지 않는다.

    **판정에 쓰는 비율과 계산에 쓰는 비율은 다르다.**
      - 판정(요건②): `gate_ratio` — ⑩ 만 뺀 법인 단위 비율. 지배주주마다 같다.
      - 계산: `ratio` — ⑩ 과 ⑭ 를 모두 뺀 지배주주별 조정비율.
    실무 계산내역이 그렇게 한다. 2025 대웅바이오는 판정비율 22.42%(> 20%)로 과세대상인데
    계산비율은 13.55% 다. 둘을 같게 두면(종전 동작) 이 법인이 통째로 비과세가 되어버린다.
    gate_ratio 를 주지 않으면 종전처럼 ratio 하나로 판정한다.

    evaluate 와 evaluate_admin_review 가 각자 계산하다 어긋나지 않도록 한 곳에 둔다.
    """
    ds = ds or dataset()
    if (ratio if gate_ratio is None else gate_ratio) <= normal_ratio:
        return 0.0
    if holding <= ds.limit_h[size]:
        return 0.0
    return (max(0, after)
            * max(0, ratio - ds.ded_r[size])
            * max(0, holding - ds.ded_h[size]))


def evaluate_admin_review(company, operating_income, corporate_tax, total_sales,
                          related_sales=None, tax_adjustments=None, year=None,
                          article10_exclusions=None, dividend_income=None,
                          distributable_income=0):
    """관리자 검토 화면 전용 집계. 주주별 적용률(=지분율)까지 노출한다.

    과세제외 계산은 evaluate 와 같은 _exclusions 를 쓴다(두 경로가 어긋나지 않도록).
    """
    ds = dataset(year)
    result = evaluate(company, operating_income, corporate_tax, total_sales,
                      related_sales, tax_adjustments, year=year,
                      article10_exclusions=article10_exclusions,
                      dividend_income=dividend_income,
                      distributable_income=distributable_income)
    related_sales = related_sales or {}
    after_tax_base = _after_tax_base(operating_income, corporate_tax, tax_adjustments)
    teuk, excluded_by_code, details, a10_total = _exclusions(
        company, related_sales, ds, article10_exclusions)
    size = result["size"]

    # ⑩ 기본 과세제외분은 지배주주와 무관하게 모두에게 동일하게 빠지는 '공통' 제외분이다.
    common_exclusion = sum(d["sales"] for d in details if d["article"] == ARTICLE_10)
    ratio_totals = _ratio_exclusion_totals(details, ds)

    exclusions = []
    adjusted_ratios = []
    shareholder_details = []
    for shareholder in ds.codes:
        excluded = excluded_by_code[shareholder]
        exclusions.append(excluded)
        denominator = total_sales - excluded
        adjusted_ratio = ((teuk - excluded) / denominator) if denominator else 0
        adjusted_ratios.append(adjusted_ratio)
        after = after_tax_base * (1 - excluded / total_sales) if total_sales else 0
        # evaluate 와 같은 헬퍼를 쓴다. 여기서 식을 따로 쓰면 두 화면의 숫자가 갈린다.
        deemed = _deemed_gift(size, after, adjusted_ratio,
                              ds.hold.get(company, {}).get(shareholder, 0),
                              result["normal_ratio"], ds,
                              gate_ratio=result["taxation_ratio"])
        deduction = _dividend_deduction(company, shareholder, deemed, distributable_income,
                                        dividend_income, ds)
        taxable_base = max(deemed - deduction, 0)
        tax = _gift_tax(taxable_base, ds)
        credit = _filing_credit(tax)
        shareholder_details.append({
            # 지배주주 실명은 내보내지 않는다. 화면은 코드(A/B/C/D/C1/C11/C12)로만
            # 표시하므로 응답에 실어봐야 개발자도구에 노출될 뿐이다.
            # params.json 의 이름은 서버 안에서만 쓴다.
            "code": shareholder,
            "holding_ratio": ds.hold.get(company, {}).get(shareholder, 0),
            "excluded_sales": round(excluded),
            "adjusted_related_ratio": adjusted_ratio,
            "after_tax_operating_income": after,
            "deemed_gift_income": deemed,
            "dividend_deduction": deduction,
            "taxable_base": taxable_base,
            "gift_tax": tax,
            "filing_credit": credit,
            "gift_tax_payable": _payable(tax, credit),
            "taxable": tax > 0,
        })

    result.update({
        # 주주별 적용률(=지분율)까지 담긴 전체 내역. 관리자 응답에만 싣는다.
        "exclusion_details": details,
        "ratio_exclusion_total_min": round(min(ratio_totals.values())) if ratio_totals else 0,
        "ratio_exclusion_total_max": round(max(ratio_totals.values())) if ratio_totals else 0,
        "excluded_sales_common": round(common_exclusion),
        "excluded_sales_min": round(min(exclusions) if exclusions else 0),
        "excluded_sales_max": round(max(exclusions) if exclusions else 0),
        "adjusted_related_ratio_min": min(adjusted_ratios) if adjusted_ratios else 0,
        "adjusted_related_ratio_max": max(adjusted_ratios) if adjusted_ratios else 0,
        "shareholder_details": shareholder_details,
    })
    return result

def _reason(size, teuk, total, normal, tax, over_threshold):
    """판정 사유. 실제 판정 결과를 그대로 옮긴다.

    종전에는 `세액 > 0` 만 보고 '정상거래비율을 초과하고' 라고 단정했다. 비율을
    실제로 비교하지 않은 문장이라, 비율이 문턱 아래인데도 그렇게 적혀 나갔다.
    """
    if total == 0:
        return "총매출액이 0이라 판정 불가 (총매출 입력 필요)."
    pct = int(round(normal * 100))
    if not over_threshold:
        return f"과세제외 후 특관거래비율이 정상거래비율({pct}%) 이하여서 해당없음입니다."
    if tax > 0:
        return f"특관거래비율이 정상거래비율({pct}%)을 초과하고 보유요건을 충족하여 과세대상입니다."
    return f"정상거래비율({pct}%)은 초과했으나 보유요건 미충족으로 해당없음입니다."
