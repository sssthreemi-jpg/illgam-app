from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
import os
import urllib.parse

# SIZES 등 데이터 전역은 calc.load_data() 가 다시 바인딩하므로 이름을 직접 import 하지 않고
# 모듈을 통해 참조한다(테스트가 fixture 데이터로 갈아끼울 수 있어야 한다).
from backend import bulk_import, calc, excel_import
from backend.calc import evaluate, evaluate_admin_review, company_list
from backend.models import (BlankSheetsRequest, BulkEvaluateRequest, LoginRequest,
                            LoginResponse, EvaluateRequest)
from backend.auth import get_current_user, User, authenticate_user, create_access_token


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 데이터가 없으면 모든 판정이 조용히 '해당없음'이 된다. 서빙 전에 죽는 편이 낫다.
    if not calc.DATA_LOADED:
        raise RuntimeError(
            f"지분 데이터를 찾을 수 없습니다: {calc.DATA}. "
            f"{', '.join(calc.DATA_FILES)} 를 배치하거나 ILLGAM_DATA_DIR 을 설정하세요."
        )
    yield


app = FastAPI(title="Illgam Tax Checker", lifespan=lifespan)

# CORS. backend/.env.example 과 docker-compose 의 env_file 이 ALLOWED_ORIGINS 를
# 약속하고 있었는데 실제로는 읽지 않아 값이 무시됐다. 이제 읽는다.
# 미설정 시에는 종전 동작(로컬 개발 오리진)을 그대로 유지한다.
#
# 참고: 사내 배포에서 프론트는 nginx 를 통해 같은 오리진의 `/api/...` 로 호출하므로
# CORS 가 관여하지 않는다. 이 설정은 8000 포트를 다른 오리진에서 직접 부르는 경우용이다.
_DEFAULT_ORIGINS = ["http://localhost", "http://localhost:3000"]
ALLOWED_ORIGINS = [
    o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()
] or _DEFAULT_ORIGINS

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/api/auth/login", response_model=LoginResponse)
def login(req: LoginRequest):
    user = authenticate_user(req.username, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="잘못된 자격증명")
    token = create_access_token(req.username, user.get("is_admin", False))
    return {"access_token": token, "token_type": "bearer"}


def _dataset_or_400(year):
    """연도에 해당하는 Dataset. 없는 연도면 400 으로 거절한다.

    조용히 기본 연도로 넘어가면 안 된다 — 사용자는 2025 로 계산했다고 믿는데
    2026 데이터가 쓰이는 상황이 최악이다.
    """
    try:
        return calc.dataset(year)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/years")
def get_years(current: User = Depends(get_current_user)):
    """계산 가능한 연도와 각 연도 데이터의 기준시점. 화면 드롭다운이 쓴다."""
    return {"years": calc.year_options(), "default": calc.DEFAULT_YEAR}


@app.get("/api/companies")
def get_companies(year: str = None, current: User = Depends(get_current_user)):
    # Return only names + '기타법인' (catch-all). No size/ownership data.
    # 법인 목록은 연도마다 다를 수 있다(신설·청산·계열 편입).
    ds = _dataset_or_400(year)
    return {"companies": company_list(ds.year), "year": ds.year}


XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@app.get("/api/related-sales/template")
def related_sales_template(year: str = None, current: User = Depends(get_current_user)):
    """거래처명이 채워진 빈 엑셀 양식. 사용자는 금액만 채워 다시 올린다."""
    ds = _dataset_or_400(year)
    content = excel_import.build_template(company_list(ds.year))
    # 한글 파일명은 Content-Disposition 에 그대로 못 넣는다. ASCII 이름을 주고
    # RFC 5987 형식으로 한글 이름을 덧붙인다(브라우저는 filename* 를 우선한다).
    korean = urllib.parse.quote("특수관계자_세부매출_양식.xlsx")
    return Response(
        content=content,
        media_type=XLSX_MEDIA_TYPE,
        headers={
            "Content-Disposition": (
                "attachment; filename=related_sales_template.xlsx; "
                f"filename*=UTF-8''{korean}"
            )
        },
    )


