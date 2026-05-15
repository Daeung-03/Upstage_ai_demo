import uuid
from datetime import datetime, date
from sqlalchemy import Enum as SAEnum
from sqlalchemy import String, Text, Integer, Boolean, Date, DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy import Column
from pgvector.sqlalchemy import HALFVEC
from app.database import Base
from app.models.enums import TermDomain, TermStatus, ClauseType


class Term(Base):
    __tablename__ = "terms"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    service_name: Mapped[str] = mapped_column(String, nullable=False)
    domain: Mapped[TermDomain] = mapped_column(
        SAEnum(TermDomain, name="term_domain", create_type=False),
        nullable=False
    )
    status: Mapped[TermStatus] = mapped_column(
        SAEnum(TermStatus, name="term_status", create_type=False),
        default=TermStatus.ACTIVE
    )
    file_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    subscribed_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user: Mapped["User"] = relationship("User", back_populates="terms")
    versions: Mapped[list["TermVersion"]] = relationship("TermVersion", back_populates="term", cascade="all, delete-orphan")
    chunks: Mapped[list["TermChunk"]] = relationship("TermChunk", back_populates="term", cascade="all, delete-orphan")
    calendar_events: Mapped[list["CalendarEvent"]] = relationship("CalendarEvent", back_populates="term", cascade="all, delete-orphan")
    notifications: Mapped[list["Notification"]] = relationship("Notification", back_populates="term", cascade="all, delete-orphan")
    chat_sessions: Mapped[list["ChatSession"]] = relationship("ChatSession", back_populates="term")


class TermVersion(Base):
    __tablename__ = "term_versions"
    __table_args__ = (UniqueConstraint("term_id", "version"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    term_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("terms.id", ondelete="CASCADE"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    diff_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_latest: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    term: Mapped["Term"] = relationship("Term", back_populates="versions")
    chunks: Mapped[list["TermChunk"]] = relationship("TermChunk", back_populates="version", cascade="all, delete-orphan")
    clauses: Mapped[list["TermClause"]] = relationship("TermClause", back_populates="version", cascade="all, delete-orphan")
    notifications: Mapped[list["Notification"]] = relationship("Notification", back_populates="version")


class TermChunk(Base):
    __tablename__ = "term_chunks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    term_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("terms.id", ondelete="CASCADE"), nullable=False)
    version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("term_versions.id", ondelete="CASCADE"), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding = Column(HALFVEC(4096), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    term: Mapped["Term"] = relationship("Term", back_populates="chunks")
    version: Mapped["TermVersion"] = relationship("TermVersion", back_populates="chunks")


class TermClause(Base):
    __tablename__ = "term_clauses"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("term_versions.id", ondelete="CASCADE"), nullable=False)
    clause_type: Mapped[ClauseType] = mapped_column(
        SAEnum(ClauseType, name="clause_type", create_type=False),
        nullable=False
    )
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    original_text: Mapped[str] = mapped_column(Text, nullable=False)
    plain_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # bbox: PDF 좌표 [x1, y1, x2, y2] (0-1 정규화). PDF가 아니거나 매칭 실패 시 NULL.
    bbox: Mapped[list[float] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    version: Mapped["TermVersion"] = relationship("TermVersion", back_populates="clauses")

