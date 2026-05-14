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

CHUNK_SIZE = 500  # 청크 분할 기준 글자 수

def _split_chunks(text: str, size: int = CHUNK_SIZE) -> list[str]:
    return [text[i:i+size] for i in range(0, len(text), size)]


async def process_upload(
    db: AsyncSession,
    user_id: uuid.UUID,
    service_name: str,
    subscribed_at,
    file_bytes: bytes,
    file_url: str,
) -> tuple[Term, TermVersion]:
    # 1. AI 파이프라인 (Mock)
    raw_text  = await ai_client.parse_document(file_bytes)
    domain    = await ai_client.classify_document(raw_text)
    clauses   = await ai_client.extract_clauses(raw_text)
    dates     = await ai_client.extract_dates(raw_text)
    chunks    = _split_chunks(raw_text)
    vectors   = await ai_client.embed_chunks(chunks)

    # 2. Term 저장
    term = Term(
        user_id=user_id,
        service_name=service_name,
        domain=domain,
        file_url=file_url,
        subscribed_at=subscribed_at,
    )
    db.add(term)
    await db.flush()  # term.id 확보

    # 3. TermVersion 저장
    version = TermVersion(
        term_id=term.id,
        version=1,
        raw_text=raw_text,
        is_latest=True,
    )
    db.add(version)
    await db.flush()  # version.id 확보

    # 4. TermChunks + Embeddings
    for idx, (content, vector) in enumerate(zip(chunks, vectors)):
        db.add(TermChunk(
            term_id=term.id,
            version_id=version.id,
            chunk_index=idx,
            content=content,
            embedding=vector,
        ))

    # 5. TermClauses (plain_text 포함)
    for c in clauses:
        plain = await ai_client.simplify_clause(c["original_text"])
        db.add(TermClause(
            version_id=version.id,
            clause_type=c["clause_type"],
            title=c.get("title"),
            original_text=c["original_text"],
            plain_text=plain,
        ))

    # 6. CalendarEvents
    for d in dates:
        db.add(CalendarEvent(
            term_id=term.id,
            user_id=user_id,
            event_type=d["event_type"],
            event_date=date.fromisoformat(d["date"]),  # str → date 변환
            label=f"{service_name} - {d['event_type']}",
        ))

    await db.flush()
    await db.refresh(term)
    await db.refresh(version)
    return term, version


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


async def process_version_update(
    db: AsyncSession,
    term_id: uuid.UUID,
    user_id: uuid.UUID,
    file_bytes: bytes,
    file_url: str,
) -> TermVersion:
    # 기존 is_latest 해제
    await db.execute(
        update(TermVersion)
        .where(TermVersion.term_id == term_id)
        .values(is_latest=False)
    )

    # 최신 버전 번호 조회
    result = await db.execute(
        select(TermVersion.version)
        .where(TermVersion.term_id == term_id)
        .order_by(TermVersion.version.desc())
        .limit(1)
    )
    last_version = result.scalar_one_or_none() or 0

    raw_text  = await ai_client.parse_document(file_bytes)
    clauses   = await ai_client.extract_clauses(raw_text)
    dates     = await ai_client.extract_dates(raw_text)
    chunks    = _split_chunks(raw_text)
    vectors   = await ai_client.embed_chunks(chunks)

    new_version = TermVersion(
        term_id=term_id,
        version=last_version + 1,
        raw_text=raw_text,
        diff_summary="(Mock) 주요 변경: 결제 조항 수정, 해지 기간 변경",
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
        plain = await ai_client.simplify_clause(c["original_text"])
        db.add(TermClause(
            version_id=new_version.id,
            clause_type=c["clause_type"],
            title=c.get("title"),
            original_text=c["original_text"],
            plain_text=plain,
        ))

    for d in dates:
        db.add(CalendarEvent(
            term_id=term_id,
            user_id=user_id,
            event_type=d["event_type"],
            event_date=date.fromisoformat(d["date"]),  # str → date 변환
            label=f"업데이트 v{last_version + 1} - {d['event_type']}",
        ))

    await db.flush()
    await db.refresh(new_version)
    return new_version