# app/services/term_service.py
import uuid
from typing import Optional
from datetime import date
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from app.models.term import Term, TermVersion, TermChunk, TermClause
from app.models.calendar import CalendarEvent
from app.models.enums import ClauseType, EventType
from app.services import ai_client

CHUNK_SIZE = 500

def _split_chunks(text: str, size: int = CHUNK_SIZE) -> list[str]:
    return [text[i:i+size] for i in range(0, len(text), size)]


# ── AnalysisResult → DB 저장용 변환 헬퍼 ──────────────────
def _parse_result_to_clauses(result) -> list[dict]:
    out = []
    for c in result.key_clauses:
        out.append({
            "clause_type": "ETC",               # KeyClause에 clause_type 없음 → 전부 ETC
            "title": c.title,
            "original_text": c.citation.quote,  # 원문 인용구
            "plain_text": c.description,        # 평문 설명
        })
    return out

def _get_raw_text(result) -> str:
    """SubscriptionTerms에서 raw_text 추출. 필드명 다르면 여기만 수정."""
    terms = result.terms
    for attr in ("raw_text", "text", "content", "full_text"):
        if hasattr(terms, attr):
            return getattr(terms, attr) or ""
    return ""

def _get_domain(result) -> str:
    """AnalysisResult에서 domain 추출."""
    terms = result.terms
    for attr in ("domain", "service_domain", "category"):
        if hasattr(terms, attr):
            return getattr(terms, attr) or "ETC"
    return "ETC"


# ── process_upload ────────────────────────────────────────
async def process_upload(
    db: AsyncSession,
    user_id: uuid.UUID,
    service_name: str,
    subscribed_at,
    file_bytes: bytes,
    file_url: str,
    domain: str = "ETC",
) -> tuple[Term, TermVersion]:

    # 1. AI 파이프라인 (단일 호출로 통합)
    result = await ai_client.run_full_pipeline(
        file_bytes=file_bytes,
        filename=file_url.split("/")[-1],
        service_name=service_name,
    )

    raw_text = _get_raw_text(result)
    domain   = _get_domain(result)
    clauses  = _parse_result_to_clauses(result)
    chunks   = _split_chunks(raw_text)
    vectors  = await ai_client.embed_chunks(chunks)
    dates    = await ai_client.extract_dates(raw_text)

    # 2. Term 저장
    term = Term(
        user_id=user_id,
        service_name=service_name,
        domain=domain.upper(),
        file_url=file_url,
        subscribed_at=subscribed_at,
    )
    db.add(term)
    await db.flush()

    # 3. TermVersion 저장
    version = TermVersion(
        term_id=term.id,
        version=1,
        raw_text=raw_text,
        summary=result.summary,
        is_latest=True,
    )
    db.add(version)
    await db.flush()

    # 4. TermChunks + Embeddings
    for idx, (content, vector) in enumerate(zip(chunks, vectors)):
        db.add(TermChunk(
            term_id=term.id,
            version_id=version.id,
            chunk_index=idx,
            content=content,
            embedding=vector,
        ))

    # 5. TermClauses
    for c in clauses:
        db.add(TermClause(
            version_id=version.id,
            clause_type=c["clause_type"],
            title=c.get("title"),
            original_text=c["original_text"],
            plain_text=c.get("plain_text"),
        ))

    # 6. CalendarEvents
    for d in dates:
        db.add(CalendarEvent(
            term_id=term.id,
            user_id=user_id,
            event_type=d["event_type"],
            event_date=date.fromisoformat(d["date"]),
            label=f"{service_name} - {d['event_type']}",
        ))

    await db.flush()
    await db.refresh(term)
    await db.refresh(version)
    return term, version


