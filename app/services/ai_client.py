# app/services/ai_client.py
from ai.pipeline import run_pipeline
from ai.services import embed as ai_embed
from ai.services import diff as ai_diff
from ai.services.upstage import UpstageClient
from ai.services.settings import Settings as AISettings
from app.config import get_settings
from sqlalchemy.ext.asyncio import AsyncSession


def _ai_settings() -> AISettings:
    app_settings = get_settings()
    # BaseSettings 자동 로딩 우회 → api_key만 직접 넘기기
    return AISettings.model_construct(upstage_api_key=app_settings.upstage_api_key)


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
    async with UpstageClient(_ai_settings()) as client:
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
    async with UpstageClient(_ai_settings()) as client:
        return await ai_embed.embed_passages(client, chunks)


async def embed_query(text: str) -> list[float]:
    """검색 질의용 임베딩 (embedding-query, 4096-d)."""
    async with UpstageClient(_ai_settings()) as client:
        return await ai_embed.embed_query(client, text)


async def summarize_version_diff(
    old_text: str, new_text: str, service_name: str = ""
) -> "ai_diff.DiffResult":
    """버전 간 변경점 요약 — `process_version_update` 에서 호출."""
    async with UpstageClient(_ai_settings()) as client:
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
    async with UpstageClient(_ai_settings()) as client:
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

async def chat_with_ai(
    query: str,
    term_ids: list[str],
    history: list[dict],
    db: AsyncSession,
) -> dict:
    try:
        from ai.pipeline import chat
        from ai.services.upstage import UpstageClient
        from ai.services.settings import Settings as AISettings   # ← ai settings 사용

        settings = AISettings()
        async with UpstageClient(settings) as client:
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
