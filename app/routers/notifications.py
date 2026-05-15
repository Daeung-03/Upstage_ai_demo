from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.database import get_db
from app.models.calendar import Notification, NotificationStatus
from app.schemas.notification import NotificationResponse, NotificationListResponse

router = APIRouter()


@router.get("", response_model=NotificationListResponse)
async def get_notifications(
    # TODO: Replace user_id query param with authenticated principal when JWT auth is in place.
    user_id: UUID = Query(..., description="조회할 사용자 UUID"),
    status: NotificationStatus | None = Query(None, description="UNREAD / READ 필터"),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(Notification)
        .where(Notification.user_id == user_id)
        .order_by(
            # UNREAD 먼저, 그 다음 최신순
            Notification.status.desc(),  # 문자열 정렬 기준으로 UNREAD가 READ보다 뒤이므로 DESC로 UNREAD 우선
            Notification.created_at.desc(),
        )
    )
    if status:
        stmt = stmt.where(Notification.status == status)

    result = await db.execute(stmt)
    notifications = result.scalars().all()

    unread_stmt = select(func.count()).where(
        Notification.user_id == user_id,
        Notification.status == NotificationStatus.UNREAD,
    )
    unread_count = (await db.execute(unread_stmt)).scalar_one()

    return NotificationListResponse(
        notifications=notifications,
        unread_count=unread_count,
    )


@router.patch("/{notification_id}/read", response_model=NotificationResponse)
async def mark_as_read(
    notification_id: UUID,
    # TODO: Replace user_id query param with authenticated principal when JWT auth is in place.
    user_id: UUID = Query(..., description="요청 사용자 UUID"),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Notification).where(
        Notification.id == notification_id,
        Notification.user_id == user_id,
    )
    result = await db.execute(stmt)
    notification = result.scalar_one_or_none()

    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")

    notification.status = NotificationStatus.READ
    await db.commit()
    await db.refresh(notification)
    return notification