"""통합본(법인=시트) 파서와 일괄 판정 엔드포인트.

실제 통합본은 사람이 손으로 만든 파일이라 시트마다 표가 시작하는 열이 다르고,
아직 안 채워진 법인은 숫자 대신 '반기매출입력' 같은 안내 문구가 들어 있다.
여기서 검증하는 것은 그 지저분함을 **조용히 넘기지 않는지**다 —
못 읽은 법인을 0 으로 계산해 '해당없음'을 내는 것이 최악이다.
"""
import io

import pytest
from fastapi.testclient import TestClient

from backend import bulk_import
from backend.auth import ADMIN_USERNAME, ADMIN_PASSWORD
from backend.main import app

client = TestClient(app)

SUBJECT = "가나전자"
COUNTERPARTY = "자차산업"
OTHER = "마바물산"


def _sheet(ws, *, name, size, total, income, rows, start_col=4, tax=None):
    """실제 통합본과 같은 모양으로 한 시트를 그린다.

    `start_col` 로 표 시작 열을 옮길 수 있다 — 원본 파일이 시트마다 다르기 때문에
    열을 고정해 읽으면 절반이 빈 값으로 읽힌다.
    """
    c = start_col
    ws.cell(row=2, column=c, value="법인명")
    ws.cell(row=2, column=c + 3, value=name)
    ws.cell(row=4, column=c, value="기업구분")
    ws.cell(row=4, column=c + 3, value=size)
    ws.cell(row=6, column=c, value="총매출액")
    ws.cell(row=6, column=c + 3, value=total)
    ws.cell(row=8, column=c, value="영업이익")
    ws.cell(row=8, column=c + 3, value=income)
    if tax is not None:
        ws.cell(row=9, column=c, value="법인세 상당액")
        ws.cell(row=9, column=c + 3, value=tax)

    ws.cell(row=11, column=c, value="매출거래처")
    ws.cell(row=11, column=c + 1, value="매출액")
    ws.cell(row=11, column=c + 2, value="매출액 중 해외매출\n(L/C, 내국신용장 등)")
    ws.cell(row=11, column=c + 3, value="매출 합계 (1년 환산)")
    # 원본에 있는 설명 행. 거래처로 읽히면 안 된다.
    ws.cell(row=13, column=c + 1, value="발생한 실제매출")
    ws.cell(row=14, column=c + 1, value="A")
    ws.cell(row=14, column=c + 2, value="B")
    ws.cell(row=14, column=c + 3, value="(A-B)")

    r = 15
    for counterparty, actual, foreign, factor in rows:
        ws.cell(row=r, column=c - 2, value="CODE")
        ws.cell(row=r, column=c - 1, value="129-81-00178")
        ws.cell(row=r, column=c, value=counterparty)
        ws.cell(row=r, column=c + 1, value=actual)
        if foreign:
            ws.cell(row=r, column=c + 2, value=foreign)
        if isinstance(actual, (int, float)):
            ws.cell(row=r, column=c + 3, value=(actual - (foreign or 0)) * factor)
        r += 1
    # 표 아래 집계 행. 값이 비율(0.xx)이라 거래처로 읽으면 1원짜리 거래처가 생긴다.
    ws.cell(row=r + 1, column=c, value="특관매출 비율")
    ws.cell(row=r + 1, column=c + 1, value=0.9987)


def _workbook(build):
    from openpyxl import Workbook

    wb = Workbook()
    wb.remove(wb.active)
    build(wb)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _parse(content, fixture_data):
    calc = fixture_data
    return bulk_import.parse_workbook(content, "통합본.xlsx",
                                      calc.company_list(), calc.dataset().sizes)


def _by_sheet(parsed, title):
    return next(s for s in parsed["sheets"] if s["sheet"] == title)


# --- 파싱 ---------------------------------------------------------------------

def test_reads_sheets_with_different_column_offsets(fixture_data):
    """시트마다 표 시작 열이 달라도 같은 값을 읽어야 한다."""
    def build(wb):
        _sheet(wb.create_sheet("왼쪽"), name=SUBJECT, size="일반",
               total=10_000_000_000, income=1_000_000_000,
               rows=[(COUNTERPARTY, 500_000_000, 0, 1)], start_col=3)
        _sheet(wb.create_sheet("오른쪽"), name="다라화학", size="중견",
               total=10_000_000_000, income=1_000_000_000,
               rows=[(COUNTERPARTY, 500_000_000, 0, 1)], start_col=6)

    parsed = _parse(_workbook(build), fixture_data)
    left, right = _by_sheet(parsed, "왼쪽"), _by_sheet(parsed, "오른쪽")
    for s in (left, right):
        assert s["total_sales"] == 10_000_000_000
        assert s["operating_income"] == 1_000_000_000
        assert s["related_sales"] == {COUNTERPARTY: 500_000_000}
    assert left["company"] == SUBJECT
    assert right["company"] == "다라화학"


