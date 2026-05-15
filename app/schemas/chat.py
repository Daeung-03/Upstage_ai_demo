# app/schemas/chat.py
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


# ── 요청 스키마 ──────────────────────────────────────────
class ChatRequest(BaseModel):
    user_id: uuid.UUID
    term_id: uuid.UUID | None = None          # 특정 약관 컨텍스트 (선택)
    session_id: uuid.UUID | None = None       # 없으면 신규 세션 생성
    message: str = Field(..., min_length=1)


# ── 응답 스키마 ──────────────────────────────────────────
class MessageOut(BaseModel):
    id: uuid.UUID
    role: str                                 # "USER" | "ASSISTANT"
    content: str
    source_chunks: list[uuid.UUID]
    created_at: datetime

    model_config = {"from_attributes": True}


class ChatResponse(BaseModel):
    session_id: uuid.UUID
    answer: str
    sources: list[uuid.UUID]
    user_message: MessageOut
    assistant_message: MessageOut


# ── 세션/메시지 조회용 ───────────────────────────────────
class SessionOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    term_id: uuid.UUID | None
    created_at: datetime
    last_message: str | None = None           # 마지막 메시지 미리보기

    model_config = {"from_attributes": True}


class SessionDetailOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    term_id: uuid.UUID | None
    created_at: datetime
    messages: list[MessageOut]

    model_config = {"from_attributes": True}