"""글로벌 exception handler 회귀 테스트 — `app/main.py` 의 4 핸들러 검증.

전략:
- 실제 DB 의존성은 `get_db` dependency override 로 차단 (테스트가 Supabase 안 건드림).
- 파이프라인 호출 지점(`term_service.process_upload`) 을 monkeypatch 해 원하는
  예외를 raise 시키고, FastAPI 가 글로벌 핸들러로 catch 해 구조화 JSON 응답으로
  바꾸는지 검증.
"""
from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from ai.services.diff import DiffSchemaError
from ai.services.extract import SchemaValidationError
from ai.services.upstage import UpstreamResponseError
from app.database import get_db
from app.main import app
from app.services import term_service


@pytest.fixture(autouse=True)
def _override_db():
    """라우터의 db: AsyncSession = Depends(get_db) 가 Supabase 접속을 시도하지 않게.
    process_upload 가 monkeypatch 로 즉시 raise 하므로 db 는 사용되지 않는다.
    """
    async def _fake():
        yield None

    app.dependency_overrides[get_db] = _fake
    yield
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def client():
    # raise_server_exceptions=False — 등록된 핸들러가 잡지 못한 예외도 500 응답으로
    # 받기 위함. 핸들러가 잡았는지/안 잡았는지 status code 만으로 판정.
    return TestClient(app, raise_server_exceptions=False)


def _post_upload(client: TestClient):
    return client.post(
        "/terms/upload",
        files={"file": ("t.pdf", b"%PDF", "application/pdf")},
        data={"service_name": "TestStream", "domain": "OTT"},
    )


# ── 502 upstream_error ───────────────────────────────────


def test_upstream_response_error_returns_502(monkeypatch, client):
    """Upstage 가 비-JSON / 빈 body 같은 걸 반환 → UpstreamResponseError → 502."""
    async def boom(*args, **kwargs):
        raise UpstreamResponseError("Upstream returned non-JSON response (status=502, len=42)")
    monkeypatch.setattr(term_service, "process_upload", boom)

    r = _post_upload(client)
    assert r.status_code == 502
    body = r.json()
    assert body["error"] == "upstream_error"
    assert "non-JSON" in body["detail"]


def test_httpx_status_error_returns_502(monkeypatch, client):
    """Upstage 가 401/429/5xx 반환 → httpx.HTTPStatusError → 502."""
    async def boom(*args, **kwargs):
        request = httpx.Request("POST", "https://api.upstage.test/v1/chat/completions")
        response = httpx.Response(401, request=request)
        raise httpx.HTTPStatusError("unauthorized", request=request, response=response)
    monkeypatch.setattr(term_service, "process_upload", boom)

    r = _post_upload(client)
    assert r.status_code == 502
    body = r.json()
    assert body["error"] == "upstream_error"
    assert "401" in body["detail"]


# ── 422 validation_error ─────────────────────────────────


def test_schema_validation_error_returns_422(monkeypatch, client):
    """SubscriptionTerms 검증 실패 → 422."""
    async def boom(*args, **kwargs):
        raise SchemaValidationError("Extract response validation failed: missing field 'pricing'")
    monkeypatch.setattr(term_service, "process_upload", boom)

    r = _post_upload(client)
    assert r.status_code == 422
    body = r.json()
    assert body["error"] == "validation_error"
    assert "validation failed" in body["detail"]


def test_diff_schema_error_returns_422(monkeypatch, client):
    """DiffResult 검증 실패 → SchemaValidationError 와 동일 카테고리(422)."""
    async def boom(*args, **kwargs):
        raise DiffSchemaError("Diff response validation failed: bad category enum")
    monkeypatch.setattr(term_service, "process_upload", boom)

    r = _post_upload(client)
    assert r.status_code == 422
    body = r.json()
    assert body["error"] == "validation_error"


# ── 500 (핸들러가 잡지 말아야 할 일반 예외) ────────────────


def test_generic_value_error_not_caught_as_422(monkeypatch, client):
    """일반 ValueError 는 도메인 검증 핸들러로 잡히지 않아야 함 — 서버 코드 버그 카테고리(500).

    SchemaValidationError 와 DiffSchemaError 가 ValueError 를 상속하므로, 핸들러가
    `ValueError` 자체를 잡으면 무관한 내부 버그까지 422 로 오분류된다. 핸들러는
    명시적 sub-class 만 매치하도록 좁혀야 한다 — 이 테스트가 그 경계의 회귀 가드.
    """
    async def boom(*args, **kwargs):
        raise ValueError("some unrelated internal value error")
    monkeypatch.setattr(term_service, "process_upload", boom)

    r = _post_upload(client)
    assert r.status_code == 500
