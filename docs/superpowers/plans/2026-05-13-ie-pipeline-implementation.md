# IE Pipeline Implementation Plan — OTT/구독 Vertical Slice

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** OTT/구독 도메인 약관 1건을 입력받아 `Document Parse → Information Extract → Solar Pro 3 요약 → Groundedness Check`까지 종단 동작하는 FastAPI 엔드포인트 구현

**Architecture:** 3개의 Upstage API(+1 헬퍼)를 얇은 어댑터(`services/*.py`)로 감싸고, Pydantic v2 스키마(`schemas/subscription.py`)를 contract로 삼아 어댑터들을 직렬로 엮는다. FastAPI 엔드포인트(`/v1/terms/analyze`)는 오케스트레이터(`services/pipeline.py`)를 호출만 한다. 모든 추출 값은 `FieldValue[T]`로 래핑되어 (값, 불확실성, 원문 인용)을 보유한다.

**Tech Stack:** Python 3.12+, FastAPI, Pydantic v2, httpx (async), pytest + pytest-asyncio + pytest-httpx (mock), uv 의존성 관리

**Upstage API 매핑 (공식 docs 검증됨)**

| 단계 | 엔드포인트 | 모델 | 비고 |
|---|---|---|---|
| Parse | `POST /document-digitization` | `document-parse` | multipart, `coordinates=true`, 좌표는 0–1 normalized |
| Extract | `POST /chat/completions` | `solar-pro3` | `response_format.json_schema` 로 nested 지원. IE 전용 API는 root-level object 금지라 부적합 |
| Summarize | `POST /chat/completions` | `solar-pro3` | `response_format.json_object`, `reasoning_effort` 조정 가능 |
| Ground | (endpoint TBD) | `solar-pro3` fallback | 공식 docs raw에 미수록 — v1은 Solar chat verification prompt로 대체, 전용 endpoint 발견 시 swap |

**Data Flow:**

```
PDF/HTML (multipart)
   │
   ▼
[services/parse.py]       /document-digitization → Markdown + Elements(bbox 0-1)
   │
   ▼
[services/extract.py]     /chat/completions + json_schema → SubscriptionTerms (citation.quote만)
   │                      + bbox 후처리: quote ↔ ParsedElement 매칭 → citation.bbox 채움
   ▼
SubscriptionTerms         Pydantic instance (validated, bbox enriched)
   │
   ▼
[services/summarize.py]   /chat/completions → 위험 조항 3~5개
   │
   ▼
[services/ground.py]      Solar chat verification → 미통과 문장 필터
   │
   ▼
API Response { terms, summary, key_clauses[], grounded, timings[] }
```

---

## File Structure

| Path | Responsibility |
|---|---|
| `pyproject.toml` | uv-friendly deps, ruff/pytest 설정 |
| `.env.example` | UPSTAGE_API_KEY 자리표 |
| `app/main.py` | FastAPI 앱 + health check |
| `app/routes/terms.py` | `POST /v1/terms/analyze` |
| `schemas/common.py` | `FieldValue[T]`, `Citation`, `Uncertainty` |
| `schemas/enums.py` | 도메인 enum 5종 |
| `schemas/pain_points.py` | Pain Point ID + 라벨 매핑 |
| `schemas/subscription.py` | 7개 섹션 + `SubscriptionTerms` root |
| `services/upstage.py` | httpx async 클라이언트 (인증/재시도/로깅) |
| `services/parse.py` | Document Parse 어댑터 |
| `services/extract.py` | Information Extract 어댑터 (SubscriptionTerms 반환) |
| `services/summarize.py` | Solar Pro 3 요약 어댑터 |
| `services/ground.py` | Groundedness Check 어댑터 |
| `services/pipeline.py` | 위 4개를 엮는 오케스트레이터 |
| `prompts/extract_subscription.py` | IE 시스템 메시지 + 스키마 참조 |
| `prompts/summarize_subscription.py` | 요약 시스템 + 사용자 프롬프트 템플릿 |
| `tests/conftest.py` | 공유 fixture (mocked httpx, sample 문서) |
| `tests/unit/test_schemas_*.py` | 스키마 단위 테스트 |
| `tests/unit/test_services_*.py` | 어댑터 단위 테스트 (httpx_mock 사용) |
| `tests/integration/test_pipeline_e2e.py` | 종단 테스트 (real fixture, 키 있을 때만) |

---

## Task 1: 프로젝트 부트스트랩

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `.env.example`, `README.md`
- Create: `app/__init__.py`, `app/main.py`, `app/routes/__init__.py`
- Create: `services/__init__.py`, `schemas/__init__.py`, `prompts/__init__.py`
- Create: `tests/__init__.py`, `tests/unit/__init__.py`, `tests/integration/__init__.py`, `tests/conftest.py`
- Create: `tests/unit/test_health.py`
- Create: `data/fixtures/.gitkeep`

- [ ] **Step 1.1: pyproject.toml 작성**

```toml
[project]
name = "upstage-ai-terms"
version = "0.1.0"
description = "Terms-of-service analysis using Upstage AI"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.110",
    "uvicorn[standard]>=0.27",
    "pydantic>=2.6",
    "pydantic-settings>=2.2",
    "httpx>=0.27",
    "python-multipart>=0.0.9",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "pytest-httpx>=0.30",
    "ruff>=0.3",
    "mypy>=1.9",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
pythonpath = ["."]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP"]
```

- [ ] **Step 1.2: .gitignore 작성**

```
__pycache__/
*.pyc
*.pyo
.venv/
.env
.pytest_cache/
.ruff_cache/
.mypy_cache/
*.egg-info/
dist/
build/
.coverage
htmlcov/
.DS_Store
```

- [ ] **Step 1.3: .env.example 작성**

```
UPSTAGE_API_KEY=your_upstage_api_key_here
UPSTAGE_BASE_URL=https://api.upstage.ai/v1
LOG_LEVEL=INFO
```

- [ ] **Step 1.4: README.md 작성 (간략)**

```markdown
# Upstage AI Terms Analysis

OTT/구독 약관 분석 파이프라인. Document Parse → Information Extract → Solar Pro 3 요약 → Groundedness Check.

## Setup

```bash
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
cp .env.example .env  # UPSTAGE_API_KEY 입력
uvicorn app.main:app --reload
```

## Test

```bash
pytest tests/unit -v
```
```

- [ ] **Step 1.5: 디렉토리 + 빈 `__init__.py` 생성**

```bash
mkdir -p app/routes services schemas prompts data/fixtures tests/unit tests/integration
touch app/__init__.py app/routes/__init__.py services/__init__.py schemas/__init__.py prompts/__init__.py
touch tests/__init__.py tests/unit/__init__.py tests/integration/__init__.py
touch data/fixtures/.gitkeep
```

- [ ] **Step 1.6: `app/main.py` 작성**

```python
from fastapi import FastAPI

app = FastAPI(title="Upstage AI Terms Analysis", version="0.1.0")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 1.7: `tests/conftest.py` 작성 (공유 fixture 자리)**

```python
import pytest


@pytest.fixture
def sample_api_key() -> str:
    return "test-api-key-not-real"


@pytest.fixture
def sample_base_url() -> str:
    return "https://api.upstage.test/v1"
```

- [ ] **Step 1.8: `tests/unit/test_health.py` 작성**

```python
from fastapi.testclient import TestClient

from app.main import app


def test_health_endpoint_returns_ok():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 1.9: 가상환경 설치 + 테스트 실행**

```bash
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
pytest tests/unit/test_health.py -v
```

Expected: `1 passed`.

- [ ] **Step 1.10: 커밋**

```bash
git add pyproject.toml .gitignore .env.example README.md \
        app/ services/ schemas/ prompts/ tests/ data/
git commit -m "$(cat <<'EOF'
chore: project bootstrap (FastAPI skeleton + health check)

- pyproject.toml: FastAPI, Pydantic v2, httpx, pytest + dev tools
- Directory: app/, services/, schemas/, prompts/, tests/, data/
- Health check endpoint with smoke test
- .env.example placeholder for UPSTAGE_API_KEY

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: 공통 스키마 타입 (FieldValue, Citation, Uncertainty)

**Files:**
- Create: `schemas/common.py`
- Create: `tests/unit/test_schemas_common.py`

- [ ] **Step 2.1: 실패 테스트 작성**

```python
# tests/unit/test_schemas_common.py
from schemas.common import Citation, FieldValue, Uncertainty


def test_uncertainty_enum_values():
    assert Uncertainty.CONFIRMED.value == "confirmed"
    assert Uncertainty.INFERRED.value == "inferred"
    assert Uncertainty.AMBIGUOUS.value == "ambiguous"
    assert Uncertainty.NOT_SPECIFIED.value == "not_specified"


def test_citation_minimal():
    c = Citation(page=1, quote="자동 갱신됩니다")
    assert c.page == 1
    assert c.section is None
    assert c.bbox is None
    assert c.pain_point_id is None


def test_citation_full():
    c = Citation(
        page=3,
        section="제5조",
        bbox=(100.0, 200.0, 300.0, 250.0),
        quote="해지 시 위약금이 발생합니다",
        pain_point_id="POST-01",
    )
    assert c.bbox == (100.0, 200.0, 300.0, 250.0)
    assert c.pain_point_id == "POST-01"


def test_fieldvalue_int_confirmed():
    fv = FieldValue[int](
        value=9900,
        uncertainty=Uncertainty.CONFIRMED,
        citation=Citation(page=1, quote="월 9,900원"),
    )
    assert fv.value == 9900
    assert fv.uncertainty == Uncertainty.CONFIRMED
    assert fv.citation is not None
    assert fv.citation.page == 1


def test_fieldvalue_not_specified():
    fv = FieldValue[bool](
        value=None,
        uncertainty=Uncertainty.NOT_SPECIFIED,
        citation=None,
    )
    assert fv.value is None
    assert fv.uncertainty == Uncertainty.NOT_SPECIFIED
    assert fv.citation is None
```

- [ ] **Step 2.2: 테스트 실행 (실패 확인)**

```bash
pytest tests/unit/test_schemas_common.py -v
```

Expected: `ImportError: cannot import name 'Citation' from 'schemas.common'` 또는 `ModuleNotFoundError`.

- [ ] **Step 2.3: `schemas/common.py` 구현**

```python
from enum import Enum
from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Uncertainty(str, Enum):
    CONFIRMED = "confirmed"
    INFERRED = "inferred"
    AMBIGUOUS = "ambiguous"
    NOT_SPECIFIED = "not_specified"


class Citation(BaseModel):
    page: int
    section: str | None = None
    bbox: tuple[float, float, float, float] | None = None
    quote: str
    pain_point_id: str | None = None


class FieldValue(BaseModel, Generic[T]):
    value: T | None
    uncertainty: Uncertainty
    citation: Citation | None = None
