"""Dispute matching 서비스.

이 모듈의 두 진입점:
- `upsert_dispute_cases(db, cases)` — fixture indexer / 향후 크롤러가 호출.
- `find_similar_disputes(...)` — 라우터가 호출 (Task 6 에서 구현).
"""

from __future__ import annotations

import uuid
from typing import TypedDict

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ai.schemas.flag_canonical import flag_canonical
from app.models.dispute import DisputeCase


# ── Public input shape (source-agnostic) ────────────────────────


class DisputeCaseInput(TypedDict, total=False):
    external_id: str | None
    title: str
    summary: str
    outcome: str
    source: str
    source_url: str | None
    pain_point_ids: list[str]
    unfair_flags: list[str]
    domain: str  # OTT/FINANCE/AI/ALL
    # embedding 은 indexer 가 채워서 직접 update 호출 — input 에는 없음


# ── Helpers ─────────────────────────────────────────────────────


def _canonical_flags(flags: list[str]) -> list[str]:
    """unfair_flag 리스트를 canonical 정렬·dedupe."""
    seen: dict[str, None] = {}
    for f in flags or []:
        if not f:
            continue
        c = flag_canonical(f)
        if c and c not in seen:
            seen[c] = None
    return list(seen.keys())


def _normalize_pain_points(ids: list[str | None]) -> list[str]:
    """pain_point id 대소문자/공백 정규화."""
    out: list[str] = []
    for x in ids or []:
        if not x:
            continue
        s = x.strip().upper()
        if s:
            out.append(s)
    return out


def _normalize_input(case: DisputeCaseInput) -> dict:
    return {
        "external_id": case.get("external_id") or None,
        "title": case["title"],
        "summary": case["summary"],
        "outcome": case["outcome"],
        "source": case["source"],
        "source_url": case.get("source_url") or None,
        "pain_point_ids": _normalize_pain_points(case.get("pain_point_ids", [])),
        "unfair_flags": _canonical_flags(case.get("unfair_flags", [])),
        "domain": (case.get("domain") or "ALL").upper(),
    }


# ── Upsert ──────────────────────────────────────────────────────


async def upsert_dispute_cases(
    db: AsyncSession,
    cases: list[DisputeCaseInput],
) -> list[uuid.UUID]:
    """source-agnostic 적재. external_id 가 있으면 upsert, 없으면 insert.

    반환: 적재된 row id 리스트 (외부 indexer 가 embedding 업데이트 시 사용).
    """
    if not cases:
        return []

    inserted_ids: list[uuid.UUID] = []
    for raw in cases:
        norm = _normalize_input(raw)
        if norm["external_id"]:
            # PostgreSQL ON CONFLICT (external_id) DO UPDATE
            stmt = (
                insert(DisputeCase)
                .values(**norm)
                .on_conflict_do_update(
                    index_elements=[DisputeCase.external_id],
                    set_={
                        "title": norm["title"],
                        "summary": norm["summary"],
                        "outcome": norm["outcome"],
                        "source": norm["source"],
                        "source_url": norm["source_url"],
                        "pain_point_ids": norm["pain_point_ids"],
                        "unfair_flags": norm["unfair_flags"],
                        "domain": norm["domain"],
                    },
                )
                .returning(DisputeCase.id)
            )
            result = await db.execute(stmt)
            row_id = result.scalar_one()
        else:
            obj = DisputeCase(**norm)
            db.add(obj)
            await db.flush()
            row_id = obj.id
        inserted_ids.append(row_id)
    return inserted_ids


async def set_dispute_embedding(
    db: AsyncSession,
    case_id: uuid.UUID,
    embedding: list[float],
) -> None:
    """indexer 가 embed 호출 후 따로 update."""
    obj = await db.get(DisputeCase, case_id)
    if obj is None:
        raise ValueError(f"DisputeCase {case_id} not found")
    obj.embedding = embedding
    await db.flush()
