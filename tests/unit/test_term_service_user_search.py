"""term_service.search_chunks_for_user 응답 정합성 검증.

cross-term 통합 검색: user_id 기준 JOIN term_chunks ⨝ terms. 응답은
`UserChunkResult` 스키마와 정합해야 함 (term_id / service_name / domain 포함).
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.schemas.term import UserChunkResult, UserSearchResponse
from app.services import term_service


@pytest.fixture
def mock_db():
    return AsyncMock()


def _row(idx: int, score: float, *, service_name: str = "Toss", domain: str = "FINANCE"):
    return SimpleNamespace(
        chunk_id=uuid.UUID(int=idx),
        content=f"본문 {idx}",
        chunk_index=idx,
        term_id=uuid.UUID(int=100 + idx),
        service_name=service_name,
        domain=domain,
        score=score,
    )


async def test_search_chunks_for_user_returns_schema_compatible_dicts(
    monkeypatch, mock_db
):
    async def fake_embed(_text):
        return [0.1] * 4096

    monkeypatch.setattr(term_service.ai_client, "embed_query", fake_embed)

    rows = [
        _row(0, 0.92, service_name="Toss", domain="FINANCE"),
        _row(1, 0.81, service_name="삼성 실손보험", domain="INSURANCE"),
    ]
    fake_result = AsyncMock()
    fake_result.fetchall = lambda: rows
    mock_db.execute = AsyncMock(return_value=fake_result)

    out = await term_service.search_chunks_for_user(
        mock_db, user_id=uuid.uuid4(), query="병원비 청구", top_k=5,
    )
    assert len(out) == 2
    expected_keys = {
        "chunk_id", "chunk_index", "content", "term_id",
        "service_name", "domain", "score",
    }
    assert set(out[0].keys()) == expected_keys
    assert out[0]["service_name"] == "Toss"
    assert out[1]["domain"] == "INSURANCE"

    # 스키마 검증 통과해야
    resp = UserSearchResponse(
        results=[UserChunkResult(**r) for r in out], total=len(out),
    )
    assert resp.total == 2
    assert resp.results[0].score == 0.92


async def test_search_chunks_for_user_domain_filter_binds_params(
    monkeypatch, mock_db
):
    """domain_filter 가 SQL ANY(:domains) 로 바인딩되는지."""

    async def fake_embed(_text):
        return [0.0] * 4096

    monkeypatch.setattr(term_service.ai_client, "embed_query", fake_embed)

    captured: dict = {}
    fake_result = AsyncMock()
    fake_result.fetchall = lambda: []

    async def capture_execute(sql, params):
        captured["sql"] = str(sql)
        captured["params"] = params
        return fake_result

    mock_db.execute = capture_execute

    await term_service.search_chunks_for_user(
        mock_db,
        user_id=uuid.uuid4(),
        query="청구",
        top_k=3,
        domain_filter=["insurance", "finance"],  # 소문자 입력 → 대문자 정규화
    )

    assert "domains" in captured["params"]
    assert captured["params"]["domains"] == ["INSURANCE", "FINANCE"]
    assert "ANY(:domains)" in captured["sql"]
    assert captured["params"]["top_k"] == 3


async def test_search_chunks_for_user_no_filter_omits_domain_clause(
    monkeypatch, mock_db
):
    async def fake_embed(_text):
        return [0.0] * 4096

    monkeypatch.setattr(term_service.ai_client, "embed_query", fake_embed)

    captured: dict = {}
    fake_result = AsyncMock()
    fake_result.fetchall = lambda: []

    async def capture_execute(sql, params):
        captured["sql"] = str(sql)
        captured["params"] = params
        return fake_result

    mock_db.execute = capture_execute

    await term_service.search_chunks_for_user(
        mock_db, user_id=uuid.uuid4(), query="청구", top_k=5,
    )
    assert "domains" not in captured["params"]
    assert "ANY(:domains)" not in captured["sql"]
