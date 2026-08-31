# -*- coding: utf-8 -*-
"""연도별 지분 데이터(JSON)를 원본 지분율 엑셀에서 다시 만든다.

`backend/data/<연도>/` 는 기밀이라 git 에 없다. 이 스크립트가 있으면 엑셀만 있어도
`shareholder_holdings.json` 과 `intercompany_holdings.json` 두 개는 복구된다.

**나머지 세 파일은 이 스크립트로 복구되지 않는다.**
  - `company_sizes.json`  : 기업분류 엑셀이 연도별로 따로 있고, 손으로 고친 값이 섞여 있다.
                            여기서는 **법인 목록의 정본으로 읽기만** 한다.
  - `params.json`         : 세율·비율 등 직접 관리하는 값.
  - `section18_indirect_investors.json` : 세무 검토로 확정해 등재하는 값.
  이 세 개는 별도로 백업해 둘 것.

사용법 (기본은 미리보기, 실제로 덮어쓰려면 --write):

    python scripts/rebuild_year_data.py --year 2025 \
        --holdings "C:/.../25.12말 기준 일감 증여세 (지분율)_260713.xlsx"

    python scripts/rebuild_year_data.py --year 2025 --holdings "..." --write
"""

import argparse
import json
import os
import sys

try:
    import openpyxl
except ImportError:
    sys.exit("openpyxl 이 필요합니다:  pip install openpyxl")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SHEET_SUMMARY = "3.지배주주지분율 요약"
SHEET_DIRECT = "1.직접지분율"

# 지배주주 코드와 `3.지배주주지분율 요약` 시트의 '합계' 열(0-based).
# 시트는 코드마다 직접/간접/합계 3열이 반복된다: F=A합계, I=B합계, L=C합계 …
CODES = ["A", "B", "C", "D", "C1", "C11", "C12"]
SUM_COL = {"A": 5, "B": 8, "C": 11, "D": 14, "C1": 17, "C11": 20, "C12": 23}
NAME_COL = 1  # B열 법인명

# `1.직접지분율` 시트: A열 출자회사, B열 피출자회사, F열 지분율
OWNER_COL, TARGET_COL, RATIO_COL = 0, 1, 5

# 지분율 엑셀은 4개 시트 모두 `엠베이스`, 기업분류 엑셀과 앱 데이터는 `시지엠베이스`.
# 기업분류 쪽 이름이 정본이므로 그쪽으로 맞춘다.
ALIAS = {"엠베이스": "시지엠베이스"}

ROUND = 10  # 기존 JSON 과 같은 자릿수


def norm(v):
    if not isinstance(v, str):
        return None
    v = v.strip()
    return ALIAS.get(v, v) or None


def read_shareholders(ws, allowed):
    """{법인: {A..C12, sum}} — 코드별 '합계' 열을 그대로 읽는다."""
    out = {}
    for row in ws.iter_rows(min_row=4, values_only=True):
        name = norm(row[NAME_COL] if len(row) > NAME_COL else None)
        if not name or name not in allowed:
            continue
        vals = {}
        for code in CODES:
            col = SUM_COL[code]
            v = row[col] if len(row) > col else None
            if not isinstance(v, (int, float)):
                vals = None
                break
            vals[code] = float(v)
        if vals is None:
            continue
        rounded = {c: round(vals[c], ROUND) for c in CODES}
        # 합계는 반올림한 코드별 값을 더한다(원본 JSON 과 같은 순서로 계산해야 끝자리가 맞는다).
        rounded["sum"] = round(sum(rounded[c] for c in CODES), ROUND)
        out[name] = rounded
    return out


def read_intercompany(ws, order):
    """{출자법인: {피출자법인: 지분율}} — 개인 코드 행은 법인 목록 필터에서 걸러진다."""
    allowed = set(order)
    out = {c: {} for c in order}
    for row in ws.iter_rows(min_row=2, values_only=True):
        owner = norm(row[OWNER_COL] if len(row) > OWNER_COL else None)
        target = norm(row[TARGET_COL] if len(row) > TARGET_COL else None)
        ratio = row[RATIO_COL] if len(row) > RATIO_COL else None
        if not owner or not target or not isinstance(ratio, (int, float)):
            continue
        if owner not in allowed or target not in allowed:
            continue
        out[owner][target] = round(float(ratio), ROUND)
    return out


