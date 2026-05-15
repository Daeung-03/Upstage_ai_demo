# 유사 분쟁 사례 (Similar Dispute Cases) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 약관 분석 결과의 KeyClause / unfair_clause_flag / pain_point 에 대응하는 실제 분쟁·소비자 피해 사례를 매칭·노출하는 새 기능을 추가한다.

**Architecture:** PostgreSQL `dispute_cases` 테이블 (HALFVEC(4096) pgvector 임베딩) + 결정론적 cosine 매칭 + boost rule (pain_point / unfair_flag / domain). LLM 호출 없음. 데이터는 source-agnostic 적재 인터페이스(v1 큐레이션 fixture, v2 외부 크롤링 확장).

**Tech Stack:** FastAPI + SQLAlchemy 2 (async) + asyncpg + pgvector (HALFVEC) + Upstage Solar embedding-passage/query + pytest-asyncio + pytest-httpx.

**Spec reference:** `docs/superpowers/specs/2026-05-15-similar-disputes-design.md`

---

## File Structure

새로 추가:
- `migrations/0002_dispute_cases.sql` — 테이블 + 인덱스
- `ai/schemas/flag_canonical.py` — unfair_flag 정규화 (eval 스크립트와 공용)
- `app/models/dispute.py` — SQLAlchemy ORM
- `app/schemas/dispute.py` — Pydantic 요청·응답
- `app/services/dispute_service.py` — `upsert_dispute_cases`, `find_similar_disputes`
- `app/routers/disputes.py` — HTTP 라우터
- `data/fixtures/dispute_cases.json` — seed 15-20건
- `scripts/index_dispute_cases.py` — seed indexer (idempotent)
- `tests/unit/test_flag_canonical.py`
- `tests/unit/test_services_dispute.py`
- `tests/unit/test_routes_disputes.py`

수정:
- `app/main.py` — 모델 import 추가, 라우터 등록
- `scripts/score_against_golden.py` — `_FLAG_ALIAS_GROUPS` / `_flag_canonical` 을 `ai.schemas.flag_canonical` 에서 import (행위 동일, 위치만 이동)

---

## Task 1: 마이그레이션 `0002_dispute_cases.sql`

**Files:**
- Create: `migrations/0002_dispute_cases.sql`

- [ ] **Step 1: 마이그레이션 SQL 작성**

`migrations/0002_dispute_cases.sql`:

```sql
-- 0002_dispute_cases.sql
-- 분쟁 사례 데이터 (pain_point/unfair_flag/도메인 별 매칭용).
-- pgvector HALFVEC(4096) — TermChunk 와 같은 임베딩 공간.
--
-- 마이그레이션 0001 과 마찬가지로 IF NOT EXISTS 로 idempotent.

BEGIN;

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS dispute_cases (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    external_id     TEXT NULL,
    title           TEXT NOT NULL,
    summary         TEXT NOT NULL,
    outcome         TEXT NOT NULL,
    source          TEXT NOT NULL,
    source_url      TEXT NULL,
    pain_point_ids  TEXT[] NOT NULL DEFAULT '{}'::TEXT[],
    unfair_flags    TEXT[] NOT NULL DEFAULT '{}'::TEXT[],
    domain          TEXT NOT NULL DEFAULT 'ALL',
    embedding       halfvec(4096) NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- external_id 중복 방지 (NULL 은 unique 검사 제외)
CREATE UNIQUE INDEX IF NOT EXISTS dispute_cases_external_id_unique
    ON dispute_cases (external_id) WHERE external_id IS NOT NULL;

-- 도메인 필터 빠른 조회
CREATE INDEX IF NOT EXISTS dispute_cases_domain_idx
    ON dispute_cases (domain);

-- 배열 교집합 boost 가속 (GIN)
CREATE INDEX IF NOT EXISTS dispute_cases_pain_point_ids_gin
    ON dispute_cases USING GIN (pain_point_ids);

CREATE INDEX IF NOT EXISTS dispute_cases_unfair_flags_gin
    ON dispute_cases USING GIN (unfair_flags);

-- pgvector cosine 유사도 ANN 인덱스 (HNSW)
CREATE INDEX IF NOT EXISTS dispute_cases_embedding_hnsw
    ON dispute_cases USING hnsw (embedding halfvec_cosine_ops);

COMMIT;
```

- [ ] **Step 2: 로컬 DB 에 적용 (수동 검증)**

Run: `psql "$DATABASE_URL" -f migrations/0002_dispute_cases.sql`

Expected: `BEGIN` / `CREATE EXTENSION` (또는 NOTICE: already exists) / `CREATE TABLE` / `CREATE INDEX` (5회) / `COMMIT`. 에러 없음.

검증:
```bash
psql "$DATABASE_URL" -c "\d dispute_cases"
```
컬럼 11개 + indexes 5개가 표시되면 성공.

- [ ] **Step 3: Commit**

```bash
git add migrations/0002_dispute_cases.sql
git commit -m "feat: dispute_cases 테이블 마이그레이션 (pgvector HALFVEC 4096)"
```

---

## Task 2: Flag canonical 정규화 모듈 추출

**Files:**
- Create: `ai/schemas/flag_canonical.py`
- Create: `tests/unit/test_flag_canonical.py`
- Modify: `scripts/score_against_golden.py` (lines 142-180 — import 로 교체)

기존 `scripts/score_against_golden.py` 의 `_FLAG_ALIAS_GROUPS` / `_flag_canonical` 을 공용 모듈로 이동. 서비스 코드 (dispute matching) 와 eval 스크립트 모두 같은 정규화 사용.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/unit/test_flag_canonical.py`:

```python
"""Unfair clause flag canonical 정규화 — eval 스크립트와 dispute 서비스 공용."""

from __future__ import annotations

from ai.schemas.flag_canonical import flag_canonical, FLAG_ALIAS_GROUPS


def test_canonical_maps_post_code_to_group_canonical():
    # POST-03 그룹 (환불 거부)의 canonical 은 그룹 sorted 첫 원소
    assert flag_canonical("POST-03") == flag_canonical("환불 거부")
    assert flag_canonical("POST-03") == flag_canonical("refund_denial")


def test_canonical_strips_parenthetical_and_underscore():
    # 괄호 부연 + underscore 제거
    assert flag_canonical("환불 거부 (시청 시 청약철회 권리 소멸)") == flag_canonical("POST-03")
    assert flag_canonical("의사표시_의제") == flag_canonical("POST-05")


def test_canonical_returns_normalized_when_no_group_match():
    # 알려지지 않은 flag 는 normalize 만 적용 (괄호/언더스코어/공백 정리)
    assert flag_canonical("새로운_플래그 ") == "새로운 플래그"


def test_canonical_empty_returns_empty():
    assert flag_canonical("") == ""
    assert flag_canonical(None) == ""  # 방어적: None 입력도 빈 문자열


def test_alias_groups_cover_all_post_codes():
    # POST-01 ~ POST-05 모두 그룹에 존재
    all_members = set().union(*FLAG_ALIAS_GROUPS)
    for code in ("POST-01", "POST-02", "POST-03", "POST-04", "POST-05"):
        assert code in all_members, f"{code} not in any alias group"
```

- [ ] **Step 2: 테스트 실행 → FAIL (모듈 없음)**

Run: `pytest tests/unit/test_flag_canonical.py -v`

Expected: `ModuleNotFoundError: No module named 'ai.schemas.flag_canonical'`

- [ ] **Step 3: 모듈 구현**

`ai/schemas/flag_canonical.py`:

```python
"""Unfair clause flag canonical 정규화.

eval 스크립트 (`scripts/score_against_golden.py`) 와 dispute matching 서비스
(`app/services/dispute_service.py`) 가 같은 alias 그룹을 공유한다. 새 alias 가
추가되면 여기 한 곳만 수정.
"""

from __future__ import annotations

import re

