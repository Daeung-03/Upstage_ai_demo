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
    if not os.getenv("UPSTAGE_API_KEY") or os.getenv("UPSTAGE_API_KEY") == "test-api-key-not-real":
        pytest.skip("UPSTAGE_API_KEY 실키 미설정")
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            sa_text("SELECT COUNT(*) FROM dispute_cases WHERE embedding IS NOT NULL")
        )
        n = result.scalar_one()
        if n < 5:
            pytest.skip(
                f"indexed dispute cases insufficient ({n} < 5) — "
                "run scripts/index_dispute_cases.py"
            )


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
    top1 = matches[0]
    # POST-03 그룹 매칭 (pain_point 또는 flag boost 중 하나는 잡혀야)
    assert (
        "pain_point:POST-03" in top1.matched_signals
        or any(s.startswith("flag:") for s in top1.matched_signals)
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
    titles = [m.title for m in matches]
    assert any("해지" in t for t in titles)


async def test_domain_mismatch_excludes_other_domain_only_matches():
    """OTT query 가 AI-only 사례에 매칭되지 않아야 (domain filter SQL 단계)."""
    async with AsyncSessionLocal() as db:
        matches = await dispute_service.find_similar_disputes(
            db,
            query_text="환불 거부 OTT 자동결제",
            clause_pain_point="POST-03",
            term_unfair_flags=["refund_denial"],
            term_domain="OTT",
            top_k=10,
        )
    # AI domain row 가 결과에 0개 (domain filter 가 OTT + ALL 만 fetch)
    ai_count = sum(1 for m in matches if "domain:AI" in m.matched_signals)
    assert ai_count == 0