@app.post("/api/related-sales/import")
async def related_sales_import(
    file: UploadFile = File(...),
    year: str = None,
    current: User = Depends(get_current_user),
):
    """업로드한 엑셀/CSV 를 읽어 거래처별 금액을 돌려준다.

    **아무것도 저장하지 않고 계산도 하지 않는다.** 화면이 표를 채우는 데만 쓰는
    읽기 전용 변환이다. 맞추지 못한 거래처는 버리지 않고 그대로 돌려주며,
    어디에 넣을지는 사용자가 화면에서 정한다.
    """
    ds = _dataset_or_400(year)
    content = await file.read()
    try:
        return excel_import.import_related_sales(content, file.filename or "",
                                                 company_list(ds.year))
    except ValueError as e:
        # 파싱 실패는 사용자가 고칠 수 있는 문제다. 그대로 문구를 전달한다.
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/my-company")
def my_company(year: str = None, current: User = Depends(get_current_user)):
    # 기업 구분은 연도마다 달라질 수 있다(중소 → 중견 승격 등).
    ds = _dataset_or_400(year)
    size = ds.sizes.get(current.company, "알수없음")
    out = {"company": current.company, "size": size, "year": ds.year}
    if current.is_admin:
        # 배당소득 입력란을 그리려면 코드 목록이 필요하다. 실명은 내보내지 않는다.
        out["shareholder_codes"] = list(ds.codes)
    return out


@app.post("/api/evaluate")
def api_evaluate(req: EvaluateRequest, current: User = Depends(get_current_user)):
    if req.company != current.company and not current.is_admin:
        raise HTTPException(status_code=403, detail="권한 없음")
    ds = _dataset_or_400(req.year)
    if req.company not in ds.sizes:
        raise HTTPException(status_code=400,
                            detail=f"{ds.year}년 데이터에 없는 법인입니다. 법인 또는 연도를 확인하세요.")
    # 간접출자 여부는 클라이언트가 정하지 않는다. 서버가 지분 데이터에서 도출한다
    # (플래그가 서면 해당 거래처 매출이 전액 제외되어 세액을 임의로 낮출 수 있다).
    res = evaluate(req.company, req.operating_income, req.corporate_tax,
                   req.total_sales, req.related_sales,
                   tax_adjustments=req.tax_adjustments, year=ds.year,
                   article10_exclusions=req.article10_exclusions,
                   dividend_income=req.dividend_income,
                   distributable_income=req.distributable_income)
    # calc.evaluate already returns only allowed aggregate fields
    return res


@app.post("/api/admin/evaluate-review")
def admin_evaluate_review(req: EvaluateRequest, current: User = Depends(get_current_user)):
    if not current.is_admin:
        raise HTTPException(status_code=403, detail="관리자 권한 필요")
    ds = _dataset_or_400(req.year)
    if req.company not in ds.sizes:
        raise HTTPException(status_code=400,
                            detail=f"{ds.year}년 데이터에 없는 법인입니다. 법인 또는 연도를 확인하세요.")
    return evaluate_admin_review(req.company, req.operating_income, req.corporate_tax,
                                 req.total_sales, req.related_sales,
                                 tax_adjustments=req.tax_adjustments, year=ds.year,
                                 article10_exclusions=req.article10_exclusions,
                                 dividend_income=req.dividend_income,
                                 distributable_income=req.distributable_income)


@app.get("/api/admin/summary")
def admin_summary(year: str = None, current: User = Depends(get_current_user)):
    if not current.is_admin:
        raise HTTPException(status_code=403, detail="관리자 권한 필요")
    ds = _dataset_or_400(year)
    out = []
    for c in ds.sizes.keys():
        # For admin summary we run evaluate with zeroed inputs (admin should supply real inputs in UI)
        r = evaluate(c, 0, 0, 0, {}, year=ds.year)
        out.append({"company": c, "taxable": r["taxable"], "gift_tax_total": r["gift_tax_total"]})
    return {"summary": out, "year": ds.year}


# 통합본 일괄 판정 --------------------------------------------------------------
# 파싱과 계산을 일부러 두 단계로 나눴다. 파일에 법인세가 없고 총매출이 아직
# 임시값인 법인이 섞여 있어서, 사용자가 표를 확인·보정한 뒤에 계산해야 한다.
# 서버는 어느 단계에서도 아무것도 저장하지 않는다.

# 한 번에 판정할 수 있는 법인 수. 통합본은 계열 법인 수만큼이라 넉넉하다.
MAX_BULK_COMPANIES = 300


