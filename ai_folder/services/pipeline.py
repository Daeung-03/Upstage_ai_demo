from __future__ import annotations

import logging
import time
from typing import Any

from pydantic import BaseModel, Field

from schemas.subscription import SubscriptionTerms
from services.extract import extract_subscription_with_voting
from services.ground import check_groundedness
from services.parse import parse_document
from services.summarize import KeyClause, summarize_risks
from services.upstage import UpstageClient

logger = logging.getLogger(__name__)


class StageTiming(BaseModel):
    stage: str
    seconds: float


class StageUsage(BaseModel):
    """단계별 Upstage 토큰/페이지 사용량 집계 (한 단계가 여러 호출일 경우 합산)."""

    stage: str
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0  # solar-pro3 chain-of-thought 토큰
    total_tokens: int = 0
    pages: int = 0  # Document Parse 전용


def _aggregate_usages(stage: str, usages: list[dict[str, Any]]) -> StageUsage:
    """다수의 raw usage dict를 StageUsage 하나로 합산."""
    agg = StageUsage(stage=stage, calls=len(usages))
    for u in usages:
        agg.prompt_tokens += int(u.get("prompt_tokens") or 0)
        agg.completion_tokens += int(u.get("completion_tokens") or 0)
        agg.total_tokens += int(u.get("total_tokens") or 0)
        details = u.get("completion_tokens_details") or {}
        agg.reasoning_tokens += int(details.get("reasoning_tokens") or 0)
        agg.pages += int(u.get("pages") or 0)
    return agg


class AnalysisResult(BaseModel):
    terms: SubscriptionTerms
    summary: str
    key_clauses: list[KeyClause]
    ungrounded_clauses: list[KeyClause] = Field(default_factory=list)
    grounded: bool
    timings: list[StageTiming] = Field(default_factory=list)
    usage: list[StageUsage] = Field(default_factory=list)


async def run_pipeline(
    client: UpstageClient,
    *,
    file_bytes: bytes,
    filename: str,
    service_name: str,
    service_provider: str,
) -> AnalysisResult:
    timings: list[StageTiming] = []
    usage: list[StageUsage] = []
    # 호출 전 누적 버퍼 초기화 (이전 요청 잔여 방지)
    client.snapshot_usage()

    t0 = time.perf_counter()
    parsed = await parse_document(client, file_bytes=file_bytes, filename=filename)
    timings.append(StageTiming(stage="parse", seconds=time.perf_counter() - t0))
    usage.append(_aggregate_usages("parse", client.snapshot_usage()))

    t0 = time.perf_counter()
    terms = await extract_subscription_with_voting(
        client,
        parsed_markdown=parsed.markdown,
        parsed_elements=parsed.elements,
        service_name=service_name,
        service_provider=service_provider,
    )
    timings.append(StageTiming(stage="extract", seconds=time.perf_counter() - t0))
    usage.append(_aggregate_usages("extract", client.snapshot_usage()))

    t0 = time.perf_counter()
    summary = await summarize_risks(client, terms=terms)
    timings.append(StageTiming(stage="summarize", seconds=time.perf_counter() - t0))
    usage.append(_aggregate_usages("summarize", client.snapshot_usage()))

    t0 = time.perf_counter()
    ground = await check_groundedness(client, summary=summary, source_markdown=parsed.markdown)
    timings.append(StageTiming(stage="ground", seconds=time.perf_counter() - t0))
    usage.append(_aggregate_usages("ground", client.snapshot_usage()))

    total_tokens = sum(u.total_tokens for u in usage)
    logger.info(
        "pipeline complete service=%s timings=%s grounded=%s total_tokens=%d",
        service_name,
        [(t.stage, round(t.seconds, 2)) for t in timings],
        ground.overall_grounded,
        total_tokens,
    )
    return AnalysisResult(
        terms=terms,
        summary=ground.summary,
        key_clauses=ground.grounded_clauses,
        ungrounded_clauses=ground.ungrounded_clauses,
        grounded=ground.overall_grounded,
        timings=timings,
        usage=usage,
    )
