# app/main.py
from fastapi import FastAPI

# SQLAlchemy가 모든 모델을 인식하도록 명시적 import (순서 중요)
from app.models import enums  # noqa
from app.models.user import User  # noqa
from app.models.term import Term, TermVersion, TermChunk, TermClause  # noqa
from app.models.calendar import CalendarEvent, Notification  # noqa
from app.models.chat import ChatSession, ChatMessage  # noqa
from app.models.dispute import DisputeCase  # noqa

from app.routers import terms, chat, calendar, notifications

app = FastAPI(title="Term Tracker API", version="0.1.0")

app.include_router(terms.router,         prefix="/terms",         tags=["Terms"])
app.include_router(chat.router,          prefix="/chat",          tags=["Chat"])
app.include_router(calendar.router,      prefix="/calendar",      tags=["Calendar"])
app.include_router(notifications.router, prefix="/notifications", tags=["Notifications"])

@app.get("/health")
async def health_check():
    return {"status": "ok"}