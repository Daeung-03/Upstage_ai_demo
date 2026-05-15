# app/services/term_service.py
import uuid
from typing import Optional
from datetime import date
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from app.models.term import Term, TermVersion, TermChunk, TermClause
from app.models.calendar import CalendarEvent
from app.models.enums import ClauseType, EventType
from app.models.vendors import canonical_vendor_slug, vendor_domain
from app.services import ai_client
from app.services.calendar_service import compute_calendar_events

CHUNK_SIZE = 500

def _split_chunks(text: str, size: int = CHUNK_SIZE) -> list[str]:
    return [text[i:i+size] for i in range(0, len(text), size)]


def _split_clauses(text: str) -> list[str]:
    """raw_text 를 *조항 단위* 로 split. Document Parse markdown 의 빈 줄 기준.

    process_version_update 의 semantic diff 와 compute_user_impacted_diff 가
    공유. token chunking (_split_chunks) 과 다름 — 임베딩 기반 의미 비교는
    *의미 단위* 가 필요해 빈 줄 기준이 더 정확.
    """
    return [c.strip() for c in (text or "").split("\n\n") if c.strip()]


# ── AnalysisResult → DB 저장용 변환 헬퍼 ──────────────────
def _collect_field_bboxes(terms) -> dict[str, tuple[int | None, list[float] | None]]:
    """SubscriptionTerms 의 모든 FieldValue.citation 을 순회하며 quote → (page, bbox) 매핑.

    extract.py 의 _enrich_with_bbox 가 채워둔 bbox 를 KeyClause 와 합치기 위함.
    KeyClauseCitation 자체는 page+quote 만 있고 bbox 가 없어서, 같은 본문을 인용한
    field citation 으로부터 보강한다. quote 가 비어있거나 bbox 가 없으면 스킵.
    """
    out: dict[str, tuple[int | None, list[float] | None]] = {}

    def walk(obj):
        if obj is None:
            return
        # FieldValue 형태: value + uncertainty + citation
        cit = getattr(obj, "citation", None)
        if cit is not None and getattr(cit, "quote", None):
            bbox = getattr(cit, "bbox", None)
            page = getattr(cit, "page", None)
            bbox_list = list(bbox) if bbox else None
            # 같은 quote 가 여러 번 잡히면 bbox 있는 쪽을 우선
            existing = out.get(cit.quote)
            if existing is None or (existing[1] is None and bbox_list is not None):
                out[cit.quote] = (page, bbox_list)
        # 하위 모델/리스트 재귀. Pydantic v2 는 model_fields 가 클래스 속성.
        fields = getattr(type(obj), "model_fields", None)
        if fields:
            for name in fields:
                walk(getattr(obj, name, None))
        elif isinstance(obj, (list, tuple)):
            for item in obj:
                walk(item)

    walk(terms)
    return out


def _match_bbox(
    quote: str, lookup: dict[str, tuple[int | None, list[float] | None]]
) -> tuple[int | None, list[float] | None]:
    """KeyClause.quote 로 field citation lookup 에서 bbox 를 best-effort 매칭.

    1) exact match → 2) lookup quote 가 keyclause quote 의 부분문자열 → 3) 역방향.
    """
    if not quote:
        return (None, None)
    if quote in lookup:
        return lookup[quote]
    for q, (page, bbox) in lookup.items():
        if q and (q in quote or quote in q):
            return (page, bbox)
    return (None, None)


def _parse_result_to_clauses(result) -> list[dict]:
    lookup = _collect_field_bboxes(result.terms)
    out = []
    for c in result.key_clauses:
        cit_page = getattr(c.citation, "page", None)
        matched_page, matched_bbox = _match_bbox(c.citation.quote, lookup)
        # risk_level / pain_point_id 는 KeyClause 가 직접 갖는 1급 시그널 — 분쟁 사례
        # 매칭 boost 와 reasoning 생성 입력에 필수. 정규화: 소문자/대문자 통일.
        risk_level = getattr(c, "risk_level", None)
        if isinstance(risk_level, str):
            risk_level = risk_level.lower()  # "high"/"medium"/"low" 형태로
        pain_point_id = getattr(c, "pain_point_id", None)
        if isinstance(pain_point_id, str):
            pain_point_id = pain_point_id.upper() or None  # "POST-01" 형태로
        out.append({
            "clause_type": "ETC",               # KeyClause에 clause_type 없음 → 전부 ETC
            "title": c.title,
            "original_text": c.citation.quote,  # 원문 인용구
            "plain_text": c.description,        # 평문 설명
            # page: KeyClauseCitation 의 page 우선, 없으면 매칭된 field citation page.
            "page": cit_page if cit_page is not None else matched_page,
            # bbox: KeyClauseCitation 엔 bbox 가 없으므로 매칭된 field citation 만 사용.
            "bbox": matched_bbox,
            "risk_level": risk_level,
            "pain_point_id": pain_point_id,
        })
    return out

