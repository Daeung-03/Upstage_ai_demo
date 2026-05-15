"""알림 도메인 비즈니스 로직 — 라우터는 HTTP 매핑만, 쿼리/상태 변경은 여기서.

`/notifications/...` 엔드포인트가 호출하는 함수들. 모든 함수는 user_id 로 row
ownership 을 강제해 다른 사용자의 알림을 건드릴 수 없게 한다.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.calendar import Notification, NotificationStatus


async def list_notifications(
    db: AsyncSession,
    user_id: UUID,
    status: NotificationStatus | None = None,
) -> tuple[list[Notification], int]:
    """사용자의 알림 목록 + UNREAD 카운트 반환.

    정렬: UNREAD 우선 → 최신순. status 필터가 주어지면 그 status 만.
    UNREAD 카운트는 status 필터와 무관하게 항상 전체 기준 (벨 뱃지용).
    """
    stmt = (
        select(Notification)
        .where(Notification.user_id == user_id)
        .order_by(
            # 'UNREAD' > 'READ' 문자열 정렬 → DESC 로 UNREAD 가 위로 옴.
            Notification.status.desc(),
            Notification.created_at.desc(),
        )
    )
    if status is not None:
        stmt = stmt.where(Notification.status == status)
    rows = (await db.execute(stmt)).scalars().all()

    unread_count = (
        await db.execute(
            select(func.count()).where(
                Notification.user_id == user_id,
                Notification.status == NotificationStatus.UNREAD,
            )
        )
    ).scalar_one()
    return list(rows), unread_count


async def _get_owned(
    db: AsyncSession, notification_id: UUID, user_id: UUID
) -> Notification:
    row = (
        await db.execute(
            select(Notification).where(
                Notification.id == notification_id,
                Notification.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    return row


async def mark_as_read(
    db: AsyncSession, notification_id: UUID, user_id: UUID
) -> Notification:
    notif = await _get_owned(db, notification_id, user_id)
    if notif.status != NotificationStatus.READ:
        notif.status = NotificationStatus.READ
        await db.commit()
        await db.refresh(notif)
    return notif


async def mark_all_as_read(db: AsyncSession, user_id: UUID) -> int:
    """user 의 모든 UNREAD 알림을 READ 로. 변경된 row 수 반환 (벨 비우기 응답용)."""
    result = await db.execute(
        update(Notification)
        .where(
            Notification.user_id == user_id,
            Notification.status == NotificationStatus.UNREAD,
        )
        .values(status=NotificationStatus.READ)
    )
    await db.commit()
    return result.rowcount or 0


async def delete_notification(
    db: AsyncSession, notification_id: UUID, user_id: UUID
) -> None:
    """단건 삭제. 다른 사용자 알림은 404."""
    # ownership 강제: where 절에 user_id 포함하여 rowcount 로 확인.
    result = await db.execute(
        delete(Notification).where(
            Notification.id == notification_id,
            Notification.user_id == user_id,
        )
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Notification not found")
    await db.commit()