def dump(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
        print(file=f)  # 기존 파일처럼 끝에 개행 하나를 남긴다


def report(label, new, old):
    if old is None:
        print(f"  {label}: 기존 파일 없음 — 새로 만듭니다 ({len(new)}개 항목)")
        return
    if new == old:
        print(f"  {label}: 기존 파일과 동일 (변경 없음)")
        return
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    changed = [k for k in sorted(set(new) & set(old)) if new[k] != old[k]]
    print(f"  {label}: 추가 {len(added)} / 삭제 {len(removed)} / 변경 {len(changed)}")
    for k in added[:10]:
        print(f"      + {k}")
    for k in removed[:10]:
        print(f"      - {k}")
    for k in changed[:10]:
        print(f"      ~ {k}")
        print(f"          기존: {old[k]}")
        print(f"          신규: {new[k]}")


def main():
    p = argparse.ArgumentParser(description="지분율 엑셀에서 연도별 JSON 재생성")
    p.add_argument("--year", required=True, help="예: 2025")
    p.add_argument("--holdings", required=True, help="지분율 엑셀 경로")
    p.add_argument("--data-dir", default=None,
                   help="기본값: <repo>/backend/data/<연도>")
    p.add_argument("--write", action="store_true",
                   help="실제로 덮어쓴다. 없으면 미리보기만 한다.")
    args = p.parse_args()

    out_dir = args.data_dir or os.path.join(REPO, "backend", "data", args.year)
    sizes_path = os.path.join(out_dir, "company_sizes.json")
    if not os.path.exists(sizes_path):
        sys.exit(
            f"{sizes_path} 가 없습니다.\n"
            "company_sizes.json 은 법인 목록의 정본이라 먼저 있어야 합니다 "
            "(이 스크립트로는 만들 수 없습니다 — 백업에서 복원하세요)."
        )

    with open(sizes_path, encoding="utf-8") as f:
        sizes = json.load(f)
    # `기타법인` 은 calc.company_list() 가 자동으로 붙이므로 데이터에 없어야 정상이다.
    # 순서까지 정본을 따라가야 재생성 결과가 기존 파일과 바이트 단위로 같아진다.
    order = [c for c in sizes if c != "기타법인"]
    allowed = set(order)
    print(f"법인 목록 정본: {sizes_path} ({len(allowed)}개)")

    wb = openpyxl.load_workbook(args.holdings, data_only=True, read_only=True)
    for sheet in (SHEET_SUMMARY, SHEET_DIRECT):
        if sheet not in wb.sheetnames:
            sys.exit(f"엑셀에 `{sheet}` 시트가 없습니다: {wb.sheetnames}")

    shareholders = read_shareholders(wb[SHEET_SUMMARY], allowed)
    # 엑셀 행 순서가 아니라 정본 목록 순서로 맞춘다.
    shareholders = {c: shareholders[c] for c in order if c in shareholders}
    intercompany = read_intercompany(wb[SHEET_DIRECT], order)

    missing = sorted(allowed - set(shareholders))
    if missing:
        print(f"\n[경고] 기업분류에 있으나 지분율 엑셀에 없는 법인 {len(missing)}건: {missing}")

    print()
    targets = [
        ("shareholder_holdings.json", shareholders),
        ("intercompany_holdings.json", intercompany),
    ]
    for name, new in targets:
        path = os.path.join(out_dir, name)
        old = None
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                old = json.load(f)
        report(name, new, old)

    if not args.write:
        print("\n미리보기입니다. 실제로 쓰려면 --write 를 붙이세요.")
        return

    for name, new in targets:
        dump(os.path.join(out_dir, name), new)
    print(f"\n{out_dir} 에 2개 파일을 썼습니다.")
    print("params.json / section18_indirect_investors.json / company_sizes.json 은 건드리지 않았습니다.")


if __name__ == "__main__":
    main()
