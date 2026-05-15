"""disputes 라우터 — 의존성 모킹으로 라우팅·응답 형식만 검증."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


async def _override_db():
    yield None  # 서비스 함수 자체를 patch — DB 안 씀


@pytest.fixture
def client():
    from app.database import get_db
    app.dependency_overrides[get_db] = _override_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_clause_disputes_returns_matches(client):
    clause_id = uuid.uuid4()
    fake_match = {
        "case_id": uuid.uuid4(),
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
