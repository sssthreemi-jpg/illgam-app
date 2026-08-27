from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os

# SIZES 등 데이터 전역은 calc.load_data() 가 다시 바인딩하므로 이름을 직접 import 하지 않고
# 모듈을 통해 참조한다(테스트가 fixture 데이터로 갈아끼울 수 있어야 한다).
from backend import calc
from backend.calc import evaluate, evaluate_admin_review, company_list
from backend.models import LoginRequest, LoginResponse, EvaluateRequest
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


@app.get("/api/companies")
def get_companies(current: User = Depends(get_current_user)):
    # Return only names + '기타법인' (catch-all). No size/ownership data.
    return {"companies": company_list()}


@app.get("/api/my-company")
def my_company(current: User = Depends(get_current_user)):
    size = calc.SIZES.get(current.company, "알수없음")
    return {"company": current.company, "size": size}


@app.post("/api/evaluate")
def api_evaluate(req: EvaluateRequest, current: User = Depends(get_current_user)):
    if req.company != current.company and not current.is_admin:
        raise HTTPException(status_code=403, detail="권한 없음")
    if req.company not in calc.SIZES:
        raise HTTPException(status_code=400, detail="계산 가능한 법인을 선택하세요")
    # 간접출자 여부는 클라이언트가 정하지 않는다. 서버가 지분 데이터에서 도출한다
    # (플래그가 서면 해당 거래처 매출이 전액 제외되어 세액을 임의로 낮출 수 있다).
    res = evaluate(req.company, req.operating_income, req.corporate_tax,
                   req.total_sales, req.related_sales,
                   tax_adjustments=req.tax_adjustments)
    # calc.evaluate already returns only allowed aggregate fields
    return res


@app.post("/api/admin/evaluate-review")
def admin_evaluate_review(req: EvaluateRequest, current: User = Depends(get_current_user)):
    if not current.is_admin:
        raise HTTPException(status_code=403, detail="관리자 권한 필요")
    if req.company not in calc.SIZES:
        raise HTTPException(status_code=400, detail="계산 가능한 법인을 선택하세요")
    return evaluate_admin_review(req.company, req.operating_income, req.corporate_tax,
                                 req.total_sales, req.related_sales,
                                 tax_adjustments=req.tax_adjustments)


@app.get("/api/admin/summary")
def admin_summary(current: User = Depends(get_current_user)):
    if not current.is_admin:
        raise HTTPException(status_code=403, detail="관리자 권한 필요")
    out = []
    for c in calc.SIZES.keys():
        # For admin summary we run evaluate with zeroed inputs (admin should supply real inputs in UI)
        r = evaluate(c, 0, 0, 0, {})
        out.append({"company": c, "taxable": r["taxable"], "gift_tax_total": r["gift_tax_total"]})
    return {"summary": out}


# Serve frontend static files in development: mount after API routes so /api/* takes precedence
FRONTEND_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
if os.path.isdir(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