```

Note: Pydantic v2의 generic은 `Generic[T]` 스타일 사용 (PEP 695 syntax는 deep nested generic에서 가끔 발 걸린다).

- [ ] **Step 2.4: 테스트 실행 (통과 확인)**

```bash
pytest tests/unit/test_schemas_common.py -v
```

Expected: `5 passed`.

- [ ] **Step 2.5: 커밋**

```bash
git add schemas/common.py tests/unit/test_schemas_common.py
git commit -m "$(cat <<'EOF'
feat(schemas): add FieldValue[T], Citation, Uncertainty

Generic FieldValue[T] wraps every extracted value with
(value, uncertainty, citation). Citation includes Document Parse
Location Coordinates (bbox) and pain_point_id for UI hyperlink
+ pain-point filtering.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: 도메인 enum

**Files:**
- Create: `schemas/enums.py`
- Create: `tests/unit/test_schemas_enums.py`

- [ ] **Step 3.1: 실패 테스트 작성**

```python
# tests/unit/test_schemas_enums.py
from schemas.enums import (
    BillingCycle,
    CancellationMethod,
    ConsentMechanism,
    NoticeChannel,
    ProrationPolicy,
)


def test_billing_cycle_values():
    assert {m.value for m in BillingCycle} == {
        "monthly", "quarterly", "semi_annual", "annual", "lifetime", "other",
    }


def test_notice_channel_values():
    assert {m.value for m in NoticeChannel} == {
        "email", "app_push", "sms", "web_notice", "in_app_banner",
    }


def test_consent_mechanism_includes_deemed_agreed():
    # 의사표시 의제는 불공정 약관 신호로 별도 enum 값
    assert ConsentMechanism.DEEMED_AGREED.value == "deemed_agreed"
    assert ConsentMechanism.OPT_IN_EXPLICIT.value == "opt_in_explicit"
    assert ConsentMechanism.OPT_OUT_AVAILABLE.value == "opt_out_available"


def test_cancellation_method_values():
    assert {m.value for m in CancellationMethod} == {
        "online", "phone", "in_person", "written",
    }


def test_proration_policy_values():
    assert {m.value for m in ProrationPolicy} == {
        "full_refund", "prorated", "no_refund",
    }
```

- [ ] **Step 3.2: 실패 확인**

```bash
pytest tests/unit/test_schemas_enums.py -v
```

Expected: `ImportError`.

- [ ] **Step 3.3: `schemas/enums.py` 구현**

```python
from enum import Enum


class BillingCycle(str, Enum):
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    SEMI_ANNUAL = "semi_annual"
    ANNUAL = "annual"
    LIFETIME = "lifetime"
    OTHER = "other"


class NoticeChannel(str, Enum):
    EMAIL = "email"
    APP_PUSH = "app_push"
    SMS = "sms"
    WEB_NOTICE = "web_notice"
    IN_APP_BANNER = "in_app_banner"


class ConsentMechanism(str, Enum):
    OPT_IN_EXPLICIT = "opt_in_explicit"
    OPT_OUT_AVAILABLE = "opt_out_available"
    DEEMED_AGREED = "deemed_agreed"


class CancellationMethod(str, Enum):
    ONLINE = "online"
    PHONE = "phone"
    IN_PERSON = "in_person"
    WRITTEN = "written"


class ProrationPolicy(str, Enum):
    FULL_REFUND = "full_refund"
    PRORATED = "prorated"
    NO_REFUND = "no_refund"
```

- [ ] **Step 3.4: 통과 확인**

```bash
pytest tests/unit/test_schemas_enums.py -v
```

Expected: `5 passed`.

- [ ] **Step 3.5: 커밋**

```bash
git add schemas/enums.py tests/unit/test_schemas_enums.py
git commit -m "$(cat <<'EOF'
feat(schemas): add domain enums

BillingCycle, NoticeChannel, ConsentMechanism, CancellationMethod,
ProrationPolicy. ConsentMechanism.DEEMED_AGREED captures the
"의사표시 의제" pattern that signals unfair clauses.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Pain Point Taxonomy

**Files:**
- Create: `schemas/pain_points.py`
- Create: `tests/unit/test_schemas_pain_points.py`

- [ ] **Step 4.1: 실패 테스트 작성**

```python
# tests/unit/test_schemas_pain_points.py
from schemas.pain_points import PAIN_POINTS, PainPointStage, get_pain_point


def test_pain_point_count():
    assert len(PAIN_POINTS) == 11  # PRE-01..04, MID-01..02, POST-01..05


def test_pain_point_ids_unique():
    ids = [pp.id for pp in PAIN_POINTS]
    assert len(ids) == len(set(ids))


def test_get_pain_point_by_id():
    pp = get_pain_point("MID-02")
    assert pp is not None
    assert pp.stage == PainPointStage.MID
    assert "의사표시 의제" in pp.label


def test_get_pain_point_unknown_id_returns_none():
    assert get_pain_point("XYZ-99") is None


def test_stages_distribution():
    by_stage = {s: 0 for s in PainPointStage}
    for pp in PAIN_POINTS:
        by_stage[pp.stage] += 1
    assert by_stage[PainPointStage.PRE] == 4
    assert by_stage[PainPointStage.MID] == 2
    assert by_stage[PainPointStage.POST] == 5
```

- [ ] **Step 4.2: 실패 확인**

```bash
pytest tests/unit/test_schemas_pain_points.py -v
```

Expected: `ImportError`.

- [ ] **Step 4.3: `schemas/pain_points.py` 구현**

```python
from enum import Enum

from pydantic import BaseModel


class PainPointStage(str, Enum):
    PRE = "pre"
    MID = "mid"
    POST = "post"


class PainPoint(BaseModel):
    id: str
    stage: PainPointStage
    label: str


PAIN_POINTS: list[PainPoint] = [
    PainPoint(id="PRE-01", stage=PainPointStage.PRE, label="약관 분량/난이도 압박"),
    PainPoint(id="PRE-02", stage=PainPointStage.PRE, label="혜택-약관 보장 범위 괴리"),
    PainPoint(id="PRE-03", stage=PainPointStage.PRE, label="무료체험 → 자동 유료 전환 미인지"),
    PainPoint(id="PRE-04", stage=PainPointStage.PRE, label="개인정보 활용 범위 불투명"),
    PainPoint(id="MID-01", stage=PainPointStage.MID, label="약관 변경 형식적 고지 (실질 인지 누락)"),
    PainPoint(id="MID-02", stage=PainPointStage.MID, label="의사표시 의제 (무응답 = 동의)"),
    PainPoint(id="POST-01", stage=PainPointStage.POST, label="위약금 미인지"),
    PainPoint(id="POST-02", stage=PainPointStage.POST, label="해지 절차 복잡성"),
    PainPoint(id="POST-03", stage=PainPointStage.POST, label="보장/혜택 청구권 미인지"),
    PainPoint(id="POST-04", stage=PainPointStage.POST, label="면책 광범위 / 손해배상 제한"),
    PainPoint(id="POST-05", stage=PainPointStage.POST, label="분쟁 절차 불투명 / 집단소송 포기"),
]

_BY_ID: dict[str, PainPoint] = {pp.id: pp for pp in PAIN_POINTS}


def get_pain_point(pp_id: str) -> PainPoint | None:
    return _BY_ID.get(pp_id)
```

- [ ] **Step 4.4: 통과 확인**

```bash
pytest tests/unit/test_schemas_pain_points.py -v
```

Expected: `5 passed`.

- [ ] **Step 4.5: 커밋**

```bash
git add schemas/pain_points.py tests/unit/test_schemas_pain_points.py
git commit -m "$(cat <<'EOF'
feat(schemas): add pain point taxonomy (PRE/MID/POST stages)

11 normalized pain point IDs (PRE-01..04, MID-01..02, POST-01..05)
linking spec §4 to runtime Citation.pain_point_id for UI filtering.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Subscription 스키마 (7 섹션 + Root)

**Files:**
- Create: `schemas/subscription.py`
- Create: `tests/unit/test_schemas_subscription.py`

- [ ] **Step 5.1: 실패 테스트 작성**

```python
# tests/unit/test_schemas_subscription.py
from schemas.common import Citation, FieldValue, Uncertainty
from schemas.enums import (
    BillingCycle,
    CancellationMethod,
    ConsentMechanism,
    NoticeChannel,
    ProrationPolicy,
)
from schemas.subscription import (
    Cancellation,
    DataUsage,
    Disputes,
    FreeTrial,
    Liability,
    Pricing,
    SubscriptionTerms,
    TermsChanges,
)


def _fv(v, u=Uncertainty.CONFIRMED, page=1, quote="..."):
    return FieldValue(value=v, uncertainty=u, citation=Citation(page=page, quote=quote))


def test_pricing_section_minimal():
    p = Pricing(
        base_price_krw=_fv(9900),
        billing_cycle=_fv(BillingCycle.MONTHLY),
        auto_renewal_enabled=_fv(True),
        auto_renewal_consent=_fv(ConsentMechanism.OPT_OUT_AVAILABLE),
        price_change_notice_days=_fv(30),
        price_change_notice_channels=_fv([NoticeChannel.EMAIL, NoticeChannel.APP_PUSH]),
    )
    assert p.base_price_krw.value == 9900
    assert p.billing_cycle.value == BillingCycle.MONTHLY


def test_full_subscription_terms_roundtrip():
    terms = SubscriptionTerms(
        service_name="TestStream",
        service_provider="TestCo",
        extraction_date="2026-05-13T00:00:00Z",
        pricing=Pricing(
            base_price_krw=_fv(9900),
            billing_cycle=_fv(BillingCycle.MONTHLY),
            auto_renewal_enabled=_fv(True),
            auto_renewal_consent=_fv(ConsentMechanism.DEEMED_AGREED),
            price_change_notice_days=_fv(30),
            price_change_notice_channels=_fv([NoticeChannel.EMAIL]),
        ),
        free_trial=FreeTrial(
            offered=_fv(True),
            duration_days=_fv(7),
            auto_convert_to_paid=_fv(True),
            cancel_required_before_end=_fv(True),
            payment_method_required_upfront=_fv(True),
            notice_before_conversion_days=_fv(3),
        ),
        cancellation=Cancellation(
            method=_fv(CancellationMethod.ONLINE),
            method_description=_fv("계정 설정에서 해지"),
            notice_period_days=_fv(0),
            penalty_present=_fv(False),
            penalty_description=_fv(""),
            proration_policy=_fv(ProrationPolicy.NO_REFUND),
            blackout_periods=_fv([]),
        ),
        terms_changes=TermsChanges(
            notice_channels=_fv([NoticeChannel.EMAIL]),
            notice_lead_time_days=_fv(30),
            user_consent_mechanism=_fv(ConsentMechanism.DEEMED_AGREED),
            user_right_to_terminate_on_change=_fv(True),
            silent_acceptance_clause=_fv(True),
        ),
        data_usage=DataUsage(
            collected_categories=_fv(["device_id", "viewing_history"]),
            third_party_sharing=_fv(True),
            third_party_recipients=_fv(["analytics_vendor"]),
            third_party_purposes=_fv(["service_improvement"]),
            retention_period_months=_fv(12),
            marketing_use=_fv(True),
            marketing_consent=_fv(ConsentMechanism.OPT_OUT_AVAILABLE),
            cross_border_transfer=_fv(False),
        ),
        liability=Liability(
            service_disruption_compensation=_fv(False),
            compensation_description=_fv(""),
            damages_cap_present=_fv(True),
            damages_cap_description=_fv("3개월 사용료 한도"),
            force_majeure_scope=_fv("천재지변, 정부조치 등"),
            indirect_damages_excluded=_fv(True),
        ),
        disputes=Disputes(
            governing_law=_fv("대한민국 법"),
            jurisdiction_clause=_fv("서울중앙지방법원"),
            arbitration_required=_fv(False),
            class_action_waiver=_fv(False),
        ),
        unfair_clause_flags=["의사표시_의제"],
    )
    # JSON round-trip 무결성
    data = terms.model_dump_json()
    restored = SubscriptionTerms.model_validate_json(data)
    assert restored.service_name == "TestStream"
    assert "의사표시_의제" in restored.unfair_clause_flags
    assert restored.schema_version == "1.0.0"


def test_schema_json_schema_generated():
    # IE API에 보낼 JSON Schema가 정상 생성되는지
    schema = SubscriptionTerms.model_json_schema()
    assert schema["type"] == "object"
    assert "pricing" in schema["properties"]
    assert "cancellation" in schema["properties"]
```