def _get_raw_text(result) -> str:
    """AnalysisResult에서 markdown (raw_text) 추출."""
    return getattr(result, "markdown", "") or result.terms.model_dump_json()

def _get_domain(result) -> str:
    """AnalysisResult에서 domain 추출."""
    terms = result.terms
    for attr in ("domain", "service_domain", "category"):
        if hasattr(terms, attr):
            return getattr(terms, attr) or "ETC"
    return "ETC"


# ── process_upload ────────────────────────────────────────
async def process_upload(
    db: AsyncSession,
    user_id: uuid.UUID,
    service_name: str,
    subscribed_at,
    file_bytes: bytes,
    file_url: str,
    domain: str = "ETC",
    sub_category: str | None = None,
    effective_date: date | None = None,
) -> tuple[Term, TermVersion]:

    # 1. AI 파이프라인 (단일 호출로 통합)
    result = await ai_client.run_full_pipeline(
        file_bytes=file_bytes,
        filename=file_url.split("/")[-1],
        service_name=service_name,
    )

    raw_text = _get_raw_text(result)
    domain   = _get_domain(result)
    clauses  = _parse_result_to_clauses(result)
    chunks   = _split_chunks(raw_text)
    vectors  = await ai_client.embed_chunks(chunks)
    dates    = compute_calendar_events(result.terms, subscribed_at)

    # Vendor 카탈로그 자동 매핑 — 15 서비스 중 하나로 인식되면 canonical slug 저장,
    # domain 도 vendor 가 명시한 값으로 override (정책 b: vendor mapping 우선).
    # 매칭 안 되면 vendor_slug=NULL + 사용자 명시 domain 그대로.
    resolved_vendor = canonical_vendor_slug(service_name)
    resolved_domain = (vendor_domain(resolved_vendor) if resolved_vendor else None) or domain.upper()

    # 2. Term 저장
    term = Term(
        user_id=user_id,
        service_name=service_name,
        domain=resolved_domain,
        sub_category=sub_category,
        vendor_slug=resolved_vendor,
        file_url=file_url,
        subscribed_at=subscribed_at,
    )
    db.add(term)
    await db.flush()

    # 3. TermVersion 저장
    version = TermVersion(
        term_id=term.id,
        version=1,
        raw_text=raw_text,
        summary=result.summary,
        is_latest=True,
        effective_date=effective_date,
    )
    db.add(version)
    await db.flush()

    # 4. TermChunks + Embeddings
    for idx, (content, vector) in enumerate(zip(chunks, vectors)):
        db.add(TermChunk(
            term_id=term.id,
            version_id=version.id,
            chunk_index=idx,
            content=content,
            embedding=vector,
        ))

    # 5. TermClauses
    for c in clauses:
        db.add(TermClause(
            version_id=version.id,
            clause_type=c["clause_type"],
            title=c.get("title"),
            original_text=c["original_text"],
            plain_text=c.get("plain_text"),
            page=c.get("page"),
            bbox=c.get("bbox"),
            risk_level=c.get("risk_level"),
            pain_point_id=c.get("pain_point_id"),
        ))

    # 6. CalendarEvents
    for d in dates:
        db.add(CalendarEvent(
            term_id=term.id,
            user_id=user_id,
            event_type=d["event_type"],
            event_date=date.fromisoformat(d["date"]),
            label=f"{service_name} - {d['event_type']}",
        ))

    await db.flush()
    await db.refresh(term)
    await db.refresh(version)
    return term, version


