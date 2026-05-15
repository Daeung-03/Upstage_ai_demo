# app/routers/terms.py
import uuid
from datetime import date 
from typing import Optional
from fastapi import APIRouter, Depends, File, Form, UploadFile, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.calendar import Notification, NotificationStatus
from app.schemas.term import (
    TermUploadResponse, TermListResponse, TermSummary,
    TermDetailResponse, TermVersionDetail, ClauseDetail,  # 추가
    TermUpdateResponse, SearchRequest, SearchResponse
)
from app.services import term_service

router = APIRouter()

# 임시 하드코딩 user_id (Thread 9에서 JWT로 교체)
TEMP_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


@router.post("/upload", response_model=TermUploadResponse, status_code=201)
async def upload_term(
    service_name: str = Form(...),
    subscribed_at: Optional[str] = Form(None),
    domain: str = Form("ETC"),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    file_bytes = await file.read()
    file_url = f"/files/{file.filename}"

    # str → date 변환
    try:
        parsed_date = date.fromisoformat(subscribed_at) if subscribed_at else None
    except ValueError:
        parsed_date = None

    term, version = await term_service.process_upload(
        db=db,
        user_id=TEMP_USER_ID,
        service_name=service_name,
        subscribed_at=parsed_date,  # ← str 대신 date 객체로
        file_bytes=file_bytes,
        file_url=file_url,
        domain=domain,
    )

    await db.commit()        # ← 추가
    await db.refresh(version)  # ← 추가

    return TermUploadResponse(
        id=term.id,
        service_name=term.service_name,
        domain=term.domain,
        status=term.status,
        version=version.version,
        created_at=term.created_at,
    )


@router.get("", response_model=TermListResponse)
async def list_terms(
    domain: Optional[str] = None,
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    terms = await term_service.get_terms(db, TEMP_USER_ID, domain, status)
    items = [
        TermSummary(
            id=t.id,
            service_name=t.service_name,
            domain=t.domain,
            status=t.status,
            subscribed_at=t.subscribed_at,
            latest_version=(
                next((v.version for v in t.versions if v.is_latest), None)
                or max((v.version for v in t.versions), default=0)
            ),
            created_at=t.created_at,
        )
        for t in terms
    ]
    return TermListResponse(items=items, total=len(items))


@router.get("/{term_id}", response_model=TermDetailResponse)
async def get_term(
    term_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    term = await term_service.get_term_detail(db, term_id, TEMP_USER_ID)
    if not term:
        raise HTTPException(status_code=404, detail="약관을 찾을 수 없습니다.")

    return TermDetailResponse(
        id=term.id,
        service_name=term.service_name,
        domain=term.domain,
        status=term.status,
        file_url=term.file_url,
        subscribed_at=term.subscribed_at,
        created_at=term.created_at,
        versions=[
            TermVersionDetail(
                id=v.id,
                version=v.version,
                summary=v.summary,
                diff_summary=v.diff_summary,
                is_latest=v.is_latest,
                created_at=v.created_at,
                clauses=[
                    ClauseDetail(
                        id=c.id,
                        clause_type=c.clause_type,
                        title=c.title,
                        original_text=c.original_text,
                        plain_text=c.plain_text,
                    )
                    for c in v.clauses
                ],
            )
            for v in term.versions
        ],
    )


@router.post("/{term_id}/update", response_model=TermUpdateResponse, status_code=201)
async def update_term(
    term_id: uuid.UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    term = await term_service.get_term_detail(db, term_id, TEMP_USER_ID)
    if not term:
        raise HTTPException(status_code=404, detail="약관을 찾을 수 없습니다.")

    file_bytes = await file.read()
    file_url = f"/files/{file.filename}"

    new_version = await term_service.process_version_update(
        db=db,
        term_id=term_id,
        user_id=TEMP_USER_ID,
        file_bytes=file_bytes,
        file_url=file_url,
    )

    new_notification = Notification(
        user_id=term.user_id,
        term_id=term.id,
        version_id=new_version.id,
        title=f"[{term.service_name}] 약관이 업데이트됐어요",
        diff_summary=new_version.diff_summary,
        status=NotificationStatus.UNREAD,
    )
    db.add(new_notification)
    await db.commit() # ← 여기서 version + notification 한 번에 커밋
    await db.refresh(new_version)

    return TermUpdateResponse(
        term_id=term_id,
        new_version=new_version.version,
        diff_summary=new_version.diff_summary,
    )


@router.post("/{term_id}/search", response_model=SearchResponse)
async def search_term(
    term_id: uuid.UUID,
    body: SearchRequest,
    db: AsyncSession = Depends(get_db),
):
    results = await term_service.search_chunks(db, term_id, body.query, body.top_k or 5)
    return SearchResponse(results=results)