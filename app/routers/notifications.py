from uuid import UUID

from fastapi import APIRouter, Depends, Query, status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.calendar import NotificationStatus
from app.schemas.notification import (
    MarkAllReadResponse,
    NotificationListResponse,
    NotificationResponse,
)
from app.services import notification_service

router = APIRouter()


@router.get("", response_model=NotificationListResponse)
async def get_notifications(
    # TODO: Replace user_id query param with authenticated principal when JWT auth is in place.
    user_id: UUID = Query(..., description="조회할 사용자 UUID"),
    status: NotificationStatus | None = Query(None, description="UNREAD / READ 필터"),
    db: AsyncSession = Depends(get_db),
):
    notifications, unread_count = await notification_service.list_notifications(
        db, user_id=user_id, status=status,
    )
    return NotificationListResponse(
        notifications=notifications,
        unread_count=unread_count,
    )


@router.patch("/read-all", response_model=MarkAllReadResponse)
async def mark_all_read(
    user_id: UUID = Query(..., description="요청 사용자 UUID"),
    db: AsyncSession = Depends(get_db),
):
    """UNREAD 알림 일괄 READ — 벨 아이콘 비우기."""
    updated = await notification_service.mark_all_as_read(db, user_id=user_id)
    return MarkAllReadResponse(updated=updated)


@router.patch("/{notification_id}/read", response_model=NotificationResponse)
async def mark_as_read(
    notification_id: UUID,
    user_id: UUID = Query(..., description="요청 사용자 UUID"),
    db: AsyncSession = Depends(get_db),
):
    return await notification_service.mark_as_read(
        db, notification_id=notification_id, user_id=user_id,
    )


@router.delete("/{notification_id}", status_code=http_status.HTTP_204_NO_CONTENT)
async def delete_notification(
    notification_id: UUID,
    user_id: UUID = Query(..., description="요청 사용자 UUID"),
    db: AsyncSession = Depends(get_db),
):
    await notification_service.delete_notification(
        db, notification_id=notification_id, user_id=user_id,
    )
    return None
