from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel

from services.pipeline import AnalysisResult, run_pipeline
from services.settings import Settings, get_settings
from services.upstage import UpstageClient

router = APIRouter(prefix="/v1/terms", tags=["terms"])


class AnalyzeResponse(BaseModel):
    terms: dict
    summary: str
    key_clauses: list[dict]
    ungrounded_clauses: list[dict]
    grounded: bool
    timings: list[dict]
    usage: list[dict]


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_terms(
    file: UploadFile = File(...),
    service_name: str = Form(...),
    service_provider: str = Form(...),
    settings: Settings = Depends(get_settings),
) -> AnalyzeResponse:
    file_bytes = await file.read()
    async with UpstageClient(settings) as client:
        result: AnalysisResult = await run_pipeline(
            client,
            file_bytes=file_bytes,
            filename=file.filename or "upload",
            service_name=service_name,
            service_provider=service_provider,
        )
    return AnalyzeResponse(
        terms=result.terms.model_dump(),
        summary=result.summary,
        key_clauses=[c.model_dump() for c in result.key_clauses],
        ungrounded_clauses=[c.model_dump() for c in result.ungrounded_clauses],
        grounded=result.grounded,
        timings=[t.model_dump() for t in result.timings],
        usage=[u.model_dump() for u in result.usage],
    )
