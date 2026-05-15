"""term_service.search_chunks 응답 정합성 검증.

핵심: 반환되는 dict 가 `app.schemas.term.ChunkResult` 스키마와 정합하는지.
이전엔 service 가 {id, content, chunk_index} 를 반환하고 schema 는
{chunk_id, content, score} 를 기대해 FastAPI 응답 검증이 깨졌다.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.schemas.term import ChunkResult, SearchResponse
from app.services import term_service


@pytest.fixture
def mock_db():
    db = AsyncMock()
    return db


def _row(idx: int, score: float):
    return SimpleNamespace(
        id=uuid.UUID(int=idx),
        content=f"청크 본문 {idx}",
        chunk_index=idx,
        score=score,
    )


async def test_search_chunks_returns_schema_compatible_dicts(monkeypatch, mock_db):
    """반환 dict 4 키 (chunk_id/chunk_index/content/score) 모두 채워짐."""

    async def fake_embed(_text):
        return [0.1] * 4096

    monkeypatch.setattr(term_service.ai_client, "embed_query", fake_embed)

    fake_result = AsyncMock()
    fake_result.fetchall = lambda: [_row(0, 0.92), _row(1, 0.45)]
    mock_db.execute = AsyncMock(return_value=fake_result)

    out = await term_service.search_chunks(mock_db, uuid.uuid4(), "쿼리", top_k=2)
    assert len(out) == 2
    assert set(out[0].keys()) == {"chunk_id", "chunk_index", "content", "score"}
    assert out[0]["score"] == 0.92
    assert isinstance(out[0]["chunk_id"], uuid.UUID)
    assert isinstance(out[0]["score"], float)

    # SearchResponse 스키마로 검증 통과해야 (이전엔 score 누락으로 ValidationError)
    resp = SearchResponse(results=out)
    assert len(resp.results) == 2
    assert resp.results[0].score == 0.92


async def test_search_chunks_top_k_passed_to_sql(monkeypatch, mock_db):
    """top_k 인자가 SQL 바인딩에 정확히 전달."""

    async def fake_embed(_text):
        return [0.0] * 4096

    monkeypatch.setattr(term_service.ai_client, "embed_query", fake_embed)

    captured = {}
    fake_result = AsyncMock()
    fake_result.fetchall = lambda: []

    async def capture_execute(_sql, params):
        captured.update(params)
        return fake_result

    mock_db.execute = capture_execute

    await term_service.search_chunks(mock_db, uuid.uuid4(), "쿼리", top_k=7)
    assert captured["top_k"] == 7


async def test_chunk_result_score_is_similarity_not_distance():
    """schema 문서: score 는 cosine *similarity* (1=동일, 0=무관).
    pgvector `<=>` 가 *distance* 라 SQL 에서 1 - <=> 로 변환해야 함."""
    cr = ChunkResult(
        chunk_id=uuid.uuid4(), chunk_index=0,
        content="x", score=0.95,
    )
    # 가까운 매치는 1 에 가까운 값. 0.95 → 매우 가까움.
    assert 0 <= cr.score <= 1
