# Upstage AI Terms — 데모

한국 OTT · Fintech · AI 약관을 분석하는 풀스택 데모. Upstage Solar Pro 3 기반 4단계 파이프라인으로 42개 필드 + 위험 조항 + 인용 근거를 추출하고, 챗봇·캘린더·알림 같은 사용자-facing 기능까지 연결.

```
입력 (PDF/HTML 약관)
  ↓ ai/pipeline.py  ← domain="subscription"|"finance"|"insurance" 분기
  ├─ Document Parse / HTML 직접 추출
  ├─ Solar Pro 3 × N=2~5 voting (도메인-aware 분기) ← Round 11: 영문/한국어 자동 분기
  ├─ Solar Pro 3 위험 조항 요약
  └─ Solar Pro 3 groundedness 검증
출력 → DB 저장 (PostgreSQL + pgvector halfvec(4096))
   → FastAPI (포트 8000)
      ├─ POST /terms/upload         업로드 + 풀 파이프라인 + DB 저장
      ├─ GET  /terms                목록 / GET /terms/{id} 상세
      ├─ POST /terms/{id}/search    의미 검색 (cosine similarity)
      ├─ POST /terms/{id}/update    버전 업데이트 + diff_summary
      ├─ POST /chat                 약관 RAG 챗봇
      ├─ GET  /calendar             자동갱신·해지 마감 캘린더
      ├─ GET  /notifications        위험 조항/버전 변경 푸시
      └─ /v1/disputes, /v1/terms/{id}/disputes  유사 분쟁 사례 매칭
```

---

## 📊 성능 평가 — Trimmed Mean (10 runs × 15 fixture × N=2)

