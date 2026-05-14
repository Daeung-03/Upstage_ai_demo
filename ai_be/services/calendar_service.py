from __future__ import annotations
from uuid import UUID
from datetime import date
from calendar import monthrange

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.calendar import CalendarEvent


async def get_calendar_events(
    db: AsyncSession,
    user_id: UUID,
    month: str,          # "YYYY-MM"
) -> list[CalendarEvent]:
    year, mon = map(int, month.split("-"))
    start = date(year, mon, 1)
    end = date(year, mon, monthrange(year, mon)[1])

    result = await db.execute(
        select(CalendarEvent)
        .where(
            CalendarEvent.user_id == user_id,
            CalendarEvent.event_date >= start,
            CalendarEvent.event_date <= end,
        )
        .order_by(CalendarEvent.event_date)
    )
    return result.scalars().all()