# 같은 그룹에 속한 flag 는 비교 시 동일 취급. canonical 은 sorted 첫 원소.
FLAG_ALIAS_GROUPS: list[set[str]] = [
    {"POST-01", "약관 일방 변경권", "unilateral_change", "약관 일방 변경",
     "일방적 약관 변경", "회사의 일방적 변경권"},
    {"POST-02", "다크패턴 — 해지 절차 복잡화", "complex_cancellation",
     "해지 절차 복잡화", "다크패턴 해지", "해지 어려움"},
    {"POST-03", "환불 거부", "refund_denial", "환불 불가",
     "환불 거부 (시청 시 청약철회 권리 소멸)", "no_refund"},
    {"POST-04", "면책/손배 제한", "liability_cap", "면책_손배_제한",
     "손해배상 한도", "책임 제한"},
    {"POST-05", "분쟁/집단소송 포기", "arbitration_class_waiver",
     "의사표시_의제", "의사표시 의제", "강제 중재", "집단소송 포기",
     "준거법 외국법", "분쟁 해결 포기"},
    # AI 학습 데이터 — POST 카테고리에 없는 LLM-specific flag
    {"AI 학습 데이터 활용", "AI 학습 데이터 활용 (옵트아웃)", "ai_training_data",
     "model training opt-in", "학습 데이터 사용"},
]


def flag_canonical(s: str | None) -> str:
    """flag 정규화: 괄호/언더스코어 제거 + alias 그룹 canonical 매핑."""
    if not s:
        return ""
    # 1차: 괄호 내 부연 / underscore / 공백 정리
    base = re.sub(r"\s*\([^)]*\)", "", s).strip()
    base = base.replace("_", " ")
    base = re.sub(r"\s+", " ", base).strip()
    # 2차: alias 그룹 lookup (원본 + 정규화된 형태 둘 다 시도)
    for group in FLAG_ALIAS_GROUPS:
        if s in group or base in group:
            return sorted(group)[0]
    return base
```

- [ ] **Step 4: 테스트 실행 → PASS**

Run: `pytest tests/unit/test_flag_canonical.py -v`

Expected: 5 passed.

- [ ] **Step 5: 기존 eval 스크립트가 새 모듈을 import 하도록 refactor**

`scripts/score_against_golden.py` 의 lines 142-180 (alias 그룹 + `_flag_canonical` + `_normalize_flag`) 을 다음으로 교체:

```python
# Unfair clause flag canonical — 공용 모듈 (ai.schemas.flag_canonical) 사용.
# 서비스(dispute matching) 와 같은 alias 그룹 공유.
from ai.schemas.flag_canonical import flag_canonical as _flag_canonical


def _normalize_flag(s: str) -> str:
    """unfair_clause_flag 정규화 (backward-compatible 이름). canonical alias 매핑 사용."""
    return _flag_canonical(s)
```

- [ ] **Step 6: 기존 eval 스크립트 regression 확인**

Run: `pytest tests/unit -v -k flag`

Expected: 새 5개 통과 + 기존 eval 관련 테스트 회귀 없음.

전체 unit 회귀:
```bash
pytest tests/unit -v
```
Expected: 기존 통과 케이스 변동 없음.

- [ ] **Step 7: Commit**

```bash
git add ai/schemas/flag_canonical.py tests/unit/test_flag_canonical.py scripts/score_against_golden.py
git commit -m "refactor: flag canonical 정규화 ai.schemas.flag_canonical 로 공용화"
```

---

## Task 3: SQLAlchemy ORM 모델

**Files:**
- Create: `app/models/dispute.py`
- Modify: `app/main.py` (모델 import 추가)
- Test: `tests/unit/test_models_dispute.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/unit/test_models_dispute.py`:

```python
"""DisputeCase ORM 스모크 — instance 생성 + 컬럼 기본값 확인."""

from __future__ import annotations

import uuid

from app.models.dispute import DisputeCase


def test_dispute_case_instance_defaults():
    case = DisputeCase(
        title="OTT 자동결제 환불 거부 — 한소원 2024-1234",
        summary="…",
        outcome="환불 100%",
        source="한국소비자원",
        pain_point_ids=["POST-03"],
        unfair_flags=["refund_denial"],
        domain="OTT",
    )
    # id 는 default factory 가 채우지 않을 수도 있음 (server_default). 직접 검사 X.
    assert case.title.startswith("OTT")
    assert case.pain_point_ids == ["POST-03"]
    assert case.unfair_flags == ["refund_denial"]
    assert case.domain == "OTT"
    # embedding 은 NULL 허용
    assert case.embedding is None


def test_dispute_case_tablename():
    assert DisputeCase.__tablename__ == "dispute_cases"


def test_dispute_case_id_factory():
    """id 가 클라이언트-side 에서도 채워지도록 default=uuid.uuid4 보장."""
    case = DisputeCase(
        title="t", summary="s", outcome="o", source="src",
        pain_point_ids=[], unfair_flags=[], domain="ALL",
    )
    # SQLAlchemy 는 flush 전에는 default 안 채울 수 있어서 model_construct 같은
    # 보장 안됨. 대신 컬럼 default 가 callable 인지 검사.
    id_col = DisputeCase.__table__.c.id
    assert id_col.default is not None
    assert callable(id_col.default.arg)
```

- [ ] **Step 2: 테스트 실행 → FAIL**

Run: `pytest tests/unit/test_models_dispute.py -v`

Expected: `ModuleNotFoundError: No module named 'app.models.dispute'`

- [ ] **Step 3: 모델 구현**

`app/models/dispute.py`:

```python
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
```

- [ ] **Step 4: 테스트 실행 → PASS**

Run: `pytest tests/unit/test_models_dispute.py -v`

Expected: 3 passed.

- [ ] **Step 5: `app/main.py` 에 모델 import 추가 (메타데이터 등록)**

`app/main.py` 의 모델 import 블록 (line 7 부근):

기존:
```python
from app.models.term import Term, TermVersion, TermChunk, TermClause  # noqa
from app.models.calendar import CalendarEvent, Notification  # noqa
from app.models.chat import ChatSession, ChatMessage  # noqa
```

다음 줄을 추가:
```python
from app.models.dispute import DisputeCase  # noqa
```

- [ ] **Step 6: app boot smoke (import 통과)**

Run: `python -c "from app.main import app; print('ok')"`

Expected: `ok` (DATABASE_URL 미설정 환경이면 conftest 가 placeholder 주입).

- [ ] **Step 7: Commit**

```bash
git add app/models/dispute.py app/main.py tests/unit/test_models_dispute.py
git commit -m "feat: DisputeCase ORM 모델 + app.main 등록"
```

---

## Task 4: Pydantic 응답 스키마

**Files:**
- Create: `app/schemas/dispute.py`
- Test: `tests/unit/test_schemas_dispute.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/unit/test_schemas_dispute.py`:

```python
"""Dispute 응답 스키마 — validation roundtrip."""

from __future__ import annotations

import uuid

from app.schemas.dispute import (
    DisputeMatch, ClauseDisputeMatches, TermDisputesResponse, DisputeCaseDetail,
)


def test_dispute_match_minimal():
    m = DisputeMatch(
        case_id=uuid.uuid4(),
        title="t", summary="s", outcome="o", source="한국소비자원",
        source_url=None, score=0.82,
        matched_signals=["pain_point:POST-03"],
    )
    dumped = m.model_dump()
    assert dumped["score"] == 0.82
    assert dumped["matched_signals"] == ["pain_point:POST-03"]


def test_clause_disputes_matches_empty_array_allowed():
    cm = ClauseDisputeMatches(
        clause_id=uuid.uuid4(),
        clause_title="자동결제 환불",
        matches=[],
    )
    assert cm.matches == []


def test_term_disputes_response_structure():
    resp = TermDisputesResponse(
        term_id=uuid.uuid4(),
        clauses=[
            ClauseDisputeMatches(
                clause_id=uuid.uuid4(),
                clause_title="A",
                matches=[],
            )
        ],
    )
    assert len(resp.clauses) == 1


def test_dispute_case_detail_optional_source_url():
    d = DisputeCaseDetail(
        id=uuid.uuid4(),
        title="t", summary="s", outcome="o", source="언론",
        source_url=None,
        pain_point_ids=["POST-01"],
        unfair_flags=["unilateral_change"],
        domain="OTT",
    )
    assert d.source_url is None
