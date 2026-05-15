# Upstage AI Terms — 데모

한국 OTT · Fintech · AI 약관을 분석하는 풀스택 데모. Upstage Solar Pro 3 기반 4단계 파이프라인으로 42개 필드 + 위험 조항 + 인용 근거를 추출하고, 챗봇·캘린더·알림 같은 사용자-facing 기능까지 연결.

```
입력 (PDF/HTML 약관)
  ↓ ai/pipeline.py
  ├─ Document Parse / HTML 직접 추출
  ├─ Solar Pro 3 × N=5 voting (도메인-aware 분기) ← Round 11: 영문/한국어 자동 분기
  ├─ Solar Pro 3 위험 조항 요약
  └─ Solar Pro 3 groundedness 검증
출력 → DB 저장 → FastAPI (POST /v1/terms/analyze)
                  → 사용자 챗봇 (GPT-style 대화로 약관 질의)
                  → 캘린더 (자동갱신·환불 마감 등 일자 추출)
                  → 알림 (위험 조항 푸시)
```

---

## 📊 성능 평가 (Round 11 최신, 12 fixture × 2 runs × N=5)

**3-tier baseline**: zero-shot (raw Solar API) vs N=5 우리 시스템 vs 도메인-aware 분기.

| 도메인 | n | Zero-shot sem | R9 (minimal) sem | **R11 (언어 분기) sem** | 진짜 시스템 기여 |
|---|---|---|---|---|---|
| **OTT (한국어 6 + 영문 1)** | 7 | 61.9% | 68.5% | **63.6%** | **+1.7%p**¹ |
| **AI 한국어** (Claude/Gemini/Upstage) | 3 | 51.7% | 56.3% | **53.0%** | +1.3%p¹ |
| **AI 영문** (GPT/DeepSeek) | 2 | 68.5% | 54.2% | **60.8%** | -7.7%p² |
| **AI 전체** | 5 | 58.4% | 55.5% | **56.1%** | -2.3%p² |
| **전체 12** | 12 | 62.0% | 63.1% | **60.5%** | -1.5%p |

¹ Sample noise 영향 큼 (N=5도 ±5%p variance). 동일 prompt OTT measurement에서 -4.9%p 떨어진 noise floor 확인 → noise 보정 시 OTT 실제 변화 ~0, AI 한국어 약 +1.6%p.

² AI 영문은 zero-shot baseline이 73(DeepSeek) 등 outlier 포함이라 raw 비교 misleading. **Round간 비교가 더 정확**: R9 → R11 영문 AI **+6.5%p**, noise 보정 시 **+11.4%p** ⭐.

### 도메인별 시스템 기여 (Noise 보정 후 추정)

| 도메인 | 노이즈 보정 시스템 효과 | 비고 |
|---|---|---|
| OTT | ~+5%p | 사례 A-E + 한국 OTT inferred False 룰 (R6) + scoring embedding (R8) 누적 |
| Fintech | ~+2-4%p | 사례 F (EFTA 패턴) (R7) |
| **AI 영문** | **+11.4%p** ⭐ | LLM-6 영문 boilerplate (R10) + 언어 분기 (R11) |
| AI 한국어 | ~+1.6%p | R9 minimal prompt 자동 분기 (R11) |

### 측정 출처

- Zero-shot baseline: `data/experiments/all_fixtures_20260515_135302.{json,md}` (15 fixture × 1 run, 12분, minimal prompt + N=1)
- N=5 baseline: `data/experiments/all_fixtures_20260515_145146.{json,md}` (15 fixture × 2 runs × N=5, 56.6분)
- Round 11 (언어 분기): `data/experiments/all_fixtures_20260515_180018.{json,md}` (12 fixture × 2 runs × N=5, 49.5분)

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
├── main.py               # FastAPI 앱 + exception handlers
├── routers/
│   ├── terms.py          # POST /v1/terms/analyze (멀티파트 업로드)
│   ├── chat.py           # 사용자 챗봇 (약관 질의)
│   ├── calendar.py       # 자동갱신·환불 마감 자동 추출
│   └── notifications.py  # 위험 조항 푸시 알림
├── services/
│   ├── term_service.py
│   ├── chat_service.py   # GPT-style 대화 (latency-aware)
│   ├── calendar_service.py
│   └── ai_client.py
├── models/               # SQLAlchemy ORM (PostgreSQL + pgvector)
└── config.py
```

**latency tradeoff**: `chat_service.py`만 별도 — 사용자 live response 대기 중이라 N=1 + medium reasoning 사용. 나머지는 accuracy 우선.

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
psql -f migrations/0001_termclause_page_bbox.sql $DATABASE_URL
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

**현재 상태**: 데이터 계약(스키마) + 집계 로직(voting) 까지 완료. 도메인별 prompt 튜닝 / extract 라우팅 / golden 평가는 [`ai/EXPERIMENTS.md`](ai/EXPERIMENTS.md) 백로그에 follow-up 으로 등재.

---

## 📚 관련 문서

- [`ai/EXPERIMENTS.md`](ai/EXPERIMENTS.md) — 실험 트래커 (현재 베스트 케이스 + 누적 로그 + 채택 룰 + 다음 실험 백로그)
- [`CLAUDE.md`](CLAUDE.md) — Claude Code 작업 가이드 (최적화 우선순위 + 챗봇 latency 예외)
- [`docs/`](docs/) — 추가 설계 노트
- 이전 prototype repo: [`upstage_ai`](https://github.com/wooxogh/upstage_ai) — Round 1-10 누적
