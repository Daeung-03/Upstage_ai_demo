# app/routers/chat.py
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.chat import (
    ChatRequest,
    ChatResponse,
    MessageOut,
    SessionDetailOut,
    SessionOut,
)
from app.services import chat_service

router = APIRouter(tags=["chat"])


@router.post("", response_model=ChatResponse)
async def post_chat(
    body: ChatRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    메시지 전송 + 세션 자동 생성.
    - session_id 없으면 신규 세션 생성
    - term_id 지정 시 해당 약관 컨텍스트로 RAG 실행
    """
    result = await chat_service.send_message(
        db=db,
        user_id=body.user_id,
        term_id=body.term_id,
        session_id=body.session_id,
        message=body.message,
    )
    return ChatResponse(
        session_id=result["session"].id,
        answer=result["answer"],
        sources=result["sources"],
        user_message=MessageOut.model_validate(result["user_message"]),
        assistant_message=MessageOut.model_validate(result["assistant_message"]),
    )


@router.get("/sessions", response_model=list[SessionOut])
async def list_sessions(
    user_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """사용자의 채팅 세션 목록 조회."""
    sessions = await chat_service.get_sessions(db, user_id)
    return [SessionOut.model_validate(s) for s in sessions]


@router.get("/sessions/{session_id}", response_model=SessionDetailOut)
async def get_session(
    session_id: uuid.UUID,
    user_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """세션 대화 이력 조회."""
    session = await chat_service.get_session_detail(db, session_id, user_id)
    return SessionDetailOut(
        id=session.id,
        user_id=session.user_id,
        term_id=session.term_id,
        created_at=session.created_at,
        messages=[MessageOut.model_validate(m) for m in session.messages],
    )