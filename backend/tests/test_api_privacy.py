from fastapi.testclient import TestClient
from calc import company_list
import json

from main import app


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
    allowed = {"company","size","taxable","total_sales","related_sales_total","related_sales_ratio","normal_ratio","deemed_gift_total","gift_tax_total","reason"}
    assert set(r.json().keys()) <= allowed

    # companies endpoint should return only names list
    r2 = client.get("/api/companies", headers=headers)
    assert r2.status_code == 200
    data = r2.json()
    assert "companies" in data and isinstance(data["companies"], list)

    # my-company should only expose company and size
    r3 = client.get("/api/my-company", headers=headers)
    assert r3.status_code == 200
    keys = set(r3.json().keys())
    assert keys <= {"company", "size"}
