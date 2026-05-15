# Spec: 유사 분쟁 사례 (Similar Dispute Cases)

> **상태**: Design v1 (2026-05-15 작성)
> **범위**: 약관 분석 결과의 KeyClause / unfair_clause_flag / pain_point 에
> 매칭되는 실제 분쟁·소비자 피해 사례를 제공하는 신규 기능.

## 1. 목표

분석된 약관의 위험 조항을 볼 때 **같은 유형의 실제 분쟁·피해 사례 3-5개**를
함께 노출해서 위험을 구체화한다. 추상적 경고("이 조항 위험합니다") 를
증거 기반 정보("작년 한국소비자원 조정 사례에서 같은 조항으로 환불 받았습니다") 로
변환하는 것이 v1 의 비기능 요구사항.

### 1.1 비목표 (Out of Scope, v2 이후)

- 외부 사이트 (한국소비자원, 공정거래위원회 등) 자동 크롤링·실시간 수집
- 챗봇 답변에 사례를 RAG 컨텍스트로 자동 주입
- 사용자 피드백 루프 (유용함/관련 없음 → 랭킹 학습)
- 영문 AI 약관에 대한 영문 분쟁 사례 매칭
- 알림 푸시 페이로드에 사례 첨부

## 2. 사용자 흐름 (User flow)

1. 사용자가 약관을 업로드해서 분석 결과를 받음 (`POST /terms/upload`, 기존 기능).
2. 결과 페이지에서 위험 조항 (KeyClause) 카드를 본다.
3. 각 카드 옆 "비슷한 분쟁 사례 보기" 영역에 자동으로 top-3 매칭이 표시된다.
4. 카드 클릭 → 해당 조항에 대한 top-K (기본 5) 상세 화면으로 이동, 출처·결과 확인.

API 계약만 정의하고 UI 구현은 별도 작업이지만, 응답 schema 가 위 흐름을 정확히 지원해야 한다.

## 3. 데이터 모델

### 3.1 새 테이블 `dispute_cases`

| 컬럼 | 타입 | NULL | 비고 |
|---|---|---|---|
| `id` | UUID PK | NO | `gen_random_uuid()` 기본값 |
| `external_id` | TEXT | YES | source 시스템의 식별자 (예: 한소원 조정번호). 중복 방지 unique. |
| `title` | TEXT | NO | "OTT 자동결제 환불 거부 — 한소원 2024-1234" |
| `summary` | TEXT | NO | 3-5문장 사실관계 (한국어, 평문) |
| `outcome` | TEXT | NO | 조정/판결 결과. 환불액, 위약금 면제 등 구체적 결과. |
| `source` | TEXT | NO | `한국소비자원` / `공정거래위원회` / `전자거래분쟁조정위` / `언론` / `기타` |
| `source_url` | TEXT | YES | 원문 링크. 직접 인용 가능한 공개 URL 만. |
| `pain_point_ids` | TEXT[] | NO | `["POST-01","POST-02"]`. `ai/schemas/pain_points.py` 의 11개 ID 와 동기화. |
| `unfair_flags` | TEXT[] | NO | `["refund_denial","complex_cancellation"]` (snake_case canonical) |
| `domain` | TEXT | NO | `OTT` / `FINANCE` / `AI` / `ALL` (TermDomain enum + ALL) |
| `embedding` | HALFVEC(4096) | YES | Solar `embedding-passage` 결과. 인덱싱 실패 시 NULL 가능. |
| `created_at` | TIMESTAMPTZ | NO | `now()` |
| `updated_at` | TIMESTAMPTZ | NO | `now()` (재인덱싱 시 갱신) |

### 3.2 인덱스

- `dispute_cases_external_id_unique` (UNIQUE, partial: `WHERE external_id IS NOT NULL`)
- `dispute_cases_embedding_hnsw` — pgvector `vector_cosine_ops`
- `dispute_cases_domain_idx` (B-tree, domain 필터링)
- `pain_point_ids` / `unfair_flags` GIN 인덱스 (배열 교집합 boost 시 가속)

### 3.3 Seed 데이터

- 경로: `data/fixtures/dispute_cases.json`
- 분량: **15-20 개** (OTT 8 / Fintech 5 / AI 3 / 공통 3)
- 출처: 사람이 큐레이션 — 한국소비자원 분쟁조정 사례집, 공정거래위원회 시정명령 공시, 주요 언론 보도.
  요약·재구성하고 출처는 메타데이터로만 기록.
- JSON 형식 (source-agnostic — 향후 크롤러도 같은 schema 로 적재):

