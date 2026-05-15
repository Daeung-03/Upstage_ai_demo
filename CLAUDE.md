# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Optimization priorities (사용자 명시)

**Applies to all services in this repo that the user is implementing — extraction
pipeline, embedding, calendar/date extraction, summary/diff, page-bbox enrichment,
etc. — EXCEPT the chatbot (which has its own latency tradeoff; see below).**

1. **Performance (accuracy / quality of output) — top priority.** Pursue any
   change that improves measured accuracy or output fidelity.
2. **Latency / wall-clock time — secondary.** Faster is better if accuracy is
   unchanged; trade time for accuracy when in doubt.
3. **Token / API cost — not a constraint.** Do **not** sacrifice accuracy or
   reasonable latency to save tokens. Solar Pro 3 `reasoning_effort=high`,
   `N=5` voting, multiple verification calls, larger embedding batches with
   re-tries — all on the table if they help. Do not propose "cheaper"
   alternatives unless they are accuracy/time-equivalent. **Do not warn the
   user about token cost** before running experiments / verifications; just
   run them.

Concretely: do not gate experiments on token budget. When presenting trade-offs,
lead with accuracy delta, then time delta. Token usage is reported for visibility
only.

## Upstage API key 분리 정책

`.env` 에 키 4개 (`UPSTAGE_API_KEY`, `UPSTAGE_API_KEY_2/3/4`). 두 사용 패턴:

- **FastAPI app (`app/services/ai_client.py`)** — `AISettings.app_api_key_pool`
  property 를 통해 **설정된 모든 키를 round-robin** 으로 사용. bulk upload / 데모
  동시 요청이 단일 키 rate-limit 에서 직렬화되는 걸 막기 위함. Railway 환경에서
  Key #2/3/4 를 비워두면 pool = `[Key #1]` 로 자동 축소돼 이전 동작과 동일.
- **평가 / 벤치마크 스크립트** — `parallel_run.py`, `run_all_fixtures.py`,
  `eval_variance.py` 등은 `Settings.eval_api_keys` 만 사용. Key #2/3/4 중 설정된
  것만 리턴 — 비어있으면 스크립트가 exit 1 (silent fallback 금지: key #1 으로
  흘러가면 분리 정책 무의미).

eval 격리는 "평가 스크립트가 app 키를 안 쓴다" 한 방향으로만 강제. app 도 키
2/3/4 를 활용해 throughput 을 늘릴 수 있지만, 평가 작업과 시간이 겹치면 quota 가
경합할 수 있으니 대용량 eval 돌릴 땐 bulk upload 를 피하거나 Railway 의
Key #2/3/4 env 를 일시 unset.

새 평가/벤치마크 스크립트 추가 시: `settings.eval_api_keys` 만 사용.
`service_api_key` 는 절대 평가 코드에서 호출하지 말 것.

### Chatbot exception
The chatbot service (`app/services/chat_service.py`, `chat_with_ai`) has a
latency-vs-accuracy tradeoff: user is waiting on a live response, so reasonable
latency is required. Token cost is still not a constraint, but multi-pass
voting / `reasoning_effort=high` chains that take 30s+ are off the table for
chatbot specifically.

## Project

FastAPI service that analyses OTT/구독 (subscription) terms-of-service documents through a 4-stage Upstage AI pipeline: **Document Parse → Information Extract → Solar Pro 3 요약 → Groundedness Check**. The single user-facing endpoint is `POST /v1/terms/analyze` (multipart upload + `service_name` + `service_provider`).

## Common Commands

Setup uses `uv`; the project is installed editable:

```bash
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
cp .env.example .env   # fill UPSTAGE_API_KEY
uvicorn app.main:app --reload
```

Tests:

```bash
pytest tests/unit -v                                  # unit (no network)
pytest tests/unit/test_services_voting.py -v          # single file
pytest tests/unit/test_services_voting.py::test_x     # single test
pytest tests/integration -v -m e2e                    # real API; needs UPSTAGE_API_KEY + data/fixtures/netflix_terms.pdf
```

Lint / type-check:

```bash
ruff check .
mypy services schemas app
```

Evaluation scripts (require a real `UPSTAGE_API_KEY` and the Netflix PDF fixture):

```bash
.venv/bin/python scripts/single_run.py                # one pipeline run → /tmp/variance_run_1.json
.venv/bin/python scripts/eval_variance.py             # 5 sequential runs, field-level consistency report
.venv/bin/python scripts/score_against_golden.py      # diff /tmp/variance_run_1.json vs data/fixtures/netflix_golden.json
.venv/bin/python scripts/build_golden_template.py     # seed a new golden label file from a pipeline result
```

## Architecture

### Pipeline orchestration (`services/pipeline.py`)
`run_pipeline()` runs the four stages sequentially against a single `UpstageClient`, capturing per-stage `StageTiming` and `StageUsage` (token/page totals aggregated from each upstream `usage` payload). The client buffers usage internally; `client.snapshot_usage()` is called at each stage boundary to drain and tag the usage.

