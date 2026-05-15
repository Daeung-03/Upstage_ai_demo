"""POST /terms/upload 라우터 wiring 테스트.

term_service.process_upload 와 DB 세션은 monkeypatch/dependency override 로
격리. 실 Supabase / Upstage 안 거치고 라우터 책임만 검증:
- 필수 필드 누락 → 422
- 정상 흐름: process_upload 결과를 TermUploadResponse 로 매핑
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.services import term_service


@pytest.fixture(autouse=True)
def _override_db():
    """get_db dependency 가 Supabase 접속 안 하도록 차단. process_upload 가
    monkeypatch 되어 즉시 반환하므로 db 객체는 실제로 안 쓰임."""
    async def _fake():
        yield None

    app.dependency_overrides[get_db] = _fake
    yield
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


def _post_upload(client: TestClient, *, service_name="Netflix", domain="OTT", file=True):
    files = {"file": ("netflix.pdf", b"%PDF fake", "application/pdf")} if file else {}
    data = {"service_name": service_name, "domain": domain}
    return client.post("/terms/upload", files=files, data=data)


def _fake_term_version():
    term_id = uuid.uuid4()
    term = SimpleNamespace(
        id=term_id,
        service_name="Netflix",
        domain="OTT",
        status="ACTIVE",
        created_at=datetime(2026, 5, 15, tzinfo=timezone.utc),
        subscribed_at=date(2026, 5, 1),
    )
    version = SimpleNamespace(id=uuid.uuid4(), version=1, term_id=term_id)
    return term, version


# ── happy path ───────────────────────────────────────────


def test_upload_endpoint_happy_path(monkeypatch, client):
    """process_upload 결과를 TermUploadResponse 로 매핑."""
    captured = {}

    async def fake_upload(*, db, user_id, service_name, subscribed_at,
                          file_bytes, file_url, domain):
        captured["service_name"] = service_name
        captured["domain"] = domain
        captured["filename"] = file_url.split("/")[-1]
        return _fake_term_version()

    monkeypatch.setattr(term_service, "process_upload", fake_upload)

    # 커밋/리프레시는 라우터가 직접 호출. db=None 이라 attr 호출 시 AttributeError.
    # raise_server_exceptions=False 이므로 200 응답 조건은 process_upload 까지만.
    # 라우터의 db.commit() / db.refresh() 호출을 막기 위해 dummy 객체로 override.
    class _DummyDB:
        async def commit(self): return None
        async def refresh(self, obj): return None

    async def _dummy_get_db():
        yield _DummyDB()

    app.dependency_overrides[get_db] = _dummy_get_db
    try:
        r = _post_upload(client, service_name="Netflix", domain="OTT")
    finally:
        app.dependency_overrides[get_db] = lambda: iter([None])

    assert r.status_code == 201, r.text
    body = r.json()
    assert body["service_name"] == "Netflix"
    assert body["domain"] == "OTT"
    assert body["version"] == 1
    assert captured["service_name"] == "Netflix"
    assert captured["domain"] == "OTT"
    assert captured["filename"] == "netflix.pdf"


# ── 422 validation ───────────────────────────────────────


def test_upload_endpoint_missing_file_returns_422(client):
    """필수 multipart file 누락 → FastAPI 가 422 자동 반환."""
    r = client.post("/terms/upload", data={"service_name": "Netflix"})
    assert r.status_code == 422


def test_upload_endpoint_missing_service_name_returns_422(client):
    """필수 form 필드 service_name 누락 → 422."""
    r = client.post(
        "/terms/upload",
        files={"file": ("netflix.pdf", b"%PDF", "application/pdf")},
    )
    assert r.status_code == 422
