# app/services/ai_client.py
from ai.pipeline import run_pipeline, AnalysisResult
from ai.services.upstage import UpstageClient
from ai.services.settings import get_settings

async def analyze_terms(
    file_bytes: bytes,
    filename: str,
    service_name: str,
    service_provider: str,
) -> AnalysisResult:
    settings = get_settings()
    async with UpstageClient(settings) as client:
        return await run_pipeline(
            client,
            file_bytes=file_bytes,
            filename=filename,
            service_name=service_name,
            service_provider=service_provider,
        )