# ── process_version_update ────────────────────────────────
async def process_version_update(
    db: AsyncSession,
    term_id: uuid.UUID,
    user_id: uuid.UUID,
    file_bytes: bytes,
    file_url: str,
    include_user_impact: bool = False,
    user_plan: str | None = None,
    user_custom_notes: str | None = None,
    effective_date: date | None = None,
) -> tuple[TermVersion, str | None]:
    """약관 신버전 업로드 처리.

    include_user_impact=True 일 때는 기존 summarize_version_diff 대신 user-impact
    diff (semantic + LLM 1회) 를 실행해 *현재 사용자에게의 영향* 자유문까지 같이
    생성. 추가 LLM 호출 1회 발생 — 사용자가 명시적으로 원할 때만 사용.

    반환: (TermVersion, user_impact | None).
    user_impact 는 include_user_impact=True 이고 prev_version 본문이 다를 때만 값 있음.
    """

    # 이전 latest 버전을 미리 끌어와 diff_summary 비교 base 로 사용.
    # 같은 트랜잭션에서 is_latest=False 로 업데이트하기 *전에* 조회해야 일관됨.
    prev_q = await db.execute(
        select(TermVersion)
        .where(TermVersion.term_id == term_id, TermVersion.is_latest == True)  # noqa: E712
        .order_by(TermVersion.version.desc())
        .limit(1)
    )
    prev_version = prev_q.scalar_one_or_none()
    # bulk update 가 prev_version 인스턴스를 expire 시킬 가능성 (SQLAlchemy 2.x async
    # synchronize_session 동작) 차단. raw_text 를 미리 로컬에 떼두고 이후엔 로컬만 참조.
    prev_raw_text: str | None = prev_version.raw_text if prev_version is not None else None

    await db.execute(
        update(TermVersion)
        .where(TermVersion.term_id == term_id)
        .values(is_latest=False)
    )

    result_q = await db.execute(
        select(TermVersion.version)
        .where(TermVersion.term_id == term_id)
        .order_by(TermVersion.version.desc())
        .limit(1)
    )
    last_version = result_q.scalar_one_or_none() or 0

    # AI 파이프라인
    term_obj = await db.get(Term, term_id)
    service_name = term_obj.service_name if term_obj else ""
    result = await ai_client.run_full_pipeline(
        file_bytes=file_bytes,
        filename=file_url.split("/")[-1],
        service_name=service_name,
    )

    raw_text = _get_raw_text(result)
    clauses  = _parse_result_to_clauses(result)
    chunks   = _split_chunks(raw_text)
    vectors  = await ai_client.embed_chunks(chunks)
    # 버전 업데이트 시점에는 가입일을 Term 으로부터 끌어와 캘린더 이벤트 재계산.
    dates    = compute_calendar_events(
        result.terms,
        term_obj.subscribed_at if term_obj else None,
    )

    # 버전 변경점 요약 — 이전 버전이 있으면 무조건 LLM 호출.
    # 약관 업데이트는 운영자가 의도적으로 트리거하는 이벤트라 항상 비교 의미가 있음.
    # 본문이 완전히 동일하면 LLM 이 "주요 변경 사항 없음" 으로 응답하도록 prompt 화 돼있음
    # (ai/prompts/diff.py:13-14). token cost 는 제약이 아니라 가드 제거 (CLAUDE.md 정책).
    # 부가 효과: VLM 파싱 비결정성으로 같은 PDF 도 markdown 이 미세하게 달라 가드가
    # 일관성 없게 발동되던 문제도 해소.
    diff_summary: str | None = None
    user_impact: str | None = None
    if prev_version is not None:
        prev_text = prev_raw_text or ""
        if include_user_impact:
            # user-impact diff 한 번에 일반 diff + 개별 영향 자유문 모두 얻음.
            # semantic diff (embedding) + LLM 1회.
            old_clauses = _split_clauses(prev_text)
            new_clauses = _split_clauses(raw_text)
            user_context: dict = {}
            if term_obj and term_obj.subscribed_at:
                user_context["subscribed_at"] = term_obj.subscribed_at.isoformat()
            if user_plan:
                user_context["plan"] = user_plan
            if user_custom_notes:
                user_context["custom_notes"] = user_custom_notes
            ui_result = await ai_client.user_impacted_diff(
                old_text=prev_text,
                new_text=raw_text,
                service_name=service_name,
                old_clauses=old_clauses,
                new_clauses=new_clauses,
                user_context=user_context or None,
            )
            diff_summary = ui_result.diff_summary
            user_impact = ui_result.user_impact
        else:
            diff_result = await ai_client.summarize_version_diff(
                old_text=prev_text,
                new_text=raw_text,
                service_name=service_name,
            )
            diff_summary = diff_result.diff_summary

    new_version = TermVersion(
        term_id=term_id,
        version=last_version + 1,
        raw_text=raw_text,
        summary=result.summary,
        diff_summary=diff_summary,
        is_latest=True,
        effective_date=effective_date,
    )
    db.add(new_version)
    await db.flush()

    for idx, (content, vector) in enumerate(zip(chunks, vectors)):
        db.add(TermChunk(
            term_id=term_id,
            version_id=new_version.id,
            chunk_index=idx,
            content=content,
            embedding=vector,
        ))

    for c in clauses:
        db.add(TermClause(
            version_id=new_version.id,
            clause_type=c["clause_type"],
            title=c.get("title"),
            original_text=c["original_text"],
            plain_text=c.get("plain_text"),
            page=c.get("page"),
            bbox=c.get("bbox"),
            risk_level=c.get("risk_level"),
            pain_point_id=c.get("pain_point_id"),
        ))

    for d in dates:
        db.add(CalendarEvent(
            term_id=term_id,
            user_id=user_id,
            event_type=d["event_type"],
            event_date=date.fromisoformat(d["date"]),
            label=f"업데이트 v{last_version + 1} - {d['event_type']}",
        ))

    await db.flush()
    await db.refresh(new_version)
    return new_version, user_impact