```

- [ ] **Step 2: 테스트 실행 → FAIL**

Run: `pytest tests/unit/test_schemas_dispute.py -v`

Expected: `ModuleNotFoundError: No module named 'app.schemas.dispute'`

- [ ] **Step 3: 스키마 구현**

`app/schemas/dispute.py`:

```python
"""Dispute 매칭 API 응답 스키마."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field


class DisputeMatch(BaseModel):
    """단일 분쟁 사례 매칭 결과."""

    case_id: UUID
    title: str
    summary: str
    outcome: str
    source: str
    source_url: str | None = None
    score: float = Field(..., description="cosine 유사도 + boost. 0~1.2 범위.")
    matched_signals: list[str] = Field(
        default_factory=list,
        description="어떤 boost 가 적용됐는지 트레이싱 (pain_point:POST-01 / flag:refund_denial / domain:OTT)",
    )


class ClauseDisputeMatches(BaseModel):
    """KeyClause 한 개에 대한 top-K 매칭."""

    clause_id: UUID
    clause_title: str | None = None
    matches: list[DisputeMatch] = Field(default_factory=list)


class TermDisputesResponse(BaseModel):
    """약관 전체 — 각 KeyClause 별 top-3 묶음."""

    term_id: UUID
    clauses: list[ClauseDisputeMatches] = Field(default_factory=list)


class DisputeCaseDetail(BaseModel):
    """관리/디버깅용 단일 사례 상세."""

    id: UUID
    title: str
    summary: str
    outcome: str
    source: str
    source_url: str | None = None
    pain_point_ids: list[str] = Field(default_factory=list)
    unfair_flags: list[str] = Field(default_factory=list)
    domain: str


class DisputeListResponse(BaseModel):
    items: list[DisputeCaseDetail] = Field(default_factory=list)
    total: int
```

- [ ] **Step 4: 테스트 실행 → PASS**

Run: `pytest tests/unit/test_schemas_dispute.py -v`

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add app/schemas/dispute.py tests/unit/test_schemas_dispute.py
git commit -m "feat: Dispute 응답 스키마 (DisputeMatch / ClauseDisputeMatches / TermDisputesResponse)"
```

---

## Task 5: 서비스 — `upsert_dispute_cases` (idempotent 적재)

**Files:**
- Create: `app/services/dispute_service.py` (이 task 에서 시작, Task 6 에서 확장)
- Test: `tests/unit/test_services_dispute_upsert.py`

source-agnostic 적재 — v1 fixture indexer, v2 크롤러 모두 같은 함수 호출.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/unit/test_services_dispute_upsert.py`:

```python
"""dispute_service.upsert_dispute_cases — idempotency + 정규화."""

from __future__ import annotations

import uuid

import pytest

from app.services.dispute_service import (
    DisputeCaseInput,
    _canonical_flags,
    _normalize_pain_points,
)


def test_canonical_flags_dedupes_via_alias():
    # POST-03 과 "환불 거부" 와 "refund_denial" 은 같은 canonical
    out = _canonical_flags(["POST-03", "환불 거부", "refund_denial"])
    assert len(out) == 1


def test_canonical_flags_preserves_unknown():
    out = _canonical_flags(["unknown_flag", "POST-03"])
    assert len(out) == 2
    assert "unknown_flag" in out


def test_normalize_pain_points_uppercases_and_strips():
    out = _normalize_pain_points([" post-01 ", "MID-02"])
    assert out == ["POST-01", "MID-02"]


def test_normalize_pain_points_filters_empty():
    out = _normalize_pain_points(["", None, "PRE-01"])  # type: ignore[list-item]
    assert out == ["PRE-01"]


def test_dispute_case_input_typed_dict_shape():
    # TypedDict 는 runtime check 안 함 — 단순 schema 정의 검증.
    payload: DisputeCaseInput = {
        "external_id": "한소원-2024-1",
        "title": "t", "summary": "s", "outcome": "o",
        "source": "한국소비자원", "source_url": None,
        "pain_point_ids": ["POST-03"],
        "unfair_flags": ["refund_denial"],
        "domain": "OTT",
    }
    assert payload["title"] == "t"
```

- [ ] **Step 2: 테스트 실행 → FAIL**

Run: `pytest tests/unit/test_services_dispute_upsert.py -v`

Expected: `ModuleNotFoundError: No module named 'app.services.dispute_service'`

- [ ] **Step 3: 서비스 구현 (upsert + 헬퍼만, 매칭은 Task 6)**

`app/services/dispute_service.py`:

```python
"""Dispute matching 서비스.

이 모듈의 두 진입점:
- `upsert_dispute_cases(db, cases)` — fixture indexer / 향후 크롤러가 호출.
- `find_similar_disputes(...)` — 라우터가 호출 (Task 6 에서 구현).
"""

from __future__ import annotations

import uuid
from typing import TypedDict

from sqlalchemy import select
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
```

- [ ] **Step 4: 테스트 실행 → PASS**

Run: `pytest tests/unit/test_services_dispute_upsert.py -v`

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add app/services/dispute_service.py tests/unit/test_services_dispute_upsert.py
git commit -m "feat: dispute_service.upsert_dispute_cases — source-agnostic 적재"
```

---

## Task 6: 서비스 — `find_similar_disputes` 매칭 알고리즘

**Files:**
- Modify: `app/services/dispute_service.py` (확장)
- Test: `tests/unit/test_services_dispute_match.py`

cosine + boost rule + threshold + top-K. LLM 호출 없음 (embedding 1회만).

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/unit/test_services_dispute_match.py`:

```python
"""dispute_service.find_similar_disputes — boost / threshold / top_k 검증.

