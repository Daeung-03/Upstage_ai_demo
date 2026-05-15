# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Optimization priorities (사용자 명시)

When tuning config / prompts / architecture for the extraction pipeline:

1. **Performance (accuracy on user-labeled golden) — top priority.** Pursue any
   change that improves measured strict / semantic accuracy.
2. **Latency / wall-clock time — secondary.** Faster is better if accuracy is
   unchanged; trade time for accuracy when in doubt.
3. **Token / API cost — not a constraint.** Do **not** sacrifice accuracy or
   reasonable latency to save tokens. Solar Pro 3 `reasoning_effort=high`,
   `N=5` voting, multiple verification calls — all on the table if they help.
   Do not propose "cheaper" alternatives unless they are accuracy/time-equivalent.

Concretely: do not gate experiments on token budget. When presenting trade-offs,
lead with accuracy delta, then time delta. Token usage is reported for visibility
only.

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

   Wrapped by `extract_subscription_with_voting()`: **N=3 sequential** calls (`ENSEMBLE_N`). Parallel calls hit Upstage 429 rate limits, so calls are serial. Aggregation lives in `services/voting.py`: per-field majority vote across the three `SubscriptionTerms` results, then `unfair_clause_flags = union`. The winning `FieldValue` is kept whole, preserving its `citation` (including bbox). `None` is treated as "empty"; `[]` and `""` are considered meaningful (e.g., `blackout_periods=[]` means "no blackouts").

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