# ── 아래는 기존 코드 그대로 ──────────────────────────────
async def get_terms(
    db: AsyncSession,
    user_id: uuid.UUID,
    domain: Optional[str] = None,
    status: Optional[str] = None,
    sub_category: Optional[str] = None,
):
    q = (
        select(Term)
        .options(selectinload(Term.versions))
        .where(Term.user_id == user_id)
    )
    if domain:
        q = q.where(Term.domain == domain)
    if status:
        q = q.where(Term.status == status)
    if sub_category:
        q = q.where(Term.sub_category == sub_category)
    result = await db.execute(q)
    return result.scalars().all()

async def get_term_detail(db: AsyncSession, term_id: uuid.UUID, user_id: uuid.UUID):
    result = await db.execute(
        select(Term)
        .options(
            selectinload(Term.versions).selectinload(TermVersion.clauses),
        )
        .where(Term.id == term_id, Term.user_id == user_id)
    )
    return result.scalar_one_or_none()


def _get_domain(result) -> str:
    terms = result.terms
    for attr in ("domain", "service_domain", "category"):
        val = getattr(terms, attr, None)
        if val and val.upper() in ("FINANCE", "OTT", "INSURANCE", "APP", "MEDICAL", "TELECOM"):
            return val.upper()
    return "ETC"  # "subscription" 같은 미매핑 값은 전부 ETC로 fallback

async def search_chunks(
    db: AsyncSession,
    term_id: uuid.UUID,
    query: str,
    top_k: int = 5,
) -> list[dict]:
    """term 의 청크 중 query 와 의미적으로 가장 유사한 top_k 개 반환.

    응답 shape 은 `ChunkResult` 스키마와 정합:
      - chunk_id: UUID (term_chunks.id)
      - chunk_index: int (해당 term 내 청크 순번)
      - content: str (청크 본문)
      - score: float (cosine similarity, 1.0 = 동일, 0 = 무관, < 0 = 반대)

    pgvector 의 `<=>` 는 cosine *distance* (0 = 동일, 2 = 정반대) 라 1 에서 빼서
    similarity 로 노출. UI 토스트에 "정확도 87%" 식으로 표시 가능.
    """
    from sqlalchemy import text as sa_text

    query_vec = await ai_client.embed_query(query)

    rows = (await db.execute(
        sa_text("""
            SELECT id, content, chunk_index,
                   1 - (embedding <=> CAST(:vec AS halfvec)) AS score
            FROM term_chunks
            WHERE term_id = :term_id
            ORDER BY embedding <=> CAST(:vec AS halfvec)
            LIMIT :top_k
        """),
        {"vec": str(query_vec), "term_id": str(term_id), "top_k": top_k},
    )).fetchall()

    return [
        {
            "chunk_id": r.id,
            "chunk_index": r.chunk_index,
            "content": r.content,
            "score": float(r.score),
        }
        for r in rows
    ]


