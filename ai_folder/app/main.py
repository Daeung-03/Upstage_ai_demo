import logging

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.routes import terms
from services.extract import SchemaValidationError
from services.upstage import UpstreamResponseError

logger = logging.getLogger(__name__)

app = FastAPI(title="Upstage AI Terms Analysis", version="0.1.0")

app.include_router(terms.router)


@app.exception_handler(httpx.HTTPStatusError)
async def upstream_http_error_handler(request: Request, exc: httpx.HTTPStatusError) -> JSONResponse:
    logger.warning("upstream http error: %s %s", exc.response.status_code, request.url.path)
    return JSONResponse(
        status_code=502,
        content={"error": "upstream_error", "detail": f"Upstage API returned {exc.response.status_code}"},
    )


@app.exception_handler(UpstreamResponseError)
async def upstream_response_handler(request: Request, exc: UpstreamResponseError) -> JSONResponse:
    """업스트림이 비-JSON/빈 body 등 비정상 응답을 보냈을 때. 422가 아니라 502."""
    logger.warning("upstream response unparsable: %s | %s", request.url.path, exc)
    return JSONResponse(
        status_code=502,
        content={"error": "upstream_error", "detail": str(exc)[:500]},
    )


@app.exception_handler(SchemaValidationError)
async def schema_validation_handler(request: Request, exc: SchemaValidationError) -> JSONResponse:
    """LLM 응답이 SubscriptionTerms 스키마와 안 맞을 때만 422. 임의의 ValueError 잡지 않음."""
    logger.warning("schema validation failed: %s", request.url.path)
    return JSONResponse(
        status_code=422,
        content={"error": "validation_error", "detail": str(exc)[:500]},
    )


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
