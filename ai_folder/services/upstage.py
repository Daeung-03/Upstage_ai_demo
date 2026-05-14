from __future__ import annotations

import asyncio
import json as _json
import logging
from typing import Any

import httpx

from services.settings import Settings

logger = logging.getLogger(__name__)


class UpstreamResponseError(Exception):
    """Upstream API returned a response we couldn't parse (non-JSON, empty, malformed)."""


class UpstageClient:
    """Thin async wrapper around Upstage HTTP APIs with auth + retry."""

    MAX_RETRIES = 3
    RETRY_BACKOFF_S = 0.5

    def __init__(self, settings: Settings, timeout_s: float = 300.0):
        self.settings = settings
        self._client = httpx.AsyncClient(
            base_url=settings.upstage_base_url,
            headers={"Authorization": f"Bearer {settings.upstage_api_key}"},
            timeout=timeout_s,
        )
        # 호출별 usage 누적 — 파이프라인이 단계별로 snapshot_usage()로 빼간다.
        self._usages: list[dict[str, Any]] = []

    async def __aenter__(self) -> "UpstageClient":
        return self

    async def __aexit__(self, *exc) -> None:
        await self._client.aclose()

    def snapshot_usage(self) -> list[dict[str, Any]]:
        """누적된 usage 리스트를 반환하고 내부 버퍼를 비움 (단계 경계용)."""
        usages = self._usages
        self._usages = []
        return usages

    async def post_json(self, path: str, *, json: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", path, json=json)

    async def post_multipart(
        self,
        path: str,
        *,
        files: dict[str, Any],
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return await self._request("POST", path, files=files, data=data)

    async def _backoff_if_more_attempts(self, attempt: int, reason: str) -> None:
        """마지막 시도면 sleep 없이 즉시 실패. 그 외엔 exponential backoff."""
        if attempt < self.MAX_RETRIES - 1:
            delay = self.RETRY_BACKOFF_S * (2**attempt)
            logger.info("upstage retry (%s), sleeping %.2fs (attempt %d)", reason, delay, attempt + 1)
            await asyncio.sleep(delay)

    async def _request(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        last_exc: Exception | None = None
        for attempt in range(self.MAX_RETRIES):
            try:
                resp = await self._client.request(method, path, **kwargs)
                if resp.status_code >= 500:
                    last_exc = httpx.HTTPStatusError(
                        f"server {resp.status_code}", request=resp.request, response=resp
                    )
                    await self._backoff_if_more_attempts(attempt, f"{resp.status_code}")
                    continue
                resp.raise_for_status()
                logger.info("upstage %s %s -> %s", method, path, resp.status_code)
                # resp.json()이 ValueError를 던질 수 있어 (HTML 오류 페이지, 빈 body 등)
                # UpstreamResponseError로 명시적 변환 — 도메인 검증 오류와 구분됨.
                try:
                    data = resp.json()
                except _json.JSONDecodeError as e:
                    raise UpstreamResponseError(
                        f"Upstream returned non-JSON response "
                        f"(status={resp.status_code}, len={len(resp.content)})"
                    ) from e
                # Upstage는 일반적으로 top-level "usage" 객체 (chat/completions, document-digitization 등)
                usage = data.get("usage") if isinstance(data, dict) else None
                if isinstance(usage, dict):
                    self._usages.append(usage)
                return data
            except httpx.TransportError as e:
                last_exc = e
                await self._backoff_if_more_attempts(attempt, "transport_error")
        assert last_exc is not None
        raise last_exc