**측정 방법론**: Hackathon 환경에서 Solar API 의 backend 부하 변동으로 동일 config 도 ±5~10%p 까지 진동 (README 본문 하단 counter-intuitive 발견 #3). 단일 run 으로 winner 판정은 통계적으로 위험. 따라서 동일 config (`BC + prompt #1, N=2 medium`, summarize=high, ground=medium) 의 **10번 전(全) fixture 실행 결과를 모아 fixture 별 trimmed mean 으로 집계** (min/max 1개씩 제외 후 평균, "drop1" policy).

집계 대상: 2026-05-15 01:45 ~ 18:00 사이 10개 `data/experiments/all_fixtures_*.json` × 15 fixture × N=2 inner runs = **236 개별 measurement**.

### 🏆 전체 평균 (per-fixture trimmed mean 의 산술평균)

| 메트릭 | 값 |
|---|---|
| **Strict avg (trimmed)** | **57.3%** |
| **Semantic avg (trimmed)** | **63.6%** |
| Latency avg / fixture | ~565s |
| Tokens avg / fixture | ~150K |

### 도메인별 trimmed mean (strict / semantic)

| 도메인 | n fixture | Strict trim | Semantic trim | 비고 |
|---|---|---|---|---|
| **OTT (7)** | 7 | **59.7%** | **66.9%** | netflix 72.9·spotify 63.5·wavve 63.6·disney_plus 60.1·tving 57.0·watcha 52.4·coupang_play 48.5 |
| **Fintech (3)** | 3 | **64.3%** | **70.6%** | kakaopay 68.6·toss 66.0·banksalad 58.3 (전체 도메인 최고) |
| **AI 영문 (2)** | 2 | **53.5%** | **57.3%** | gpt 55.3·deepseek 51.6 |
| **AI 한국어 (3)** | 3 | **47.0%** | **53.1%** | claude 55.1·upstage 45.9·gemini 39.9 ⚠️ |

### Per-fixture (상위/하위)

| Fixture | n | Strict trim | std | range (전 measurement) | Semantic trim |
|---|---|---|---|---|---|
| 🟢 netflix | 18 | 72.9% | ±5.0 | 59-80 | 78.1% |
| 🟢 kakaopay | 11 | 68.6% | ±4.3 | 61-76 | 74.1% |
| 🟢 toss | 10 | 66.0% | ±2.1 | 59-71 | 68.9% |
| ... | ... | ... | ... | ... | ... |
| 🔴 coupang_play | 19 | 48.5% | ±4.8 | 40-61 | 54.4% |
| 🔴 upstage | 15 | 45.9% | ±6.1 | 35-57 | 49.5% |
| 🔴 gemini | 12 | 39.9% | ±4.0 | 33-50 | 44.2% |

전체 per-fixture 표는 [`data/experiments/trimmed_mean_drop1_20260515_222419.md`](data/experiments/trimmed_mean_drop1_20260515_222419.md).

### 관찰

- **단일 winner 보고치 (이전 README): 55.3% strict / 60.5% sem 은 자연 분산의 한쪽 꼬리**. 실제 trimmed mean 은 +2.0/+3.1%p 더 높음.
- **사용자 관찰 검증** ("Solar Pro 3 한국어 LLM 인데 한국어 AI 점수 낮음"): 한국 OTT (netflix) 72.9% vs 한국 AI (upstage/gemini) 39.9~45.9%. **언어가 아닌 스키마-도메인 fit** 이 진짜 변수. AI 약관에 필요한 필드 (training data 사용, output IP, prompt 학습 옵트아웃) 가 `SubscriptionTerms` 7섹션 안에 없음.
- **Fintech 가 OTT 보다 도메인 평균이 높음** (64.3 vs 59.7%) — 사례 F (EFTA §9) 룰 효과 + fintech 약관이 한국 강행규정 따라 구조가 일관됨.

### 측정 출처

- Trimmed mean 산출: [`scripts/aggregate_trimmed_mean.py`](scripts/aggregate_trimmed_mean.py).
- 원시 데이터: `data/experiments/all_fixtures_2026051*.json` (10개).
- Trim policy: `drop1` (각 fixture 의 measurement 에서 min 1 + max 1 제외 후 평균). `--trim p10` / `p20` 옵션도 사용 가능.

> 누적 실험 트래커·채택 룰·백로그: [`ai/EXPERIMENTS.md`](ai/EXPERIMENTS.md). 새 실험에서 전 fixture 평균 strict가 +2%p 이상 좋아질 때 위 표가 갱신됩니다.

---

## 🛠 시스템 구조

### `ai/` — 추출 파이프라인 (4-stage)

```
ai/
├── pipeline.py             # 4-stage 직렬 orchestrator
├── services/
│   ├── upstage.py          # httpx 비동기 client + retry + 토큰 사용량 캡처
│   ├── parse.py            # Document Parse 어댑터 + HTML 우회
│   ├── extract.py          # Solar + json_schema 추출 + N=2/5 voting + 도메인/언어 분기
│   ├── voting.py           # 필드별 majority voting (enum/list/citation 정규화)
│   ├── summarize.py        # Solar 위험 조항 요약
│   ├── ground.py           # Solar verification (fallback)
│   └── settings.py         # 멀티 API 키 라운드로빈 분배
├── schemas/                # FieldValue[T] generic wrapper, 7 sections × 42 fields
└── prompts/
    ├── extract_subscription.py    # SYSTEM_PROMPT (OTT/Fintech 도메인-aware)
    ├── summarize_subscription.py  # 위험 조항 식별 룰
    └── groundedness_check.py      # 검증 verifier
```

**시스템 프롬프트 분기** (`ai/services/extract.py:_select_system_prompt`)

```
도메인 감지 (service_name + 본문 keyword)
    │
    ├─ MINIMAL_PROMPT=1 강제 → MINIMAL_SYSTEM_PROMPT
    │
    ├─ AI 도메인 감지?
    │   ├─ Yes:
    │   │   ├─ 영문 (한글 비율 < 30%) → AI_SYSTEM_PROMPT  ← LLM-1~6 영문 boilerplate 룰
    │   │   └─ 한국어 (≥ 30%)         → MINIMAL_SYSTEM_PROMPT  ← R9 검증, OTT-overfit 방지
    │   │
    │   └─ No → SYSTEM_PROMPT (OTT/Fintech 도메인-aware, 사례 A-F + 한국 강행규정 inferred)
```

| 환경변수 | Default | 효과 |
|---|---|---|
| `AUTO_AI_DOMAIN` | `1` | service_name/본문 keyword로 AI 자동 감지 |
| `AI_SPECIALIZED` | `1` | AI 도메인일 때 영문이면 AI_SYSTEM_PROMPT, 한국어면 MINIMAL |
| `MINIMAL_PROMPT` | `0` | 모든 fixture에 minimal prompt 강제 (zero-shot 측정용) |
| `EXTRACT_ENSEMBLE_N` | `2` | voting N. 평가용 N=5 권장 |
| `EXTRACT_REASONING_EFFORT` | `medium` | Round 1-4에서 medium이 winner |
| `SUMMARIZE_REASONING_EFFORT` | `high` | Round 5에서 high가 +1.5%p |
| `GROUND_REASONING_EFFORT` | `medium` | Round 5에서 medium이 +1.2%p |

### `app/` — FastAPI 백엔드

```
app/
├── main.py                    # FastAPI 앱 + 글로벌 exception handlers (502/422 매핑)
├── routers/
│   ├── terms.py               # POST /terms/upload, GET /terms, /search, /update
│   ├── chat.py                # POST /chat (약관 질의 RAG)
│   ├── calendar.py            # GET /calendar?user_id&month
│   ├── notifications.py       # GET / PATCH /read-all / PATCH /{id}/read / DELETE
│   └── disputes.py            # /v1/disputes, /v1/terms/{id}/disputes (유사 사례)
├── services/
│   ├── term_service.py        # 업로드 처리, 청크 임베딩 검색, page/bbox 매핑
│   ├── chat_service.py        # GPT-style 대화 (latency-aware)
│   ├── calendar_service.py    # compute_calendar_events (결정론적, LLM 미사용)
│   ├── notification_service.py
│   ├── dispute_service.py     # 분쟁 사례 upsert + find_similar_disputes
│   └── ai_client.py           # ai/* 와 server 사이 thin wrapper, key 분리
├── models/                    # SQLAlchemy ORM (PostgreSQL + pgvector halfvec)
│   └── dispute.py             # DisputeCase 테이블
├── schemas/                   # API 응답 Pydantic 스키마
└── config.py
```

**Latency tradeoff**: `chat_service.py`만 별도 — 사용자 live response 대기 중이라 N=1 + medium reasoning 사용. 나머지(추출/요약/diff/임베딩/분쟁 매칭)는 accuracy 우선.

**Upstage API 키 분리** (`.env` 의 `UPSTAGE_API_KEY` + `_2/3/4`):
- **Key #1**: 서비스 dev / FastAPI app / `single_run.py` 전용. `Settings.service_api_key`.
- **Key #2/3/4**: 평가 스크립트 (`parallel_run`, `run_all_fixtures`, `eval_variance`) 전용. `Settings.eval_api_keys`. 빈 리스트면 평가 스크립트가 exit 1 (key #1 으로 폴백 금지).

**글로벌 exception handlers** (`app/main.py`) — 클라이언트가 분류 가능한 응답:
- `UpstreamResponseError` / `httpx.HTTPStatusError` → 502 `{error: "upstream_error", detail}`
- `SchemaValidationError` / `DiffSchemaError` → 422 `{error: "validation_error", detail}`
- 일반 `ValueError` → 500 (코드 버그)

---

## 🔬 실험 라운드 요약 (R1-R11)

| Round | 변경 | 효과 (semantic) |
|---|---|---|
| R1-R4 | Config matrix (Netflix PDF 23 runs) | G config (N=2 medium) 선정 |
| R5 | Per-stage reasoning_effort 튜닝 | summarize=high, ground=medium → +2.7%p |
| R6 | Prompt #1: 한국 OTT inferred False | OTT Netflix +5%p (74.7 → 79.7) |
| R7 | Prompt #2: 도메인 인식 (OTT/Fintech 분리) + 사례 F (EFTA) | Fintech +5%p |
| R8a-c | 15 fixture domain spread 측정 + AI specialization 시도 → rollback | AI 회귀 발견 |
| R8d | Scoring embedding (multilingual-MiniLM) + flag canonical + list vocab | Watcha precision 0.00 → 0.17, str semantic +8-12%p |
| R9 | AI 도메인 conditional minimal prompt | AI +4.1%p sem (Claude +7.5, Gemini +1.5) |
| R10 | AI 영문 boilerplate specialized prompt | 영문 AI +7.8%p / 한국어 AI -8.5%p (혼합 결과) |
| **R11** | **언어 자동 분기** (영문→AI_SYSTEM, 한국어→MINIMAL) | **영문 AI +6.5%p 유지 + 한국어 AI R9 수준 유지** ⭐ |

### counter-intuitive 발견

1. **`reasoning_effort: medium > high` (extract)** — voting과 충돌
2. **`reasoning_effort: high` (summarize/ground)** — 단일 호출은 voting 보호 없어 reasoning 깊이 직접 기여
3. **temperature=0인데도 ±5-13%p 변동** — Solar API 비-결정성 잔존, N=5도 ±3.2%p
4. **Scoring layer > prompt tuning** (안전성 측면) — embedding/flag canonical은 회귀 없이 누적
5. **벤치마크 (MCQ 80%) 직접 비교 부적절** — 객관식 vs 자유 추출, task 자체가 다름
6. **AI 약관 ≠ OTT 약관** (구조적으로 다름) — token/MAU, 학습 데이터, 출력 IP. 도메인 분기 필요
7. **언어 분기 > 도메인 분기 단독** — AI 한국어 vs 영문이 같은 prompt에서 정반대 효과 보임
8. **fixture 크기 ≠ 정확도** — Gemini 437KB (49%) vs KakaoPay 109KB (74%)

---

## 🚀 Setup

```bash
uv venv && source .venv/bin/activate
uv pip install -r requirements.txt
cp .env.example .env  # UPSTAGE_API_KEY + DB 설정
```

평가 시 임베딩 매칭 (`scripts/score_against_golden.py --semantic`) 사용하려면:

```bash
uv pip install sentence-transformers
```

### DB 마이그레이션

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f migrations/0001_termclause_page_bbox.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f migrations/0002_dispute_cases.sql
```

또는 Supabase SQL Editor 에 파일 내용 그대로 붙여넣고 실행. 적용 후 분쟁 사례 시드:

```bash
PYTHONPATH=. python scripts/index_dispute_cases.py
# → data/fixtures/dispute_cases.json (19건) upsert + embedding-passage 인덱싱
```

### 단일 분석 (CLI)

```bash
PYTHONPATH=. .venv/bin/python scripts/single_run.py netflix
PYTHONPATH=. .venv/bin/python scripts/score_against_golden.py /tmp/variance_run_1.json data/fixtures/netflix_golden.json --semantic
```

### 전체 fixture 일괄 평가

```bash
EXTRA_FIXTURES=all EXTRACT_ENSEMBLE_N=5 PYTHONPATH=. .venv/bin/python scripts/run_all_fixtures.py 2 3
# → 15 fixture × 2 runs × N=5 × 3 keys, ~50분 wall clock
# → data/experiments/all_fixtures_<timestamp>.{json,md}
```

### FastAPI 서버

```bash
PYTHONPATH=. uvicorn app.main:app --reload
```

---

## 📁 산출물

| 위치 | 내용 |
|---|---|
| `ai/services/extract.py` | 도메인/언어-aware 시스템 프롬프트 분기 (R9-R11) |
| `scripts/score_against_golden.py` | embedding + flag canonical + list vocab + enum alias 정규화 (R8d) |
| `data/fixtures/*_golden.json` | 15개 사람 라벨 데이터 (OTT 7 + Fintech 3 + AI 5) |
| `data/experiments/all_fixtures_*.{json,md}` | 라운드별 measurement raw + aggregate report |

---

## 🚧 한계 및 다음 단계

1. **Sample variance 한계**: N=5도 ±3-5%p. 진짜 effect size 측정에는 N≥10 또는 cross-time average 필요.
2. **AI 약관 schema 미스매치**: DeepSeek/GPT 같은 영문 AI에서 우리 schema (42 fields, OTT-fit) 가 AI 핵심 필드 (training_data_use, output_ownership, api_key_management) 부재 — Round 12 후보.
3. **벤치마크 직접 비교 부적절**: Solar Pro 3 MCQ 80%는 *4지선다*, 우리 task는 *42 필드 자유 추출*. 진짜 baseline은 zero-shot (위 표 참조).
4. **언어 분기 OTT 미적용**: Spotify(영문 OTT) 같은 boundary case는 현재 SYSTEM_PROMPT로 잘 처리되지만, 영문 OTT가 늘면 OTT-en 분기 추가 가치 있음.
5. **Inter-annotator agreement 미측정**: 골든 라벨 ceiling을 모름. 우리 64%가 ceiling 85%인지 75%인지 확실치 않음.

---

## 🏦 도메인 확장 (Finance / Insurance) — 스키마 정의 완료

OTT/구독 외 도메인용 추출 스키마를 별도 정의해 두었습니다 — 기존 `SubscriptionTerms` 7-section 구조가 fit 하지 않는 도메인을 위한 스키마 분리입니다 (`data/fixtures/toss_golden.json` 의 `schema_fit_note`: *"pricing.*, free_trial.* 등은 의미 없음"* 명시).

| 도메인 | 스키마 | 주요 섹션 |
|---|---|---|
| 전자금융/결제/송금 | [`ai/schemas/finance.py`](ai/schemas/finance.py) — `FinanceTerms` | Fees · TransactionLimits · LiabilityAllocation (EFTA §9) · DepositProtection · AccountTermination · TermsChanges · DataUsage · Disputes |
| 보험 (실손/생명/손해 등) | [`ai/schemas/insurance.py`](ai/schemas/insurance.py) — `InsuranceTerms` | Coverage · Exclusions · Premium · Claims · CancellationRefund · Renewal · TermsChanges · DataUsage · Disputes |

`ai/services/voting.py` 는 schema-polymorphic 으로 리팩되어 위 두 도메인 + 기존 OTT 스키마에 모두 동작합니다 (`vote_terms(terms_list)`). 단위 테스트는 `tests/unit/test_schemas_{finance,insurance}.py`, `test_services_voting.py::test_vote_terms_works_on_*` 에 포함.

**파이프라인 라우팅**: `run_pipeline(..., domain="finance" | "insurance" | "subscription")` 으로 도메인 분기.

```python
# app/services/ai_client.py
result = await run_full_pipeline(file_bytes, filename, service_name, domain="finance")
# result.terms 는 FinanceTerms 인스턴스, result.domain == "finance"
```

| 진입점 | 위치 |
|---|---|
| 프롬프트 | [`ai/prompts/extract_finance.py`](ai/prompts/extract_finance.py), [`ai/prompts/extract_insurance.py`](ai/prompts/extract_insurance.py) |
| Extract 함수 | `extract_finance` / `extract_finance_with_voting` / `extract_insurance` / `extract_insurance_with_voting` ([`ai/services/extract.py`](ai/services/extract.py)) |
| Pipeline 진입점 | `run_pipeline(..., domain=...)` ([`ai/pipeline.py`](ai/pipeline.py)) |

**Golden 라벨링 도구**:
- 기존 OTT-shaped fintech golden 을 finance 좌표계로 자동 변환: [`scripts/remap_fintech_golden_v03.py`](scripts/remap_fintech_golden_v03.py) → `data/fixtures/{toss,kakaopay,banksalad}_golden_v03_finance.json`
- 새 약관용 빈 템플릿: [`scripts/build_finance_golden_template.py`](scripts/build_finance_golden_template.py), [`scripts/build_insurance_golden_template.py`](scripts/build_insurance_golden_template.py)

**현재 상태**: 스키마 + voting + 프롬프트 + 라우팅 + golden 자동 remap (fintech 3건) + insurance 템플릿까지 완료. 실 약관 fixture 추가 + 도메인별 정확도 평가는 deadline 후 진행 ([`ai/EXPERIMENTS.md`](ai/EXPERIMENTS.md) 백로그).

---

## ⚖️ 유사 분쟁 사례 매칭

업로드된 약관의 위험 조항(`KeyClause`)에 대해 **과거 한국소비자원·법원 분쟁 사례 중 의미적으로 유사한 케이스**를 매칭해 보여주는 시스템.

- 데이터: [`data/fixtures/dispute_cases.json`](data/fixtures/dispute_cases.json) — OTT 8 + Fintech 5 + AI/LLM 3 + ALL 3 = 19건. 각 case = `{title, summary, outcome, source, pain_point_ids, unfair_flags, domain}`.
- 임베딩: title + summary + outcome 결합 텍스트를 Upstage `embedding-passage` 로 4096-d halfvec 저장.
- 매칭 함수: [`dispute_service.find_similar_disputes`](app/services/dispute_service.py) — cosine similarity + **pain_point/unfair_flag/domain 일치 boost**.
- 라우터: [`app/routers/disputes.py`](app/routers/disputes.py)
  - `POST /v1/disputes` — 임의 텍스트로 유사 사례 검색
  - `GET  /v1/terms/{term_id}/disputes` — 해당 약관의 각 KeyClause 마다 매칭된 유사 사례 묶음
- ANN 인덱스 부재 사유: pgvector HNSW/IVFFlat 둘 다 4000-d 한계 → halfvec(4096) 미지원. 19~수백 row 규모는 linear cosine scan 으로 1ms 미만, 수만 row 이상 시 차원 축소 필요 (`migrations/README.md` 참조).
- 적재 스크립트: `PYTHONPATH=. python scripts/index_dispute_cases.py` (idempotent — `external_id` 기준 upsert).
- e2e 검증: [`tests/integration/test_disputes_e2e.py`](tests/integration/test_disputes_e2e.py) (실 DB + Upstage 호출).

---

## 📚 관련 문서

- [`ai/EXPERIMENTS.md`](ai/EXPERIMENTS.md) — 실험 트래커 (현재 베스트 케이스 + 누적 로그 + 채택 룰 + 다음 실험 백로그)
- [`CLAUDE.md`](CLAUDE.md) — Claude Code 작업 가이드 (최적화 우선순위 + 챗봇 latency 예외)
- [`docs/`](docs/) — 추가 설계 노트
- 이전 prototype repo: [`upstage_ai`](https://github.com/wooxogh/upstage_ai) — Round 1-10 누적
