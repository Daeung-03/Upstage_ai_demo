import httpx
import pytest

from services.settings import Settings
from services.upstage import UpstageClient, UpstreamResponseError


@pytest.fixture
def settings(sample_api_key, sample_base_url) -> Settings:
    return Settings(upstage_api_key=sample_api_key, upstage_base_url=sample_base_url)


async def test_client_sends_bearer_token(httpx_mock, settings):
    httpx_mock.add_response(
        url=f"{settings.upstage_base_url}/test",
        json={"ok": True},
    )
    async with UpstageClient(settings) as client:
        r = await client.post_json("/test", json={"x": 1})
    assert r["ok"] is True
    request = httpx_mock.get_request()
    assert request.headers["authorization"] == f"Bearer {settings.upstage_api_key}"


async def test_client_retries_on_5xx(httpx_mock, settings):
    httpx_mock.add_response(status_code=503, url=f"{settings.upstage_base_url}/r")
    httpx_mock.add_response(status_code=503, url=f"{settings.upstage_base_url}/r")
    httpx_mock.add_response(json={"ok": True}, url=f"{settings.upstage_base_url}/r")
    async with UpstageClient(settings) as client:
        r = await client.post_json("/r", json={})
    assert r["ok"] is True
    assert len(httpx_mock.get_requests()) == 3


async def test_client_raises_on_4xx(httpx_mock, settings):
    httpx_mock.add_response(
        status_code=400,
        url=f"{settings.upstage_base_url}/bad",
        json={"error": "invalid"},
    )
    async with UpstageClient(settings) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await client.post_json("/bad", json={})


async def test_client_raises_upstream_response_error_on_non_json(httpx_mock, settings):
    """200이지만 응답이 JSON이 아니면 UpstreamResponseError (도메인 검증 오류 아님)."""
    httpx_mock.add_response(
        url=f"{settings.upstage_base_url}/html",
        status_code=200,
        content=b"<html><body>service unavailable</body></html>",
        headers={"Content-Type": "text/html"},
    )
    async with UpstageClient(settings) as client:
        with pytest.raises(UpstreamResponseError, match="non-JSON"):
            await client.post_json("/html", json={})


async def test_client_captures_usage_and_snapshot_clears(httpx_mock, settings):
    """응답의 top-level usage가 누적되고, snapshot_usage()가 비우면서 반환."""
    httpx_mock.add_response(
        url=f"{settings.upstage_base_url}/a",
        json={"ok": True, "usage": {"prompt_tokens": 100, "total_tokens": 150}},
    )
    httpx_mock.add_response(
        url=f"{settings.upstage_base_url}/b",
        json={"ok": True, "usage": {"pages": 3}},
    )
    httpx_mock.add_response(
        url=f"{settings.upstage_base_url}/c",
        json={"ok": True},  # usage 없는 응답
    )
    async with UpstageClient(settings) as client:
        await client.post_json("/a", json={})
        await client.post_json("/b", json={})
        await client.post_json("/c", json={})
        snap1 = client.snapshot_usage()
        snap2 = client.snapshot_usage()
    assert len(snap1) == 2  # /c 는 usage 없으니 제외
    assert snap1[0]["prompt_tokens"] == 100
    assert snap1[1]["pages"] == 3
    assert snap2 == []  # snapshot은 비웠으므로


async def test_retry_does_not_sleep_after_final_attempt(httpx_mock, settings, monkeypatch):
    """3번 다 5xx 실패 시 sleep은 2번만 (시도 1과 2 사이, 2와 3 사이). 3번째 후 즉시 raise."""
    httpx_mock.add_response(status_code=503, url=f"{settings.upstage_base_url}/fail", is_reusable=True)

    sleep_calls: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    monkeypatch.setattr("services.upstage.asyncio.sleep", fake_sleep)

    async with UpstageClient(settings) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await client.post_json("/fail", json={})
    # MAX_RETRIES=3 → 첫 시도와 두 번째 시도 후에만 sleep, 마지막 시도 후엔 sleep 없이 즉시 raise
    assert len(sleep_calls) == 2
    assert sleep_calls == [0.5, 1.0]  # 0.5 * 2^0, 0.5 * 2^1