@app.post("/api/admin/bulk/parse")
async def bulk_parse(
    file: UploadFile = File(...),
    year: str = None,
    current: User = Depends(get_current_user),
):
    """통합본(법인=시트) 엑셀을 법인별 판정 입력으로 바꾼다. 계산도 저장도 하지 않는다."""
    if not current.is_admin:
        raise HTTPException(status_code=403, detail="관리자 권한 필요")
    ds = _dataset_or_400(year)
    content = await file.read()
    try:
        out = bulk_import.parse_workbook(content, file.filename or "",
                                         company_list(ds.year), ds.sizes)
    except ValueError as e:
        # 파싱 실패는 사용자가 고칠 수 있는 문제다. 그대로 문구를 전달한다.
        raise HTTPException(status_code=400, detail=str(e))
    out["year"] = ds.year
    out["data_as_of"] = ds.as_of
    return out


@app.post("/api/admin/bulk/evaluate")
def bulk_evaluate(req: BulkEvaluateRequest, current: User = Depends(get_current_user)):
    """법인별 입력을 한 번에 판정해 종합표를 돌려준다."""
    if not current.is_admin:
        raise HTTPException(status_code=403, detail="관리자 권한 필요")
    ds = _dataset_or_400(req.year)
    if len(req.companies) > MAX_BULK_COMPANIES:
        raise HTTPException(
            status_code=400,
            detail=f"한 번에 판정할 수 있는 법인은 {MAX_BULK_COMPANIES}개까지입니다.")

    results = []
    failed = []
    for item in req.companies:
        if item.company not in ds.sizes:
            # 한 법인이 틀렸다고 전체를 400 으로 되돌리지 않는다. 나머지는 계산해 주고
            # 어느 법인이 왜 빠졌는지 함께 알린다.
            failed.append({"company": item.company,
                           "detail": f"{ds.year}년 데이터에 없는 법인입니다."})
            continue
        try:
            results.append(evaluate(
                item.company, item.operating_income, item.corporate_tax,
                item.total_sales, item.related_sales,
                tax_adjustments=item.tax_adjustments, year=ds.year,
                article10_exclusions=item.article10_exclusions))
        except ValueError as e:
            failed.append({"company": item.company, "detail": str(e)})

    taxable = [r for r in results if r["taxable"]]
    return {
        "year": ds.year,
        "data_as_of": ds.as_of,
        "results": results,
        "failed": failed,
        "totals": {
            "evaluated": len(results),
            "taxable_count": len(taxable),
            "deemed_gift_total": sum(r["deemed_gift_total"] for r in results),
            "gift_tax_total": sum(r["gift_tax_total"] for r in results),
            "gift_tax_payable_total": sum(r["gift_tax_payable_total"] for r in results),
            "related_sales_total": sum(r["related_sales_total"] for r in results),
            "total_sales": sum(r["total_sales"] for r in results),
        },
    }


@app.post("/api/admin/bulk/blank-sheets")
def bulk_blank_sheets(req: BlankSheetsRequest, current: User = Depends(get_current_user)):
    """시트가 없는 법인들의 빈 시트를 담은 엑셀. 통합본에 그대로 복사해 넣을 수 있다."""
    if not current.is_admin:
        raise HTTPException(status_code=403, detail="관리자 권한 필요")
    ds = _dataset_or_400(req.year)
    unknown = [c for c in req.companies if c not in ds.sizes]
    if unknown:
        raise HTTPException(status_code=400,
                            detail=f"{ds.year}년 데이터에 없는 법인입니다: {', '.join(unknown[:5])}")
    if not req.companies:
        raise HTTPException(status_code=400, detail="법인을 하나 이상 지정하세요.")
    if len(req.companies) > MAX_BULK_COMPANIES:
        raise HTTPException(
            status_code=400,
            detail=f"한 번에 만들 수 있는 시트는 {MAX_BULK_COMPANIES}개까지입니다.")

    content = bulk_import.build_blank_sheets(req.companies, company_list(ds.year),
                                             ds.sizes, ds.as_of)
    korean = urllib.parse.quote(f"통합본_빈시트_{ds.year}.xlsx")
    return Response(
        content=content,
        media_type=XLSX_MEDIA_TYPE,
        headers={
            "Content-Disposition": (
                "attachment; filename=bulk_blank_sheets.xlsx; "
                f"filename*=UTF-8''{korean}"
            )
        },
    )


# Serve frontend static files in development: mount after API routes so /api/* takes precedence
FRONTEND_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
if os.path.isdir(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
