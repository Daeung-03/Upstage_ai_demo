# app/services/ai_client.py
import itertools
from functools import lru_cache

from ai.pipeline import run_pipeline
from ai.services import dispute_reasoning as ai_dispute_reasoning
from ai.services import embed as ai_embed
from ai.services import diff as ai_diff
from ai.services.upstage import UpstageClient
from ai.services.settings import Settings as AISettings
from sqlalchemy.ext.asyncio import AsyncSession


@lru_cache(maxsize=1)
def _ai_settings() -> AISettings:
    """AISettings 를 정상 로딩 — Key #1/2/3/4 + base_url 등 모두 env 에서 읽어옴.

    이전엔 `model_construct(upstage_api_key=...)` 로 Key #1 만 강제 주입했지만,
    bulk upload 의 4-way 병렬을 위해 풀 전체를 들고 와야 함. 평가 격리 정책은
    Railway 환경에서 Key #2/3/4 를 비워두는 것으로 유지 가능 (그러면 풀 = [Key #1]).
    """
    return AISettings()


_key_cycler: "itertools.cycle[str] | None" = None


def _next_api_key() -> str:
    """현재 호출에 사용할 Upstage 키 — 풀 round-robin.

    asyncio 단일 스레드 환경이라 `next()` 는 원자적, 별도 락 불필요.
    """
    global _key_cycler
    if _key_cycler is None:
        pool = _ai_settings().app_api_key_pool
        if not pool:
            raise RuntimeError("no Upstage API key configured (need UPSTAGE_API_KEY)")
        _key_cycler = itertools.cycle(pool)
    return next(_key_cycler)


async def run_full_pipeline(
    file_bytes: bytes,
    filename: str,
    service_name: str,
    service_provider: str = "",
    domain: str = "subscription",
):
    """run_pipeline 래퍼. AnalysisResult 반환.

    domain: "subscription" (OTT/구독, 기본) | "finance" (전자금융/PG) |
    "insurance" (보험). 도메인별 schema/prompt 가 분기됨.
    """
    async with UpstageClient(_ai_settings(), api_key=_next_api_key()) as client:
        return await run_pipeline(
            client,
            file_bytes=file_bytes,
            filename=filename,
            service_name=service_name,
            service_provider=service_provider,
            domain=domain,
        )


async def embed_chunks(chunks: list[str]) -> list[list[float]]:
    """문서 인덱싱용 임베딩 (embedding-passage, 4096-d)."""
    if not chunks:
        return []
    async with UpstageClient(_ai_settings(), api_key=_next_api_key()) as client:
        return await ai_embed.embed_passages(client, chunks)


async def embed_query(text: str) -> list[float]:
    """검색 질의용 임베딩 (embedding-query, 4096-d)."""
    async with UpstageClient(_ai_settings(), api_key=_next_api_key()) as client:
        return await ai_embed.embed_query(client, text)


async def summarize_version_diff(
    old_text: str, new_text: str, service_name: str = ""
) -> "ai_diff.DiffResult":
    """버전 간 변경점 요약 — `process_version_update` 에서 호출."""
    async with UpstageClient(_ai_settings(), api_key=_next_api_key()) as client:
        return await ai_diff.summarize_version_diff(
            client,
            old_text=old_text,
            new_text=new_text,
            service_name=service_name,
        )


async def user_impacted_diff(
    *,
    old_text: str,
    new_text: str,
    service_name: str,
    old_clauses: list[str],
    new_clauses: list[str],
    user_context: dict | None,
) -> "ai_diff.UserImpactedDiffResult":
    """약관 변경의 *개별 사용자 영향* 까지 분석. semantic diff + LLM 1회.

    한 UpstageClient 세션 안에서 (a) compute_semantic_diff (embedding) 와
    (b) summarize_version_diff_for_user (chat completions) 를 순차 호출.
    """
    async with UpstageClient(_ai_settings(), api_key=_next_api_key()) as client:
        semantic = await ai_diff.compute_semantic_diff(
            client, old_clauses=old_clauses, new_clauses=new_clauses,
        )
        return await ai_diff.summarize_version_diff_for_user(
            client,
            old_text=old_text,
            new_text=new_text,
            service_name=service_name,
            user_context=user_context,
            semantic=semantic,
        )

async def generate_dispute_reasoning(
    *,
    clause_title: str | None,
    clause_quote: str | None,
    clause_description: str | None,
    risk_level: str | None,
    pain_point_id: str | None,
    matches: list[dict],
) -> "ai_dispute_reasoning.ReasoningResult":
    """TermClause + 매칭 사례 → "왜 위험한가" 자연어 reasoning. 첫 조회 시 caller
    가 lazy cache 로 한 번만 호출. accuracy-first (reasoning_effort=high)."""
    async with UpstageClient(_ai_settings(), api_key=_next_api_key()) as client:
        return await ai_dispute_reasoning.generate_clause_reasoning(
            client,
            clause_title=clause_title,
            clause_quote=clause_quote,
            clause_description=clause_description,
            risk_level=risk_level,
            pain_point_id=pain_point_id,
            matches=matches,
        )


async def chat_with_ai(
    query: str,
    term_ids: list[str],
    history: list[dict],
    db: AsyncSession,
) -> dict:
    try:
        from ai.pipeline import chat
        from ai.services.upstage import UpstageClient

        async with UpstageClient(_ai_settings(), api_key=_next_api_key()) as client:
            return await chat(
                client,
                query=query,
                term_ids=term_ids,
                history=history,
                db=db,
            )
    except ImportError:
        return {
            "answer": f"[STUB] '{query}'에 대한 답변입니다.",
            "sources": [],
        }