- [ ] **Step 5.2: 실패 확인**

```bash
pytest tests/unit/test_schemas_subscription.py -v
```

Expected: `ImportError`.

- [ ] **Step 5.3: `schemas/subscription.py` 구현**

```python
from pydantic import BaseModel, Field

from schemas.common import FieldValue
from schemas.enums import (
    BillingCycle,
    CancellationMethod,
    ConsentMechanism,
    NoticeChannel,
    ProrationPolicy,
)


class Pricing(BaseModel):
    base_price_krw: FieldValue[int]
    billing_cycle: FieldValue[BillingCycle]
    auto_renewal_enabled: FieldValue[bool]
    auto_renewal_consent: FieldValue[ConsentMechanism]
    price_change_notice_days: FieldValue[int]
    price_change_notice_channels: FieldValue[list[NoticeChannel]]


class FreeTrial(BaseModel):
    offered: FieldValue[bool]
    duration_days: FieldValue[int]
    auto_convert_to_paid: FieldValue[bool]
    cancel_required_before_end: FieldValue[bool]
    payment_method_required_upfront: FieldValue[bool]
    notice_before_conversion_days: FieldValue[int]


class Cancellation(BaseModel):
    method: FieldValue[CancellationMethod]
    method_description: FieldValue[str]
    notice_period_days: FieldValue[int]
    penalty_present: FieldValue[bool]
    penalty_description: FieldValue[str]
    proration_policy: FieldValue[ProrationPolicy]
    blackout_periods: FieldValue[list[str]]


class TermsChanges(BaseModel):
    notice_channels: FieldValue[list[NoticeChannel]]
    notice_lead_time_days: FieldValue[int]
    user_consent_mechanism: FieldValue[ConsentMechanism]
    user_right_to_terminate_on_change: FieldValue[bool]
    silent_acceptance_clause: FieldValue[bool]


class DataUsage(BaseModel):
    collected_categories: FieldValue[list[str]]
    third_party_sharing: FieldValue[bool]
    third_party_recipients: FieldValue[list[str]]
    third_party_purposes: FieldValue[list[str]]
    retention_period_months: FieldValue[int]
    marketing_use: FieldValue[bool]
    marketing_consent: FieldValue[ConsentMechanism]
    cross_border_transfer: FieldValue[bool]


class Liability(BaseModel):
    service_disruption_compensation: FieldValue[bool]
    compensation_description: FieldValue[str]
    damages_cap_present: FieldValue[bool]
    damages_cap_description: FieldValue[str]
    force_majeure_scope: FieldValue[str]
    indirect_damages_excluded: FieldValue[bool]


class Disputes(BaseModel):
    governing_law: FieldValue[str]
    jurisdiction_clause: FieldValue[str]
    arbitration_required: FieldValue[bool]
    class_action_waiver: FieldValue[bool]


class SubscriptionTerms(BaseModel):
    schema_version: str = "1.0.0"
    domain: str = "subscription"

    service_name: str
    service_provider: str
    document_url: str | None = None
    effective_date: str | None = None
    extraction_date: str

    pricing: Pricing
    free_trial: FreeTrial
    cancellation: Cancellation
    terms_changes: TermsChanges
    data_usage: DataUsage
    liability: Liability
    disputes: Disputes

    unfair_clause_flags: list[str] = Field(default_factory=list)
    raw_document_hash: str | None = None
```

- [ ] **Step 5.4: 통과 확인**

```bash
pytest tests/unit/test_schemas_subscription.py -v
```

Expected: `3 passed`.

- [ ] **Step 5.5: 커밋**

```bash
git add schemas/subscription.py tests/unit/test_schemas_subscription.py
git commit -m "$(cat <<'EOF'
feat(schemas): add SubscriptionTerms (7 sections + root)

Pricing, FreeTrial, Cancellation, TermsChanges, DataUsage,
Liability, Disputes. Each field is FieldValue[T] for citation
provenance. Root includes unfair_clause_flags + raw_document_hash
for change tracking.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Upstage 공통 클라이언트

**Files:**
- Create: `services/upstage.py`
- Create: `services/settings.py`
- Create: `tests/unit/test_services_upstage.py`

- [ ] **Step 6.1: 실패 테스트 작성**

```python
# tests/unit/test_services_upstage.py
import httpx
import pytest

from services.settings import Settings
from services.upstage import UpstageClient


@pytest.fixture
def settings(sample_api_key, sample_base_url) -> Settings:
    return Settings(upstage_api_key=sample_api_key, upstage_base_url=sample_base_url)


async def test_client_sends_bearer_token(httpx_mock, settings):
    httpx_mock.add_response(
        url=f"{settings.upstage_base_url}/test",
        json={"ok": True},
    )
    async with UpstageClient(settings) as client:
        r = await client.post_json("/test", json={"x": 1})
    assert r["ok"] is True
    request = httpx_mock.get_request()
    assert request.headers["authorization"] == f"Bearer {settings.upstage_api_key}"


async def test_client_retries_on_5xx(httpx_mock, settings):
    httpx_mock.add_response(status_code=503, url=f"{settings.upstage_base_url}/r")
    httpx_mock.add_response(status_code=503, url=f"{settings.upstage_base_url}/r")
    httpx_mock.add_response(json={"ok": True}, url=f"{settings.upstage_base_url}/r")
    async with UpstageClient(settings) as client:
        r = await client.post_json("/r", json={})
    assert r["ok"] is True
    assert len(httpx_mock.get_requests()) == 3


async def test_client_raises_on_4xx(httpx_mock, settings):
    httpx_mock.add_response(
        status_code=400,
        url=f"{settings.upstage_base_url}/bad",
        json={"error": "invalid"},
    )
    async with UpstageClient(settings) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await client.post_json("/bad", json={})
```

- [ ] **Step 6.2: 실패 확인**

```bash
pytest tests/unit/test_services_upstage.py -v
```

Expected: `ImportError`.

- [ ] **Step 6.3: `services/settings.py` 구현**

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    upstage_api_key: str
    upstage_base_url: str = "https://api.upstage.ai/v1"
    log_level: str = "INFO"

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)
```

- [ ] **Step 6.4: `services/upstage.py` 구현**

```python
from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from services.settings import Settings

logger = logging.getLogger(__name__)


class UpstageClient:
    """Thin async wrapper around Upstage HTTP APIs with auth + retry."""

    MAX_RETRIES = 3
    RETRY_BACKOFF_S = 0.5

    def __init__(self, settings: Settings, timeout_s: float = 60.0):
        self.settings = settings
        self._client = httpx.AsyncClient(
            base_url=settings.upstage_base_url,
            headers={"Authorization": f"Bearer {settings.upstage_api_key}"},
            timeout=timeout_s,
        )

    async def __aenter__(self) -> "UpstageClient":
        return self

    async def __aexit__(self, *exc) -> None:
        await self._client.aclose()

    async def post_json(self, path: str, *, json: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", path, json=json)

    async def post_multipart(
        self,
        path: str,
        *,
        files: dict[str, Any],
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return await self._request("POST", path, files=files, data=data)

    async def _request(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        last_exc: Exception | None = None
        for attempt in range(self.MAX_RETRIES):
            try:
                resp = await self._client.request(method, path, **kwargs)
                if resp.status_code >= 500:
                    last_exc = httpx.HTTPStatusError(
                        f"server {resp.status_code}", request=resp.request, response=resp
                    )
                    await asyncio.sleep(self.RETRY_BACKOFF_S * (2**attempt))
                    continue
                resp.raise_for_status()
                logger.info("upstage %s %s -> %s", method, path, resp.status_code)
                return resp.json()
            except httpx.TransportError as e:
                last_exc = e
                await asyncio.sleep(self.RETRY_BACKOFF_S * (2**attempt))
        assert last_exc is not None
        raise last_exc
```

- [ ] **Step 6.5: 통과 확인**

```bash
pytest tests/unit/test_services_upstage.py -v
```

Expected: `3 passed`.

- [ ] **Step 6.6: 커밋**

```bash
git add services/settings.py services/upstage.py tests/unit/test_services_upstage.py
git commit -m "$(cat <<'EOF'
feat(services): add Upstage async HTTP client + Settings

httpx-based async client with Bearer auth, 5xx retry (exponential
backoff, 3 attempts), 4xx raises. Settings loaded from .env via
pydantic-settings.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Document Parse 어댑터

**Files:**
- Create: `services/parse.py`
- Create: `tests/unit/test_services_parse.py`

Upstage Document Parse (`POST /document-digitization`): PDF/이미지 → markdown + elements(0–1 normalized 좌표).

- [ ] **Step 7.1: 실패 테스트 작성**

```python
# tests/unit/test_services_parse.py
import io

import pytest

from services.parse import DocumentParseResult, parse_document
from services.settings import Settings
from services.upstage import UpstageClient


@pytest.fixture
def settings(sample_api_key, sample_base_url):
    return Settings(upstage_api_key=sample_api_key, upstage_base_url=sample_base_url)


