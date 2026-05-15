"""DisputeCase ORM — 실제 분쟁 사례 (한소원/공정위/언론) 저장.

매칭 알고리즘:
1. KeyClause/flag → embedding-query 호출
2. pgvector cosine top-K
3. pain_point_ids / unfair_flags / domain 교집합 boost
4. threshold 컷 → top-N 반환
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import HALFVEC

from app.database import Base


class DisputeCase(Base):
    __tablename__ = "dispute_cases"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    external_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # PostgreSQL TEXT[] — 비어있어도 빈 list (NULL X) 로 유지
    pain_point_ids: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list
    )
    unfair_flags: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list
    )

    domain: Mapped[str] = mapped_column(Text, nullable=False, default="ALL")

    # 임베딩 — 인덱싱 실패 또는 indexer 미실행 시 NULL 가능
    embedding = Column(HALFVEC(4096), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