# ── process_version_update ────────────────────────────────
async def process_version_update(
    db: AsyncSession,
    term_id: uuid.UUID,
    user_id: uuid.UUID,
    file_bytes: bytes,
    file_url: str,
) -> TermVersion:

    await db.execute(
        update(TermVersion)
        .where(TermVersion.term_id == term_id)
        .values(is_latest=False)
    )

    result_q = await db.execute(
        select(TermVersion.version)
        .where(TermVersion.term_id == term_id)
        .order_by(TermVersion.version.desc())
        .limit(1)
    )
    last_version = result_q.scalar_one_or_none() or 0

    # AI 파이프라인
    term_obj = await db.get(Term, term_id)
    result = await ai_client.run_full_pipeline(
        file_bytes=file_bytes,
        filename=file_url.split("/")[-1],
        service_name=term_obj.service_name if term_obj else "",
    )

    raw_text = _get_raw_text(result)
    clauses  = _parse_result_to_clauses(result)
    chunks   = _split_chunks(raw_text)
    vectors  = await ai_client.embed_chunks(chunks)
    dates    = await ai_client.extract_dates(raw_text)

    new_version = TermVersion(
        term_id=term_id,
        version=last_version + 1,
        raw_text=raw_text,
        summary=result.summary,
        diff_summary=None,  # TODO: AI팀 diff 연결 시 채움
        is_latest=True,
    )
    db.add(new_version)
    await db.flush()

    for idx, (content, vector) in enumerate(zip(chunks, vectors)):
        db.add(TermChunk(
            term_id=term_id,
            version_id=new_version.id,
            chunk_index=idx,
            content=content,
            embedding=vector,
        ))

    for c in clauses:
        db.add(TermClause(
            version_id=new_version.id,
            clause_type=c["clause_type"],
            title=c.get("title"),
            original_text=c["original_text"],
            plain_text=c.get("plain_text"),
        ))

    for d in dates:
        db.add(CalendarEvent(
            term_id=term_id,
            user_id=user_id,
            event_type=d["event_type"],
            event_date=date.fromisoformat(d["date"]),
            label=f"업데이트 v{last_version + 1} - {d['event_type']}",
        ))

    await db.flush()
    await db.refresh(new_version)
    return new_version


# ── 아래는 기존 코드 그대로 ──────────────────────────────
async def get_terms(
    db: AsyncSession,
    user_id: uuid.UUID,
    domain: Optional[str] = None,
    status: Optional[str] = None,
):
    q = (
        select(Term)
        .options(selectinload(Term.versions))
        .where(Term.user_id == user_id)
    )
    if domain:
        q = q.where(Term.domain == domain)
    if status:
        q = q.where(Term.status == status)
    result = await db.execute(q)
    return result.scalars().all()

async def get_term_detail(db: AsyncSession, term_id: uuid.UUID, user_id: uuid.UUID):
    result = await db.execute(
        select(Term)
        .options(
            selectinload(Term.versions).selectinload(TermVersion.clauses),
        )
        .where(Term.id == term_id, Term.user_id == user_id)
    )
    return result.scalar_one_or_none()


def _get_domain(result) -> str:
    terms = result.terms
    for attr in ("domain", "service_domain", "category"):
        val = getattr(terms, attr, None)
        if val and val.upper() in ("FINANCE", "OTT", "INSURANCE", "APP", "MEDICAL", "TELECOM"):
            return val.upper()
    return "ETC"  # "subscription" 같은 미매핑 값은 전부 ETC로 fallback

async def search_chunks(
    db: AsyncSession,
    term_id: uuid.UUID,
    query: str,
    top_k: int = 5,
) -> list[dict]:
    from sqlalchemy import text as sa_text

    query_vec = (await ai_client.embed_chunks([query]))[0]

    rows = (await db.execute(
        sa_text("""
            SELECT id, content, chunk_index
            FROM term_chunks
            WHERE term_id = :term_id
            ORDER BY embedding <=> CAST(:vec AS halfvec)
            LIMIT :top_k
        """),
        {"vec": str(query_vec), "term_id": str(term_id), "top_k": top_k},
    )).fetchall()

    return [
        {"id": str(r.id), "content": r.content, "chunk_index": r.chunk_index}
        for r in rows
    ]