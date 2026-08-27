"""관리자 검토 API(`/api/admin/evaluate-review`)의 권한과 집계 정합성 테스트.

evaluate_admin_review 는 evaluate 와 별도의 경로로 제외분을 다시 계산하므로,
두 경로의 총액이 어긋나지 않는지 회귀로 고정한다.
"""
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.auth import ADMIN_USERNAME, ADMIN_PASSWORD
from backend.calc import evaluate, evaluate_admin_review

# 실제 법인명("이지메디컴")과 소유구조에 의존한다.
# 권한 거부(401/403)와 관리자 전용 필드 노출은 test_calc_synthetic.py 에서도 검증한다.
pytestmark = pytest.mark.realdata

client = TestClient(app)

ARGS = ("이지메디컴", 10_000_000_000, 0, 10_000_000_000, {"대웅제약": 9_000_000_000})

BODY = {
    "company": ARGS[0],
    "operating_income": ARGS[1],
    "corporate_tax": ARGS[2],
    "total_sales": ARGS[3],
    "related_sales": ARGS[4],
}


def _token(username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_admin_review_rejects_anonymous():
    assert client.post("/api/admin/evaluate-review", json=BODY).status_code == 401


def test_admin_review_rejects_non_admin():
    token = _token("이지메디컴", "demo")
    r = client.post("/api/admin/evaluate-review", json=BODY, headers=_auth(token))
    assert r.status_code == 403


def test_admin_review_totals_match_plain_evaluate():
    plain = evaluate(*ARGS)
    review = evaluate_admin_review(*ARGS)
    assert review["gift_tax_total"] == plain["gift_tax_total"]
    assert review["deemed_gift_total"] == plain["deemed_gift_total"]
    assert sum(d["gift_tax"] for d in review["shareholder_details"]) == plain["gift_tax_total"]


def test_common_exclusion_never_exceeds_per_shareholder_exclusion():
    """공통 제외분은 제10항 분(모든 주주에게 동일)이므로 주주별 제외분의 최솟값 이하여야 한다."""
    review = evaluate_admin_review(*ARGS)
    assert review["excluded_sales_common"] <= review["excluded_sales_min"]
    assert review["excluded_sales_min"] <= review["excluded_sales_max"]


def test_admin_review_exposes_shareholder_details():
    token = _token(ADMIN_USERNAME, ADMIN_PASSWORD)
    r = client.post("/api/admin/evaluate-review", json=BODY, headers=_auth(token))
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["shareholder_details"], "관리자 응답에 주주별 상세가 있어야 한다"
    assert data["excluded_sales_common"] <= data["excluded_sales_min"]
