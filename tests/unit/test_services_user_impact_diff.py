"""summarize_version_diff_for_user 단위 테스트.

LLM 호출은 httpx_mock 으로 mock. user_context 와 semantic 결과가 prompt 에
정확히 주입되는지 + UserImpactedDiffResult 검증 정합성 확인.
"""

from __future__ import annotations

import json

import pytest

from ai.services.diff import (
    SemanticDiffResult,
    UserImpactedDiffResult,
    _format_semantic_summary,
    _format_user_context,
    summarize_version_diff_for_user,
)
from ai.services.settings import Settings
from ai.services.upstage import UpstageClient


@pytest.fixture
def settings(sample_api_key, sample_base_url):
    return Settings(upstage_api_key=sample_api_key, upstage_base_url=sample_base_url)


def _llm_response(payload: dict) -> dict:
    return {"choices": [{"message": {"content": json.dumps(payload)}}]}


# === pure helpers ===


def test_format_user_context_known_keys():
    s = _format_user_context(
        {"subscribed_at": "2026-01-01", "plan": "PRO", "remaining_period_days": 12}
    )
    assert "가입일: 2026-01-01" in s
    assert "현재 플랜: PRO" in s
    assert "잔여 기간 (일): 12" in s


def test_format_user_context_empty_or_none():
    assert "컨텍스트 제공되지 않음" in _format_user_context(None)
    assert "컨텍스트 제공되지 않음" in _format_user_context({})
    # 모든 값이 None
    assert "컨텍스트 제공되지 않음" in _format_user_context(
        {"subscribed_at": None, "plan": None}
    )


def test_format_user_context_extra_keys_passed_through():
    s = _format_user_context({"subscribed_at": "2026-01-01", "promo_code": "XMAS"})
    assert "가입일: 2026-01-01" in s
    assert "promo_code: XMAS" in s


def test_format_semantic_summary_no_changes():
    s = _format_semantic_summary(SemanticDiffResult(counts={}))
    assert "변경 없음" in s


def test_format_semantic_summary_mixed_counts():
    s = _format_semantic_summary(SemanticDiffResult(
        counts={"phrasing_only": 5, "substantive": 2, "added": 1, "removed": 0}
    ))
    assert "표현만 변경 5건" in s
    assert "실질 변경 2건" in s
    assert "신규 조항 1건" in s
    assert "삭제 조항" not in s  # 0 건은 생략


def test_format_semantic_summary_none():
    assert "미실행" in _format_semantic_summary(None)


# === full call with httpx_mock ===


async def test_summarize_version_diff_for_user_basic(httpx_mock, settings):
    httpx_mock.add_response(
        url=f"{settings.upstage_base_url}/chat/completions",
        json=_llm_response({
            "diff_summary": "갱신 통지 기간이 30일에서 7일로 단축됨.",
            "changes": [{
                "category": "terms_changes",
                "direction": "less_consumer_friendly",
                "description": "이전: 30일 전 통지 → 새 버전: 7일 전 통지",
                "risk_level": "high",
            }],
            "user_impact": (
                "PRO 플랜 가입자 (가입일 2026-01-01) 는 다음 갱신일 2026-07-01 전에 "
                "변경된 7일 통지 기준이 적용됩니다. 현재 잔여 12일이라 변경 시행일 전에 "
                "결정 가능. 갱신 거부를 원하면 *지금 1주일 내* 해지 검토 권장."
            ),
        }),
    )

    semantic = SemanticDiffResult(
        counts={"phrasing_only": 1, "substantive": 1, "added": 0, "removed": 0}
    )

    async with UpstageClient(settings) as client:
        result = await summarize_version_diff_for_user(
            client,
            old_text="기존 약관 본문 ...",
            new_text="신규 약관 본문 ...",
            service_name="Toss",
            user_context={
                "subscribed_at": "2026-01-01",
                "plan": "PRO",
                "remaining_period_days": 12,
                "next_renewal_at": "2026-07-01",
            },
            semantic=semantic,
        )

    assert isinstance(result, UserImpactedDiffResult)
    assert "7일" in result.diff_summary or "단축" in result.diff_summary
    assert "PRO" in result.user_impact
    assert result.semantic_counts == {
        "phrasing_only": 1, "substantive": 1, "added": 0, "removed": 0,
    }


async def test_summarize_version_diff_for_user_no_context(httpx_mock, settings):
    """user_context 없어도 동작 — user_impact 는 '컨텍스트 없음' 으로."""
    httpx_mock.add_response(
        url=f"{settings.upstage_base_url}/chat/completions",
        json=_llm_response({
            "diff_summary": "주요 변경 사항 없음",
            "changes": [],
            "user_impact": "컨텍스트 제공되지 않아 개별 영향 분석 불가.",
        }),
    )
    async with UpstageClient(settings) as client:
        result = await summarize_version_diff_for_user(
            client,
            old_text="A", new_text="A",
            service_name="X",
            user_context=None,
            semantic=None,
        )
    assert result.user_impact.startswith("컨텍스트")
    assert result.semantic_counts == {}


async def test_summarize_version_diff_for_user_prompt_contains_context(
    httpx_mock, settings
):
    """실제로 prompt 에 user_context / semantic_summary 가 들어가는지 확인."""
    httpx_mock.add_response(
        url=f"{settings.upstage_base_url}/chat/completions",
        json=_llm_response({
            "diff_summary": "x", "changes": [], "user_impact": "y",
        }),
    )
    async with UpstageClient(settings) as client:
        await summarize_version_diff_for_user(
            client,
            old_text="OLD", new_text="NEW",
            service_name="Netflix",
            user_context={"plan": "BASIC", "subscribed_at": "2025-06-15"},
            semantic=SemanticDiffResult(counts={"phrasing_only": 3}),
        )
    req = httpx_mock.get_request()
    body = json.loads(req.content)
    user_msg = body["messages"][1]["content"]
    assert "현재 플랜: BASIC" in user_msg
    assert "가입일: 2025-06-15" in user_msg
    assert "표현만 변경 3건" in user_msg
    assert "OLD" in user_msg and "NEW" in user_msg
