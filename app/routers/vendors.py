"""GET /vendors — 지원 vendor 카탈로그 (15 서비스).

프론트가 카테고리 드롭다운에 사용. alias-mismatch 파싱 오류 0% 보장 위해
백엔드 single source 와 동기화.

용도:
- 사용자가 업로드 시 service_name 자유 입력하지만, vendor 카탈로그에서 선택하면
  더 안전 (canonical slug + domain 자동 결정).
- 사이드바 카테고리 그룹핑 시 vendor_slug 와 domain 모두 활용 가능.
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.models.vendors import VENDORS


class VendorOut(BaseModel):
    slug: str = Field(..., description="canonical kebab-case slug (예: \"netflix\", \"kakao-pay\")")
    display_name: str = Field(..., description="UI 표시명 (예: \"Netflix\", \"카카오페이\")")
    domain: str = Field(..., description="TermDomain enum value (OTT/FINANCE/AI/APP/...)")
    aliases: list[str] = Field(..., description="허용 입력값 (canonicalization 매칭 대상)")


class VendorListResponse(BaseModel):
    total: int
    vendors: list[VendorOut]


router = APIRouter(tags=["Vendors"])


@router.get(
    "",
    response_model=VendorListResponse,
    summary="지원 vendor 카탈로그 (15 서비스)",
    description=(
        "프론트가 카테고리 드롭다운 / 사이드바 그룹핑에 사용할 vendor 리스트.\n\n"
        "- `slug`: 백엔드와 정합되는 canonical id. 업로드 시 service_name 으로 입력 시 "
        "alias 매칭으로 자동 결정됨.\n"
        "- `domain`: 도메인 카테고리 (OTT/FINANCE/AI/APP/...). vendor 매핑이 있으면 "
        "사용자가 입력한 domain 보다 우선.\n"
        "- `aliases`: 사용자가 service_name 으로 자유 입력해도 canonical slug 로 "
        "치환되는 매칭 후보들 (한/영 모두 포함)."
    ),
)
async def list_vendors():
    items = [
        VendorOut(
            slug=slug,
            display_name=meta["display_name"],
            domain=meta["domain"],
            aliases=list(meta["aliases"]),
        )
        for slug, meta in VENDORS.items()
    ]
    return VendorListResponse(total=len(items), vendors=items)