async def test_parse_document_returns_structured_result(httpx_mock, settings):
    httpx_mock.add_response(
        url=f"{settings.upstage_base_url}/document-digitization",
        json={
            "apiVersion": "1.1",
            "model": "document-parse-260128",
            "content": {"markdown": "# 이용약관\n\n제1조 (목적)..."},
            "elements": [
                {
                    "id": 1,
                    "page": 1,
                    "category": "heading1",
                    "content": {"text": "이용약관", "markdown": "# 이용약관"},
                    "coordinates": [
                        {"x": 0.125, "y": 0.05},
                        {"x": 0.425, "y": 0.05},
                        {"x": 0.425, "y": 0.08},
                        {"x": 0.125, "y": 0.08},
                    ],
                },
                {
                    "id": 2,
                    "page": 1,
                    "category": "paragraph",
                    "content": {"text": "제1조 (목적)...", "markdown": "제1조 (목적)..."},
                    "coordinates": [
                        {"x": 0.10, "y": 0.10},
                        {"x": 0.50, "y": 0.10},
                        {"x": 0.50, "y": 0.20},
                        {"x": 0.10, "y": 0.20},
                    ],
                },
            ],
            "usage": {"pages": 1},
        },
    )
    fake_pdf = io.BytesIO(b"%PDF-1.4 fake content")
    async with UpstageClient(settings) as client:
        result = await parse_document(client, file_bytes=fake_pdf.getvalue(), filename="t.pdf")
    assert isinstance(result, DocumentParseResult)
    assert "이용약관" in result.markdown
    assert len(result.elements) == 2
    assert result.elements[0].page == 1
    # bbox는 0-1 normalized
    assert result.elements[0].bbox == (0.125, 0.05, 0.425, 0.08)


async def test_parse_document_raises_on_empty_response(httpx_mock, settings):
    httpx_mock.add_response(
        url=f"{settings.upstage_base_url}/document-digitization",
        json={"content": {"markdown": ""}, "elements": []},
    )
    async with UpstageClient(settings) as client:
        with pytest.raises(ValueError, match="empty"):
            await parse_document(client, file_bytes=b"", filename="empty.pdf")
```

- [ ] **Step 7.2: 실패 확인**

```bash
pytest tests/unit/test_services_parse.py -v
```

Expected: `ImportError`.

- [ ] **Step 7.3: `services/parse.py` 구현**

```python
from __future__ import annotations

from pydantic import BaseModel

from services.upstage import UpstageClient

DOCUMENT_PARSE_PATH = "/document-digitization"
MODEL = "document-parse"


class ParsedElement(BaseModel):
    id: int
    page: int
    category: str
    text: str
    # bbox는 0-1 normalized (페이지 width/height 곱해서 pixel로 변환)
    bbox: tuple[float, float, float, float] | None = None  # (x0, y0, x1, y1)


class DocumentParseResult(BaseModel):
    markdown: str
    elements: list[ParsedElement]


def _coords_to_bbox(coords: list[dict]) -> tuple[float, float, float, float] | None:
    if not coords:
        return None
    xs = [c["x"] for c in coords]
    ys = [c["y"] for c in coords]
    return (min(xs), min(ys), max(xs), max(ys))


async def parse_document(
    client: UpstageClient,
    *,
    file_bytes: bytes,
    filename: str,
) -> DocumentParseResult:
    """Upstage Document Parse 호출 → DocumentParseResult 반환.

    좌표는 0-1 normalized이며 페이지 width/height 곱해서 pixel로 변환 가능.
    """
    files = {"document": (filename, file_bytes, "application/pdf")}
    data = {
        "model": MODEL,
        "output_formats": '["markdown"]',
        "coordinates": "true",
        "ocr": "auto",
    }
    raw = await client.post_multipart(DOCUMENT_PARSE_PATH, files=files, data=data)

    markdown = (raw.get("content") or {}).get("markdown", "")
    elements_raw = raw.get("elements") or []

    if not markdown and not elements_raw:
        raise ValueError("Document Parse returned empty content")

    elements = [
        ParsedElement(
            id=e["id"],
            page=e["page"],
            category=e["category"],
            text=(e.get("content") or {}).get("text", ""),
            bbox=_coords_to_bbox(e.get("coordinates") or []),
        )
        for e in elements_raw
    ]
    return DocumentParseResult(markdown=markdown, elements=elements)
```

- [ ] **Step 7.4: 통과 확인**

```bash
pytest tests/unit/test_services_parse.py -v
```

Expected: `2 passed`.

- [ ] **Step 7.5: 커밋**

```bash
git add services/parse.py tests/unit/test_services_parse.py
git commit -m "$(cat <<'EOF'
feat(services): add Document Parse adapter

POST /document-digitization (model=document-parse). Returns
DocumentParseResult with markdown + ParsedElement list (page,
category, text, bbox). Coordinates are 0-1 normalized per
Upstage spec; multiply by page dims for pixel coords downstream.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: 구조화 추출 어댑터 (Solar Pro 3 + json_schema)

**Files:**
- Create: `prompts/extract_subscription.py`
- Create: `services/extract.py`
- Create: `tests/unit/test_services_extract.py`

**전략 변경 사유**: Upstage Information Extract API는 root-level object 및 nested object를 허용하지 않음 (first-level은 scalar/array만, max 100 properties). `SubscriptionTerms`는 7개 nested 섹션을 가지므로 IE API에 직접 못 보냄. 대안으로 **Solar Pro 3 chat completions + `response_format.json_schema`** 사용 — nested 스키마 완전 지원. Document Parse의 element 좌표는 post-processing(`_enrich_with_bbox`)으로 citation에 채워넣음.

- [ ] **Step 8.1: 실패 테스트 작성**

```python
# tests/unit/test_services_extract.py
import json

import pytest

from schemas.common import Uncertainty
from schemas.enums import BillingCycle, ConsentMechanism
from schemas.subscription import SubscriptionTerms
from services.extract import extract_subscription
from services.parse import ParsedElement
from services.settings import Settings
from services.upstage import UpstageClient


@pytest.fixture
def settings(sample_api_key, sample_base_url):
    return Settings(upstage_api_key=sample_api_key, upstage_base_url=sample_base_url)


def _all_not_specified(field_names: list[str]) -> dict:
    return {n: {"value": None, "uncertainty": "not_specified", "citation": None} for n in field_names}


@pytest.fixture
def fake_extract_payload():
    """Minimal but valid SubscriptionTerms JSON."""
    return {
        "schema_version": "1.0.0",
        "domain": "subscription",
        "service_name": "TestStream",
        "service_provider": "TestCo",
        "extraction_date": "2026-05-13T00:00:00Z",
        "pricing": {
            "base_price_krw": {"value": 9900, "uncertainty": "confirmed",
                                "citation": {"page": 1, "quote": "월 9,900원"}},
            "billing_cycle": {"value": "monthly", "uncertainty": "confirmed",
                               "citation": {"page": 1, "quote": "매월 결제"}},
            "auto_renewal_enabled": {"value": True, "uncertainty": "confirmed",
                                      "citation": {"page": 2, "quote": "자동 갱신됩니다"}},
            "auto_renewal_consent": {"value": "deemed_agreed", "uncertainty": "confirmed",
                                      "citation": {"page": 2, "quote": "이의 없으면 동의로 간주",
                                                    "pain_point_id": "MID-02"}},
            "price_change_notice_days": {"value": 30, "uncertainty": "confirmed",
                                          "citation": {"page": 3, "quote": "30일 전 통지"}},
            "price_change_notice_channels": {"value": ["email"], "uncertainty": "confirmed",
                                              "citation": {"page": 3, "quote": "이메일로 통지"}},
        },
        "free_trial": _all_not_specified(["offered", "duration_days", "auto_convert_to_paid",
                                           "cancel_required_before_end", "payment_method_required_upfront",
                                           "notice_before_conversion_days"]),
        "cancellation": _all_not_specified(["method", "method_description", "notice_period_days",
                                             "penalty_present", "penalty_description",
                                             "proration_policy", "blackout_periods"]),
        "terms_changes": _all_not_specified(["notice_channels", "notice_lead_time_days",
                                              "user_consent_mechanism",
                                              "user_right_to_terminate_on_change",
                                              "silent_acceptance_clause"]),
        "data_usage": _all_not_specified(["collected_categories", "third_party_sharing",
                                           "third_party_recipients", "third_party_purposes",
                                           "retention_period_months", "marketing_use",
                                           "marketing_consent", "cross_border_transfer"]),
        "liability": _all_not_specified(["service_disruption_compensation", "compensation_description",
                                          "damages_cap_present", "damages_cap_description",
                                          "force_majeure_scope", "indirect_damages_excluded"]),
        "disputes": _all_not_specified(["governing_law", "jurisdiction_clause",
                                         "arbitration_required", "class_action_waiver"]),
        "unfair_clause_flags": ["의사표시_의제"],
    }


async def test_extract_subscription_returns_validated_terms(
    httpx_mock, settings, fake_extract_payload
):
    httpx_mock.add_response(
        url=f"{settings.upstage_base_url}/chat/completions",
        json={"choices": [{"message": {"content": json.dumps(fake_extract_payload)}}]},
    )
    elements = [
        ParsedElement(id=1, page=2, category="paragraph",
                       text="이의 없으면 동의로 간주합니다", bbox=(0.1, 0.2, 0.5, 0.25)),
    ]
    async with UpstageClient(settings) as client:
        terms = await extract_subscription(
            client,
            parsed_markdown="...",
            parsed_elements=elements,
            service_name="TestStream",
            service_provider="TestCo",
        )
    assert isinstance(terms, SubscriptionTerms)
    assert terms.service_name == "TestStream"
    assert terms.pricing.base_price_krw.value == 9900
    assert terms.pricing.billing_cycle.value == BillingCycle.MONTHLY
    assert terms.pricing.auto_renewal_consent.value == ConsentMechanism.DEEMED_AGREED
    assert "의사표시_의제" in terms.unfair_clause_flags
    assert terms.free_trial.offered.uncertainty == Uncertainty.NOT_SPECIFIED
    # bbox 후처리 검증: auto_renewal_consent의 citation에 bbox가 채워졌어야 함
    assert terms.pricing.auto_renewal_consent.citation.bbox == (0.1, 0.2, 0.5, 0.25)


async def test_extract_subscription_raises_on_invalid_payload(httpx_mock, settings):
    httpx_mock.add_response(
        url=f"{settings.upstage_base_url}/chat/completions",
        json={"choices": [{"message": {"content": '{"service_name": "X"}'}}]},
    )
    async with UpstageClient(settings) as client:
        with pytest.raises(ValueError, match="validation"):
            await extract_subscription(
                client, parsed_markdown="...", parsed_elements=[],
                service_name="X", service_provider="Y"
            )
```

- [ ] **Step 8.2: 실패 확인**

```bash
pytest tests/unit/test_services_extract.py -v
```

Expected: `ImportError`.

- [ ] **Step 8.3: `prompts/extract_subscription.py` 작성**

