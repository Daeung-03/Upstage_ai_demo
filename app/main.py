# app/main.py
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

# SQLAlchemy가 모든 모델을 인식하도록 명시적 import (순서 중요)
from app.models import enums  # noqa
from app.models.user import User  # noqa
from app.models.term import Term, TermVersion, TermChunk, TermClause  # noqa
from app.models.calendar import CalendarEvent, Notification  # noqa
from app.models.chat import ChatSession, ChatMessage  # noqa
from app.models.dispute import DisputeCase  # noqa

from app.routers import terms, chat, calendar, notifications
from ai.services.diff import DiffSchemaError
from ai.services.extract import SchemaValidationError
from ai.services.upstage import UpstreamResponseError

app = FastAPI(title="Term Tracker API", version="0.1.0")

app.include_router(terms.router,         prefix="/terms",         tags=["Terms"])
app.include_router(chat.router,          prefix="/chat",          tags=["Chat"])
app.include_router(calendar.router,      prefix="/calendar",      tags=["Calendar"])
app.include_router(notifications.router, prefix="/notifications", tags=["Notifications"])


# ── 글로벌 예외 → 구조화 HTTP 응답 ─────────────────────────
#
# 클라이언트가 "내 입력 잘못" vs "Upstage 외부 의존성 문제" vs "서버 내부 버그" 를
# 구분할 수 있도록 status code 와 응답 body 의 `error` 키로 카테고리를 명시한다.
#
#   - upstream_error (502): Upstage API 가 비-JSON 응답, 5xx, 401/429 등을 반환.
#                           서비스 장애 또는 quota 문제. 클라이언트 잘못 아님.
#   - validation_error (422): LLM 출력이 Pydantic 스키마 검증 실패. 일시적 모델
#                             output 이슈 가능 — 재시도해볼 가치 있음.
#   - 미지정 ValueError / 일반 예외: FastAPI 기본 500 (서버 코드 버그로 분류).


def _json(status: int, error: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": error, "detail": detail})


@app.exception_handler(UpstreamResponseError)
async def _upstream_response_error_handler(request: Request, exc: UpstreamResponseError):
    return _json(502, "upstream_error", str(exc))


@app.exception_handler(httpx.HTTPStatusError)
async def _httpx_status_error_handler(request: Request, exc: httpx.HTTPStatusError):
    # Upstage 가 4xx/5xx 를 반환했을 때. 401(키 무효)/429(rate limit)/5xx 모두 502 로
    # 통일 — 클라이언트 입장에선 모두 "외부 의존성 문제".
    upstream_status = exc.response.status_code if exc.response is not None else "?"
    url = str(exc.request.url) if exc.request is not None else "?"
    return _json(502, "upstream_error", f"{upstream_status} from {url}")


@app.exception_handler(SchemaValidationError)
async def _schema_validation_error_handler(request: Request, exc: SchemaValidationError):
    return _json(422, "validation_error", str(exc))


@app.exception_handler(DiffSchemaError)
async def _diff_schema_error_handler(request: Request, exc: DiffSchemaError):
    return _json(422, "validation_error", str(exc))


@app.get("/health")
async def health_check():
    return {"status": "ok"}
