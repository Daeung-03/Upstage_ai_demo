import json

import pytest

from ai.services.diff import (
    DiffResult,
    DiffSchemaError,
    summarize_version_diff,
)
from ai.services.settings import Settings
from ai.services.upstage import UpstageClient


@pytest.fixture
def settings(sample_api_key, sample_base_url) -> Settings:
    return Settings(upstage_api_key=sample_api_key, upstage_base_url=sample_base_url)


def _chat_response(payload: dict) -> dict:
    return {"choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}]}


async def test_summarize_version_diff_parses_changes(httpx_mock, settings):
    fake = {
        "diff_summary": "월 요금이 9,900원에서 11,000원으로 인상되었고 약관 변경 통지 기간이 30일에서 15일로 단축됨.",
        "changes": [
            {
                "category": "pricing",
                "direction": "less_consumer_friendly",
                "description": "이전: 월 9,900원 → 새 버전: 월 11,000원",
                "risk_level": "high",
            },
            {
                "category": "terms_changes",
                "direction": "less_consumer_friendly",
                "description": "이전: 변경 30일 전 통지 → 새 버전: 15일 전 통지",
                "risk_level": "medium",
            },
        ],
    }
    httpx_mock.add_response(
        url=f"{settings.upstage_base_url}/chat/completions",
        json=_chat_response(fake),
    )
    async with UpstageClient(settings) as client:
        res = await summarize_version_diff(
            client,
            old_text="월 9,900원, 변경 30일 전 통지",
            new_text="월 11,000원, 변경 15일 전 통지",
            service_name="TestStream",
        )
    assert isinstance(res, DiffResult)
    assert "9,900" in res.diff_summary and "11,000" in res.diff_summary
    assert len(res.changes) == 2
    assert res.changes[0].category == "pricing"
    assert res.changes[0].direction == "less_consumer_friendly"
    assert res.changes[0].risk_level == "high"
    assert res.changes[1].category == "terms_changes"


async def test_summarize_version_diff_accepts_empty_changes(httpx_mock, settings):
    """변경이 없을 때 빈 changes 리스트도 정상 처리."""
    fake = {"diff_summary": "주요 변경 사항 없음", "changes": []}
    httpx_mock.add_response(
        url=f"{settings.upstage_base_url}/chat/completions",
        json=_chat_response(fake),
    )
    async with UpstageClient(settings) as client:
        res = await summarize_version_diff(
            client, old_text="A", new_text="A", service_name="X"
        )
    assert res.diff_summary == "주요 변경 사항 없음"
    assert res.changes == []


async def test_summarize_version_diff_raises_on_bad_schema(httpx_mock, settings):
    """LLM 이 invalid category 보내면 DiffSchemaError."""
    fake = {
        "diff_summary": "x",
        "changes": [{"category": "INVALID_KEY", "direction": "neutral",
                     "description": "y", "risk_level": "low"}],
    }
    httpx_mock.add_response(
        url=f"{settings.upstage_base_url}/chat/completions",
        json=_chat_response(fake),
    )
    async with UpstageClient(settings) as client:
        with pytest.raises(DiffSchemaError, match="validation failed"):
            await summarize_version_diff(
                client, old_text="x", new_text="y", service_name="X"
            )


async def test_summarize_version_diff_sends_high_reasoning_effort(httpx_mock, settings):
    """CLAUDE.md 정확도 우선 — reasoning_effort 가 'high' 로 기본 설정되어 호출되어야."""
    httpx_mock.add_response(
        url=f"{settings.upstage_base_url}/chat/completions",
        json=_chat_response({"diff_summary": "ok", "changes": []}),
    )
    async with UpstageClient(settings) as client:
        await summarize_version_diff(
            client, old_text="a", new_text="b", service_name="X"
        )
    body = json.loads(httpx_mock.get_request().content)
    assert body["reasoning_effort"] == "high"
    assert body["temperature"] == 0
    assert body["model"] == "solar-pro3"
    # 응답 포맷 json_object 인지
    assert body["response_format"] == {"type": "json_object"}