```python
SYSTEM_PROMPT = """\
당신은 한국 소비자 약관 분석 어시스턴트입니다.
주어진 약관 본문에서 SubscriptionTerms JSON 스키마의 각 필드를 추출하세요.

규칙:
1. 모든 필드는 FieldValue 형식 (value, uncertainty, citation) 으로 채웁니다.
2. value: 약관에 명시된 값. 없으면 null.
3. uncertainty:
   - "confirmed": 약관에 직접 명시됨
   - "inferred": 다른 조항에서 유추됨
   - "ambiguous": 다중 해석 가능
   - "not_specified": 약관이 침묵
4. citation: value가 null이 아니면 page + quote 필수. quote는 약관 원문 그대로 발췌 (변형/요약 금지). bbox/section은 채우지 말 것 — 후처리에서 채워짐. pain_point_id는 해당하는 ID가 명확할 때만 (PRE-01..04, MID-01..02, POST-01..05).
5. 의사표시 의제(무응답 = 동의) 조항을 발견하면:
   - 해당 ConsentMechanism 필드를 "deemed_agreed"
   - unfair_clause_flags 에 "의사표시_의제" 추가
6. 응답은 SubscriptionTerms JSON 객체 하나 (response_format=json_schema 강제).
"""

USER_PROMPT_TEMPLATE = """\
다음 약관 본문을 분석해 SubscriptionTerms JSON을 생성하세요.

서비스: {service_name} ({service_provider})

약관 본문 (Document Parse markdown 결과):
---
{parsed_markdown}
---
"""
```

- [ ] **Step 8.4: `services/extract.py` 구현**

```python
from __future__ import annotations

import json
from datetime import datetime, timezone

from pydantic import ValidationError

from prompts.extract_subscription import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE
from schemas.common import Citation, FieldValue
from schemas.subscription import SubscriptionTerms
from services.parse import ParsedElement
from services.upstage import UpstageClient

CHAT_COMPLETIONS_PATH = "/chat/completions"
MODEL = "solar-pro3"
SECTION_NAMES = (
    "pricing", "free_trial", "cancellation", "terms_changes",
    "data_usage", "liability", "disputes",
)


def _find_element_for_quote(
    quote: str, page: int, elements: list[ParsedElement]
) -> ParsedElement | None:
    """page를 우선으로, quote가 element.text에 포함되는 첫 element 반환."""
    if not quote:
        return None
    # 같은 페이지부터 검사, 없으면 다른 페이지에서도 검사
    for elem in elements:
        if elem.page == page and quote in elem.text:
            return elem
    for elem in elements:
        if quote in elem.text:
            return elem
    return None


def _enrich_citation(
    citation: Citation | None, elements: list[ParsedElement]
) -> Citation | None:
    if citation is None or citation.bbox is not None:
        return citation
    elem = _find_element_for_quote(citation.quote, citation.page, elements)
    if elem is None:
        return citation
    updates: dict = {"bbox": elem.bbox}
    if citation.section is None:
        updates["section"] = elem.category
    return citation.model_copy(update=updates)


def _enrich_with_bbox(
    terms: SubscriptionTerms, elements: list[ParsedElement]
) -> SubscriptionTerms:
    """각 섹션의 모든 FieldValue에 대해 citation.bbox를 element 매칭으로 채움."""
    for section_name in SECTION_NAMES:
        section = getattr(terms, section_name)
        for field_name in section.__class__.model_fields:
            fv: FieldValue = getattr(section, field_name)
            new_citation = _enrich_citation(fv.citation, elements)
            if new_citation is not fv.citation:
                # Pydantic v2 모델은 immutable이 아니므로 직접 할당 가능
                fv.citation = new_citation
    return terms


async def extract_subscription(
    client: UpstageClient,
    *,
    parsed_markdown: str,
    parsed_elements: list[ParsedElement],
    service_name: str,
    service_provider: str,
) -> SubscriptionTerms:
    """Solar Pro 3 chat completions + json_schema로 SubscriptionTerms 추출.

    Information Extract API는 nested 스키마 미지원이라 chat completions 사용.
    citation.bbox는 Document Parse elements와 quote 매칭으로 후처리에서 채워짐.
    """
    response_format = {
        "type": "json_schema",
        "json_schema": {
            "name": "SubscriptionTerms",
            "schema": SubscriptionTerms.model_json_schema(),
            "strict": True,
        },
    }
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": USER_PROMPT_TEMPLATE.format(
                    service_name=service_name,
                    service_provider=service_provider,
                    parsed_markdown=parsed_markdown,
                ),
            },
        ],
        "response_format": response_format,
        "reasoning_effort": "low",
    }
    raw = await client.post_json(CHAT_COMPLETIONS_PATH, json=payload)
    content_str = raw["choices"][0]["message"]["content"]
    parsed = json.loads(content_str)
    parsed.setdefault("extraction_date", datetime.now(timezone.utc).isoformat())
    parsed.setdefault("service_name", service_name)
    parsed.setdefault("service_provider", service_provider)
    try:
        terms = SubscriptionTerms.model_validate(parsed)
    except ValidationError as e:
        raise ValueError(f"Extract response validation failed: {e}") from e
    return _enrich_with_bbox(terms, parsed_elements)
```

- [ ] **Step 8.5: 통과 확인**

```bash
pytest tests/unit/test_services_extract.py -v
```

Expected: `2 passed`.

- [ ] **Step 8.6: 커밋**

```bash
git add prompts/extract_subscription.py services/extract.py tests/unit/test_services_extract.py
git commit -m "$(cat <<'EOF'
feat(services): add structured extraction via Solar Pro 3 + json_schema

Upstage Information Extract API doesn't support nested object schemas
(first-level scalar/array only); we use Solar Pro 3 chat completions
with response_format=json_schema instead. SubscriptionTerms is validated
into a Pydantic instance, then _enrich_with_bbox matches each citation
quote against Document Parse elements to fill in bbox + section.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Solar Pro 3 요약 어댑터

**Files:**
- Create: `prompts/summarize_subscription.py`
- Create: `services/summarize.py`
- Create: `tests/unit/test_services_summarize.py`

- [ ] **Step 9.1: 실패 테스트 작성**

```python
# tests/unit/test_services_summarize.py
import json

import pytest

from schemas.common import Citation, FieldValue, Uncertainty
from schemas.enums import BillingCycle, ConsentMechanism, NoticeChannel
from schemas.subscription import (
    Cancellation,
    DataUsage,
    Disputes,
    FreeTrial,
    Liability,
    Pricing,
    SubscriptionTerms,
    TermsChanges,
)
from services.settings import Settings
from services.summarize import KeyClause, SummaryResult, summarize_risks
from services.upstage import UpstageClient


@pytest.fixture
def settings(sample_api_key, sample_base_url):
    return Settings(upstage_api_key=sample_api_key, upstage_base_url=sample_base_url)


def _fv(v, u=Uncertainty.CONFIRMED, page=1, quote="...", pain_point_id=None):
    return FieldValue(value=v, uncertainty=u, citation=Citation(page=page, quote=quote, pain_point_id=pain_point_id))


@pytest.fixture
def sample_terms():
    return SubscriptionTerms(
        service_name="TestStream", service_provider="TestCo",
        extraction_date="2026-05-13T00:00:00Z",
        pricing=Pricing(
            base_price_krw=_fv(9900),
            billing_cycle=_fv(BillingCycle.MONTHLY),
            auto_renewal_enabled=_fv(True, pain_point_id="PRE-03"),
            auto_renewal_consent=_fv(ConsentMechanism.DEEMED_AGREED, pain_point_id="MID-02"),
            price_change_notice_days=_fv(30),
            price_change_notice_channels=_fv([NoticeChannel.EMAIL]),
        ),
        free_trial=FreeTrial(offered=_fv(False), duration_days=_fv(0), auto_convert_to_paid=_fv(False),
                             cancel_required_before_end=_fv(False), payment_method_required_upfront=_fv(False),
                             notice_before_conversion_days=_fv(0)),
        cancellation=Cancellation(method=_fv("online"), method_description=_fv(""), notice_period_days=_fv(0),
                                   penalty_present=_fv(False), penalty_description=_fv(""),
                                   proration_policy=_fv("no_refund"), blackout_periods=_fv([])),
        terms_changes=TermsChanges(notice_channels=_fv([NoticeChannel.EMAIL]), notice_lead_time_days=_fv(30),
                                    user_consent_mechanism=_fv(ConsentMechanism.DEEMED_AGREED),
                                    user_right_to_terminate_on_change=_fv(True), silent_acceptance_clause=_fv(True)),
        data_usage=DataUsage(collected_categories=_fv([]), third_party_sharing=_fv(False),
                              third_party_recipients=_fv([]), third_party_purposes=_fv([]),
                              retention_period_months=_fv(0), marketing_use=_fv(False),
                              marketing_consent=_fv(ConsentMechanism.OPT_OUT_AVAILABLE),
                              cross_border_transfer=_fv(False)),
        liability=Liability(service_disruption_compensation=_fv(False), compensation_description=_fv(""),
                             damages_cap_present=_fv(False), damages_cap_description=_fv(""),
                             force_majeure_scope=_fv(""), indirect_damages_excluded=_fv(False)),
        disputes=Disputes(governing_law=_fv(""), jurisdiction_clause=_fv(""),
                           arbitration_required=_fv(False), class_action_waiver=_fv(False)),
        unfair_clause_flags=["의사표시_의제"],
    )


async def test_summarize_risks_returns_top_clauses(httpx_mock, settings, sample_terms):
    fake_response = {
        "summary": "본 약관은 자동결제 + 의사표시 의제 조항으로 소비자 불이익 가능성이 있습니다.",
        "key_clauses": [
            {
                "title": "자동 갱신 + 무응답 동의 간주",
                "description": "이의 없으면 약관 변경 동의로 간주되며 자동 결제됩니다.",
                "risk_level": "high",
                "pain_point_id": "MID-02",
                "citation": {"page": 2, "quote": "이의 없으면 동의로 간주"},
            },
            {
                "title": "가격 인상 시 이메일 통지만 제공",
                "description": "30일 전 이메일 통지가 유일한 채널입니다. 이메일 미확인 시 인지 곤란.",
                "risk_level": "medium",
                "pain_point_id": "MID-01",
                "citation": {"page": 3, "quote": "30일 전 이메일로 통지"},
            },
        ],
    }
    httpx_mock.add_response(
        url=f"{settings.upstage_base_url}/chat/completions",
        json={"choices": [{"message": {"content": json.dumps(fake_response)}}]},
    )
    async with UpstageClient(settings) as client:
        result = await summarize_risks(client, terms=sample_terms)
    assert isinstance(result, SummaryResult)
    assert len(result.key_clauses) == 2
    assert isinstance(result.key_clauses[0], KeyClause)
    assert result.key_clauses[0].risk_level == "high"
    assert "의사표시 의제" in result.summary
