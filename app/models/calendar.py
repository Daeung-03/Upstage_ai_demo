import uuid
from datetime import datetime, date
from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Date, Boolean, Text, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base
from app.models.enums import EventType, NotificationStatus


class CalendarEvent(Base):
    __tablename__ = "calendar_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    term_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("terms.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    event_type: Mapped[EventType] = mapped_column(
        SAEnum(EventType, name="event_type", create_type=False),
        nullable=False
    )
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    label: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_notified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    term: Mapped["Term"] = relationship("Term", back_populates="calendar_events")
    user: Mapped["User"] = relationship("User", back_populates="calendar_events")


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    term_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("terms.id", ondelete="CASCADE"), nullable=False)
    version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("term_versions.id"), nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    diff_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[NotificationStatus] = mapped_column(
        SAEnum(NotificationStatus, name="notification_status", create_type=False),
        default=NotificationStatus.UNREAD
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship("User", back_populates="notifications")
    term: Mapped["Term"] = relationship("Term", back_populates="notifications")
    version: Mapped["TermVersion | None"] = relationship("TermVersion", back_populates="notifications")