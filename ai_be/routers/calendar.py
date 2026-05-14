from __future__ import annotations
from uuid import UUID
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.calendar import CalendarMonthResponse
from app.services.calendar_service import get_calendar_events

router = APIRouter(tags=["calendar"])


@router.get("", response_model=CalendarMonthResponse)
async def list_calendar_events(
    user_id: UUID = Query(..., description="조회할 사용자 UUID"),
    month: str = Query(..., description="조회 월 (YYYY-MM 형식), 예: 2026-05"),
    db: AsyncSession = Depends(get_db),
):
    """
    특정 월의 캘린더 이벤트 목록 반환.
    month 파라미터가 YYYY-MM 형식인지 검증.
    """
    # 형식 검증
    try:
        year, mon = month.split("-")
        assert len(year) == 4 and len(mon) == 2
        int(year); int(mon)
    except Exception:
        raise HTTPException(status_code=422, detail="month 형식은 YYYY-MM 이어야 합니다.")

    events = await get_calendar_events(db, user_id=user_id, month=month)
    return CalendarMonthResponse(month=month, events=events)