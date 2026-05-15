# app/schemas/term.py
from __future__ import annotations
from uuid import UUID
from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel

# ── 업로드 ──────────────────────────────────────────
class TermUploadResponse(BaseModel):
    id: UUID
    service_name: str
    domain: str
    sub_category: Optional[str] = None
    status: str
    version: int
    created_at: datetime

# ── 목록 조회 ────────────────────────────────────────
class TermSummary(BaseModel):
    id: UUID
    service_name: str
    domain: str
    sub_category: Optional[str] = None
    # 15 서비스 카탈로그의 canonical slug (예: "netflix"). 매칭 안 됐으면 NULL.
    # 프론트가 vendor 기준 사이드바 그룹핑에 사용.
    vendor_slug: Optional[str] = None
    status: str
    subscribed_at: Optional[date]
    latest_version: int
    created_at: datetime

    model_config = {"from_attributes": True}

class TermListResponse(BaseModel):
    items: list[TermSummary]
    total: int

# ── 상세 조회 ────────────────────────────────────────
class ClauseDetail(BaseModel):
    id: UUID
    clause_type: str
    title: Optional[str]
    original_text: str
    plain_text: Optional[str]
    page: Optional[int] = None
    bbox: Optional[list[float]] = None

class TermVersionDetail(BaseModel):
    id: UUID
    version: int
    summary: Optional[str]
    diff_summary: Optional[str]
    is_latest: bool
    clauses: list[ClauseDetail]
    created_at: datetime
    # 약관 자체에 적힌 시행일 (버전마다 다름). NULL 일 때 프론트는 created_at fallback.
    effective_date: Optional[date] = None

class TermDetailResponse(BaseModel):
    id: UUID
    service_name: str
    domain: str
    sub_category: Optional[str] = None
    # 15 서비스 카탈로그의 canonical slug (예: "netflix"). 매칭 안 됐으면 NULL.
    vendor_slug: Optional[str] = None
    status: str
    file_url: Optional[str]
    subscribed_at: Optional[date]
    versions: list[TermVersionDetail]
    created_at: datetime

# ── 버전 업데이트 ─────────────────────────────────────
class TermUpdateResponse(BaseModel):
    term_id: UUID
    new_version: int
    diff_summary: Optional[str]
    # include_user_impact=true 로 업로드했을 때만 채워짐. 그 외엔 null.
    user_impact: Optional[str] = None

# ── 의미 검색 ─────────────────────────────────────────
class SearchRequest(BaseModel):
    query: str
    top_k: int = 5

class ChunkResult(BaseModel):
    chunk_id: UUID
    chunk_index: int
    content: str
    # cosine similarity (1.0 = 동일, 0 = 무관). pgvector cosine distance 의 1 보수.
    score: float

class SearchResponse(BaseModel):
    results: list[ChunkResult]


# ── 통합 검색 (사용자 전체 약관) ─────────────────────
class UserSearchRequest(BaseModel):
    query: str
    top_k: int = 5
    # ["INSURANCE", "FINANCE"] 식으로 도메인 좁히기 (없으면 전체).
    domain_filter: Optional[list[str]] = None


class UserChunkResult(BaseModel):
    chunk_id: UUID
    chunk_index: int
    content: str
    term_id: UUID
    service_name: str
    domain: str
    score: float


class UserSearchResponse(BaseModel):
    results: list[UserChunkResult]
    total: int


# ── 사용자 영향 diff ─────────────────────────────────
class UserImpactDiffRequest(BaseModel):
    """약관 변경의 *나에게의 영향* 분석 요청.

    Term.subscribed_at 은 DB 에서 자동으로 가져오므로 본 요청 body 에 넣지 않음.
    plan/custom_notes 는 선택 — 더 정밀한 영향 분석을 원하면 채워서 보내기.
    """
    plan: Optional[str] = None
    custom_notes: Optional[str] = None

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"plan": "PRO", "custom_notes": "내달 해외 출장 예정"},
                {"plan": "BASIC"},
                {},
            ]
        }
    }


class DiffChangeOut(BaseModel):
    category: str
    direction: str
    description: str
    risk_level: str


# ── Sub-category 권장 vocab ─────────────────────────
class SubCategoryRecommendations(BaseModel):
    """도메인별 권장 sub-category 리스트.

    DB 컬럼은 자유 TEXT — 새 sub-category 도 자유롭게 입력 가능. 이 응답은 UI
    드롭다운 채움용. 추가/수정은 `app/models/sub_category.py` 수정.
    """
    domain: str
    sub_categories: list[str]

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "domain": "INSURANCE",
                    "sub_categories": [
                        "실손의료보험", "생명보험", "암보험",
                        "여행자보험", "자동차보험", "연금보험",
                        "화재보험", "단체보험",
                    ],
                },
                {
                    "domain": "FINANCE",
                    "sub_categories": [
                        "PG/결제대행", "송금", "선불전자지급수단",
                        "PFM/자산관리", "카드모집", "P2P/대출중개",
                    ],
                },
            ]
        }
    }


class UserImpactDiffResponse(BaseModel):
    """약관 두 버전 비교 + *현재 사용자에게의 영향* 자유문 + semantic diff 사전 분류."""

    term_id: UUID
    service_name: str
    old_version: int
    new_version: int
    diff_summary: str
    changes: list[DiffChangeOut]
    user_impact: str
    semantic_counts: dict[str, int]

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "term_id": "00000000-0000-0000-0000-000000000001",
                    "service_name": "Netflix",
                    "old_version": 1,
                    "new_version": 2,
                    "diff_summary": "갱신 통지 기간이 30일에서 7일로 단축되었습니다.",
                    "changes": [
                        {
                            "category": "terms_changes",
                            "direction": "less_consumer_friendly",
                            "description": "이전: 30일 전 통지 → 새 버전: 7일 전 통지",
                            "risk_level": "high",
                        }
                    ],
                    "user_impact": (
                        "PRO 플랜 가입자 (가입일 2026-01-01) 의 경우 다음 갱신일 "
                        "2026-07-01 전에 단축된 7일 통지 기준이 적용됩니다. 잔여 12일이라 "
                        "변경 시행일 전에 결정 가능. 갱신 거부를 원하면 *지금 1주일 내* "
                        "해지 검토를 권장합니다."
                    ),
                    "semantic_counts": {
                        "phrasing_only": 5, "substantive": 1,
                        "added": 0, "removed": 0,
                    },
                }
            ]
        }
    }