"""Dispute matching 서비스.

이 모듈의 두 진입점:
- `upsert_dispute_cases(db, cases)` — fixture indexer / 향후 크롤러가 호출.
- `find_similar_disputes(...)` — 라우터가 호출 (Task 6 에서 구현).
"""

from __future__ import annotations

import uuid
from typing import TypedDict

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ai.schemas.flag_canonical import flag_canonical
from app.models.dispute import DisputeCase


# ── Public input shape (source-agnostic) ────────────────────────


class DisputeCaseInput(TypedDict, total=False):
    external_id: str | None
    title: str
    summary: str
    outcome: str
    source: str
    source_url: str | None
    pain_point_ids: list[str]
    unfair_flags: list[str]
    domain: str  # OTT/FINANCE/AI/ALL
    # embedding 은 indexer 가 채워서 직접 update 호출 — input 에는 없음


# ── Helpers ─────────────────────────────────────────────────────


def _canonical_flags(flags: list[str]) -> list[str]:
    """unfair_flag 리스트를 canonical 정렬·dedupe."""
    seen: dict[str, None] = {}
    for f in flags or []:
        if not f:
            continue
        c = flag_canonical(f)
        if c and c not in seen:
            seen[c] = None
    return list(seen.keys())


def _normalize_pain_points(ids: list[str | None]) -> list[str]:
    """pain_point id 대소문자/공백 정규화."""
    out: list[str] = []
    for x in ids or []:
        if not x:
            continue
        s = x.strip().upper()
        if s:
            out.append(s)
    return out


def _normalize_input(case: DisputeCaseInput) -> dict:
    return {
        "external_id": case.get("external_id") or None,
        "title": case["title"],
        "summary": case["summary"],
        "outcome": case["outcome"],
        "source": case["source"],
        "source_url": case.get("source_url") or None,
        "pain_point_ids": _normalize_pain_points(case.get("pain_point_ids", [])),
        "unfair_flags": _canonical_flags(case.get("unfair_flags", [])),
        "domain": (case.get("domain") or "ALL").upper(),
    }


# ── Upsert ──────────────────────────────────────────────────────


async def upsert_dispute_cases(
    db: AsyncSession,
    cases: list[DisputeCaseInput],
) -> list[uuid.UUID]:
    """source-agnostic 적재. external_id 가 있으면 upsert, 없으면 insert.

    반환: 적재된 row id 리스트 (외부 indexer 가 embedding 업데이트 시 사용).
    """
    if not cases:
        return []

    inserted_ids: list[uuid.UUID] = []
    for raw in cases:
        norm = _normalize_input(raw)
        if norm["external_id"]:
            # PostgreSQL ON CONFLICT (external_id) DO UPDATE
            stmt = (
                insert(DisputeCase)
                .values(**norm)
                .on_conflict_do_update(
                    index_elements=[DisputeCase.external_id],
                    set_={
                        "title": norm["title"],
                        "summary": norm["summary"],
                        "outcome": norm["outcome"],
                        "source": norm["source"],
                        "source_url": norm["source_url"],
                        "pain_point_ids": norm["pain_point_ids"],
                        "unfair_flags": norm["unfair_flags"],
                        "domain": norm["domain"],
                    },
                )
                .returning(DisputeCase.id)
            )
            result = await db.execute(stmt)
            row_id = result.scalar_one()
        else:
            obj = DisputeCase(**norm)
            db.add(obj)
            await db.flush()
            row_id = obj.id
        inserted_ids.append(row_id)
    return inserted_ids


async def set_dispute_embedding(
    db: AsyncSession,
    case_id: uuid.UUID,
    embedding: list[float],
) -> None:
    """indexer 가 embed 호출 후 따로 update."""
    obj = await db.get(DisputeCase, case_id)
    if obj is None:
        raise ValueError(f"DisputeCase {case_id} not found")
    obj.embedding = embedding
    await db.flush()


# ── Matching ────────────────────────────────────────────────────

import os
from dataclasses import dataclass, field

from sqlalchemy import text as sa_text


DEFAULT_TOP_K = int(os.getenv("DISPUTE_TOP_K", "3"))
DEFAULT_MIN_SCORE = float(os.getenv("DISPUTE_MIN_SCORE", "0.65"))

# Boost 가산값 — 결정론. spec 4.1 참조.
BOOST_PAIN_POINT = 0.10
BOOST_UNFAIR_FLAG = 0.05
BOOST_DOMAIN = 0.05


@dataclass
class _CandidateRow:
    """pgvector 후보 1행 (boost 적용 전 raw)."""

    id: uuid.UUID
    title: str
    summary: str
    outcome: str
    source: str
    source_url: str | None
    pain_point_ids: list[str]
    unfair_flags: list[str]
    domain: str
    cosine_distance: float