### Stage-by-stage

1. **`services/parse.py`** — `POST /document-digitization` (model `document-parse`, `mode=enhanced` by default = VLM, accurate but costlier; callers may pass `mode="standard"` or `"auto"`). Returns markdown + `ParsedElement[]` with **0–1 normalized bboxes** (multiply by page width/height to convert to pixels).

2. **`services/extract.py`** — `POST /chat/completions` with `model=solar-pro3`, `response_format.json_schema`, `reasoning_effort=high`, `temperature=0`. The Information Extract API is **not** used: it forbids nested root objects, which conflicts with the 7-section `SubscriptionTerms` schema. After parsing, `_enrich_with_bbox` walks every `FieldValue.citation`, matches `citation.quote` against `ParsedElement.text` (page-first → global → whitespace-normalized → 20-char anchor prefix) and back-fills `bbox` + `section`.

   Wrapped by `extract_subscription_with_voting()`: **default N=2 sequential** calls (`ENSEMBLE_N`, env-overridable). Parallel calls hit Upstage 429 rate limits, so calls are serial (429 is now retried with `Retry-After` honored, see `services/upstage.py`). N=2 + `reasoning_effort=medium` is the experimentally chosen winner (2026-05-14 23-run benchmark: avg 71.6% vs N=3 medium 65.8% at -28% wall-time; see `ai/EXPERIMENTS.md`). Aggregation lives in `services/voting.py`: per-field majority vote across the runs, then `unfair_clause_flags = union`. The winning `FieldValue` is kept whole, preserving its `citation` (including bbox). `None` is treated as "empty"; `[]` and `""` are considered meaningful (e.g., `blackout_periods=[]` means "no blackouts").

3. **`services/summarize.py`** — `POST /chat/completions` with `response_format=json_object`, `temperature=0`. Produces `summary` + 3–5 `KeyClause` objects (`title`, `description`, `risk_level`, `pain_point_id`, `citation`).

4. **`services/ground.py`** — Falls back to a Solar-Pro-3 verification prompt because Upstage's dedicated groundedness endpoint is not yet in the public docs (TODO comment marks the swap-in point). Each clause's `citation.quote` is first checked **deterministically** against the source markdown (normalized + 16-char anchor); if found, an LLM judgment of `score ≥ 0.4` keeps it grounded. Without an anchor, the threshold rises to `MIN_SCORE = 0.6` with `grounded is True`. The summary itself has no anchor and depends entirely on the LLM judgment.

### Contract layer (`schemas/`)
- `FieldValue[T]` = `{value: T | None, uncertainty: Uncertainty, citation: Citation | None}` — every extracted scalar/list goes through this generic wrapper. Drives both the JSON Schema given to the model and the voting/scoring logic downstream.
- `SubscriptionTerms` = 7 section models (`Pricing`, `FreeTrial`, `Cancellation`, `TermsChanges`, `DataUsage`, `Liability`, `Disputes`) + metadata + `unfair_clause_flags: list[str]`. Section names are duplicated as a tuple `SECTION_NAMES` in `services/extract.py`, `services/voting.py`, and the scripts — keep these in sync if you add a section.
- `schemas/enums.py` defines the enum vocabulary the model is constrained to. Adding values requires updating prompts under `prompts/`.

### Upstage HTTP client (`services/upstage.py`)
- `UpstageClient` is async-context-managed. Default timeout 180s, 3 retries with exponential backoff on transport errors and 5xx (no sleep on the final attempt).
- Two distinct upstream failure modes are raised so handlers map them differently:
  - `UpstreamResponseError` (non-JSON / unparsable body) → `app/main.py` returns **502**.
  - `SchemaValidationError` (LLM output failed Pydantic validation) → returns **422**. Plain `ValueError` is **not** caught — keep that distinction when refactoring.
- Top-level `usage` from every successful response is appended to `_usages` for the pipeline to snapshot.

### Evaluation harness
`data/fixtures/netflix_golden.json` is the human-edited ground truth. The scoring script classifies each field as `ok / ok_null / wrong / missed / over_extracted` and breaks accuracy down by section and by type (`int / bool / enum / list / str`). Variance runs write to `/tmp/variance_run_{N}.json` so the same file can feed both `score_against_golden.py` and `build_golden_template.py`.

## Conventions

- Comments and prompts contain Korean copy intentionally (target audience + domain prompts). Keep new domain-facing strings in Korean unless changing user-visible language.
- Async everywhere below the route layer — every Upstage call goes through `UpstageClient`; don't introduce blocking I/O in `services/*`.
- E2E fixtures (`data/fixtures/*.pdf`, `*.html`) are gitignored. Real terms documents must be added locally before running `-m e2e` tests.
- `pytest.ini_options.asyncio_mode = "auto"` — async tests don't need `@pytest.mark.asyncio`.