async def compute_user_impacted_diff(
    db: AsyncSession,
    term_id: uuid.UUID,
    user_id: uuid.UUID,
    plan: str | None = None,
    custom_notes: str | None = None,
) -> dict:
    """약관의 최신 2개 버전을 비교해 *현재 사용자에게의 영향* 까지 분석.

    절차:
      1. term 의 최신 2버전 raw_text 로드 (없으면 ValueError).
      2. raw_text 를 \\n\\n 으로 split 해 조항 단위로 만든 후 compute_semantic_diff
         로 (phrasing_only / substantive / added / removed) 분류.
      3. Term.subscribed_at + (선택) plan + custom_notes 를 user_context dict 로
         묶어 summarize_version_diff_for_user 호출 (LLM 1회).
      4. UserImpactedDiffResult.model_dump() 반환.

    호출자가 user_id 가 term owner 인지 확인할 책임.
    """
    from sqlalchemy import select as sa_select

    # owner 검증 + Term 조회
    term = await db.get(Term, term_id)
    if term is None or term.user_id != user_id:
        raise ValueError("term not found or not owned by user")

    # 최신 2버전
    rows = (await db.execute(
        sa_select(TermVersion)
        .where(TermVersion.term_id == term_id)
        .order_by(TermVersion.version.desc())
        .limit(2)
    )).scalars().all()
    if len(rows) < 2:
        raise ValueError("term has fewer than 2 versions; nothing to compare")
    new_v, old_v = rows[0], rows[1]

    old_clauses = _split_clauses(old_v.raw_text or "")
    new_clauses = _split_clauses(new_v.raw_text or "")

    user_context: dict = {}
    if term.subscribed_at:
        user_context["subscribed_at"] = term.subscribed_at.isoformat()
    if plan:
        user_context["plan"] = plan
    if custom_notes:
        user_context["custom_notes"] = custom_notes

    result = await ai_client.user_impacted_diff(
        old_text=old_v.raw_text or "",
        new_text=new_v.raw_text or "",
        service_name=term.service_name,
        old_clauses=old_clauses,
        new_clauses=new_clauses,
        user_context=user_context or None,
    )
    return {
        "term_id": str(term_id),
        "service_name": term.service_name,
        "old_version": old_v.version,
        "new_version": new_v.version,
        **result.model_dump(),
    }


async def search_chunks_for_user(
    db: AsyncSession,
    user_id: uuid.UUID,
    query: str,
    top_k: int = 5,
    domain_filter: list[str] | None = None,
) -> list[dict]:
    """사용자가 가입한 *모든* 약관 chunk 중 query 와 의미가 가장 가까운 top_k 반환.

    `search_chunks` 와 달리 (a) term_id 가 아니라 user_id 기준 cross-term, (b)
    응답에 어느 term 에서 왔는지 (service_name, domain) 까지 포함. UI 가
    "이 답은 X 약관 (보험) 에서 나왔습니다" 보여줄 수 있게.

    domain_filter 가 주어지면 (예: ["INSURANCE", "FINANCE"]) 그 도메인만 검색.
    기획안 2-3 "메인 페이지 통합 검색" 시나리오: "이번 병원 진료비에 청구 가능한
    혜택?" → 사용자가 가입한 보험·렌탈·통신·OTT 약관 전체를 한 번에 cross-search.
    """
    from sqlalchemy import text as sa_text

    query_vec = await ai_client.embed_query(query)

    base_sql = """
        SELECT
          tc.id              AS chunk_id,
          tc.content         AS content,
          tc.chunk_index     AS chunk_index,
          tc.term_id         AS term_id,
          t.service_name     AS service_name,
          t.domain           AS domain,
          1 - (tc.embedding <=> CAST(:vec AS halfvec)) AS score
        FROM term_chunks tc
        JOIN terms t ON t.id = tc.term_id
        WHERE t.user_id = :user_id
          {domain_clause}
        ORDER BY tc.embedding <=> CAST(:vec AS halfvec)
        LIMIT :top_k
    """
    params: dict = {
        "vec": str(query_vec),
        "user_id": str(user_id),
        "top_k": top_k,
    }
    if domain_filter:
        sql = base_sql.format(domain_clause="AND t.domain = ANY(:domains)")
        params["domains"] = [d.upper() for d in domain_filter]
    else:
        sql = base_sql.format(domain_clause="")

    rows = (await db.execute(sa_text(sql), params)).fetchall()

    return [
        {
            "chunk_id": r.chunk_id,
            "chunk_index": r.chunk_index,
            "content": r.content,
            "term_id": r.term_id,
            "service_name": r.service_name,
            "domain": str(r.domain),
            "score": float(r.score),
        }
        for r in rows
    ]