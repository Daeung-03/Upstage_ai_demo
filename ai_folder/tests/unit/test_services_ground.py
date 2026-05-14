import json

import pytest

from services.ground import GroundednessResult, check_groundedness
from services.settings import Settings
from services.summarize import KeyClause, KeyClauseCitation, SummaryResult
from services.upstage import UpstageClient


@pytest.fixture
def settings(sample_api_key, sample_base_url):
    return Settings(upstage_api_key=sample_api_key, upstage_base_url=sample_base_url)


@pytest.fixture
def sample_summary():
    return SummaryResult(
        summary="자동결제와 의사표시 의제 조항이 있습니다.",
        key_clauses=[
            KeyClause(
                title="자동 갱신",
                description="이의 없으면 동의로 간주됩니다.",
                risk_level="high",
                pain_point_id="MID-02",
                citation=KeyClauseCitation(page=2, quote="이의 없으면 동의로 간주"),
            ),
            KeyClause(
                title="가공의 조항",
                description="실제 약관에 없는 가짜 조항입니다.",
                risk_level="medium",
                pain_point_id="PRE-04",
                citation=KeyClauseCitation(page=99, quote="이런 문구는 원문에 없음"),
            ),
        ],
    )


def _grounded_response(grounded: bool, score: float) -> dict:
    return {"choices": [{"message": {"content": json.dumps({"grounded": grounded, "score": score})}}]}


async def test_check_groundedness_filters_ungrounded(httpx_mock, settings, sample_summary):
    # clause 1: grounded
    httpx_mock.add_response(
        url=f"{settings.upstage_base_url}/chat/completions",
        json=_grounded_response(True, 0.95),
    )
    # clause 2: not grounded
    httpx_mock.add_response(
        url=f"{settings.upstage_base_url}/chat/completions",
        json=_grounded_response(False, 0.12),
    )
    # summary: grounded
    httpx_mock.add_response(
        url=f"{settings.upstage_base_url}/chat/completions",
        json=_grounded_response(True, 0.90),
    )
    async with UpstageClient(settings) as client:
        result = await check_groundedness(
            client,
            summary=sample_summary,
            source_markdown="...이의 없으면 동의로 간주합니다...",
        )
    assert isinstance(result, GroundednessResult)
    assert len(result.grounded_clauses) == 1
    assert result.grounded_clauses[0].title == "자동 갱신"
    assert len(result.ungrounded_clauses) == 1
    assert result.ungrounded_clauses[0].title == "가공의 조항"
    # 하나라도 ungrounded면 overall_grounded는 False
    assert result.overall_grounded is False


async def test_check_groundedness_marks_overall_false_when_summary_ungrounded(
    httpx_mock, settings, sample_summary
):
    """모든 clause가 grounded더라도 summary 자체가 hallucinated면 overall_grounded=False."""
    # 두 clause 모두 grounded
    httpx_mock.add_response(
        url=f"{settings.upstage_base_url}/chat/completions",
        json=_grounded_response(True, 0.95),
    )
    httpx_mock.add_response(
        url=f"{settings.upstage_base_url}/chat/completions",
        json=_grounded_response(True, 0.90),
    )
    # summary: not grounded
    httpx_mock.add_response(
        url=f"{settings.upstage_base_url}/chat/completions",
        json=_grounded_response(False, 0.15),
    )
    async with UpstageClient(settings) as client:
        result = await check_groundedness(
            client,
            summary=sample_summary,
            source_markdown="원문...",
        )
    assert len(result.grounded_clauses) == 2
    assert len(result.ungrounded_clauses) == 0
    assert result.overall_grounded is False  # summary가 ungrounded이므로


async def test_check_groundedness_strict_bool_rejects_string_true(httpx_mock, settings):
    """LLM이 '{grounded: "true"}' 같은 문자열을 돌려줘도 ungrounded로 안전 처리."""
    summary = SummaryResult(
        summary="요약",
        key_clauses=[
            KeyClause(
                title="t", description="d", risk_level="low",
                pain_point_id="PRE-01", citation=KeyClauseCitation(page=1, quote="q"),
            ),
        ],
    )
    # 문자열 "true" 반환 → strict bool 비교에서 ungrounded로 처리되어야 함
    httpx_mock.add_response(
        url=f"{settings.upstage_base_url}/chat/completions",
        json={"choices": [{"message": {"content": json.dumps({"grounded": "true", "score": 0.99})}}]},
    )
    httpx_mock.add_response(
        url=f"{settings.upstage_base_url}/chat/completions",
        json=_grounded_response(True, 0.95),
    )
    async with UpstageClient(settings) as client:
        result = await check_groundedness(client, summary=summary, source_markdown="...")
    assert len(result.grounded_clauses) == 0
    assert len(result.ungrounded_clauses) == 1
