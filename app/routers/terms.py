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
    TermUpdateResponse, SearchRequest, SearchResponse,
    UserSearchRequest, UserSearchResponse, UserChunkResult,
    UserImpactDiffRequest, UserImpactDiffResponse, DiffChangeOut,
    SubCategoryRecommendations,
)
from app.models.sub_category import recommendations_for
from app.services import term_service

router = APIRouter()

# 임시 하드코딩 user_id (Thread 9에서 JWT로 교체)
TEMP_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


@router.post(
    "/upload",
    response_model=TermUploadResponse,
    status_code=201,
    summary="약관 업로드 + 4-stage AI 파이프라인 실행",
    description=(
        "PDF/HTML 약관을 업로드하면 Document Parse → Solar Pro 3 추출 → 요약 → "
        "Groundedness Check 까지 동기 실행되고 결과가 DB 에 저장됩니다.\n\n"
        "**Form 필드**\n"
        "- `file` (필수): PDF 또는 HTML 약관 본문.\n"
        "- `service_name` (필수): 서비스명 (예: \"Netflix\", \"삼성 실손의료보험\").\n"
        "- `subscribed_at` (선택): ISO 8601 date (YYYY-MM-DD). 캘린더 이벤트 자동 계산에 사용.\n"
        "- `domain` (선택, 기본 `ETC`): 1단계 enum — FINANCE/OTT/INSURANCE/APP/MEDICAL/TELECOM/ETC.\n"
        "- `sub_category` (선택): domain 안의 세부 분류 (예: INSURANCE 內 \"실손의료보험\"). "
        "권장 vocab 은 `GET /terms/sub-categories?domain=...` 참조."
    ),
    tags=["Terms / 업로드"],
)
async def upload_term(
    service_name: str = Form(...),
    subscribed_at: Optional[str] = Form(None),
    domain: str = Form("ETC"),
    sub_category: Optional[str] = Form(None),
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
        sub_category=sub_category,
    )

    await db.commit()        # ← 추가
    await db.refresh(version)  # ← 추가

    return TermUploadResponse(
        id=term.id,
        service_name=term.service_name,
        domain=term.domain,
        sub_category=term.sub_category,
        status=term.status,
        version=version.version,
        created_at=term.created_at,
    )


@router.get(
    "/sub-categories",
    response_model=SubCategoryRecommendations,
    summary="도메인별 권장 sub-category vocab 조회",
    description=(
        "사이드바 UI 가 도메인 선택 시 사용할 *권장* sub-category 리스트.\n\n"
        "DB 컬럼 (`terms.sub_category`) 은 자유 TEXT — 권장 vocab 에 없는 값을 입력해도 "
        "받아들임. 그러나 사이드바 그룹핑은 권장 vocab 기준이라 권장 외 값은 \"기타\" 그룹.\n\n"
        "vocab 갱신은 `app/models/sub_category.py` 수정 (DB 마이그레이션 불필요)."
    ),
    tags=["Terms / 카테고리"],
)
async def list_sub_categories(domain: str):
    return SubCategoryRecommendations(
        domain=domain.upper(),
        sub_categories=recommendations_for(domain.upper()),
    )


@router.get(
    "",
    response_model=TermListResponse,
    summary="가입 약관 목록 조회 (필터링 가능)",
    description=(
        "현재 사용자가 가입한 약관 리스트.\n\n"
        "**필터 쿼리 파라미터**\n"
        "- `domain` (선택): FINANCE/OTT/INSURANCE/APP/MEDICAL/TELECOM/ETC 중 하나.\n"
        "- `status` (선택): ACTIVE / ARCHIVED.\n"
        "- `sub_category` (선택): 도메인 안의 세부 분류 (예: \"실손의료보험\"). 권장 vocab 은 "
        "`GET /terms/sub-categories?domain=...` 참고. 사이드바에서 같은 sub-category 끼리 그룹핑하는 데 사용."
    ),
    tags=["Terms / 목록"],
)
async def list_terms(
    domain: Optional[str] = None,
    status: Optional[str] = None,
    sub_category: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    terms = await term_service.get_terms(
        db, TEMP_USER_ID, domain, status, sub_category=sub_category,
    )
    items = [
        TermSummary(
            id=t.id,
            service_name=t.service_name,
            domain=t.domain,
            sub_category=t.sub_category,
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
        sub_category=term.sub_category,
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
                        page=c.page,
                        bbox=c.bbox,
                    )
                    for c in v.clauses
                ],
            )
            for v in term.versions
        ],
    )


