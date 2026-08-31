# -*- coding: utf-8 -*-
"""`scripts/rebuild_year_data.py` 의 요약 시트 검증 테스트.

이 검증이 있는 이유는 실제 사고 직전까지 갔기 때문이다. `26.06말 ..._260730.xlsx` 는
`3.지배주주지분율 요약` 시트만 낡은 채로 와서 시지 계열 법인의 합계가 0% 였다.
그대로 재생성했다면 시지바이오 지분이 80.5% → 0% 가 되어 증여세가 조용히 0 이 된다.
"""

import importlib.util
import os

import pytest
from openpyxl import Workbook

SCRIPT = os.path.join(os.path.dirname(__file__), "..", "..",
                      "scripts", "rebuild_year_data.py")


def _load():
    spec = importlib.util.spec_from_file_location("rebuild_year_data", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rebuild = _load()
CODES = rebuild.CODES


def holdings(**vals):
    """지배주주 코드별 지분율 dict. 안 준 코드는 0."""
    return {c: vals.get(c, 0.0) for c in CODES}


# --- 체인 계산 ---------------------------------------------------------------

def test_chain_expands_indirect_holdings():
    """A 가 지주 60%, 지주가 자회사 50% 를 가지면 A 의 자회사 지분은 30% 다."""
    edges = rebuild.direct_graph([("A", "지주", 0.6), ("지주", "자회사", 0.5)])
    hold = rebuild.chain_holdings(edges)
    assert hold["A"]["지주"] == pytest.approx(0.6)
    assert hold["A"]["자회사"] == pytest.approx(0.3)


def test_chain_adds_direct_and_indirect():
    """직접 보유분과 간접 보유분은 더한다."""
    edges = rebuild.direct_graph([("A", "지주", 0.6), ("지주", "자회사", 0.5),
                                  ("A", "자회사", 0.1)])
    hold = rebuild.chain_holdings(edges)
    assert hold["A"]["자회사"] == pytest.approx(0.4)


def test_chain_follows_a_new_holding_company():
    """지주회사가 새로 끼어도 지분율은 그대로 내려간다.

    2026 상반기에 에이하나가 시지바이오 위에, 하나누리가 엠서클 위에 새로 생겼다.
    이름만 바뀌었을 뿐 실질 지분은 유지된다는 것을 이 계산이 보여준다.
    """
    before = rebuild.chain_holdings(rebuild.direct_graph(
        [("C11", "시지바이오", 0.15), ("시지바이오", "클리슈어리서치", 1.0)]))
    after = rebuild.chain_holdings(rebuild.direct_graph(
        [("C11", "에이하나", 0.15), ("에이하나", "시지바이오", 1.0),
         ("시지바이오", "클리슈어리서치", 1.0)]))
    assert before["C11"]["클리슈어리서치"] == pytest.approx(after["C11"]["클리슈어리서치"])


def test_chain_terminates_on_circular_ownership():
    """순환출자가 있어도 멈춘다(값이 수렴한다)."""
    edges = rebuild.direct_graph([("A", "갑", 0.5), ("갑", "을", 0.5), ("을", "갑", 0.5)])
    hold = rebuild.chain_holdings(edges)
    assert hold["A"]["갑"] > 0.5
    assert hold["A"]["을"] < 1.0


# --- 요약 시트 대조 ------------------------------------------------------------

def test_summary_matching_direct_passes():
    summary = {"자회사": holdings(A=0.3)}
    hold = rebuild.chain_holdings(rebuild.direct_graph(
        [("A", "지주", 0.6), ("지주", "자회사", 0.5)]))
    assert rebuild.summary_vs_direct(summary, hold) == []
    assert rebuild.report_summary_check(summary, []) is False


def test_rounding_level_gap_is_not_a_mismatch():
    """0.1%p 이내 차이는 반올림·자기주식 처리 차이로 보고 넘어간다."""
    summary = {"자회사": holdings(A=0.3005)}
    hold = rebuild.chain_holdings(rebuild.direct_graph([("A", "자회사", 0.3)]))
    assert rebuild.summary_vs_direct(summary, hold) == []


def test_summary_zero_while_chain_nonzero_is_fatal():
    """요약만 0% 인 법인이 있으면 멈춰야 한다 — 260730 파일이 정확히 이랬다."""
    summary = {"시지바이오": holdings()}
    hold = rebuild.chain_holdings(rebuild.direct_graph([("C11", "시지바이오", 0.8)]))
    mismatches = rebuild.summary_vs_direct(summary, hold)
    assert [m[0] for m in mismatches] == ["시지바이오"]
    assert rebuild.report_summary_check(summary, mismatches) is True


def test_a_few_mismatches_only_warn():
    """소수의 불일치는 경고만 한다. 25.12말 파일이 43개 중 2개 어긋나지만 정상이다."""
    summary = {f"법인{i}": holdings(A=0.5) for i in range(20)}
    summary["법인0"] = holdings(A=0.4)
    hold = {c: {co: 0.5 for co in summary} for c in CODES}
    hold["A"] = {co: 0.5 for co in summary}
    for c in CODES:
        if c != "A":
            hold[c] = {co: 0.0 for co in summary}
    mismatches = rebuild.summary_vs_direct(summary, hold)
    assert len(mismatches) == 1
    assert rebuild.report_summary_check(summary, mismatches) is False


def test_many_mismatches_are_fatal():
    """1/4 넘게 어긋나면 시트 자체를 믿을 수 없다."""
    summary = {f"법인{i}": holdings(A=0.5) for i in range(20)}
    hold = {c: {} for c in CODES}
    hold["A"] = {f"법인{i}": (0.4 if i < 10 else 0.5) for i in range(20)}
    mismatches = rebuild.summary_vs_direct(summary, hold)
    assert len(mismatches) == 10
    assert rebuild.report_summary_check(summary, mismatches) is True


# --- 시트 열 매핑 --------------------------------------------------------------

def test_read_direct_reads_owner_target_ratio_columns():
    wb = Workbook()
    ws = wb.active
    ws.append(["출자", "피출자", None, None, None, "지분율"])
    ws.append(["블루넷", "에이하나", None, None, None, 0.5585644752])
    ws.append(["C11", "에이하나", None, None, None, 0.1499293403])
    ws.append(["엠베이스", "무엇", None, None, None, 0.5])       # 별칭 정규화
    ws.append(["빈칸", None, None, None, None, 0.5])             # 버려진다
    rows = rebuild.read_direct(ws)
    assert ("블루넷", "에이하나", 0.5585644752) in rows
    assert ("C11", "에이하나", 0.1499293403) in rows
    assert ("시지엠베이스", "무엇", 0.5) in rows, "엠베이스 → 시지엠베이스 로 맞춘다"
    assert len(rows) == 3


def test_read_intercompany_drops_rows_outside_the_company_list():
    """개인 코드 행과 목록 밖 법인은 법인간 지분 파일에 들어가지 않는다."""
    rows = [("블루넷", "에이하나", 0.5), ("C11", "에이하나", 0.15),
            ("블루넷", "목록밖", 0.3)]
    out = rebuild.read_intercompany(rows, ["블루넷", "에이하나"])
    assert out == {"블루넷": {"에이하나": 0.5}, "에이하나": {}}


def test_read_shareholders_reads_the_sum_columns():
    wb = Workbook()
    ws = wb.active
    for _ in range(3):
        ws.append([])
    row = [None] * 24
    row[rebuild.NAME_COL] = "대웅"
    for i, code in enumerate(CODES):
        row[rebuild.SUM_COL[code]] = 0.1 * (i + 1)
    ws.append(row)
    out = rebuild.read_shareholders(ws)
    assert out["대웅"]["A"] == pytest.approx(0.1)
    assert out["대웅"]["C12"] == pytest.approx(0.7)
    assert out["대웅"]["sum"] == pytest.approx(2.8)
    assert rebuild.read_shareholders(ws, allowed={"다른법인"}) == {}