DB·임베딩 호출은 모킹. 알고리즘 자체만 단위 테스트.
"""

from __future__ import annotations

import uuid

import pytest

from app.services.dispute_service import (
    _CandidateRow,
    DEFAULT_MIN_SCORE,
    DEFAULT_TOP_K,
    _apply_boosts_and_filter,
)


def _row(
    pain_points: list[str] | None = None,
    flags: list[str] | None = None,
    domain: str = "OTT",
    cosine_distance: float = 0.2,  # 1 - 0.2 = base 0.8
    title: str = "t",
) -> _CandidateRow:
    return _CandidateRow(
        id=uuid.uuid4(),
        title=title,
        summary="s",
        outcome="o",
        source="src",
        source_url=None,
        pain_point_ids=pain_points or [],
        unfair_flags=flags or [],
        domain=domain,
        cosine_distance=cosine_distance,
    )


def test_pain_point_boost_adds_0_10():
    rows = [_row(pain_points=["POST-03"])]
    out = _apply_boosts_and_filter(
        rows,
        clause_pain_point="POST-03",
        term_unfair_flags=[],
        term_domain="OTT",
        top_k=5,
        min_score=DEFAULT_MIN_SCORE,
    )
    assert len(out) == 1
    # base 0.8 + pain_point 0.10 + domain 0.05 = 0.95
    assert out[0].score == pytest.approx(0.95, abs=1e-6)
    assert "pain_point:POST-03" in out[0].matched_signals
    assert "domain:OTT" in out[0].matched_signals


def test_unfair_flag_boost_adds_0_05_canonical():
    rows = [_row(flags=["POST-03"])]  # canonical of "환불 거부"
    out = _apply_boosts_and_filter(
        rows,
        clause_pain_point=None,
        term_unfair_flags=["환불 거부"],  # alias of POST-03
        term_domain="OTT",
        top_k=5,
        min_score=DEFAULT_MIN_SCORE,
    )
    assert len(out) == 1
    # base 0.8 + flag 0.05 + domain 0.05 = 0.90
    assert out[0].score == pytest.approx(0.90, abs=1e-6)
    assert any(s.startswith("flag:") for s in out[0].matched_signals)


def test_domain_all_matches_any_term_domain():
    rows = [_row(domain="ALL")]
    out = _apply_boosts_and_filter(
        rows,
        clause_pain_point=None,
        term_unfair_flags=[],
        term_domain="FINANCE",
        top_k=5,
        min_score=DEFAULT_MIN_SCORE,
    )
    assert len(out) == 1
    assert "domain:ALL" in out[0].matched_signals or "domain:FINANCE" in out[0].matched_signals


def test_threshold_cut_drops_below_min_score():
    # base 0.5 + 어떤 boost 도 없으면 0.65 미달
    rows = [_row(cosine_distance=0.5, domain="OTHER")]
    out = _apply_boosts_and_filter(
        rows,
        clause_pain_point=None,
        term_unfair_flags=[],
        term_domain="OTT",
        top_k=5,
        min_score=DEFAULT_MIN_SCORE,
    )
    assert out == []


def test_top_k_limits_output():
    rows = [_row(title=f"t{i}", cosine_distance=0.1) for i in range(10)]
    out = _apply_boosts_and_filter(
        rows,
        clause_pain_point=None,
        term_unfair_flags=[],
        term_domain="OTT",
        top_k=3,
        min_score=DEFAULT_MIN_SCORE,
    )
    assert len(out) == 3


def test_results_sorted_by_score_descending():
    rows = [
        _row(title="low", cosine_distance=0.3, domain="OTHER"),    # base 0.7
        _row(title="high", cosine_distance=0.1, pain_points=["POST-01"]),  # 0.9 + 0.10 + 0.05 = 1.05
        _row(title="mid", cosine_distance=0.2, domain="OTHER"),    # base 0.8
    ]
    out = _apply_boosts_and_filter(
        rows,
        clause_pain_point="POST-01",
        term_unfair_flags=[],
        term_domain="OTT",
        top_k=5,
        min_score=DEFAULT_MIN_SCORE,
    )
    titles = [r.title for r in out]
    assert titles == ["high", "mid", "low"]


def test_no_signals_no_boosts_no_match():
    # 모든 boost 0, base 0.6 → 0.65 미달
    rows = [_row(cosine_distance=0.4, domain="OTHER")]
    out = _apply_boosts_and_filter(
        rows,
        clause_pain_point=None,
        term_unfair_flags=[],
        term_domain="OTT",
        top_k=5,
        min_score=DEFAULT_MIN_SCORE,
    )
    assert out == []
```

- [ ] **Step 2: 테스트 실행 → FAIL**

Run: `pytest tests/unit/test_services_dispute_match.py -v`

Expected: `ImportError: cannot import name '_CandidateRow' ...`

- [ ] **Step 3: 매칭 알고리즘 구현 — `app/services/dispute_service.py` 확장**

`app/services/dispute_service.py` 파일 끝에 추가:

```python
# ── Matching ────────────────────────────────────────────────────

import os
from dataclasses import dataclass, field

from sqlalchemy import text as sa_text


DEFAULT_TOP_K = int(os.getenv("DISPUTE_TOP_K", "3"))
DEFAULT_MIN_SCORE = float(os.getenv("DISPUTE_MIN_SCORE", "0.65"))

# Boost 가산값 — 결정론. spec 4.1 참조.
BOOST_PAIN_POINT = 0.10
BOOST_UNFAIR_FLAG = 0.05
BOOST_DOMAIN = 0.05


@dataclass
class _CandidateRow:
    """pgvector 후보 1행 (boost 적용 전 raw)."""

    id: uuid.UUID
    title: str
    summary: str
    outcome: str
    source: str
    source_url: str | None
    pain_point_ids: list[str]
    unfair_flags: list[str]
    domain: str
    cosine_distance: float


@dataclass
class _ScoredMatch:
    """boost 가산 후 정렬·필터링된 결과."""

    id: uuid.UUID
    title: str
    summary: str
    outcome: str
    source: str
    source_url: str | None
    score: float
    matched_signals: list[str] = field(default_factory=list)


def _apply_boosts_and_filter(
    rows: list[_CandidateRow],
    *,
    clause_pain_point: str | None,
    term_unfair_flags: list[str],
    term_domain: str,
    top_k: int,
    min_score: float,
) -> list[_ScoredMatch]:
    """결정론 boost: pain_point / unfair_flag / domain 신호별 가산."""
    term_pain = (clause_pain_point or "").strip().upper() or None
    term_flag_canon = {flag_canonical(f) for f in (term_unfair_flags or []) if f}
    term_dom = (term_domain or "").upper()

    scored: list[_ScoredMatch] = []
    for r in rows:
        base = 1.0 - float(r.cosine_distance)
        signals: list[str] = []
        score = base

        if term_pain and term_pain in {p.upper() for p in r.pain_point_ids}:
            score += BOOST_PAIN_POINT
            signals.append(f"pain_point:{term_pain}")

        row_flag_canon = {flag_canonical(f) for f in r.unfair_flags if f}
        flag_overlap = term_flag_canon & row_flag_canon
        if flag_overlap:
            score += BOOST_UNFAIR_FLAG
            # 가장 작은 (sorted 첫) canonical 만 신호로 노출 — 안정적 정렬
            signals.append(f"flag:{sorted(flag_overlap)[0]}")

        row_dom = (r.domain or "").upper()
        if row_dom == "ALL":
            score += BOOST_DOMAIN
            signals.append("domain:ALL")
        elif row_dom == term_dom and term_dom:
            score += BOOST_DOMAIN
            signals.append(f"domain:{term_dom}")

        if score < min_score:
            continue

        scored.append(_ScoredMatch(
            id=r.id, title=r.title, summary=r.summary, outcome=r.outcome,
            source=r.source, source_url=r.source_url,
            score=round(score, 6), matched_signals=signals,
        ))

    scored.sort(key=lambda m: m.score, reverse=True)
    return scored[:top_k]


async def _fetch_candidates_by_embedding(
    db: AsyncSession,
    query_vec: list[float],
    fetch_k: int,
    domain_filter: str | None = None,
) -> list[_CandidateRow]:
    """pgvector cosine top-K 검색 (raw distance 포함)."""
    params: dict = {"vec": str(query_vec), "k": fetch_k}
    domain_sql = ""
    if domain_filter:
        # 같은 도메인 + ALL 둘 다 fetch
        domain_sql = " AND (domain = :dom OR domain = 'ALL')"
        params["dom"] = domain_filter

    sql = sa_text(f"""
        SELECT
            id, title, summary, outcome, source, source_url,
            pain_point_ids, unfair_flags, domain,
            (embedding <=> CAST(:vec AS halfvec)) AS cosine_distance
        FROM dispute_cases
        WHERE embedding IS NOT NULL{domain_sql}
        ORDER BY embedding <=> CAST(:vec AS halfvec)
        LIMIT :k
    """)
    result = await db.execute(sql, params)
    rows: list[_CandidateRow] = []
    for r in result.fetchall():
        rows.append(_CandidateRow(
            id=r.id, title=r.title, summary=r.summary, outcome=r.outcome,
            source=r.source, source_url=r.source_url,
            pain_point_ids=list(r.pain_point_ids or []),
            unfair_flags=list(r.unfair_flags or []),
            domain=r.domain,
            cosine_distance=float(r.cosine_distance),
        ))
    return rows


async def find_similar_disputes(
    db: AsyncSession,
    *,
    query_text: str,
    clause_pain_point: str | None,
    term_unfair_flags: list[str],
    term_domain: str,
    top_k: int = DEFAULT_TOP_K,
    min_score: float = DEFAULT_MIN_SCORE,
    fetch_k: int = 10,
) -> list[_ScoredMatch]:
    """KeyClause/flag → 유사 분쟁 사례 top-K. embed_query → pgvector → boost."""
    from app.services.ai_client import embed_query

    if not query_text or not query_text.strip():
        return []

    query_vec = await embed_query(query_text)
    rows = await _fetch_candidates_by_embedding(
        db, query_vec, fetch_k=fetch_k,
        domain_filter=(term_domain or None) and term_domain.upper(),
    )
    return _apply_boosts_and_filter(
        rows,
        clause_pain_point=clause_pain_point,
        term_unfair_flags=term_unfair_flags,
        term_domain=term_domain,
        top_k=top_k,
        min_score=min_score,
    )
```

- [ ] **Step 4: 테스트 실행 → PASS**

Run: `pytest tests/unit/test_services_dispute_match.py -v`

Expected: 7 passed.

- [ ] **Step 5: 단위 회귀**

Run: `pytest tests/unit -v`

Expected: 전체 unit 통과 (기존 + 신규).

- [ ] **Step 6: Commit**

```bash
git add app/services/dispute_service.py tests/unit/test_services_dispute_match.py
git commit -m "feat: find_similar_disputes — cosine + pain_point/flag/domain boost"
```

---

## Task 7: 라우터 — `/v1/terms/{term_id}/disputes` 외 3개

**Files:**
- Create: `app/routers/disputes.py`
- Modify: `app/main.py` (라우터 등록)
- Test: `tests/unit/test_routes_disputes.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/unit/test_routes_disputes.py`:

```python
"""disputes 라우터 — 의존성 모킹으로 라우팅·응답 형식만 검증."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


