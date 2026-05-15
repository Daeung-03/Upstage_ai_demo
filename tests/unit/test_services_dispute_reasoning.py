"""ai/services/dispute_reasoning 단위 테스트.

Solar Pro 3 응답을 httpx_mock 로 stub 하고 prompt/응답 처리 정합성만 검증.
"""
from __future__ import annotations

import json

import pytest

from ai.services.dispute_reasoning import (
    ReasoningResult,
    ReasoningSchemaError,
    _format_cases,
    generate_clause_reasoning,
)
from ai.services.settings import Settings
from ai.services.upstage import UpstageClient


@pytest.fixture
def settings(sample_api_key, sample_base_url) -> Settings:
    return Settings(upstage_api_key=sample_api_key, upstage_base_url=sample_base_url)


def _chat_response(payload: dict) -> dict:
    return {"choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}]}


def _sample_match(idx: int = 1) -> dict:
    return {
        "title": f"사례 {idx}: 자동결제 환불 거부",
        "source": "한국소비자원",
        "summary": "14일 체험 후 자동 결제, 환불 거부",
        "outcome": "전액 환불 + 시정 권고",
        "matched_signals": ["pain_point:POST-01", "domain:OTT"],
    }


# ── _format_cases ────────────────────────────────────────


def test_format_cases_empty_returns_placeholder():
    assert _format_cases([]) == "(매칭된 사례 없음)"


def test_format_cases_includes_title_source_outcome_signals():
    block = _format_cases([_sample_match(1)])
    assert "사례 1: 자동결제 환불 거부" in block
    assert "한국소비자원" in block
    assert "전액 환불 + 시정 권고" in block
    assert "pain_point:POST-01" in block


def test_format_cases_indexes_starting_at_1():
    block = _format_cases([_sample_match(1), _sample_match(2)])
    # idx 1, 2 가 모두 등장
    assert "1. 사례 1" in block
    assert "2. 사례 2" in block


# ── generate_clause_reasoning ─────────────────────────────


async def test_generate_reasoning_parses_result(httpx_mock, settings):
    fake = {
        "reasoning": "이 자동 갱신 조항은 한국소비자원 2건 사례와 동일 패턴입니다. ...",
        "user_action": "결제 직후 7일 이내라면 환불 요청을 고려할 수 있습니다.",
    }
    httpx_mock.add_response(
        url=f"{settings.upstage_base_url}/chat/completions",
        json=_chat_response(fake),
    )
    async with UpstageClient(settings) as client:
        res = await generate_clause_reasoning(
            client,
            clause_title="자동 갱신 조항",
            clause_quote="구독은 해지될 때까지 유지됩니다",
            clause_description="자동 결제됨",
            risk_level="high",
            pain_point_id="POST-01",
            matches=[_sample_match()],
        )
    assert isinstance(res, ReasoningResult)
    assert "한국소비자원" in res.reasoning
    assert "환불" in res.user_action


async def test_generate_reasoning_sends_high_reasoning_effort(httpx_mock, settings):
    """CLAUDE.md 정확도 우선 — reasoning_effort=high + temperature=0."""
    httpx_mock.add_response(
        url=f"{settings.upstage_base_url}/chat/completions",
        json=_chat_response({"reasoning": "x", "user_action": "y"}),
    )
    async with UpstageClient(settings) as client:
        await generate_clause_reasoning(
            client,
            clause_title=None, clause_quote=None, clause_description=None,
            risk_level=None, pain_point_id=None,
            matches=[_sample_match()],
        )
    body = json.loads(httpx_mock.get_request().content)
    assert body["reasoning_effort"] == "high"
    assert body["temperature"] == 0
    assert body["model"] == "solar-pro3"
    assert body["response_format"] == {"type": "json_object"}


async def test_generate_reasoning_raises_on_bad_schema(httpx_mock, settings):
    """LLM 이 reasoning 키 누락 → ReasoningSchemaError."""
    httpx_mock.add_response(
        url=f"{settings.upstage_base_url}/chat/completions",
        json=_chat_response({"user_action": "only this"}),  # reasoning 누락
    )
    async with UpstageClient(settings) as client:
        with pytest.raises(ReasoningSchemaError, match="validation failed"):
            await generate_clause_reasoning(
                client,
                clause_title=None, clause_quote=None, clause_description=None,
                risk_level=None, pain_point_id=None,
                matches=[_sample_match()],
            )


async def test_generate_reasoning_user_action_optional(httpx_mock, settings):
    """user_action 은 빈 문자열 default — reasoning 만 있으면 통과."""
    httpx_mock.add_response(
        url=f"{settings.upstage_base_url}/chat/completions",
        json=_chat_response({"reasoning": "분쟁 사례 없음. 일반 위험도 분석."}),
    )
    async with UpstageClient(settings) as client:
        res = await generate_clause_reasoning(
            client,
            clause_title="t", clause_quote="q", clause_description="d",
            risk_level="medium", pain_point_id=None,
            matches=[],  # 사례 없는 경우도 LLM 호출은 가능 (fallback 텍스트로)
        )
    assert res.user_action == ""
    assert "일반 위험도" in res.reasoning
