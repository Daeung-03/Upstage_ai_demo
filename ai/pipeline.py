from __future__ import annotations

import logging
import time
import json
from typing import Literal, Any

from pydantic import BaseModel, Field

from sqlalchemy.ext.asyncio import AsyncSession

from ai.schemas.subscription import SubscriptionTerms
<<<<<<< Updated upstream
from ai.services.extract import extract_subscription_with_voting
=======
from ai.schemas.finance import FinanceTerms
from ai.schemas.insurance import InsuranceTerms 
from ai.services.extract import (
    extract_finance_with_voting,
    extract_insurance_with_voting,
    extract_subscription_with_voting,
)
>>>>>>> Stashed changes
from ai.services.ground import check_groundedness
from ai.services.parse import parse_document
from ai.services.summarize import KeyClause, summarize_risks
from ai.services.upstage import UpstageClient

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


# ── Chat Pipeline ───────────────────────────────────────
async def chat(
    client: UpstageClient,
    *,
    query: str,
    term_ids: list[str],
    history: list[dict],
    db: AsyncSession,
) -> dict:
    try:
        # 1. 질문 임베딩
        embed_resp = await client.post_json(
            "embeddings",
            json={
                "model": "solar-embedding-1-large-query",
                "input": [query],
            },
        )
        query_vector: list[float] = embed_resp["data"][0]["embedding"]
        vec_str = "[" + ",".join(str(v) for v in query_vector) + "]"

        # 2. pgvector top-5 검색
        from sqlalchemy import text
        sql = text("""
            SELECT id::text, content,
                   embedding <=> CAST(:vec AS halfvec(4096)) AS distance
            FROM term_chunks
            WHERE (:no_filter OR term_id = ANY(CAST(:term_ids AS uuid[])))
            ORDER BY distance ASC
            LIMIT 5
        """)
        result = await db.execute(sql, {
            "vec": vec_str,
            "term_ids": term_ids,
            "no_filter": len(term_ids) == 0,
        })
        chunks = result.fetchall()

        # 3. context 조립
        context = "\n\n".join(
            f"[{i+1}] {row.content}" for i, row in enumerate(chunks)
        )
        source_ids = [row.id for row in chunks]

        # 4. Solar Pro 3 답변 생성
        messages = [
            {
                "role": "system",
                "content": (
                    "당신은 약관 분석 전문가입니다. "
                    "주어진 약관 내용만 참고하여 답변하세요.\n\n"
                    f"[약관 내용]\n{context}"
                ),
            },
            *history,
            {"role": "user", "content": query},
        ]
        chat_resp = await client.post_json(
            "chat/completions",
            json={
                "model": "solar-pro3",
                "messages": messages,
            },
        )
        answer: str = chat_resp["choices"][0]["message"]["content"]

        # 5. Groundedness Check (인라인)
        try:
            ground_payload = {
                "model": "solar-pro3",
                "messages": [
                    {"role": "system", "content": "You are a groundedness checker. Reply JSON {\"grounded\": bool, \"score\": float}."},
                    {"role": "user", "content": f"context:\n{context}\n\nanswer:\n{answer}"},
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0,
            }
            ground_resp = await client.post_json("chat/completions", json=ground_payload)
            import json
            ground_data = json.loads(ground_resp["choices"][0]["message"]["content"])
            if not (ground_data.get("grounded") is True and float(ground_data.get("score", 0)) >= 0.6):
                answer += "\n\n⚠️ 일부 내용은 약관 원문에서 확인이 필요할 수 있습니다."
        except Exception:
            pass  # groundedness 실패해도 답변 반환

        return {"answer": answer, "sources": source_ids}

    except Exception:
        logger.exception("chat pipeline failed")
        return {"answer": "답변을 생성할 수 없습니다.", "sources": []}