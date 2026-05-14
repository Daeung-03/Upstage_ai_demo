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
    status: str
    version: int
    created_at: datetime

# ── 목록 조회 ────────────────────────────────────────
class TermSummary(BaseModel):
    id: UUID
    service_name: str
    domain: str
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

class TermVersionDetail(BaseModel):
    id: UUID
    version: int
    summary: Optional[str]
    diff_summary: Optional[str]
    is_latest: bool
    clauses: list[ClauseDetail]
    created_at: datetime

class TermDetailResponse(BaseModel):
    id: UUID
    service_name: str
    domain: str
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

# ── 의미 검색 ─────────────────────────────────────────
class SearchRequest(BaseModel):
    query: str
    top_k: int = 5

class ChunkResult(BaseModel):
    chunk_id: UUID
    content: str
    score: float

class SearchResponse(BaseModel):
    results: list[ChunkResult]