import httpx
from fastapi.testclient import TestClient

from app.main import app
from services.extract import SchemaValidationError
from services.upstage import UpstreamResponseError


def _post(client):
    return client.post(
        "/v1/terms/analyze",
        files={"file": ("t.pdf", b"%PDF", "application/pdf")},
        data={"service_name": "X", "service_provider": "Y"},
    )


def test_upstream_http_error_returns_502(monkeypatch):
    """파이프라인에서 httpx.HTTPStatusError 발생 시 502 + 구조화 응답."""

    async def fake_run_pipeline(*args, **kwargs):
        request = httpx.Request("POST", "https://api.upstage.test/v1/chat/completions")
        response = httpx.Response(401, request=request)
        raise httpx.HTTPStatusError("unauthorized", request=request, response=response)

    monkeypatch.setattr("app.routes.terms.run_pipeline", fake_run_pipeline)
    monkeypatch.setenv("UPSTAGE_API_KEY", "test-key")

    client = TestClient(app, raise_server_exceptions=False)
    response = _post(client)
    assert response.status_code == 502
    body = response.json()
    assert body["error"] == "upstream_error"
    assert "401" in body["detail"]


def test_upstream_response_error_returns_502(monkeypatch):
    """비-JSON 응답 같은 UpstreamResponseError 발생 시 422가 아닌 502."""

    async def fake_run_pipeline(*args, **kwargs):
        raise UpstreamResponseError("Upstream returned non-JSON response (status=502, len=42)")

    monkeypatch.setattr("app.routes.terms.run_pipeline", fake_run_pipeline)
    monkeypatch.setenv("UPSTAGE_API_KEY", "test-key")

    client = TestClient(app, raise_server_exceptions=False)
    response = _post(client)
    assert response.status_code == 502
    body = response.json()
    assert body["error"] == "upstream_error"
    assert "non-JSON" in body["detail"]


def test_schema_validation_error_returns_422(monkeypatch):
    """파이프라인에서 SchemaValidationError(도메인 스키마 검증 실패) 발생 시 422."""

    async def fake_run_pipeline(*args, **kwargs):
        raise SchemaValidationError("Extract response validation failed: missing field 'pricing'")

    monkeypatch.setattr("app.routes.terms.run_pipeline", fake_run_pipeline)
    monkeypatch.setenv("UPSTAGE_API_KEY", "test-key")

    client = TestClient(app, raise_server_exceptions=False)
    response = _post(client)
    assert response.status_code == 422
    body = response.json()
    assert body["error"] == "validation_error"
    assert "validation failed" in body["detail"]


def test_generic_value_error_not_caught_as_422(monkeypatch):
    """일반 ValueError(SchemaValidationError가 아닌)는 도메인 검증 핸들러로 잡히지 않아야 함.

    Copilot 리뷰 핵심: json.JSONDecodeError 같은 ValueError가 422로 오분류되던 버그 회귀 방지.
    """

    async def fake_run_pipeline(*args, **kwargs):
        # JSONDecodeError가 ValueError를 상속하므로 같은 카테고리
        raise ValueError("some unrelated internal value error")

    monkeypatch.setattr("app.routes.terms.run_pipeline", fake_run_pipeline)
    monkeypatch.setenv("UPSTAGE_API_KEY", "test-key")

    client = TestClient(app, raise_server_exceptions=False)
    response = _post(client)
    # 좁힌 핸들러는 SchemaValidationError만 잡으므로 일반 ValueError는 500
    assert response.status_code == 500