def test_annualizes_half_year_detail_rows(fixture_data):
    """상세표의 실매출만 연환산 전 금액이다. 계수를 역산해 맞춘다.

    총매출·영업이익은 파일 안에서 이미 환산된 값이므로 건드리지 않는다.
    이걸 놓치면 분자만 반기, 분모는 연간이 되어 비율이 절반으로 나온다.
    """
    def build(wb):
        _sheet(wb.create_sheet("반기"), name=SUBJECT, size="일반",
               total=10_000_000_000, income=1_000_000_000,
               rows=[(COUNTERPARTY, 1_000_000_000, 0, 2),
                     (OTHER, 500_000_000, 100_000_000, 2)])

    s = _by_sheet(_parse(_workbook(build), fixture_data), "반기")
    assert s["annualize_factor"] == 2.0
    assert s["related_sales"][COUNTERPARTY] == 2_000_000_000
    assert s["related_sales"][OTHER] == 1_000_000_000
    # 해외매출도 같은 계수로 환산해 ⑩ 로 넘긴다.
    assert s["article10_exclusions"][OTHER] == 200_000_000
    # 환산합계 열 = (실매출 − 해외) × 계수 이므로 특관 − ⑩ 이 그 합과 같아야 한다.
    assert s["related_total"] - s["article10_total"] == 2_000_000_000 + 800_000_000
    # 총매출은 파일 값 그대로다(이미 환산돼 있다).
    assert s["total_sales"] == 10_000_000_000


def test_placeholder_text_is_pending_not_zero(fixture_data):
    """'반기매출입력' 같은 안내 문구를 0 으로 읽어 '해당없음'을 내면 안 된다."""
    def build(wb):
        _sheet(wb.create_sheet("미입력"), name=SUBJECT, size="일반",
               total="반기매출입력", income="반기영업이익 입력",
               rows=[(COUNTERPARTY, 500_000_000, 0, 2)])

    s = _by_sheet(_parse(_workbook(build), fixture_data), "미입력")
    assert s["status"] == "입력대기"
    assert s["total_sales"] is None and s["operating_income"] is None
    assert any("반기매출입력" in w for w in s["warnings"])


def test_related_sales_over_total_sales_flagged(fixture_data):
    """총매출이 아직 임시값이면 비율이 터무니없어진다. 조용히 계산하지 않는다."""
    def build(wb):
        _sheet(wb.create_sheet("임시값"), name=SUBJECT, size="일반",
               total=2, income=2,
               rows=[(COUNTERPARTY, 500_000_000, 0, 2)])

    s = _by_sheet(_parse(_workbook(build), fixture_data), "임시값")
    assert s["status"] == "확인필요"
    assert any("총매출" in w for w in s["warnings"])


def test_zero_total_sales_is_pending(fixture_data):
    def build(wb):
        _sheet(wb.create_sheet("영"), name=SUBJECT, size="일반", total=0, income=0, rows=[])

    s = _by_sheet(_parse(_workbook(build), fixture_data), "영")
    assert s["status"] == "입력대기"


def test_size_mismatch_warns_and_keeps_server_value(fixture_data):
    """규모가 바뀌면 정상거래비율이 통째로 달라진다. 엑셀 표기를 따라가면 안 된다."""
    def build(wb):
        _sheet(wb.create_sheet("규모"), name=SUBJECT, size="대기업",
               total=10_000_000_000, income=1_000_000_000,
               rows=[(COUNTERPARTY, 500_000_000, 0, 1)])

    s = _by_sheet(_parse(_workbook(build), fixture_data), "규모")
    assert s["size_mismatch"] is True
    assert s["size_excel"] == "대기업"
    assert s["size_app"] == "일반"          # 서버 값이 정본
    assert any("기업구분" in w for w in s["warnings"])


def test_size_suffix_variants_are_not_mismatch(fixture_data):
    """'일반' 과 '일반기업' 은 같은 뜻이다. 매번 경고를 띄우면 진짜 불일치가 묻힌다."""
    def build(wb):
        _sheet(wb.create_sheet("표기"), name=SUBJECT, size="일반기업",
               total=10_000_000_000, income=1_000_000_000, rows=[])

    assert _by_sheet(_parse(_workbook(build), fixture_data), "표기")["size_mismatch"] is False


def test_sheet_name_abbreviation_resolved_by_company_cell(fixture_data):
    """시트명은 '생명과학' 처럼 줄임말이 흔하다. 법인명 셀이 정본이다."""
    def build(wb):
        _sheet(wb.create_sheet("가나"), name=SUBJECT, size="일반",
               total=10_000_000_000, income=1_000_000_000, rows=[])

    s = _by_sheet(_parse(_workbook(build), fixture_data), "가나")
    assert s["company"] == SUBJECT
    assert s["status"] == "ok"


def test_summary_row_is_not_read_as_counterparty(fixture_data):
    """표 아래 '특관매출 비율' 행의 0.9987 이 1원짜리 거래처가 되면 안 된다."""
    def build(wb):
        _sheet(wb.create_sheet("집계"), name=SUBJECT, size="일반",
               total=10_000_000_000, income=1_000_000_000,
               rows=[(COUNTERPARTY, 500_000_000, 0, 1)])

    s = _by_sheet(_parse(_workbook(build), fixture_data), "집계")
    assert list(s["related_sales"]) == [COUNTERPARTY]
    assert s["unmatched"] == []