```json
{
  "external_id": "한소원-2024-1234",
  "title": "OTT 자동결제 환불 거부 — 한소원 조정 2024-1234",
  "summary": "...",
  "outcome": "환불 100%",
  "source": "한국소비자원",
  "source_url": "https://...",
  "pain_point_ids": ["POST-03"],
  "unfair_flags": ["refund_denial"],
  "domain": "OTT"
}
```

## 4. 매칭 알고리즘 (결정론)

입력: `KeyClause`(title + description + citation.quote) **또는** unfair_flag/pain_point ID.

1. **Query 텍스트 구성**: `"{title}\n{description}\n{quote}"` (KeyClause 의 경우).
   Flag/pain_point 직접 입력 시 → 해당 라벨(`PainPoint.label`) 사용.
2. `ai_client.embed_query` 호출 → 4096-d 벡터 (기존 Upstage Solar embedding 재사용).
3. **pgvector cosine top-K** (K=10): `embedding <=> :vec`.
4. **Boost rules** (가산 점수):
   - dispute.`pain_point_ids` ∩ KeyClause.`pain_point_id` ≠ ∅ → **+0.10**
   - dispute.`unfair_flags` ∩ Term.`unfair_clause_flags` ≠ ∅ → **+0.05**
   - dispute.`domain ∈ {Term.domain, "ALL"}` → **+0.05**
5. `score = (1 - cosine_distance) + sum(boosts)`
6. Filter `score ≥ 0.65` 컷 → top-3 (기본) 반환. `top_k` 파라미터로 조정 가능.
7. **0개여도 빈 배열**: false positive 회피 우선 (CLAUDE.md 의 accuracy-first 정책에 부합).

매칭 결과 객체에는 `matched_signals: list[str]` 을 포함:
`["pain_point:POST-01", "flag:refund_denial", "domain:OTT"]` 형태로
**어떤 신호로 boost 됐는지** 트레이싱 가능하게 한다.

### 4.1 결정론·일관성

- LLM 호출 없음 → 챗봇과 달리 latency 부담 X (서버 단일 응답 < 200ms 목표).
- 임베딩 캐싱: KeyClause 별 query embedding 은 매 요청 새로 계산 (조항 텍스트가
  KeyClause 단위로 작아서 부담 없음). 추후 캐시 도입은 v2.
- 같은 입력 → 같은 결과: pgvector `<=>` 는 결정적이고, boost 가산도 결정적.

### 4.2 정밀도 vs 재현율

- **default threshold 0.65** — 보수적. 데모 신뢰성 우선.
- **default top_k 3** — UI 노출 한정. 너무 많으면 노이즈.
- threshold/top_k 는 환경변수 `DISPUTE_MIN_SCORE` / `DISPUTE_TOP_K` 로 튜닝 가능.

## 5. API

새 router `app/routers/disputes.py` (prefix `/disputes`, top-level mount):

| Method | Path | 용도 |
|---|---|---|
| `GET` | `/v1/terms/{term_id}/disputes` | 약관 전체 KeyClause × top-3 매칭 (대시보드 일괄 조회) |
| `GET` | `/v1/terms/{term_id}/clauses/{clause_id}/disputes?top_k=5` | 단일 조항 드릴다운 (top-K, 기본 5) |
| `GET` | `/v1/disputes` | 전체 사례 목록 (관리/디버깅, 페이지네이션) |
| `GET` | `/v1/disputes/{case_id}` | 단일 사례 상세 |

**응답 (per-clause)**:
```json
{
  "clause_id": "uuid",
  "clause_title": "자동결제 환불 거부",
  "matches": [
    {
      "case_id": "uuid",
      "title": "...",
      "summary": "...",
      "outcome": "환불 100%",
      "source": "한국소비자원",
      "source_url": "https://...",
      "score": 0.82,
      "matched_signals": ["pain_point:POST-03", "flag:refund_denial", "domain:OTT"]
    }
  ]
}
```

**응답 (term 전체)**:
```json
{
  "term_id": "uuid",
  "clauses": [ /* per-clause 응답 배열 */ ]
}
```

## 6. 컴포넌트 경계

| 파일 | 책임 |
|---|---|
| `migrations/0002_dispute_cases.sql` | 테이블 + 인덱스 |
| `app/models/dispute.py` | SQLAlchemy ORM |
| `app/schemas/dispute.py` | Pydantic 응답 schema |
| `app/services/dispute_service.py` | **단일 진입점** `find_similar_disputes(clause, term)` 등 |
| `app/routers/disputes.py` | HTTP 어댑터 (얇음) |
| `scripts/index_dispute_cases.py` | seed JSON → embed → upsert (idempotent) |
| `data/fixtures/dispute_cases.json` | seed 데이터 |
| `tests/unit/test_services_dispute.py` | boost 로직, threshold, 빈 결과 케이스 (임베딩 mock) |
| `tests/integration/test_disputes_e2e.py` | 실제 seed 인덱싱 후 golden 매칭 1-2 케이스 (`-m e2e`) |