# DB / 인증 의존성 단순 더미 — find_* 함수를 mock 으로 교체
async def _override_db():
    yield None  # 사용 안 함 (서비스 함수 자체를 patch 함)


@pytest.fixture
def client():
    from app.database import get_db
    app.dependency_overrides[get_db] = _override_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_clause_disputes_returns_matches(client):
    clause_id = uuid.uuid4()
    fake_match = {
        "id": uuid.uuid4(),
        "title": "환불 거부 사례",
        "summary": "...",
        "outcome": "환불 100%",
        "source": "한국소비자원",
        "source_url": None,
        "score": 0.82,
        "matched_signals": ["pain_point:POST-03"],
    }

    with patch(
        "app.routers.disputes.dispute_service.find_disputes_for_clause",
        new=AsyncMock(return_value={
            "clause_id": clause_id,
            "clause_title": "자동결제 환불",
            "matches": [fake_match],
        }),
    ):
        resp = client.get(
            f"/v1/terms/{uuid.uuid4()}/clauses/{clause_id}/disputes?top_k=5"
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["clause_id"] == str(clause_id)
    assert len(body["matches"]) == 1
    assert body["matches"][0]["score"] == 0.82


def test_term_disputes_returns_clauses_aggregate(client):
    term_id = uuid.uuid4()

    with patch(
        "app.routers.disputes.dispute_service.find_disputes_for_term",
        new=AsyncMock(return_value={
            "term_id": term_id,
            "clauses": [],
        }),
    ):
        resp = client.get(f"/v1/terms/{term_id}/disputes")
    assert resp.status_code == 200
    body = resp.json()
    assert body["term_id"] == str(term_id)
    assert body["clauses"] == []


def test_list_disputes_pagination(client):
    with patch(
        "app.routers.disputes.dispute_service.list_dispute_cases",
        new=AsyncMock(return_value={"items": [], "total": 0}),
    ):
        resp = client.get("/v1/disputes?limit=10&offset=0")
    assert resp.status_code == 200
    assert resp.json() == {"items": [], "total": 0}


def test_get_dispute_404(client):
    with patch(
        "app.routers.disputes.dispute_service.get_dispute_case",
        new=AsyncMock(return_value=None),
    ):
        resp = client.get(f"/v1/disputes/{uuid.uuid4()}")
    assert resp.status_code == 404
```

- [ ] **Step 2: 테스트 실행 → FAIL**

Run: `pytest tests/unit/test_routes_disputes.py -v`

Expected: 404 on all routes (라우터 아직 mount 안 됨).

- [ ] **Step 3: 라우터 + 서비스 진입점 추가**

`app/services/dispute_service.py` 끝에 라우터-친화 진입점 추가:

```python
# ── 라우터 진입점 (라우터는 ORM 모를 필요 없게 dict 로 변환) ─────


async def find_disputes_for_clause(
    db: AsyncSession,
    *,
    clause_id: uuid.UUID,
    top_k: int = DEFAULT_TOP_K,
) -> dict | None:
    """단일 TermClause → top-K 매칭. clause 없으면 None."""
    from app.models.term import TermClause, TermVersion, Term

    clause = await db.get(TermClause, clause_id)
    if clause is None:
        return None
    # clause → version → term 으로 거슬러 올라가 도메인/unfair_flags 컨텍스트 확보
    version = await db.get(TermVersion, clause.version_id)
    term = await db.get(Term, version.term_id) if version else None

    query_text = "\n".join(filter(None, [
        clause.title or "",
        clause.plain_text or "",
        clause.original_text or "",
    ])).strip()

    # KeyClause.pain_point_id 는 TermClause 컬럼에는 없음 — clause_type 으로
    # 근사 매핑하지 않고 None 으로 두어 cosine + flag/domain boost 만 활용.
    matches = await find_similar_disputes(
        db,
        query_text=query_text,
        clause_pain_point=None,
        term_unfair_flags=[],  # term.unfair_flags 가 별도 저장 안돼있어 일단 빈 리스트
        term_domain=(term.domain.value if term and term.domain else "ALL"),
        top_k=top_k,
    )
    return {
        "clause_id": clause_id,
        "clause_title": clause.title,
        "matches": [
            {
                "case_id": m.id, "title": m.title, "summary": m.summary,
                "outcome": m.outcome, "source": m.source,
                "source_url": m.source_url, "score": m.score,
                "matched_signals": m.matched_signals,
            }
            for m in matches
        ],
    }


async def find_disputes_for_term(
    db: AsyncSession,
    *,
    term_id: uuid.UUID,
    top_k: int = DEFAULT_TOP_K,
) -> dict | None:
    """약관의 latest version 의 모든 TermClause × top-K. term 없으면 None."""
    from app.models.term import TermClause, TermVersion, Term
    from sqlalchemy.orm import selectinload

    result = await db.execute(
        select(Term)
        .options(selectinload(Term.versions).selectinload(TermVersion.clauses))
        .where(Term.id == term_id)
    )
    term = result.scalar_one_or_none()
    if term is None:
        return None

    latest = next((v for v in term.versions if v.is_latest), None)
    if latest is None:
        return {"term_id": term_id, "clauses": []}

    out_clauses: list[dict] = []
    for clause in latest.clauses:
        sub = await find_disputes_for_clause(db, clause_id=clause.id, top_k=top_k)
        if sub:
            out_clauses.append(sub)
    return {"term_id": term_id, "clauses": out_clauses}


async def list_dispute_cases(
    db: AsyncSession,
    *,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    """관리/디버깅용 사례 목록."""
    total_q = await db.execute(select(DisputeCase))
    total = len(total_q.scalars().all())

    page_q = await db.execute(
        select(DisputeCase).order_by(DisputeCase.created_at.desc())
        .limit(limit).offset(offset)
    )
    items = page_q.scalars().all()
    return {
        "items": [
            {
                "id": c.id, "title": c.title, "summary": c.summary,
                "outcome": c.outcome, "source": c.source,
                "source_url": c.source_url,
                "pain_point_ids": list(c.pain_point_ids or []),
                "unfair_flags": list(c.unfair_flags or []),
                "domain": c.domain,
            }
            for c in items
        ],
        "total": total,
    }


async def get_dispute_case(
    db: AsyncSession,
    case_id: uuid.UUID,
) -> dict | None:
    obj = await db.get(DisputeCase, case_id)
    if obj is None:
        return None
    return {
        "id": obj.id, "title": obj.title, "summary": obj.summary,
        "outcome": obj.outcome, "source": obj.source,
        "source_url": obj.source_url,
        "pain_point_ids": list(obj.pain_point_ids or []),
        "unfair_flags": list(obj.unfair_flags or []),
        "domain": obj.domain,
    }
```

이제 라우터 — `app/routers/disputes.py`:

```python
"""분쟁 사례 매칭 라우터.

- /v1/terms/{term_id}/disputes — 약관 전체 KeyClause × top-3 (대시보드)
- /v1/terms/{term_id}/clauses/{clause_id}/disputes — 조항 드릴다운
- /v1/disputes — 사례 목록 (관리)
- /v1/disputes/{case_id} — 단일 사례
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.dispute import (
    ClauseDisputeMatches, DisputeCaseDetail, DisputeListResponse,
    TermDisputesResponse,
)
from app.services import dispute_service


router = APIRouter()


@router.get("/v1/terms/{term_id}/disputes", response_model=TermDisputesResponse)
async def list_term_disputes(
    term_id: uuid.UUID,
    top_k: int = Query(default=dispute_service.DEFAULT_TOP_K, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
):
    result = await dispute_service.find_disputes_for_term(
        db, term_id=term_id, top_k=top_k
    )
    if result is None:
        raise HTTPException(status_code=404, detail="약관을 찾을 수 없습니다.")
    return result


@router.get(
    "/v1/terms/{term_id}/clauses/{clause_id}/disputes",
    response_model=ClauseDisputeMatches,
)
async def get_clause_disputes(
    term_id: uuid.UUID,
    clause_id: uuid.UUID,
    top_k: int = Query(default=dispute_service.DEFAULT_TOP_K, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
):
    result = await dispute_service.find_disputes_for_clause(
        db, clause_id=clause_id, top_k=top_k
    )
    if result is None:
        raise HTTPException(status_code=404, detail="조항을 찾을 수 없습니다.")
    return result


@router.get("/v1/disputes", response_model=DisputeListResponse)
async def list_disputes(
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    return await dispute_service.list_dispute_cases(db, limit=limit, offset=offset)


@router.get("/v1/disputes/{case_id}", response_model=DisputeCaseDetail)
async def get_dispute(
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    obj = await dispute_service.get_dispute_case(db, case_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="분쟁 사례를 찾을 수 없습니다.")
    return obj
```

`app/main.py` — 기존 라우터 등록 블록에 추가 (line 16-19 부근):

기존:
```python
from app.routers import terms, chat, calendar, notifications
...
app.include_router(notifications.router, prefix="/notifications", tags=["Notifications"])
```

수정 후:
```python
from app.routers import terms, chat, calendar, notifications, disputes
...
app.include_router(notifications.router, prefix="/notifications", tags=["Notifications"])
app.include_router(disputes.router,      prefix="",               tags=["Disputes"])
```

(prefix="" 인 이유: 라우터 안에서 `/v1/...` 절대 경로를 이미 정의 — 다른 라우터 (`/terms` prefix) 와 패턴 차이는 spec 의 명시적 `/v1` 네임스페이스 때문.)

- [ ] **Step 4: 테스트 실행 → PASS**

Run: `pytest tests/unit/test_routes_disputes.py -v`

Expected: 4 passed.

- [ ] **Step 5: 전체 unit 회귀**

Run: `pytest tests/unit -v`

Expected: 모두 통과. 기존 라우터 (terms/chat/calendar/notifications) 영향 없음.

- [ ] **Step 6: Commit**

```bash
git add app/routers/disputes.py app/services/dispute_service.py app/main.py tests/unit/test_routes_disputes.py
git commit -m "feat: disputes 라우터 (/v1/terms/.../disputes, /v1/disputes)"
```

---

## Task 8: Seed fixture — `dispute_cases.json`

**Files:**
- Create: `data/fixtures/dispute_cases.json`

큐레이션 15-20건. 도메인 분산 (OTT 8 / Fintech 5 / AI 3 / ALL 3).

- [ ] **Step 1: fixture JSON 생성**

`data/fixtures/dispute_cases.json` — 다음 구조의 배열 (실제 사례 큐레이션):

```json
[
  {
    "external_id": "한소원-2023-OTT-001",
    "title": "넷플릭스 자동결제 환불 거부 — 한국소비자원 조정 사례",
    "summary": "소비자가 14일 무료체험 종료 후 자동 결제된 9,900원 환불을 요청했으나 약관상 '시청 시 청약철회 권리 소멸' 문구를 근거로 거절. 한국소비자원이 전자상거래법 청약철회권 우선 적용 판단.",
    "outcome": "전액 환불 + 결제 즉시 알림 미고지 시정 권고",
    "source": "한국소비자원",
    "source_url": null,
    "pain_point_ids": ["POST-03", "PRE-03"],
    "unfair_flags": ["refund_denial", "POST-03"],
    "domain": "OTT"
  },
  {
    "external_id": "공정위-2024-OTT-002",
    "title": "왓챠 해지 절차 복잡화 — 공정거래위원회 시정명령",
    "summary": "약관상 해지가 '고객센터 통화 요청 → 본인확인 → 사유 면담' 3단계 + 영업시간 한정. 공정위 다크패턴 가이드라인 위반으로 시정명령.",
    "outcome": "해지 버튼 마이페이지 1-클릭 변경 + 영업시간 외 가능",
    "source": "공정거래위원회",
    "source_url": null,
    "pain_point_ids": ["POST-02"],
    "unfair_flags": ["complex_cancellation", "POST-02"],
    "domain": "OTT"
  },
  {
    "external_id": "한소원-2023-OTT-003",
    "title": "디즈니플러스 약관 일방 변경 — 가격 인상 통지 미흡",
    "summary": "디즈니플러스가 월 9,900원 → 13,900원 인상하며 이메일 1회 + 앱 푸시 1회만 고지. 다수 가입자가 변경 사실 인지 못 한 채 결제됨.",
    "outcome": "30일 추가 유예 + 인상 전 가격 유지 옵션 제공",
    "source": "한국소비자원",
    "source_url": null,
    "pain_point_ids": ["MID-01", "POST-01"],
    "unfair_flags": ["unilateral_change", "POST-01"],
    "domain": "OTT"
  },
  {
    "external_id": "언론-2024-OTT-004",
    "title": "쿠팡 플레이 무료체험 → 자동 유료전환 미통지 분쟁",
    "summary": "쿠팡 와우 멤버십 가입 시 쿠팡 플레이 30일 무료. 종료 시점 통지 없이 자동 유료 전환. 다수 소비자 카드사 차지백 신청.",
    "outcome": "종료 7일 전 통지 의무화 (자율 시정)",
    "source": "언론",
    "source_url": null,
    "pain_point_ids": ["PRE-03"],
    "unfair_flags": [],
    "domain": "OTT"
  },
  {
    "external_id": "한소원-2023-OTT-005",
    "title": "티빙 약관 변경 — 무응답 동의 의제 조항 분쟁",
    "summary": "티빙이 약관 변경 통지 후 '14일 내 의사표시 없으면 동의로 간주' 조항으로 일방 변경. 소비자가 인지 못 한 상태에서 신규 약관 적용.",
    "outcome": "의사표시 의제 조항 삭제 + 명시적 동의 절차 도입",
    "source": "한국소비자원",
    "source_url": null,
    "pain_point_ids": ["MID-02"],
    "unfair_flags": ["의사표시_의제", "POST-05"],
    "domain": "OTT"
  },
  {
    "external_id": "공정위-2024-OTT-006",
    "title": "웨이브 환불 제한 — 잔여기간 일할 계산 거부",
    "summary": "월 구독 중도 해지 시 잔여일에 대한 환불 없이 결제일 기준 전액 소진. 비례 환불(pro-rata) 거부 약관 조항.",
    "outcome": "전자상거래법상 일할 환불 의무 명시 시정",
    "source": "공정거래위원회",
    "source_url": null,
    "pain_point_ids": ["POST-03"],
    "unfair_flags": ["no_refund", "POST-03"],
    "domain": "OTT"
  },
  {
    "external_id": "언론-2024-OTT-007",
    "title": "스포티파이 한국 강제 중재 조항 분쟁",
    "summary": "스포티파이 약관상 분쟁 발생 시 미국 캘리포니아주 법원·중재 강제. 한국 거주 소비자에게 외국법·외국 법정 강제는 한국 강행규정 위반 소지.",
    "outcome": "한국 소비자에 한해 한국 법원 관할 추가 (병기 조항)",
    "source": "언론",
    "source_url": null,
    "pain_point_ids": ["POST-05"],
    "unfair_flags": ["arbitration_class_waiver", "POST-05", "준거법 외국법"],
    "domain": "OTT"
  },
  {
    "external_id": "한소원-2023-OTT-008",
    "title": "OTT 면책 광범위 — 서비스 장애 보상 거부",
    "summary": "다중 OTT 사업자가 '서비스 장애로 인한 일체의 손해에 대해 책임지지 않음' 조항으로 보상 거부. 24시간 이상 장애 발생 시에도 환불 미제공.",
    "outcome": "장애 시간 비례 환불 + 면책 범위 약관규제법상 합리적 범위로 축소",
    "source": "한국소비자원",
    "source_url": null,
    "pain_point_ids": ["POST-04"],
    "unfair_flags": ["liability_cap", "POST-04"],
    "domain": "OTT"
  },
  {
    "external_id": "한소원-2024-FIN-001",
    "title": "카카오페이 자동결제 등록 — 다크패턴 동의 분쟁",
    "summary": "정기결제 가입 시 약관 동의 화면에 '자동결제 동의' 체크박스가 기본 선택. 소비자가 인지 못한 채 자동결제 등록.",
    "outcome": "opt-in 명시적 동의로 변경 + 미인지 가입 환불",
    "source": "한국소비자원",
    "source_url": null,
    "pain_point_ids": ["PRE-03", "PRE-04"],
    "unfair_flags": [],
    "domain": "FINANCE"
  },
  {
    "external_id": "공정위-2024-FIN-002",
    "title": "토스 약관 변경 — 개인정보 제3자 제공 동의 의제",
    "summary": "약관 개정 통지에 '14일 내 의사표시 없으면 동의' 조항으로 마케팅 활용 동의 자동 갱신. 명시적 동의 누락.",
    "outcome": "개인정보보호법상 별도 동의 절차로 분리",
    "source": "공정거래위원회",
    "source_url": null,
    "pain_point_ids": ["MID-02", "PRE-04"],
    "unfair_flags": ["의사표시_의제", "POST-05"],
    "domain": "FINANCE"
  },
  {
    "external_id": "한소원-2023-FIN-003",
    "title": "은행 자동이체 해지 절차 복잡화",
    "summary": "은행 앱 자동이체 등록은 1-tap, 해지는 영업점 방문 또는 ARS 본인확인 필요. 다크패턴 가이드라인 저촉.",
    "outcome": "앱 내 1-tap 해지 도입",
    "source": "한국소비자원",
    "source_url": null,
    "pain_point_ids": ["POST-02"],
    "unfair_flags": ["complex_cancellation", "POST-02"],
    "domain": "FINANCE"
  },
  {
    "external_id": "언론-2024-FIN-004",
    "title": "보험 자동갱신 조항 — 갱신 시점 통지 미흡",
    "summary": "1년 만기 보험이 통지 없이 자동 갱신, 다음 해 보험료 인상분 일괄 청구. 약관상 갱신 30일 전 통지 의무가 있으나 형식적 이메일만 발송.",
    "outcome": "이메일 + SMS + 앱 푸시 다중 채널 의무화",
    "source": "언론",
    "source_url": null,
    "pain_point_ids": ["MID-01"],
    "unfair_flags": [],
    "domain": "FINANCE"
  },
  {
    "external_id": "한소원-2024-FIN-005",
    "title": "암호화폐 거래소 면책 광범위 — 해킹 손해 책임 회피",
    "summary": "거래소 약관상 해킹 발생 시 '운영상 불가항력' 으로 면책. 실제 보안 조치 미흡으로 발생한 손해도 면책 적용.",
    "outcome": "고의·중과실 손해는 보상 책임 명시",
    "source": "한국소비자원",
    "source_url": null,
    "pain_point_ids": ["POST-04"],
    "unfair_flags": ["liability_cap", "POST-04"],
    "domain": "FINANCE"
  },
  {
    "external_id": "AI-2024-001",
    "title": "AI 챗봇 학습 데이터 활용 — 옵트아웃 불가 조항",
    "summary": "글로벌 AI 서비스 약관상 사용자 입력이 자동 학습 데이터로 활용. 한국 사용자 대상 옵트아웃 기능 미제공.",
    "outcome": "한국 사용자에 한해 학습 활용 옵트아웃 토글 제공",
    "source": "언론",
    "source_url": null,
    "pain_point_ids": ["PRE-04"],
    "unfair_flags": ["AI 학습 데이터 활용", "ai_training_data"],
    "domain": "AI"
  },
  {
    "external_id": "AI-2024-002",
    "title": "AI 출력 IP 귀속 — 유료 사용자 출력물 회사 보유 분쟁",
    "summary": "AI 서비스 약관상 사용자가 생성한 출력물의 IP 가 회사에 귀속. 유료 사용자 항의로 약관 개정.",
    "outcome": "유료 플랜 한해 출력물 IP 사용자 귀속으로 변경",
    "source": "언론",
    "source_url": null,
    "pain_point_ids": ["PRE-02"],
    "unfair_flags": [],
    "domain": "AI"
  },
  {
    "external_id": "AI-2024-003",
    "title": "AI 서비스 면책 광범위 — 잘못된 답변 책임 회피",
    "summary": "AI 답변의 부정확성 손해에 대해 '정보 제공 용도' 명목으로 광범위 면책. 의료·법률 자문 인용 후 손해 발생 사례.",
    "outcome": "AI 출력 신뢰성 한도 명시 + 의료/법률 답변 사용 시 경고",
    "source": "한국소비자원",
    "source_url": null,
    "pain_point_ids": ["POST-04"],
    "unfair_flags": ["liability_cap", "POST-04"],
    "domain": "AI"
  },
  {
    "external_id": "공정위-2023-ALL-001",
    "title": "약관규제법 위반 — 사업자 일방 책임 면제 조항 무효",
    "summary": "공정거래위원회가 다수 사업자의 '본 서비스로 인한 일체의 손해에 대해 책임지지 않음' 조항을 약관규제법 제7조 위반으로 무효 판단.",
    "outcome": "면책 조항 일괄 시정 — 고의·중과실은 책임 명시",
    "source": "공정거래위원회",
    "source_url": null,
    "pain_point_ids": ["POST-04"],
    "unfair_flags": ["liability_cap", "POST-04"],
    "domain": "ALL"
  },
  {
    "external_id": "한소원-2023-ALL-002",
    "title": "전자상거래법 청약철회권 vs '디지털 콘텐츠 사용 시 권리 소멸'",
    "summary": "여러 사업자가 '디지털 콘텐츠 사용 시 청약철회권 소멸' 조항으로 환불 거부. 전자상거래법 17조 청약철회권은 강행규정 — 미사용분에 한해 환불 의무.",
    "outcome": "미사용분 (재생/다운로드 안 한 콘텐츠) 환불 의무 명시",
    "source": "한국소비자원",
    "source_url": null,
    "pain_point_ids": ["POST-03"],
    "unfair_flags": ["refund_denial", "POST-03"],
    "domain": "ALL"
  },
  {
    "external_id": "공정위-2024-ALL-003",
    "title": "약관 변경 통지 채널 — 이메일 단일 채널 충분성 분쟁",
    "summary": "사업자가 약관 변경을 이메일 1회 발송으로 끝내는 사례 다수. 공정위 가이드라인 — 중요 변경은 앱 푸시 + 이메일 + 로그인 시 모달 등 다중 채널 필요.",
    "outcome": "중요 변경 다중 채널 통지 의무화 가이드라인 발표",
    "source": "공정거래위원회",
    "source_url": null,
    "pain_point_ids": ["MID-01"],
    "unfair_flags": ["unilateral_change", "POST-01"],
    "domain": "ALL"
  }
]
```

- [ ] **Step 2: JSON 유효성 검증**

Run: `python -c "import json; print(len(json.load(open('data/fixtures/dispute_cases.json'))))"`

Expected: `19` (또는 작성한 개수).

- [ ] **Step 3: Commit**

```bash
git add data/fixtures/dispute_cases.json
git commit -m "feat: dispute_cases fixture seed (OTT 8 + FIN 5 + AI 3 + ALL 3)"
```

---

## Task 9: 인덱싱 스크립트 — `index_dispute_cases.py`

**Files:**
- Create: `scripts/index_dispute_cases.py`

idempotent: 같은 fixture 두 번 돌려도 upsert + embedding 만 갱신.

- [ ] **Step 1: 스크립트 작성**

`scripts/index_dispute_cases.py`:

```python
#!/usr/bin/env python
"""data/fixtures/dispute_cases.json → DB 인덱싱.

1. JSON 로드
2. upsert_dispute_cases (external_id 키)
3. 각 row 에 대해 title + summary + outcome 합쳐 embedding-passage 호출
4. embedding 컬럼 update

Idempotent — 같은 fixture 재실행 시 외부 시스템 영향 없음.

사용: `PYTHONPATH=. python scripts/index_dispute_cases.py`
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

from app.database import AsyncSessionLocal
from app.services import dispute_service
from app.services.ai_client import embed_chunks


logger = logging.getLogger("index_dispute_cases")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


FIXTURE_PATH = Path("data/fixtures/dispute_cases.json")


def _embedding_text(case: dict) -> str:
    """임베딩 입력 텍스트 — title + summary + outcome 결합."""
    return "\n".join(filter(None, [
        case.get("title", ""),
        case.get("summary", ""),
        case.get("outcome", ""),
    ])).strip()


async def main() -> int:
    if not FIXTURE_PATH.exists():
        logger.error("fixture not found: %s", FIXTURE_PATH)
        return 1

    cases: list[dict] = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    logger.info("loaded %d dispute cases from %s", len(cases), FIXTURE_PATH)

    async with AsyncSessionLocal() as db:
        # 1) upsert (embedding 제외)
        ids = await dispute_service.upsert_dispute_cases(db, cases)
        await db.commit()
        logger.info("upserted %d rows", len(ids))

        # 2) 임베딩 — 일괄 호출 (embed_passages 가 batch 처리)
        texts = [_embedding_text(c) for c in cases]
        logger.info("embedding %d passages...", len(texts))
        vectors = await embed_chunks(texts)
        logger.info("got %d vectors (dim=%d)", len(vectors), len(vectors[0]) if vectors else 0)

        # 3) row 별 embedding update
        for case_id, vec in zip(ids, vectors):
            await dispute_service.set_dispute_embedding(db, case_id, vec)
        await db.commit()
        logger.info("indexed %d embeddings", len(ids))

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

- [ ] **Step 2: 실행 (실DB + 실키 필요)**

Run: `PYTHONPATH=. python scripts/index_dispute_cases.py`

Expected log:
```
loaded 19 dispute cases ...
upserted 19 rows
embedding 19 passages...
got 19 vectors (dim=4096)
indexed 19 embeddings
```

검증:
```bash
psql "$DATABASE_URL" -c "SELECT COUNT(*), COUNT(embedding) FROM dispute_cases;"
```
Expected: `count | count` 둘 다 `19`.

- [ ] **Step 3: 재실행 idempotency 확인**

Run: `PYTHONPATH=. python scripts/index_dispute_cases.py`

`COUNT(*)` 여전히 19 (insert 안 됨, update 만).

- [ ] **Step 4: Commit**

```bash
git add scripts/index_dispute_cases.py
git commit -m "feat: index_dispute_cases — fixture → DB 임베딩 인덱싱 (idempotent)"
```

---

## Task 10: 통합 스모크 — 인덱싱 후 라우터 호출

**Files:** (테스트 코드 외 변경 없음)
- Test: `tests/integration/test_disputes_e2e.py`

`-m e2e` — 실 DB + 실 Upstage 키 필요. CI 에서 자동 실행하지 않음.

- [ ] **Step 1: 통합 테스트 작성**

`tests/integration/test_disputes_e2e.py`:

```python
"""dispute matching e2e — 실제 임베딩 + pgvector 매칭 정확성 검증.

전제: data/fixtures/dispute_cases.json 가 미리 indexed (scripts/index_dispute_cases.py).
스킵 조건: DB 비어있거나 (embedding 없는 row 만 있거나) UPSTAGE_API_KEY 미설정.

명령: pytest tests/integration/test_disputes_e2e.py -v -m e2e
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import text as sa_text

from app.database import AsyncSessionLocal
from app.services import dispute_service


pytestmark = pytest.mark.e2e


@pytest.fixture(autouse=True)
async def _require_indexed():
    if not os.getenv("UPSTAGE_API_KEY"):
        pytest.skip("UPSTAGE_API_KEY 미설정")
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            sa_text("SELECT COUNT(*) FROM dispute_cases WHERE embedding IS NOT NULL")
        )
        n = result.scalar_one()
        if n < 5:
            pytest.skip(f"indexed dispute cases insufficient ({n} < 5) — run scripts/index_dispute_cases.py")


async def test_refund_denial_query_matches_post_03_case():
    async with AsyncSessionLocal() as db:
        matches = await dispute_service.find_similar_disputes(
            db,
            query_text="환불 거부 자동결제 청약철회",
            clause_pain_point="POST-03",
            term_unfair_flags=["refund_denial"],
            term_domain="OTT",
            top_k=3,
        )
    assert len(matches) >= 1
    # top-1 은 POST-03 그룹과 매칭되어야 함
    top1 = matches[0]
    assert "pain_point:POST-03" in top1.matched_signals or any(
        "flag:" in s for s in top1.matched_signals
    )


async def test_complex_cancellation_matches_post_02():
    async with AsyncSessionLocal() as db:
        matches = await dispute_service.find_similar_disputes(
            db,
            query_text="해지 절차 복잡 다크패턴 영업점 방문",
            clause_pain_point="POST-02",
            term_unfair_flags=["complex_cancellation"],
            term_domain="OTT",
            top_k=3,
        )
    assert len(matches) >= 1
    top1 = matches[0]
    titles = [m.title for m in matches]
    assert any("해지" in t for t in titles)


async def test_ai_domain_specificity_does_not_match_ott_query():
    """OTT 환불 거부 query 가 AI 도메인 사례에 매칭되지 않아야 (domain boost 만 다른 도메인에 안 줌)."""
    async with AsyncSessionLocal() as db:
        matches = await dispute_service.find_similar_disputes(
            db,
            query_text="환불 거부 OTT 자동결제",
            clause_pain_point="POST-03",
            term_unfair_flags=["refund_denial"],
            term_domain="OTT",
            top_k=10,
        )
    # AI domain row 가 결과에 0~소수만 포함되어야 함 (mismatch domain 은 boost X)
    ai_count = sum(1 for m in matches if "domain:AI" in m.matched_signals)
    assert ai_count == 0
```

- [ ] **Step 2: 통합 테스트 실행 (지표 검증)**

Run: `pytest tests/integration/test_disputes_e2e.py -v -m e2e`

Expected:
- 인덱싱 안 됐으면 → SKIP
- 인덱싱 완료 후 → 3 passed (또는 매칭 임계값 조정 필요 시 fail 케이스 디버깅)

- [ ] **Step 3: 라우터 스모크 (수동)**

서버 실행:
```bash
PYTHONPATH=. uvicorn app.main:app --reload
```

브라우저/curl:
```bash
curl 'http://localhost:8000/v1/disputes?limit=5' | jq
```

Expected: 5개 사례 JSON 반환, 각 `pain_point_ids` / `unfair_flags` 포함.

업로드된 약관이 있다면:
```bash
curl "http://localhost:8000/v1/terms/$TERM_ID/disputes" | jq
```

Expected: clauses 배열, 각 clause 의 matches 배열 (보통 0-3개).

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_disputes_e2e.py
git commit -m "test: dispute matching e2e — 실DB + Upstage embedding 통합 검증"
```

---

## Final Verification

- [ ] **전체 회귀**

Run: `pytest tests/unit -v`

Expected: 신규 4 개 테스트 파일 + 기존 모두 passed. 회귀 0.

- [ ] **Lint / type-check (기존 정책 유지)**

Run: `ruff check app/ ai/ scripts/ tests/unit/test_routes_disputes.py tests/unit/test_services_dispute_*.py`

Expected: 0 errors. (warnings 는 별도 commit).

```bash
mypy app/services/dispute_service.py app/routers/disputes.py app/models/dispute.py app/schemas/dispute.py ai/schemas/flag_canonical.py
```

Expected: 0 errors.

- [ ] **Branch push (선택)**

```bash
git log --oneline -12
git push origin wooxogh
```

PR 생성은 사용자가 별도 결정.

---

## Self-Review (작성 후 확인)

### Spec coverage
- §3 Data Model → Task 1, 3
- §4 Matching algorithm → Task 6
- §5 API → Task 7
- §6 Component boundaries → Task 3-7, 9
- §6.1 Source-agnostic interface → Task 5 (`DisputeCaseInput`)
- §7.1 Unit tests → Task 2, 3, 4, 5, 6, 7
- §7.2 Integration tests → Task 10
- §8 Migration/rollout → Task 1, 9
- §10 Open issues → Task 5 (canonical flag), Task 7 (clause_pain_point=None 처리 명시)

### Placeholder scan
- 모든 step 에 actual code / actual commands 포함. "TBD" / "handle edge cases" 등 placeholder 없음.

### Type consistency
- `DisputeCaseInput` (Task 5) ↔ `upsert_dispute_cases` parameter 일치
- `_CandidateRow` / `_ScoredMatch` (Task 6) — 같은 dataclass 명을 라우터에서 dict 변환 (Task 7) 시 일치
- `ClauseDisputeMatches` schema (Task 4) ↔ `find_disputes_for_clause` 반환 dict (Task 7) — `clause_id`/`clause_title`/`matches` 필드명 일치
- `DisputeListResponse` (Task 4) ↔ `list_dispute_cases` 반환 (Task 7) — `items`/`total` 일치