```

- [ ] **Step 9.2: 실패 확인**

```bash
pytest tests/unit/test_services_summarize.py -v
```

Expected: `ImportError`.

- [ ] **Step 9.3: `prompts/summarize_subscription.py` 작성**

```python
SYSTEM_PROMPT = """\
당신은 한국 소비자 보호 어시스턴트입니다. 구조화된 약관 데이터(SubscriptionTerms)를 받아
소비자가 가장 조심해야 할 조항 3~5개를 식별하고 평문으로 설명하세요.

규칙:
1. 응답은 JSON 객체 하나: { "summary": str, "key_clauses": [...] }
2. summary: 약관 전체에 대한 한 문단 요약 (한국어, 2~3문장)
3. key_clauses 각 항목:
   - title: 조항의 핵심을 표현한 짧은 제목 (한국어)
   - description: 일반 소비자가 이해할 수 있는 평문 설명 (한국어, 2~3문장)
   - risk_level: "high" | "medium" | "low"
   - pain_point_id: PRE-XX / MID-XX / POST-XX 중 하나
   - citation: { page: int, quote: str } (원문 인용 - SubscriptionTerms의 citation을 그대로 활용)
4. 다음 패턴을 발견하면 항상 high 위험:
   - ConsentMechanism = "deemed_agreed" (의사표시 의제)
   - auto_convert_to_paid = true + payment_method_required_upfront = true
   - penalty_present = true 인데 description이 모호
   - class_action_waiver = true 또는 arbitration_required = true
5. 구체적 사례를 들어 설명 (예: "이메일을 확인하지 않으면 변경 사항을 모르고 자동 결제됩니다").
"""

USER_PROMPT_TEMPLATE = """\
다음 SubscriptionTerms JSON을 분석해 위험 조항 요약을 생성하세요.

```json
{terms_json}
```
"""
```

- [ ] **Step 9.4: `services/summarize.py` 구현**

```python
from __future__ import annotations

import json

from pydantic import BaseModel, Field

from prompts.summarize_subscription import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE
from schemas.subscription import SubscriptionTerms
from services.upstage import UpstageClient

CHAT_COMPLETIONS_PATH = "/chat/completions"
MODEL = "solar-pro3"  # Upstage 공식 alias: solar-pro3 → solar-pro3-260323


class KeyClauseCitation(BaseModel):
    page: int
    quote: str


class KeyClause(BaseModel):
    title: str
    description: str
    risk_level: str  # "high" | "medium" | "low"
    pain_point_id: str
    citation: KeyClauseCitation


class SummaryResult(BaseModel):
    summary: str
    key_clauses: list[KeyClause] = Field(default_factory=list)


async def summarize_risks(client: UpstageClient, *, terms: SubscriptionTerms) -> SummaryResult:
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": USER_PROMPT_TEMPLATE.format(terms_json=terms.model_dump_json(indent=2)),
            },
        ],
        "response_format": {"type": "json_object"},
    }
    raw = await client.post_json(CHAT_COMPLETIONS_PATH, json=payload)
    content_str = raw["choices"][0]["message"]["content"]
    data = json.loads(content_str)
    return SummaryResult.model_validate(data)
```

- [ ] **Step 9.5: 통과 확인**

```bash
pytest tests/unit/test_services_summarize.py -v
```

Expected: `1 passed`.

- [ ] **Step 9.6: 커밋**

```bash
git add prompts/summarize_subscription.py services/summarize.py tests/unit/test_services_summarize.py
git commit -m "$(cat <<'EOF'
feat(services): add Solar Pro 3 risk summarization

Takes SubscriptionTerms instance, returns SummaryResult with top
3-5 KeyClauses (title, plain-language description, risk_level,
pain_point_id, citation). Prompt enforces high-risk classification
for 의사표시 의제, hidden auto-conversion, class action waiver.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Groundedness Check 어댑터 (Solar chat fallback)

**Files:**
- Create: `prompts/groundedness_check.py`
- Create: `services/ground.py`
- Create: `tests/unit/test_services_ground.py`

**전략**: Upstage 공식 docs raw에 전용 `/groundedness-check` 엔드포인트가 수록되지 않았다 (Chat/Embeddings/Document Parse/IE만 명시). v1은 Solar Pro 3 chat completions로 verification prompt를 보내 `{grounded: bool, score: float}` JSON 응답을 받는 **fallback 구현**. 전용 endpoint가 확인되면 Step 10.6에서 swap.

- [ ] **Step 10.1: 실패 테스트 작성**

```python
# tests/unit/test_services_ground.py
import json

import pytest

from services.ground import GroundednessResult, check_groundedness
from services.settings import Settings
from services.summarize import KeyClause, KeyClauseCitation, SummaryResult
from services.upstage import UpstageClient


@pytest.fixture
def settings(sample_api_key, sample_base_url):
    return Settings(upstage_api_key=sample_api_key, upstage_base_url=sample_base_url)


@pytest.fixture
def sample_summary():
    return SummaryResult(
        summary="자동결제와 의사표시 의제 조항이 있습니다.",
        key_clauses=[
            KeyClause(
                title="자동 갱신",
                description="이의 없으면 동의로 간주됩니다.",
                risk_level="high",
                pain_point_id="MID-02",
                citation=KeyClauseCitation(page=2, quote="이의 없으면 동의로 간주"),
            ),
            KeyClause(
                title="가공의 조항",
                description="실제 약관에 없는 가짜 조항입니다.",
                risk_level="medium",
                pain_point_id="PRE-04",
                citation=KeyClauseCitation(page=99, quote="이런 문구는 원문에 없음"),
            ),
        ],
    )


async def test_check_groundedness_filters_ungrounded(httpx_mock, settings, sample_summary):
    # 첫 호출: grounded
    httpx_mock.add_response(
        url=f"{settings.upstage_base_url}/chat/completions",
        json={"choices": [{"message": {"content": json.dumps({"grounded": True, "score": 0.95})}}]},
    )
    # 두 번째 호출: not grounded
    httpx_mock.add_response(
        url=f"{settings.upstage_base_url}/chat/completions",
        json={"choices": [{"message": {"content": json.dumps({"grounded": False, "score": 0.12})}}]},
    )
    async with UpstageClient(settings) as client:
        result = await check_groundedness(
            client,
            summary=sample_summary,
            source_markdown="...이의 없으면 동의로 간주합니다...",
        )
    assert isinstance(result, GroundednessResult)
    assert len(result.grounded_clauses) == 1
    assert result.grounded_clauses[0].title == "자동 갱신"
    assert len(result.ungrounded_clauses) == 1
    assert result.ungrounded_clauses[0].title == "가공의 조항"
    assert result.overall_grounded is False
```

- [ ] **Step 10.2: 실패 확인**

```bash
pytest tests/unit/test_services_ground.py -v
```

Expected: `ImportError`.

- [ ] **Step 10.3: `prompts/groundedness_check.py` 작성**

```python
SYSTEM_PROMPT = """\
당신은 응답 검증자입니다. 주어진 '원문 컨텍스트'와 '응답 문장'을 비교해
응답이 원문에 의해 뒷받침되는지(grounded) 판정하세요.

규칙:
1. 응답이 원문에 직접/간접적으로 명시되어 있으면 grounded=true.
2. 원문에 없는 내용이거나 원문과 모순되면 grounded=false.
3. score: 0.0 (전혀 근거 없음) ~ 1.0 (완전한 근거) 사이 float.
4. 출력은 JSON 객체 하나: { "grounded": bool, "score": float }
"""

USER_PROMPT_TEMPLATE = """\
원문 컨텍스트:
---
{context}
---

검증할 응답 문장:
---
{answer}
---

위 응답이 원문에 의해 뒷받침됩니까?
"""
```

- [ ] **Step 10.4: `services/ground.py` 구현**

```python
from __future__ import annotations

import json

from pydantic import BaseModel, Field

from prompts.groundedness_check import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE
from services.summarize import KeyClause, SummaryResult
from services.upstage import UpstageClient

CHAT_COMPLETIONS_PATH = "/chat/completions"
MODEL = "solar-pro3"
MIN_SCORE = 0.7


class GroundednessResult(BaseModel):
    summary: str
    grounded_clauses: list[KeyClause] = Field(default_factory=list)
    ungrounded_clauses: list[KeyClause] = Field(default_factory=list)
    overall_grounded: bool


async def _check_one(
    client: UpstageClient,
    *,
    context: str,
    answer: str,
) -> tuple[bool, float]:
    """Solar Pro 3 chat completions으로 verification (전용 endpoint 미수록 fallback)."""
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": USER_PROMPT_TEMPLATE.format(context=context, answer=answer),
            },
        ],
        "response_format": {"type": "json_object"},
        "reasoning_effort": "low",
    }
    raw = await client.post_json(CHAT_COMPLETIONS_PATH, json=payload)
    content_str = raw["choices"][0]["message"]["content"]
    data = json.loads(content_str)
    return bool(data.get("grounded", False)), float(data.get("score", 0.0))


async def check_groundedness(
    client: UpstageClient,
    *,
    summary: SummaryResult,
    source_markdown: str,
) -> GroundednessResult:
    grounded: list[KeyClause] = []
    ungrounded: list[KeyClause] = []
    for clause in summary.key_clauses:
        answer = f"{clause.title}: {clause.description} (원문 인용: \"{clause.citation.quote}\")"
        is_grounded, score = await _check_one(client, context=source_markdown, answer=answer)
        if is_grounded and score >= MIN_SCORE:
            grounded.append(clause)
        else:
            ungrounded.append(clause)
    return GroundednessResult(
        summary=summary.summary,
        grounded_clauses=grounded,
        ungrounded_clauses=ungrounded,
        overall_grounded=(len(ungrounded) == 0),
    )
```

- [ ] **Step 10.5: 통과 확인**

```bash
pytest tests/unit/test_services_ground.py -v
```

Expected: `1 passed`.

- [ ] **Step 10.6: TODO 주석 — 전용 endpoint swap 지점**

`services/ground.py` 최상단에 다음 주석 추가:

```python
# TODO(groundedness): Upstage 전용 /groundedness-check endpoint가 공식 문서에 추가되면
# CHAT_COMPLETIONS_PATH → 전용 path로 swap, payload를 {context, answer} 단순 형태로 변경.
# 현재는 Solar Pro 3 chat에 verification prompt 보내는 fallback 구현.
```

- [ ] **Step 10.7: 커밋**

```bash
git add prompts/groundedness_check.py services/ground.py tests/unit/test_services_ground.py
git commit -m "$(cat <<'EOF'
feat(services): add groundedness check (Solar chat fallback)

Upstage's dedicated /groundedness-check endpoint isn't documented in
the for-agents API spec, so v1 uses Solar Pro 3 chat completions with
a verification prompt returning {grounded: bool, score: float}.
Clauses below MIN_SCORE=0.7 or marked not-grounded are routed to
ungrounded_clauses; overall_grounded is True only if all pass.

TODO: swap endpoint when dedicated API surfaces.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: 파이프라인 오케스트레이터

**Files:**
- Create: `services/pipeline.py`
- Create: `tests/unit/test_services_pipeline.py`

- [ ] **Step 11.1: 실패 테스트 작성**

```python
# tests/unit/test_services_pipeline.py
from unittest.mock import AsyncMock

