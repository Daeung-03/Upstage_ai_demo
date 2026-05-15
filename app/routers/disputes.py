"""분쟁 사례 매칭 라우터.

- /v1/terms/{term_id}/disputes — 약관 전체 KeyClause × top-3 (대시보드)
- /v1/terms/{term_id}/clauses/{clause_id}/disputes — 조항 드릴다운
- /v1/disputes — 사례 목록 (관리)
- /v1/disputes/{case_id} — 단일 사례
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.dispute import (
    ClauseDisputeMatches, DisputeCaseDetail, DisputeListResponse,
    TermDisputesResponse,
)
from app.services import dispute_service


router = APIRouter()


@router.get("/v1/terms/{term_id}/disputes", response_model=TermDisputesResponse)
async def list_term_disputes(
    term_id: uuid.UUID,
    top_k: int = Query(default=dispute_service.DEFAULT_TOP_K, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
):
    result = await dispute_service.find_disputes_for_term(
        db, term_id=term_id, top_k=top_k
    )
    if result is None:
        raise HTTPException(status_code=404, detail="약관을 찾을 수 없습니다.")
    return result


@router.get(
    "/v1/terms/{term_id}/clauses/{clause_id}/disputes",
    response_model=ClauseDisputeMatches,
)
async def get_clause_disputes(
    term_id: uuid.UUID,
    clause_id: uuid.UUID,
    top_k: int = Query(default=dispute_service.DEFAULT_TOP_K, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
):
    result = await dispute_service.find_disputes_for_clause(
        db, clause_id=clause_id, top_k=top_k
    )
    if result is None:
        raise HTTPException(status_code=404, detail="조항을 찾을 수 없습니다.")
    return result


@router.get("/v1/disputes", response_model=DisputeListResponse)
async def list_disputes(
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    return await dispute_service.list_dispute_cases(db, limit=limit, offset=offset)


@router.get("/v1/disputes/{case_id}", response_model=DisputeCaseDetail)
async def get_dispute(
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    obj = await dispute_service.get_dispute_case(db, case_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="분쟁 사례를 찾을 수 없습니다.")
    return obj
