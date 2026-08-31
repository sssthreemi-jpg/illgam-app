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
    # 어느 연도 지분·규모·세율로 계산할지. 미지정이면 서버의 기본(최신) 연도.
    # 서버에 없는 연도를 보내면 조용히 기본 연도로 넘어가지 않고 400 으로 거절한다 —
    # 2025 로 계산했다고 믿는데 2026 데이터가 쓰이는 것이 최악이다.
    year: Optional[str] = None
    operating_income: int
    corporate_tax: int = 0
    total_sales: int
    related_sales: Optional[Dict[str, int]] = None
    # indirect_invest 는 받지 않는다. 간접출자 여부는 서버가 지분 데이터에서 도출한다
    # (calc.indirect_invest_map). 클라이언트가 보내도 무시된다.
    # 세무조정내역: 가산 항목은 양수, 차감 항목은 음수
    tax_adjustments: Optional[Dict[str, int]] = None
    # 거래처별 ⑩ 과세제외금액(상증령 §34의3 ⑩). 수출목적 매출 등 지분 데이터로는
    # 도출되지 않는 값이라 신고서에서 확정한 금액을 그대로 받는다.
    # 수혜법인이 그 거래처에 출자한 관계면 이 값과 무관하게 전액이 ⑩ 이다.
    article10_exclusions: Optional[Dict[str, int]] = None
