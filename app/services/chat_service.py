# app/services/chat_service.py
from __future__ import annotations

import uuid
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.chat import ChatMessage, ChatSession
from app.models.enums import MessageRole
from app.services.ai_client import chat_with_ai


# ── 내부 헬퍼 ────────────────────────────────────────────

async def _get_or_create_session(
    db: AsyncSession,
    user_id: uuid.UUID,
    term_id: uuid.UUID | None,
    session_id: uuid.UUID | None,
) -> ChatSession:
    """session_id가 있으면 검증 후 반환, 없으면 신규 생성."""
    if session_id:
        result = await db.execute(
            select(ChatSession).where(
                ChatSession.id == session_id,
                ChatSession.user_id == user_id,
            )
        )
        session = result.scalar_one_or_none()
        if not session:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Session not found")
        return session

    session = ChatSession(user_id=user_id, term_id=term_id)
    db.add(session)
    await db.flush()  # id 확보 (commit은 라우터에서)
    return session


async def _build_history(
    db: AsyncSession, session_id: uuid.UUID
) -> list[dict]:
    """세션의 기존 메시지를 AI R3 history 포맷으로 변환."""
    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at)
    )
    messages = result.scalars().all()
    return [
        {"role": msg.role.value.lower(), "content": msg.content}
        for msg in messages
    ]


# ── 공개 서비스 함수 ─────────────────────────────────────

async def send_message(
    db: AsyncSession,
    user_id: uuid.UUID,
    term_id: uuid.UUID | None,
    session_id: uuid.UUID | None,
    message: str,
) -> dict:
    """
    1. 세션 조회/생성
    2. 히스토리 구성
    3. AI R3 chat 호출
    4. USER + ASSISTANT 메시지 저장
    5. 결과 반환
    """
    session = await _get_or_create_session(db, user_id, term_id, session_id)

    # 기존 히스토리 구성 (신규 세션이면 빈 리스트)
    history = await _build_history(db, session.id)

    # term_ids: session.term_id 있으면 단일 항목, 없으면 빈 리스트
    term_ids = [str(session.term_id)] if session.term_id else []

    # AI R3 호출
    ai_result = await chat_with_ai(
        query=message,
        term_ids=term_ids,
        history=history,
        db=db,
    )
    answer: str = ai_result.get("answer", "")
    sources: list[str] = ai_result.get("sources", [])
    source_uuids = [uuid.UUID(s) for s in sources if s]

    # 사용자 메시지 저장
    user_msg = ChatMessage(
        session_id=session.id,
        role=MessageRole.USER,
        content=message,
        source_chunks=[],
    )
    db.add(user_msg)

    # 어시스턴트 메시지 저장
    assistant_msg = ChatMessage(
        session_id=session.id,
        role=MessageRole.ASSISTANT,
        content=answer,
        source_chunks=source_uuids,
    )
    db.add(assistant_msg)

    await db.commit()
    await db.refresh(user_msg)
    await db.refresh(assistant_msg)

    return {
        "session": session,
        "answer": answer,
        "sources": source_uuids,
        "user_message": user_msg,
        "assistant_message": assistant_msg,
    }


async def get_sessions(
    db: AsyncSession, user_id: uuid.UUID
) -> Sequence[ChatSession]:
    result = await db.execute(
        select(ChatSession)
        .where(ChatSession.user_id == user_id)
        .order_by(ChatSession.created_at.desc())
    )
    return result.scalars().all()


async def get_session_detail(
    db: AsyncSession, session_id: uuid.UUID, user_id: uuid.UUID
) -> ChatSession:
    result = await db.execute(
        select(ChatSession)
        .where(
            ChatSession.id == session_id,
            ChatSession.user_id == user_id,
        )
        .options(selectinload(ChatSession.messages))
    )
    session = result.scalar_one_or_none()
    if not session:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Session not found")
    return session