def test_unknown_counterparty_is_reported_not_dropped(fixture_data):
    def build(wb):
        _sheet(wb.create_sheet("낯선"), name=SUBJECT, size="일반",
               total=10_000_000_000, income=1_000_000_000,
               rows=[("없는거래처", 300_000_000, 0, 1)])

    s = _by_sheet(_parse(_workbook(build), fixture_data), "낯선")
    assert [u["name"] for u in s["unmatched"]] == ["없는거래처"]
    assert s["related_sales"] == {}


def test_corporate_tax_read_when_present_else_warned(fixture_data):
    """지금 통합본에는 법인세가 없다. 나중에 양식에 생기면 자동으로 읽혀야 한다."""
    def build(wb):
        _sheet(wb.create_sheet("있음"), name=SUBJECT, size="일반",
               total=10_000_000_000, income=1_000_000_000, rows=[], tax=200_000_000)
        _sheet(wb.create_sheet("없음"), name="다라화학", size="중견",
               total=10_000_000_000, income=1_000_000_000, rows=[])

    parsed = _parse(_workbook(build), fixture_data)
    assert _by_sheet(parsed, "있음")["corporate_tax"] == 200_000_000
    absent = _by_sheet(parsed, "없음")
    assert absent["corporate_tax"] is None
    assert any("법인세" in w for w in absent["warnings"])


def test_missing_companies_listed(fixture_data):
    """시트가 아예 없는 법인은 '미제출'로 드러나야 한다. 빠진 줄 모르는 것이 문제다."""
    def build(wb):
        _sheet(wb.create_sheet("하나"), name=SUBJECT, size="일반",
               total=10_000_000_000, income=1_000_000_000, rows=[])

    parsed = _parse(_workbook(build), fixture_data)
    assert SUBJECT not in parsed["missing_companies"]
    assert "다라화학" in parsed["missing_companies"]
    assert parsed["stats"]["missing"] == len(parsed["missing_companies"])
    # 기타법인은 거래처일 뿐 판정 대상이 아니다.
    assert fixture_data.OTHER_COMPANY not in parsed["missing_companies"]


def test_rejects_non_excel(fixture_data):
    with pytest.raises(ValueError):
        _parse(b"not an excel file", fixture_data)


# --- 엔드포인트 ---------------------------------------------------------------

def _admin():
    r = client.post("/api/auth/login",
                    json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_bulk_parse_requires_admin(fixture_data):
    files = {"file": ("x.xlsx", b"PK", "application/vnd.ms-excel")}
    assert client.post("/api/admin/bulk/parse", files=files).status_code == 401


def test_bulk_evaluate_requires_admin(fixture_data):
    body = {"companies": [{"company": SUBJECT, "operating_income": 0, "total_sales": 0}]}
    assert client.post("/api/admin/bulk/evaluate", json=body).status_code == 401


def test_bulk_evaluate_totals_match_per_company(fixture_data):
    body = {"companies": [
        {"company": SUBJECT, "operating_income": 10_000_000_000, "corporate_tax": 0,
         "total_sales": 10_000_000_000, "related_sales": {COUNTERPARTY: 5_000_000_000}},
        {"company": "다라화학", "operating_income": 1_000_000_000, "corporate_tax": 0,
         "total_sales": 10_000_000_000, "related_sales": {COUNTERPARTY: 100_000_000}},
    ]}
    r = client.post("/api/admin/bulk/evaluate", json=body, headers=_admin())
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["failed"] == []
    assert data["totals"]["evaluated"] == 2
    assert data["totals"]["gift_tax_total"] == sum(x["gift_tax_total"] for x in data["results"])
    assert data["totals"]["taxable_count"] == sum(1 for x in data["results"] if x["taxable"])


def test_bulk_evaluate_reports_bad_company_without_failing_the_rest(fixture_data):
    """한 법인이 틀렸다고 나머지 판정까지 버리면 15개짜리 통합본을 못 쓴다."""
    body = {"companies": [
        {"company": "없는법인", "operating_income": 0, "total_sales": 1},
        {"company": SUBJECT, "operating_income": 10_000_000_000, "corporate_tax": 0,
         "total_sales": 10_000_000_000, "related_sales": {COUNTERPARTY: 5_000_000_000}},
    ]}
    data = client.post("/api/admin/bulk/evaluate", json=body, headers=_admin()).json()
    assert [f["company"] for f in data["failed"]] == ["없는법인"]
    assert [x["company"] for x in data["results"]] == [SUBJECT]


def test_bulk_evaluate_rejects_unknown_year(fixture_data):
    body = {"year": "1999",
            "companies": [{"company": SUBJECT, "operating_income": 0, "total_sales": 0}]}
    assert client.post("/api/admin/bulk/evaluate", json=body,
                       headers=_admin()).status_code == 400