@router.post(
    "/{term_id}/update",
    response_model=TermUpdateResponse,
    status_code=201,
    summary="약관 신버전 업로드 + diff (선택적으로 user-impact 자동 생성)",
    description=(
        "기존 term 에 새 버전을 추가하고 이전 버전과의 변경점 요약을 생성. "
        "신버전이 prev_version 과 동일 본문이면 LLM 호출 생략 (diff_summary=null).\n\n"
        "**`include_user_impact` Form 플래그**\n"
        "- `false` (기본): 기존 흐름 — Solar Pro 3 일반 diff_summary 1회 호출. 응답의 "
        "`user_impact` 는 null.\n"
        "- `true`: semantic diff (embedding 기반 조항 분류) + user-impact LLM 호출 (1회) "
        "을 합쳐 *현재 사용자에게의 영향* 자유문까지 생성. 응답의 `user_impact` 채워짐.\n"
        "  - `user_plan`, `user_custom_notes` Form 으로 사용자 컨텍스트 보강 가능.\n"
        "  - `Term.subscribed_at` 은 DB 에서 자동으로 가져와 user_context 에 포함.\n"
        "  - 추가 LLM 호출 1회 발생 → 응답 시간 ~2-3초 늘어남.\n\n"
        "변경 사항이 있으면 `Notification` 자동 생성. user_impact 가 있으면 알림 본문에 "
        "함께 저장되어 사용자가 \"무엇이 어떻게 바뀌었고, 나에게 어떤 영향이 있나\" 한 번에 확인 가능.\n\n"
        "대안: 별도로 호출하려면 `POST /terms/{term_id}/user-impact` (이미 업로드된 두 버전을 "
        "재비교) 사용."
    ),
    tags=["Terms / 버전 업데이트"],
)
async def update_term(
    term_id: uuid.UUID,
    file: UploadFile = File(...),
    include_user_impact: bool = Form(False),
    user_plan: Optional[str] = Form(None),
    user_custom_notes: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
):
    term = await term_service.get_term_detail(db, term_id, TEMP_USER_ID)
    if not term:
        raise HTTPException(status_code=404, detail="약관을 찾을 수 없습니다.")

    file_bytes = await file.read()
    file_url = f"/files/{file.filename}"

    new_version, user_impact = await term_service.process_version_update(
        db=db,
        term_id=term_id,
        user_id=TEMP_USER_ID,
        file_bytes=file_bytes,
        file_url=file_url,
        include_user_impact=include_user_impact,
        user_plan=user_plan,
        user_custom_notes=user_custom_notes,
    )

    # 알림 본문: user_impact 있으면 함께 노출, 없으면 diff_summary 만.
    notif_body = new_version.diff_summary or ""
    if user_impact:
        notif_body = (notif_body + "\n\n[나에게의 영향]\n" + user_impact).strip()

    new_notification = Notification(
        user_id=term.user_id,
        term_id=term.id,
        version_id=new_version.id,
        title=f"[{term.service_name}] 약관이 업데이트됐어요",
        diff_summary=notif_body or None,
        status=NotificationStatus.UNREAD,
    )
    db.add(new_notification)
    await db.commit() # ← 여기서 version + notification 한 번에 커밋
    await db.refresh(new_version)

    return TermUpdateResponse(
        term_id=term_id,
        new_version=new_version.version,
        diff_summary=new_version.diff_summary,
        user_impact=user_impact,
    )


@router.post(
    "/search",
    response_model=UserSearchResponse,
    summary="사용자 전체 약관 통합 검색 (cross-term)",
    description=(
        "**사용 시나리오**: 사용자가 메인 페이지 검색창에서 *자신이 가입한 모든 약관* 을 "
        "동시에 의미 검색. 예: `\"이번 병원 진료비 청구 가능한 보장이 있나?\"` 한 번의 "
        "쿼리로 보험·렌탈·통신·OTT 약관 chunk 를 cross-search.\n\n"
        "**알고리즘**:\n"
        "1. 쿼리를 Upstage `solar-embedding-1-large-query` 로 임베딩 (4096-d).\n"
        "2. `term_chunks ⨝ terms` 에서 `user_id = 현재 사용자` 인 chunk 만 후보로.\n"
        "3. pgvector cosine 거리 (`<=>`) ORDER BY → top-K 반환.\n"
        "4. `domain_filter` 가 주어지면 (예: `[\"INSURANCE\", \"FINANCE\"]`) 그 도메인만.\n\n"
        "**응답**: 각 chunk 와 함께 어느 term (`service_name`, `domain`) 에서 왔는지까지 "
        "포함 → UI 가 \"이 답은 X 약관 (보험) 에서 나왔습니다\" 식으로 출처 표시 가능.\n\n"
        "**단일 term 검색**: 자세한 한 약관 내부 검색이 필요하면 `POST /terms/{term_id}/search` "
        "사용. 그 엔드포인트는 term 한 건에 한정되어 cross-domain 답변이 안 나옴.\n\n"
        "**`score` 의미**: cosine *similarity* (1.0 = 동일, 0 = 무관). pgvector `<=>` 가 "
        "*distance* 라 SQL 내부에서 `1 - <=>` 로 변환되어 UI 친화 형태로 반환됨."
    ),
    response_description=(
        "결과는 cosine similarity 내림차순. 결과가 없거나 사용자가 가입한 약관이 없으면 "
        "`results=[]`, `total=0`."
    ),
    responses={
        200: {
            "description": "검색 성공",
            "content": {
                "application/json": {
                    "example": {
                        "results": [
                            {
                                "chunk_id": "11111111-1111-1111-1111-111111111111",
                                "chunk_index": 7,
                                "content": "본 보험은 입원 의료비를 보장합니다...",
                                "term_id": "22222222-2222-2222-2222-222222222222",
                                "service_name": "삼성 실손의료보험",
                                "domain": "INSURANCE",
                                "score": 0.91,
                            }
                        ],
                        "total": 1,
                    }
                }
            },
        },
    },
    tags=["Terms / 통합 검색"],
)
async def search_user_terms(
    body: UserSearchRequest,
    db: AsyncSession = Depends(get_db),
):
    """사용자가 가입한 *모든* 약관 cross-search.

    ⚠️ Route 순서 주의: 이 literal route 가 `{term_id}/search` 동적 route 보다
    먼저 등록돼야 "search" 가 UUID 로 잘못 파싱되지 않음.
    """
    results = await term_service.search_chunks_for_user(
        db,
        user_id=TEMP_USER_ID,
        query=body.query,
        top_k=body.top_k or 5,
        domain_filter=body.domain_filter,
    )
    return UserSearchResponse(
        results=[UserChunkResult(**r) for r in results],
        total=len(results),
    )