import pytest

from schemas.common import Citation, FieldValue, Uncertainty
from schemas.enums import BillingCycle, ConsentMechanism, NoticeChannel
from schemas.subscription import (
    Cancellation, DataUsage, Disputes, FreeTrial, Liability,
    Pricing, SubscriptionTerms, TermsChanges,
)
from services.ground import GroundednessResult
from services.parse import DocumentParseResult, ParsedElement
from services.pipeline import AnalysisResult, run_pipeline
from services.summarize import KeyClause, KeyClauseCitation, SummaryResult


def _fv(v, page=1, quote="..."):
    return FieldValue(value=v, uncertainty=Uncertainty.CONFIRMED, citation=Citation(page=page, quote=quote))


def _build_terms() -> SubscriptionTerms:
    return SubscriptionTerms(
        service_name="X", service_provider="Y", extraction_date="2026-05-13T00:00:00Z",
        pricing=Pricing(base_price_krw=_fv(9900), billing_cycle=_fv(BillingCycle.MONTHLY),
                         auto_renewal_enabled=_fv(True), auto_renewal_consent=_fv(ConsentMechanism.OPT_OUT_AVAILABLE),
                         price_change_notice_days=_fv(30), price_change_notice_channels=_fv([NoticeChannel.EMAIL])),
        free_trial=FreeTrial(offered=_fv(False), duration_days=_fv(0), auto_convert_to_paid=_fv(False),
                              cancel_required_before_end=_fv(False), payment_method_required_upfront=_fv(False),
                              notice_before_conversion_days=_fv(0)),
        cancellation=Cancellation(method=_fv("online"), method_description=_fv(""), notice_period_days=_fv(0),
                                   penalty_present=_fv(False), penalty_description=_fv(""),
                                   proration_policy=_fv("no_refund"), blackout_periods=_fv([])),
        terms_changes=TermsChanges(notice_channels=_fv([NoticeChannel.EMAIL]), notice_lead_time_days=_fv(30),
                                    user_consent_mechanism=_fv(ConsentMechanism.OPT_OUT_AVAILABLE),
                                    user_right_to_terminate_on_change=_fv(True), silent_acceptance_clause=_fv(False)),
        data_usage=DataUsage(collected_categories=_fv([]), third_party_sharing=_fv(False),
                              third_party_recipients=_fv([]), third_party_purposes=_fv([]),
                              retention_period_months=_fv(0), marketing_use=_fv(False),
                              marketing_consent=_fv(ConsentMechanism.OPT_OUT_AVAILABLE),
                              cross_border_transfer=_fv(False)),
        liability=Liability(service_disruption_compensation=_fv(False), compensation_description=_fv(""),
                             damages_cap_present=_fv(False), damages_cap_description=_fv(""),
                             force_majeure_scope=_fv(""), indirect_damages_excluded=_fv(False)),
        disputes=Disputes(governing_law=_fv(""), jurisdiction_clause=_fv(""),
                           arbitration_required=_fv(False), class_action_waiver=_fv(False)),
    )


async def test_run_pipeline_invokes_each_stage_in_order(monkeypatch):
    """파이프라인이 parse → extract → summarize → ground 순으로 호출되는지 검증."""
    call_order: list[str] = []

    parse_result = DocumentParseResult(
        markdown="# 약관\n...",
        elements=[ParsedElement(id=1, page=1, category="paragraph", text="...", bbox=None)],
    )
    terms = _build_terms()
    summary = SummaryResult(summary="요약", key_clauses=[
        KeyClause(title="t", description="d", risk_level="high", pain_point_id="MID-02",
                  citation=KeyClauseCitation(page=1, quote="...")),
    ])
    ground = GroundednessResult(
        summary="요약", grounded_clauses=summary.key_clauses, ungrounded_clauses=[],
        overall_grounded=True,
    )

    async def fake_parse(client, *, file_bytes, filename):
        call_order.append("parse")
        return parse_result

    async def fake_extract(client, *, parsed_markdown, parsed_elements, service_name, service_provider):
        call_order.append("extract")
        return terms

    async def fake_summarize(client, *, terms):
        call_order.append("summarize")
        return summary

    async def fake_ground(client, *, summary, source_markdown):
        call_order.append("ground")
        return ground

    monkeypatch.setattr("services.pipeline.parse_document", fake_parse)
    monkeypatch.setattr("services.pipeline.extract_subscription", fake_extract)
    monkeypatch.setattr("services.pipeline.summarize_risks", fake_summarize)
    monkeypatch.setattr("services.pipeline.check_groundedness", fake_ground)

    fake_client = AsyncMock()
    result = await run_pipeline(
        fake_client,
        file_bytes=b"...",
        filename="t.pdf",
        service_name="X",
        service_provider="Y",
    )
    assert call_order == ["parse", "extract", "summarize", "ground"]
    assert isinstance(result, AnalysisResult)
    assert result.terms.service_name == "X"
    assert result.summary == "요약"
    assert result.grounded is True
    assert len(result.key_clauses) == 1
```

- [ ] **Step 11.2: 실패 확인**

```bash
pytest tests/unit/test_services_pipeline.py -v
```

Expected: `ImportError`.

- [ ] **Step 11.3: `services/pipeline.py` 구현**

```python
from __future__ import annotations

import logging
import time

from pydantic import BaseModel, Field

from schemas.subscription import SubscriptionTerms
from services.extract import extract_subscription
from services.ground import check_groundedness
from services.parse import parse_document
from services.summarize import KeyClause, summarize_risks
from services.upstage import UpstageClient

logger = logging.getLogger(__name__)


class StageTiming(BaseModel):
    stage: str
    seconds: float


class AnalysisResult(BaseModel):
    terms: SubscriptionTerms
    summary: str
    key_clauses: list[KeyClause]
    ungrounded_clauses: list[KeyClause] = Field(default_factory=list)
    grounded: bool
    timings: list[StageTiming] = Field(default_factory=list)


async def run_pipeline(
    client: UpstageClient,
    *,
    file_bytes: bytes,
    filename: str,
    service_name: str,
    service_provider: str,
) -> AnalysisResult:
    timings: list[StageTiming] = []

    t0 = time.perf_counter()
    parsed = await parse_document(client, file_bytes=file_bytes, filename=filename)
    timings.append(StageTiming(stage="parse", seconds=time.perf_counter() - t0))

    t0 = time.perf_counter()
    terms = await extract_subscription(
        client,
        parsed_markdown=parsed.markdown,
        parsed_elements=parsed.elements,
        service_name=service_name,
        service_provider=service_provider,
    )
    timings.append(StageTiming(stage="extract", seconds=time.perf_counter() - t0))

    t0 = time.perf_counter()
    summary = await summarize_risks(client, terms=terms)
    timings.append(StageTiming(stage="summarize", seconds=time.perf_counter() - t0))

    t0 = time.perf_counter()
    ground = await check_groundedness(client, summary=summary, source_markdown=parsed.markdown)
    timings.append(StageTiming(stage="ground", seconds=time.perf_counter() - t0))

    logger.info(
        "pipeline complete service=%s timings=%s grounded=%s",
        service_name, [(t.stage, round(t.seconds, 2)) for t in timings], ground.overall_grounded,
    )
    return AnalysisResult(
        terms=terms,
        summary=ground.summary,
        key_clauses=ground.grounded_clauses,
        ungrounded_clauses=ground.ungrounded_clauses,
        grounded=ground.overall_grounded,
        timings=timings,
    )
```

- [ ] **Step 11.4: 통과 확인**

```bash
pytest tests/unit/test_services_pipeline.py -v
```

Expected: `1 passed`.

- [ ] **Step 11.5: 커밋**

```bash
git add services/pipeline.py tests/unit/test_services_pipeline.py
git commit -m "$(cat <<'EOF'
feat(services): add pipeline orchestrator (parse→IE→summarize→ground)

run_pipeline chains the four Upstage adapters in order, records
per-stage timings, and returns AnalysisResult with grounded /
ungrounded clauses separated. Each stage timing is logged for
latency/cost analysis.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: FastAPI `/v1/terms/analyze` 엔드포인트

**Files:**
- Create: `app/routes/terms.py`
- Modify: `app/main.py` (router 등록)
- Create: `tests/unit/test_routes_terms.py`

- [ ] **Step 12.1: 실패 테스트 작성**

```python
# tests/unit/test_routes_terms.py
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from schemas.common import Citation, FieldValue, Uncertainty
from schemas.enums import BillingCycle, ConsentMechanism, NoticeChannel
from schemas.subscription import (
    Cancellation, DataUsage, Disputes, FreeTrial, Liability,
    Pricing, SubscriptionTerms, TermsChanges,
)
from services.pipeline import AnalysisResult, StageTiming
from services.summarize import KeyClause, KeyClauseCitation


def _fv(v, page=1, quote="..."):
    return FieldValue(value=v, uncertainty=Uncertainty.CONFIRMED, citation=Citation(page=page, quote=quote))


def _fake_result() -> AnalysisResult:
    terms = SubscriptionTerms(
        service_name="TestStream", service_provider="TestCo", extraction_date="2026-05-13T00:00:00Z",
        pricing=Pricing(base_price_krw=_fv(9900), billing_cycle=_fv(BillingCycle.MONTHLY),
                         auto_renewal_enabled=_fv(True),
                         auto_renewal_consent=_fv(ConsentMechanism.OPT_OUT_AVAILABLE),
                         price_change_notice_days=_fv(30),
                         price_change_notice_channels=_fv([NoticeChannel.EMAIL])),
        free_trial=FreeTrial(offered=_fv(False), duration_days=_fv(0), auto_convert_to_paid=_fv(False),
                              cancel_required_before_end=_fv(False), payment_method_required_upfront=_fv(False),
                              notice_before_conversion_days=_fv(0)),
        cancellation=Cancellation(method=_fv("online"), method_description=_fv(""), notice_period_days=_fv(0),
                                   penalty_present=_fv(False), penalty_description=_fv(""),
                                   proration_policy=_fv("no_refund"), blackout_periods=_fv([])),
        terms_changes=TermsChanges(notice_channels=_fv([NoticeChannel.EMAIL]), notice_lead_time_days=_fv(30),
                                    user_consent_mechanism=_fv(ConsentMechanism.OPT_OUT_AVAILABLE),
                                    user_right_to_terminate_on_change=_fv(True),
                                    silent_acceptance_clause=_fv(False)),
        data_usage=DataUsage(collected_categories=_fv([]), third_party_sharing=_fv(False),
                              third_party_recipients=_fv([]), third_party_purposes=_fv([]),
                              retention_period_months=_fv(0), marketing_use=_fv(False),
                              marketing_consent=_fv(ConsentMechanism.OPT_OUT_AVAILABLE),
                              cross_border_transfer=_fv(False)),
        liability=Liability(service_disruption_compensation=_fv(False), compensation_description=_fv(""),
                             damages_cap_present=_fv(False), damages_cap_description=_fv(""),
                             force_majeure_scope=_fv(""), indirect_damages_excluded=_fv(False)),
        disputes=Disputes(governing_law=_fv(""), jurisdiction_clause=_fv(""),
                           arbitration_required=_fv(False), class_action_waiver=_fv(False)),
    )
    clause = KeyClause(title="자동갱신", description="...", risk_level="high",
                       pain_point_id="MID-02", citation=KeyClauseCitation(page=1, quote="..."))
    return AnalysisResult(
        terms=terms, summary="요약", key_clauses=[clause], ungrounded_clauses=[],
        grounded=True, timings=[StageTiming(stage="parse", seconds=0.1)],
    )


def test_analyze_endpoint_happy_path(monkeypatch):
    async def fake_run_pipeline(*args, **kwargs):
        return _fake_result()

    monkeypatch.setattr("app.routes.terms.run_pipeline", fake_run_pipeline)
    monkeypatch.setenv("UPSTAGE_API_KEY", "test-key")

    client = TestClient(app)
    response = client.post(
        "/v1/terms/analyze",
        files={"file": ("netflix.pdf", b"%PDF fake", "application/pdf")},
        data={"service_name": "Netflix", "service_provider": "Netflix Inc."},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["summary"] == "요약"
    assert body["grounded"] is True
    assert len(body["key_clauses"]) == 1
    assert body["terms"]["service_name"] == "TestStream"


def test_analyze_endpoint_missing_file_returns_422():
    client = TestClient(app)
    response = client.post(
        "/v1/terms/analyze",
        data={"service_name": "Netflix", "service_provider": "Netflix Inc."},
    )
    assert response.status_code == 422
```

