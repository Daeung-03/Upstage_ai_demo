"""Dispute 매칭 API 응답 스키마."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field


class DisputeMatch(BaseModel):
    """단일 분쟁 사례 매칭 결과."""

    case_id: UUID
    title: str
    summary: str
    outcome: str
    source: str
    source_url: str | None = None
    score: float = Field(..., description="cosine 유사도 + boost. 0~1.2 범위.")
    matched_signals: list[str] = Field(
        default_factory=list,
        description="어떤 boost 가 적용됐는지 트레이싱 (pain_point:POST-01 / flag:refund_denial / domain:OTT)",
    )


class ClauseDisputeMatches(BaseModel):
    """KeyClause 한 개에 대한 top-K 매칭."""

    clause_id: UUID
    clause_title: str | None = None
    matches: list[DisputeMatch] = Field(default_factory=list)


class TermDisputesResponse(BaseModel):
    """약관 전체 — 각 KeyClause 별 top-3 묶음."""

    term_id: UUID
    clauses: list[ClauseDisputeMatches] = Field(default_factory=list)


class DisputeCaseDetail(BaseModel):
    """관리/디버깅용 단일 사례 상세."""

    id: UUID
    title: str
    summary: str
    outcome: str
    source: str
    source_url: str | None = None
    pain_point_ids: list[str] = Field(default_factory=list)
    unfair_flags: list[str] = Field(default_factory=list)
    domain: str


class DisputeListResponse(BaseModel):
    items: list[DisputeCaseDetail] = Field(default_factory=list)
    total: int
