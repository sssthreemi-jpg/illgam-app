from pydantic import BaseModel
from typing import Dict, Optional


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class EvaluateRequest(BaseModel):
    company: str
    operating_income: int
    corporate_tax: int = 0
    total_sales: int
    related_sales: Optional[Dict[str, int]] = None
    indirect_invest: Optional[Dict[str, bool]] = None
    # 세무조정내역: 가산 항목은 양수, 차감 항목은 음수
    tax_adjustments: Optional[Dict[str, int]] = None
