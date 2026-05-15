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
    # 약관 KeyClause 의 LLM 분류 결과. 프론트에서 ★ 색상/뱃지에 사용.
    clause_risk_level: str | None = None
    clause_pain_point_id: str | None = None
    # LLM 으로 생성된 "왜 위험한가" 자연어 단락 (3-4문장).
    # 첫 조회 시 생성/캐시, 이후 즉시 반환. dispute_cases 갱신 시 무효화.
    risk_reasoning: str | None = None
    # reasoning 단락 다음 줄 "이 조항이 영향 받으면 ~ 할 수 있습니다" 식 행동 가이드.
    user_action: str | None = None
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
