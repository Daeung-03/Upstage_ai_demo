# app/services/ai_client.py
from ai.pipeline import run_pipeline
from ai.services.upstage import UpstageClient
from ai.services.settings import Settings as AISettings
from app.config import get_settings


def _ai_settings() -> AISettings:
    app_settings = get_settings()
    # BaseSettings 자동 로딩 우회 → api_key만 직접 넘기기
    return AISettings.model_construct(upstage_api_key=app_settings.upstage_api_key)


async def run_full_pipeline(
    file_bytes: bytes,
    filename: str,
    service_name: str,
    service_provider: str = "",
):
    """run_pipeline 래퍼. AnalysisResult 반환."""
    async with UpstageClient(_ai_settings()) as client:
        return await run_pipeline(
            client,
            file_bytes=file_bytes,
            filename=filename,
            service_name=service_name,
            service_provider=service_provider,
        )


async def embed_chunks(chunks: list[str]) -> list[list[float]]:
    # TODO: AI팀 R1 구현 완료 시 교체
    return [[0.0] * 4096 for _ in chunks]


async def extract_dates(text: str) -> list[dict]:
    # TODO: AI팀 R2 구현 완료 시 교체
    return []

async def chat_with_ai(
    query: str,
    term_ids: list[str],
    history: list[dict],
) -> dict:
    """
    R3 chat stub — AI팀 구현 완료 시 교체
    from ai.pipeline import chat  으로 교체 예정
    """
    try:
        from ai.pipeline import chat  # AI팀 구현 후 활성화
        return await chat(query=query, term_ids=term_ids, history=history)
    except ImportError:
        # --- STUB ---
        return {
            "answer": f"[STUB] '{query}'에 대한 답변입니다. AI팀 구현 후 교체됩니다.",
            "sources": [],
        }