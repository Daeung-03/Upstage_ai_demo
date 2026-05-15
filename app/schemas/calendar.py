from __future__ import annotations
from uuid import UUID
from datetime import date
from pydantic import BaseModel
from app.models.enums import EventType


class CalendarEventResponse(BaseModel):
    id: UUID
    term_id: UUID
    user_id: UUID
    event_type: EventType
    event_date: date
    label: str | None
    is_notified: bool

    model_config = {"from_attributes": True}


class CalendarMonthResponse(BaseModel):
    month: str          # "YYYY-MM"
    events: list[CalendarEventResponse]