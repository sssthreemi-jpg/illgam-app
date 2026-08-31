import pytest
from fastapi.testclient import TestClient

from backend.main import app

# 데모 계정 "이지메디컴" 이 실제 데이터에 존재해야 한다.
# 합성 fixture 환경의 API 노출면 검증은 test_calc_synthetic.py 가 담당한다.
pytestmark = pytest.mark.realdata

client = TestClient(app)


def login(username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200
    return r.json()["access_token"]


def test_api_response_privacy():
    token = login("이지메디컴", "demo")
    headers = {"Authorization": f"Bearer {token}"}

    # call evaluate
    body = {"company": "이지메디컴", "operating_income": 1000000, "corporate_tax": 0, "total_sales": 1000000, "related_sales": {"대웅제약": 100000}}
    r = client.post("/api/evaluate", json=body, headers=headers)
    assert r.status_code == 200
    allowed = {"company","size","taxable","total_sales","related_sales_total","related_sales_ratio","article10_total","taxation_ratio","normal_ratio","deemed_gift_total","dividend_deduction_total","notices","gift_tax_total","filing_credit_total","gift_tax_payable_total","reason","exclusion_details","year","data_as_of"}
    assert set(r.json().keys()) <= allowed, set(r.json().keys()) - allowed

    # ⑭ 지분율 상당액 건에서 지분율이 역산될 만한 값이 새어나가면 안 된다.
    for detail in r.json().get("exclusion_details", []):
        assert set(detail) == {"counterparty", "sales", "reason", "article",
                               "rate", "excluded_sales"}, detail
        # 공개되는 적용률은 0%(사유 없음) 또는 100%(⑩·§18) 뿐이다.
        # 그 사이 값은 곧 지배주주 지분율이므로 None 이어야 한다.
        assert detail["rate"] in (None, 0.0, 1.0), detail
        if detail["rate"] is None:
            assert detail["excluded_sales"] is None, detail

    # companies endpoint should return only names list
    r2 = client.get("/api/companies", headers=headers)
    assert r2.status_code == 200
    data = r2.json()
    assert "companies" in data and isinstance(data["companies"], list)

    # my-company should only expose company and size
    r3 = client.get("/api/my-company", headers=headers)
    assert r3.status_code == 200
    keys = set(r3.json().keys())
    assert keys <= {"company", "size", "year"}