@router.post(
    "/{term_id}/search",
    response_model=SearchResponse,
    summary="단일 약관 내부 의미 검색",
    description=(
        "**사용 시나리오**: 특정 약관 한 건 안에서 \"환불 조건\", \"위약금 조항\" 같은 "
        "주제를 찾는 경우. 챕터/조항 번호를 모르더라도 자연어로 검색 가능.\n\n"
        "전체 가입 약관을 한 번에 cross-search 하고 싶다면 `POST /terms/search` 사용."
    ),
    tags=["Terms / 단일 검색"],
)
async def search_term(
    term_id: uuid.UUID,
    body: SearchRequest,
    db: AsyncSession = Depends(get_db),
):
    results = await term_service.search_chunks(db, term_id, body.query, body.top_k or 5)
    return SearchResponse(results=results)


@router.post(
    "/{term_id}/user-impact",
    response_model=UserImpactDiffResponse,
    summary="약관 변경의 *현재 사용자에게의 영향* 분석",
    description=(
        "**사용 시나리오**: 약관이 새 버전으로 업데이트된 후, 일반 diff 요약 (\"무엇이 "
        "어떻게 바뀌었는가\") 을 넘어 *나에게* 어떤 구체적 영향이 있는지 평문으로 받기.\n\n"
        "기획안 3-3 핵심 차별점: \"변경 고지가 전달되더라도 그 변경이 자신의 계약 조건에 "
        "어떠한 영향을 미치는지 파악하기는 어렵다\" 문제를 직접 해결.\n\n"
        "**파이프라인** (LLM 호출 1회, embedding 호출 N회):\n"
        "1. 약관 최신 2버전 raw_text 로드.\n"
        "2. 조항 단위 (`\\n\\n` 기준) 로 split 후 Upstage embedding 으로 cosine 분류:\n"
        "   - `phrasing_only` (≥0.92): 표현만 변경, 실질 동일.\n"
        "   - `substantive` (0.70~0.92): 실질 변경.\n"
        "   - `added` (<0.70 또는 매칭 없음): 신규 조항.\n"
        "   - `removed`: 매칭되지 않은 OLD 조항.\n"
        "3. `Term.subscribed_at` + (선택) `plan` + `custom_notes` 를 user_context 로 만들고,\n"
        "4. Solar Pro 3 (`reasoning_effort=high`) 호출 → 일반 diff_summary + `user_impact` "
        "자유문 생성.\n\n"
        "**`user_impact` 필드**: 2~5문장의 한국어 평문. 다음을 *반드시* 포함:\n"
        "- 사용자의 현재 상태 기준 어떤 조항이 영향받는가\n"
        "- 변경 시행일이 결제 주기/만료일 전인지 후인지\n"
        "- 지금 취해야 할 액션 (있다면)\n"
        "- 영향의 체감 정도 (높음/중간/낮음/영향 없음)\n\n"
        "**전제조건**: 해당 term 의 버전이 2개 이상이어야 함. 1개뿐이면 422 ValueError."
    ),
    responses={
        404: {"description": "term 을 찾을 수 없거나 본인 소유 아님."},
        422: {"description": "버전이 1개뿐이라 비교 불가능."},
    },
    tags=["Terms / 사용자 영향 분석"],
)
async def get_user_impact_diff(
    term_id: uuid.UUID,
    body: UserImpactDiffRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await term_service.compute_user_impacted_diff(
            db,
            term_id=term_id,
            user_id=TEMP_USER_ID,
            plan=body.plan,
            custom_notes=body.custom_notes,
        )
    except ValueError as e:
        msg = str(e)
        if "not found" in msg:
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=422, detail=msg)
    return UserImpactDiffResponse(
        term_id=result["term_id"],
        service_name=result["service_name"],
        old_version=result["old_version"],
        new_version=result["new_version"],
        diff_summary=result["diff_summary"],
        changes=[DiffChangeOut(**c) for c in result["changes"]],
        user_impact=result["user_impact"],
        semantic_counts=result["semantic_counts"],
    )