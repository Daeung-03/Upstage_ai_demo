"""Dispute matching 서비스.

이 모듈의 두 진입점:
- `upsert_dispute_cases(db, cases)` — fixture indexer / 향후 크롤러가 호출.
- `find_similar_disputes(...)` — 라우터가 호출 (Task 6 에서 구현).
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from typing import TypedDict

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ai.schemas.flag_canonical import flag_canonical
from app.models.dispute import DisputeCase

logger = logging.getLogger(__name__)


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
            # PostgreSQL ON CONFLICT (external_id) WHERE external_id IS NOT NULL DO UPDATE
            #
            # 마이그레이션 0002 의 unique index 가 `WHERE external_id IS NOT NULL`
            # 부분 인덱스라, ON CONFLICT spec 에도 동일 WHERE 절을 줘야 매칭됨.
            # 안 그러면 InvalidColumnReferenceError ("no unique or exclusion constraint
            # matching the ON CONFLICT specification").
            stmt = (
                insert(DisputeCase)
                .values(**norm)
                .on_conflict_do_update(
                    index_elements=[DisputeCase.external_id],
                    index_where=DisputeCase.external_id.is_not(None),
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


# ── 라우터 진입점 (라우터는 ORM 모를 필요 없게 dict 로 변환) ─────


async def _compute_disputes_signature(db: AsyncSession) -> str:
    """dispute_cases 의 현재 상태를 short hash 로. 캐시 무효화 키.

    `max(updated_at)` + `count(*)` 만 조합 — case 추가/수정 시 둘 중 하나 변함.
    삭제(count 감소) 도 detect. SQL 단일 row 라 비용 무시.
    """
    row = (await db.execute(
        select(func.max(DisputeCase.updated_at), func.count(DisputeCase.id))
    )).one()
    max_updated, n = row
    raw = f"{max_updated.isoformat() if max_updated else 'null'}|{n}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


async def _get_or_generate_reasoning(
    db: AsyncSession,
    *,
    clause,
    matches: list[dict],
    signature: str,
) -> tuple[str | None, str | None]:
    """clause 에 대한 reasoning lazy cache. 캐시 hit 면 즉시, miss 면 LLM 호출 후 저장.

    반환: (reasoning, user_action). matches 가 비면 둘 다 None (LLM 호출 안 함).
    """
    if not matches:
        return None, None

    cached_sig = clause.disputes_signature
    cached_reasoning = clause.dispute_reasoning
    if cached_sig == signature and cached_reasoning:
        # cache hit — user_action 은 reasoning 안에 묶여있던 시기가 있을 수 있어
        # 컬럼 분리는 follow-up. 지금은 reasoning 만 반환.
        return cached_reasoning, None

    # cache miss → LLM 생성
    from app.services.ai_client import generate_dispute_reasoning
    try:
        result = await generate_dispute_reasoning(
            clause_title=clause.title,
            clause_quote=clause.original_text,
            clause_description=clause.plain_text,
            risk_level=clause.risk_level,
            pain_point_id=clause.pain_point_id,
            matches=matches,
        )
    except Exception as e:
        # LLM 실패해도 매칭 결과는 정상 반환 — reasoning 만 빈 상태로.
        # 다음 호출에서 signature 갱신 없이 재시도 가능 (cached_reasoning 이 NULL 이라 miss 유지).
        logger.exception("dispute reasoning generation failed for clause %s: %s",
                         clause.id, e)
        return None, None

    # DB 저장 (commit 은 호출자 — find_disputes_for_term 끝나면 자동 commit 또는
    # 라우터에서 처리. 여기선 add/update 만)
    clause.dispute_reasoning = result.reasoning
    clause.disputes_signature = signature
    # NOTE: user_action 은 응답으로만 노출, DB 컬럼은 미저장 (재방문 시 reasoning
    # 안에 동일 행동 가이드가 들어있어 redundant).
    try:
        await db.commit()
        await db.refresh(clause)
    except Exception:
        await db.rollback()
        logger.exception("failed to persist dispute reasoning for clause %s", clause.id)
    return result.reasoning, result.user_action


def _clause_query_text(clause) -> str:
    return "\n".join(filter(None, [
        clause.title or "",
        clause.plain_text or "",
        clause.original_text or "",
    ])).strip()


async def find_disputes_for_clause(
    db: AsyncSession,
    *,
    clause_id: uuid.UUID,
    top_k: int = DEFAULT_TOP_K,
    disputes_signature: str | None = None,
) -> dict | None:
    """단일 TermClause → top-K 매칭 + LLM reasoning (lazy cache).

    disputes_signature 가 주어지면 그걸 사용 (find_disputes_for_term 호출 경로).
    None 이면 여기서 computed — 단건 호출 경로용.
    clause 없으면 None.
    """
    from app.models.term import TermClause, TermVersion, Term

    clause = await db.get(TermClause, clause_id)
    if clause is None:
        return None
    version = await db.get(TermVersion, clause.version_id)
    term = await db.get(Term, version.term_id) if version else None

    matches = await find_similar_disputes(
        db,
        query_text=_clause_query_text(clause),
        # ← 0003 마이그레이션으로 pain_point_id 컬럼 등장. 이제 pain_point boost 활성.
        clause_pain_point=clause.pain_point_id,
        term_unfair_flags=[],
        term_domain=(term.domain.value if term and term.domain else "ALL"),
        top_k=top_k,
    )
    match_dicts = [
        {
            "case_id": m.id, "title": m.title, "summary": m.summary,
            "outcome": m.outcome, "source": m.source,
            "source_url": m.source_url, "score": m.score,
            "matched_signals": m.matched_signals,
        }
        for m in matches
    ]
    signature = disputes_signature or await _compute_disputes_signature(db)
    reasoning, user_action = await _get_or_generate_reasoning(
        db, clause=clause, matches=match_dicts, signature=signature,
    )

    return {
        "clause_id": clause_id,
        "clause_title": clause.title,
        "clause_risk_level": clause.risk_level,
        "clause_pain_point_id": clause.pain_point_id,
        "risk_reasoning": reasoning,
        "user_action": user_action,
        "matches": match_dicts,
    }


async def find_disputes_for_term(
    db: AsyncSession,
    *,
    term_id: uuid.UUID,
    top_k: int = DEFAULT_TOP_K,
) -> dict | None:
    """약관의 latest version 의 모든 TermClause × top-K + reasoning. term 없으면 None.

    dispute_cases 의 signature 를 한 번만 계산해 모든 clause 에 공유 — N 회 쿼리
    절약 + 동일 batch 내 일관성 보장.
    """
    from app.models.term import TermVersion, Term
    from sqlalchemy.orm import selectinload

    result = await db.execute(
        select(Term)
        .options(selectinload(Term.versions).selectinload(TermVersion.clauses))
        .where(Term.id == term_id)
    )
    term = result.scalar_one_or_none()
    if term is None:
        return None

    latest = next((v for v in term.versions if v.is_latest), None)
    if latest is None:
        return {"term_id": term_id, "clauses": []}

    signature = await _compute_disputes_signature(db)
    out_clauses: list[dict] = []
    for clause in latest.clauses:
        sub = await find_disputes_for_clause(
            db, clause_id=clause.id, top_k=top_k,
            disputes_signature=signature,
        )
        if sub:
            out_clauses.append(sub)
    return {"term_id": term_id, "clauses": out_clauses}


async def list_dispute_cases(
    db: AsyncSession,
    *,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    """관리/디버깅용 사례 목록."""
    total_q = await db.execute(select(DisputeCase))
    total = len(total_q.scalars().all())

    page_q = await db.execute(
        select(DisputeCase).order_by(DisputeCase.created_at.desc())
        .limit(limit).offset(offset)
    )
    items = page_q.scalars().all()
    return {
        "items": [
            {
                "id": c.id, "title": c.title, "summary": c.summary,
                "outcome": c.outcome, "source": c.source,
                "source_url": c.source_url,
                "pain_point_ids": list(c.pain_point_ids or []),
                "unfair_flags": list(c.unfair_flags or []),
                "domain": c.domain,
            }
            for c in items
        ],
        "total": total,
    }


async def get_dispute_case(
    db: AsyncSession,
    case_id: uuid.UUID,
) -> dict | None:
    obj = await db.get(DisputeCase, case_id)
    if obj is None:
        return None
    return {
        "id": obj.id, "title": obj.title, "summary": obj.summary,
        "outcome": obj.outcome, "source": obj.source,
        "source_url": obj.source_url,
        "pain_point_ids": list(obj.pain_point_ids or []),
        "unfair_flags": list(obj.unfair_flags or []),
        "domain": obj.domain,
    }