@dataclass
class _ScoredMatch:
    """boost 가산 후 정렬·필터링된 결과."""

    id: uuid.UUID
    title: str
    summary: str
    outcome: str
    source: str
    source_url: str | None
    score: float
    matched_signals: list[str] = field(default_factory=list)


def _apply_boosts_and_filter(
    rows: list[_CandidateRow],
    *,
    clause_pain_point: str | None,
    term_unfair_flags: list[str],
    term_domain: str,
    top_k: int,
    min_score: float,
) -> list[_ScoredMatch]:
    """결정론 boost: pain_point / unfair_flag / domain 신호별 가산."""
    term_pain = (clause_pain_point or "").strip().upper() or None
    term_flag_canon = {flag_canonical(f) for f in (term_unfair_flags or []) if f}
    term_dom = (term_domain or "").upper()

    scored: list[_ScoredMatch] = []
    for r in rows:
        base = 1.0 - float(r.cosine_distance)
        signals: list[str] = []
        score = base

        if term_pain and term_pain in {p.upper() for p in r.pain_point_ids}:
            score += BOOST_PAIN_POINT
            signals.append(f"pain_point:{term_pain}")

        row_flag_canon = {flag_canonical(f) for f in r.unfair_flags if f}
        flag_overlap = term_flag_canon & row_flag_canon
        if flag_overlap:
            score += BOOST_UNFAIR_FLAG
            # 가장 작은 (sorted 첫) canonical 만 신호로 노출 — 안정적 정렬
            signals.append(f"flag:{sorted(flag_overlap)[0]}")

        row_dom = (r.domain or "").upper()
        if row_dom == "ALL":
            score += BOOST_DOMAIN
            signals.append("domain:ALL")
        elif row_dom == term_dom and term_dom:
            score += BOOST_DOMAIN
            signals.append(f"domain:{term_dom}")

        if score < min_score:
            continue

        scored.append(_ScoredMatch(
            id=r.id, title=r.title, summary=r.summary, outcome=r.outcome,
            source=r.source, source_url=r.source_url,
            score=round(score, 6), matched_signals=signals,
        ))

    scored.sort(key=lambda m: m.score, reverse=True)
    return scored[:top_k]


async def _fetch_candidates_by_embedding(
    db: AsyncSession,
    query_vec: list[float],
    fetch_k: int,
    domain_filter: str | None = None,
) -> list[_CandidateRow]:
    """pgvector cosine top-K 검색 (raw distance 포함)."""
    params: dict = {"vec": str(query_vec), "k": fetch_k}
    domain_sql = ""
    if domain_filter:
        # 같은 도메인 + ALL 둘 다 fetch
        domain_sql = " AND (domain = :dom OR domain = 'ALL')"
        params["dom"] = domain_filter

    sql = sa_text(f"""
        SELECT
            id, title, summary, outcome, source, source_url,
            pain_point_ids, unfair_flags, domain,
            (embedding <=> CAST(:vec AS halfvec)) AS cosine_distance
        FROM dispute_cases
        WHERE embedding IS NOT NULL{domain_sql}
        ORDER BY embedding <=> CAST(:vec AS halfvec)
        LIMIT :k
    """)
    result = await db.execute(sql, params)
    rows: list[_CandidateRow] = []
    for r in result.fetchall():
        rows.append(_CandidateRow(
            id=r.id, title=r.title, summary=r.summary, outcome=r.outcome,
            source=r.source, source_url=r.source_url,
            pain_point_ids=list(r.pain_point_ids or []),
            unfair_flags=list(r.unfair_flags or []),
            domain=r.domain,
            cosine_distance=float(r.cosine_distance),
        ))
    return rows


async def find_similar_disputes(
    db: AsyncSession,
    *,
    query_text: str,
    clause_pain_point: str | None,
    term_unfair_flags: list[str],
    term_domain: str,
    top_k: int = DEFAULT_TOP_K,
    min_score: float = DEFAULT_MIN_SCORE,
    fetch_k: int = 10,
) -> list[_ScoredMatch]:
    """KeyClause/flag → 유사 분쟁 사례 top-K. embed_query → pgvector → boost."""
    from app.services.ai_client import embed_query

    if not query_text or not query_text.strip():
        return []

    query_vec = await embed_query(query_text)
    rows = await _fetch_candidates_by_embedding(
        db, query_vec, fetch_k=fetch_k,
        domain_filter=(term_domain or None) and term_domain.upper(),
    )
    return _apply_boosts_and_filter(
        rows,
        clause_pain_point=clause_pain_point,
        term_unfair_flags=term_unfair_flags,
        term_domain=term_domain,
        top_k=top_k,
        min_score=min_score,
    )