기존 `app/services/ai_client.embed_query` 를 그대로 재사용. 새 임베딩 모델
도입 없음 — Term 청크와 같은 4096-d 벡터 공간 안에서 일관성 유지.

### 6.1 Source-agnostic 인터페이스

v2 크롤링 확장을 위해 `dispute_service` 의 적재 로직은 다음 추상화를 따른다:

```python
class DisputeCaseInput(TypedDict):
    external_id: str | None
    title: str
    summary: str
    outcome: str
    source: str
    source_url: str | None
    pain_point_ids: list[str]
    unfair_flags: list[str]
    domain: str  # OTT/FINANCE/AI/ALL

async def upsert_dispute_cases(
    db: AsyncSession,
    cases: list[DisputeCaseInput],
) -> int: ...
```

`scripts/index_dispute_cases.py` 는 fixture JSON → `DisputeCaseInput` 변환 → 위 함수 호출.
v2 크롤러도 같은 변환 → 같은 함수 호출. 적재 인프라 재사용.

## 7. 테스트 전략

### 7.1 Unit (`tests/unit/test_services_dispute.py`)

- **boost 가산 정확성**: 임베딩 mock 으로 cosine 고정, boost rule 별 score 변화 검증
- **threshold 컷**: `score < 0.65` 케이스 → 빈 배열 보장 (false positive 회피)
- **top_k 제한**: 후보 10개여도 top_k=3 이면 3개만 반환
- **matched_signals 정확성**: 어떤 boost 가 적용됐는지 신호 문자열로 추적 가능
- **빈 후보 케이스**: DB 비어있으면 빈 배열, 에러 X
- **upsert idempotency**: 같은 `external_id` 두 번 적재해도 row 1개 (embedding 만 갱신)

### 7.2 Integration (`tests/integration/test_disputes_e2e.py`, `-m e2e`)

- 실제 Solar embed_query 로 seed 5개 인덱싱
- "환불 거부" 키워드 KeyClause → 환불 거부 fixture top-1 검증
- "위약금" 키워드 → 위약금 fixture top-1 검증
- 도메인 mismatch (OTT 약관에 AI 사례) → 도메인 boost 없이 매칭 안 됨 확인

## 8. 마이그레이션·롤아웃

1. `migrations/0002_dispute_cases.sql` 적용 (idempotent: `CREATE TABLE IF NOT EXISTS` + `CREATE INDEX IF NOT EXISTS`).
2. `python scripts/index_dispute_cases.py` 실행 — fixture seed → DB.
3. FastAPI 서버 재시작 → 새 라우터 활성.
4. 기존 API/스키마 변경 없음 — 기존 테스트·통합 영향 0.

롤백: 라우터만 제거하면 기존 동작 유지. 테이블은 그대로 둬도 무관 (DROP 은 옵션).

## 9. CLAUDE.md 정합성

- **Accuracy-first**: threshold 0.65 + 빈 결과 허용으로 false positive 최소화. boost 는 가산만 (감산 X) — 매칭 신호가 있으면 신뢰도 ↑.
- **Latency secondary**: 임베딩 1회 + pgvector 한 번. <200ms 목표 (체이닝 LLM 없음).
- **Token 비제약**: 임베딩 비용은 1 호출 당 미미. 사례 인덱싱은 1회성 (재인덱싱 시 fixture 크기 × 1).
- **API key 분리**: 서비스 경로는 `service_api_key` (key #1) 사용. 평가/벤치마크 스크립트 별도 추가 시에만 `eval_api_keys` 사용.

## 10. 오픈 이슈 (구현 시 결정)

- **pain_point ↔ KeyClause 매핑 (확인됨)**: `ai/services/summarize.py` 의 `KeyClause`
  schema 가 이미 `pain_point_id: str` 필드를 정의 → boost rule 즉시 작동 가능.
  단, 프롬프트가 실제로 일관되게 11개 ID 중 하나를 채우는지는 구현 단계에서
  몇 개 fixture 로 sanity check 후, 비어있는 경우는 string normalize 후 빈
  문자열로 처리해서 매칭 boost 만 skip (전체 매칭은 cosine + 다른 boost 로 유지).

- **unfair_flag canonical alias**: `scripts/score_against_golden.py` 의
  `_normalize_flag` 와 동기화 필요. → 매칭 단계에서 같은 정규화 함수 재사용
  (서비스 코드로 옮기거나 import).
