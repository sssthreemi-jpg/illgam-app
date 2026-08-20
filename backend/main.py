from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os

from backend.calc import evaluate, company_list, SIZES
from backend.models import LoginRequest, LoginResponse, EvaluateRequest
from backend.auth import get_current_user, User, authenticate_user, create_access_token

app = FastAPI(title="Illgam Tax Checker")

# CORS: in production set allowed origins via ENV; here allow localhost for dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost", "http://localhost:3000"],
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
    # Return only names + '기타'
    return {"companies": company_list()}


@app.get("/api/my-company")
def my_company(current: User = Depends(get_current_user)):
    size = SIZES.get(current.company, "알수없음")
    return {"company": current.company, "size": size}


@app.post("/api/evaluate")
def api_evaluate(req: EvaluateRequest, current: User = Depends(get_current_user)):
    if req.company != current.company and not current.is_admin:
        raise HTTPException(status_code=403, detail="권한 없음")
    res = evaluate(req.company, req.operating_income, req.corporate_tax,
                   req.total_sales, req.related_sales, req.indirect_invest)
    # calc.evaluate already returns only allowed aggregate fields
    return res


@app.get("/api/admin/summary")
def admin_summary(current: User = Depends(get_current_user)):
    if not current.is_admin:
        raise HTTPException(status_code=403, detail="관리자 권한 필요")
    out = []
    for c in SIZES.keys():
        # For admin summary we run evaluate with zeroed inputs (admin should supply real inputs in UI)
        r = evaluate(c, 0, 0, 0, {}, {})
        out.append({"company": c, "taxable": r["taxable"], "gift_tax_total": r["gift_tax_total"]})
    return {"summary": out}


# Serve frontend static files in development: mount after API routes so /api/* takes precedence
FRONTEND_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
if os.path.isdir(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
