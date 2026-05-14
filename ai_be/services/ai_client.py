from app.config import settings
from schemas.subscription import SubscriptionTerms
from services.pipeline import AnalysisResult, run_pipeline
from services.upstage import UpstageClient


async def analyze_terms(
    file_bytes: bytes,
    filename: str,
    service_name: str,
    service_provider: str,
) -> AnalysisResult:
    async with UpstageClient(settings) as client:
        return await run_pipeline(
            client,
            file_bytes=file_bytes,
            filename=filename,
            service_name=service_name,
            service_provider=service_provider,
        )