- [ ] **Step 12.2: 실패 확인**

```bash
pytest tests/unit/test_routes_terms.py -v
```

Expected: ImportError 또는 404 (라우터 미등록).

- [ ] **Step 12.3: `app/routes/terms.py` 작성**

```python
from __future__ import annotations

from fastapi import APIRouter, File, Form, UploadFile
from pydantic import BaseModel

from services.pipeline import AnalysisResult, run_pipeline
from services.settings import Settings
from services.upstage import UpstageClient

router = APIRouter(prefix="/v1/terms", tags=["terms"])


class AnalyzeResponse(BaseModel):
    terms: dict
    summary: str
    key_clauses: list[dict]
    ungrounded_clauses: list[dict]
    grounded: bool
    timings: list[dict]


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_terms(
    file: UploadFile = File(...),
    service_name: str = Form(...),
    service_provider: str = Form(...),
) -> AnalyzeResponse:
    file_bytes = await file.read()
    settings = Settings()  # loads from .env
    async with UpstageClient(settings) as client:
        result: AnalysisResult = await run_pipeline(
            client,
            file_bytes=file_bytes,
            filename=file.filename or "upload",
            service_name=service_name,
            service_provider=service_provider,
        )
    return AnalyzeResponse(
        terms=result.terms.model_dump(),
        summary=result.summary,
        key_clauses=[c.model_dump() for c in result.key_clauses],
        ungrounded_clauses=[c.model_dump() for c in result.ungrounded_clauses],
        grounded=result.grounded,
        timings=[t.model_dump() for t in result.timings],
    )
```

- [ ] **Step 12.4: `app/main.py` 수정 (router 등록)**

기존 `app/main.py` 전체를 다음으로 교체:

```python
from fastapi import FastAPI

from app.routes import terms

app = FastAPI(title="Upstage AI Terms Analysis", version="0.1.0")

app.include_router(terms.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 12.5: 통과 확인**

```bash
pytest tests/unit/test_routes_terms.py tests/unit/test_health.py -v
```

Expected: `3 passed`.

- [ ] **Step 12.6: 커밋**

```bash
git add app/main.py app/routes/terms.py tests/unit/test_routes_terms.py
git commit -m "$(cat <<'EOF'
feat(api): add POST /v1/terms/analyze endpoint

Multipart endpoint: accepts (file, service_name, service_provider),
runs the full Parse→IE→Summarize→Ground pipeline, returns
AnalyzeResponse with terms (full schema), summary, key_clauses,
ungrounded_clauses, grounded flag, and per-stage timings.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 13: E2E 통합 테스트 (real fixture, opt-in)

**Files:**
- Create: `tests/integration/test_pipeline_e2e.py`
- Create: `data/fixtures/README.md` (fixture 추가 가이드)

- [ ] **Step 13.1: `data/fixtures/README.md` 작성**

```markdown
# Fixtures

E2E 테스트용 실제 약관 PDF/HTML 보관소.

## 필요 파일

- `netflix_terms.pdf` — Netflix 이용약관 (https://help.netflix.com/legal/termsofuse 다운로드)
- `spotify_terms.pdf` — Spotify 이용약관
- `wavve_terms.pdf` — Wavve 이용약관

## 추가 방법

각 서비스 약관 페이지에서 PDF/HTML로 저장 후 위 파일명으로 본 디렉토리에 배치.

## 실행

```bash
# UPSTAGE_API_KEY 가 .env에 설정되어 있어야 함
pytest tests/integration -v -m e2e
```
```

- [ ] **Step 13.2: `pyproject.toml`에 `e2e` 마커 추가**

기존 `[tool.pytest.ini_options]` 블록을 다음으로 교체:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
pythonpath = ["."]
markers = [
    "e2e: real Upstage API integration test (requires UPSTAGE_API_KEY + fixture files)",
]
```

- [ ] **Step 13.3: E2E 테스트 작성**

```python
# tests/integration/test_pipeline_e2e.py
import os
from pathlib import Path

import pytest

from services.pipeline import run_pipeline
from services.settings import Settings
from services.upstage import UpstageClient

FIXTURE_DIR = Path(__file__).parent.parent.parent / "data" / "fixtures"


def _skip_if_no_key():
    if not os.getenv("UPSTAGE_API_KEY"):
        pytest.skip("UPSTAGE_API_KEY not set")


def _skip_if_no_fixture(name: str) -> Path:
    path = FIXTURE_DIR / name
    if not path.exists():
        pytest.skip(f"fixture {name} not found at {path}")
    return path


@pytest.mark.e2e
async def test_netflix_terms_end_to_end():
    _skip_if_no_key()
    fixture = _skip_if_no_fixture("netflix_terms.pdf")

    settings = Settings()
    async with UpstageClient(settings) as client:
        result = await run_pipeline(
            client,
            file_bytes=fixture.read_bytes(),
            filename=fixture.name,
            service_name="Netflix",
            service_provider="Netflix, Inc.",
        )

    assert result.terms.service_name == "Netflix"
    assert result.terms.pricing.base_price_krw.value is not None
    assert result.summary
    assert len(result.key_clauses) >= 1
    print("\n=== Netflix E2E Result ===")
    print(f"Summary: {result.summary}")
    print(f"Grounded: {result.grounded}")
    print("Key clauses:")
    for c in result.key_clauses:
        print(f"  - [{c.risk_level}] {c.title}: {c.description}")
    print("Timings:", [(t.stage, round(t.seconds, 2)) for t in result.timings])
```

- [ ] **Step 13.4: E2E 테스트 실행 (fixture 없어도 skip 으로 통과)**

```bash
pytest tests/integration -v -m e2e
```

Expected: 1 skipped (fixture 없음) 또는 1 passed (fixture + key 있을 때).

- [ ] **Step 13.5: 전체 단위 테스트 회귀 실행**

```bash
pytest tests/unit -v
```

Expected: 이전 task들의 테스트가 모두 통과 (~20 passed).

- [ ] **Step 13.6: 커밋**

```bash
git add pyproject.toml tests/integration/test_pipeline_e2e.py data/fixtures/README.md
git commit -m "$(cat <<'EOF'
test(integration): add E2E pipeline test on real Netflix fixture

Opt-in test via @pytest.mark.e2e marker. Skips when UPSTAGE_API_KEY
or fixture PDF is missing. Prints summary/clauses/timings for manual
inspection of the first real Upstage round-trip.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Wrap-Up Task: dev 브랜치 푸시

- [ ] **Step W.1: dev 브랜치 푸시**

```bash
git push -u origin dev
```

- [ ] **Step W.2: PR 생성 (선택)**

```bash
gh pr create --title "feat: OTT/subscription IE pipeline v1" --body "$(cat <<'EOF'
## Summary
- Document Parse → Information Extract → Solar Pro 3 요약 → Groundedness Check 종단 파이프라인
- SubscriptionTerms 스키마 (7 섹션 + Root, FieldValue[T] 래핑)
- POST /v1/terms/analyze 엔드포인트
- 단위 테스트 ~20개 + opt-in E2E 테스트

## Test plan
- [ ] pytest tests/unit -v (all green)
- [ ] Real fixture: pytest tests/integration -v -m e2e (with UPSTAGE_API_KEY + netflix_terms.pdf)
- [ ] Manual: curl + Netflix PDF → 응답 확인
EOF
)"
```

---

## Self-Review

**Spec coverage check:**
- ✅ §2.1 Approach C → Task 4 (pain points) + Task 5 (concept-grouped sections)
- ✅ §2.2 FieldValue 래퍼 → Task 2
- ✅ §2.3 enum + description → Task 3 (enums) + Task 5 (description 필드 포함)
- ✅ §2.4 의사표시 의제 → Task 3 (DEEMED_AGREED) + Task 5 (unfair_clause_flags) + Task 8 (prompt 룰) + Task 9 (high-risk 강제)
- ✅ §3 Type System → Task 2, 3
- ✅ §4 Pain Point Taxonomy → Task 4
- ✅ §5 Section Schema (7개) → Task 5
- ✅ §6.1 Versioning → Task 5 (`schema_version="1.0.0"` 고정 필드)
- ✅ §6.2 변경 추적 → Task 5 (`raw_document_hash` 필드 포함)
- ✅ §6.3 도메인 확장 → spec의 디자인 결정으로, 코드 작업은 v2+에서

**Placeholder scan:** 모든 단계에 실제 코드/명령어가 포함됨. 추정 부분(Upstage API 정확한 endpoint/payload)은 명시적으로 "공식 문서 확인" note 표시.

**Type consistency check:**
- `FieldValue[T]` 사용처 (Task 2 정의 → Task 5/7/8/9/10/11/12에서 사용): ✅ 일관
- `Citation` 필드명 (page, section, bbox, quote, pain_point_id): ✅ 일관
- `SubscriptionTerms` 필드명 (Task 5 정의 → Task 8/11/12 사용): ✅ 일관
- `KeyClause` / `SummaryResult` (Task 9 정의 → Task 10/11/12 사용): ✅ 일관
- `AnalysisResult` (Task 11 정의 → Task 12 사용): ✅ 일관

No gaps identified.
