# IE Schema v1 — OTT/구독 도메인 약관 분석

**Status**: Draft → Awaiting user review
**Date**: 2026-05-13
**Scope**: Information Extraction 스키마 v1 (첫 번째 도메인: OTT/구독)
**Skill Trace**: brainstorming → writing-plans (다음 단계)

---

## 1. Context

본 서비스는 한국 소비자에게 약관/계약 검토를 위한 구조화된 분석을 제공한다. 핵심 차별화는 "도메인별 의미 있는 필드"를 추출하는 IE 스키마이며, 이 스키마가 곧 서비스의 moat다. 본 문서는 첫 번째 도메인인 OTT/구독 서비스(Netflix, Spotify, Wavve 등)를 대상으로 한 IE 스키마 v1을 정의한다.

### 1.1 설계 목표

- **Pain Point 추적성**: 모든 필드가 기획서 1-3절의 소비자 pain point 중 하나 이상과 연결된다.
- **출처 검증성**: 모든 추출 값은 원문 위치(page, bbox, quote)를 보유. Groundedness Check 입력 및 UI 하이라이트 근거.
- **불확실성 표현**: 약관이 침묵하거나 모호한 경우를 별도로 표현 (할루시네이션 방지).
- **변경 추적 호환**: 동일 스키마로 약관 재추출 시 필드별 구조적 diff 가능.
- **도메인 확장 호환**: 보험/금융 도메인 추가 시 공통 섹션 재사용, 도메인 전용 섹션만 추가.

### 1.2 Out of Scope (v1)

- 보험·금융·렌탈 등 다른 도메인 (v2+)
- 임베딩 기반 의미적 변경 분석 (별도 모듈 `services/diff.py`, v1.1)
- 약관 캘린더용 일정 추출 (v1.1+)
- 사용자별 가입 상태 모델링 (별도 사용자 도메인 스펙)

---

## 2. Design Decisions

### 2.1 Approach C (Concept-Grouped + Pain-Point-Tagged)

세 가지 조직 방식을 비교한 결과 채택:

| 항목 | A: Pain-Point Flat | B: Legal-Concept Hierarchical | **C: Hybrid (채택)** |
|---|---|---|---|
| Pain Point 추적성 | ★★★ | ★ | ★★★ |
| 도메인 확장성 | ★ | ★★★ | ★★★ |
| AI 추출 친화성 | ★★ | ★★★ | ★★★ |
| 초기 설계 비용 | 낮음 | 중간 | 중간-높음 |

C는 계층 구조는 B(법률 개념)를 따르되, pain point 매핑을 **두 레이어**로 둔다:

- **스키마 레이어 (정적)**: 각 섹션이 어떤 pain point를 다루는지 문서/스키마 주석으로 명시 (본 스펙의 §5.1~§5.7 "Pain Points" 라인이 이 역할). UI에서 "POST-01(위약금)에 해당하는 모든 필드 보기" 같은 그룹핑의 근거.
- **인스턴스 레이어 (런타임)**: 추출된 각 `Citation`이 `pain_point_id`를 보유. LLM이 이 인용을 어떤 pain point 때문에 가져왔는지 표시. UI에서 "이 인용이 왜 중요한지" 라벨링에 사용.

두 레이어는 보통 일치하지만, 한 필드가 여러 조항에서 결정될 때(예: 가격 조정이 본문 + 부록 양쪽에서 다뤄질 때) 각 citation이 다른 pain_point_id를 가질 수 있다.

### 2.2 모든 값을 `FieldValue[T]`로 감싼다

단순 `bool`/`str`이 아니라 `(value, uncertainty, citation)` 튜플로 감싼다. 이유:

- **Groundedness Check 입력**: 각 필드의 citation이 원문 chunk 검증 단위가 된다.
- **UI 하이라이트**: bbox 좌표로 원문 위치 표시 (Document Parse Location Coordinates 활용).
- **불확실성 표현**: 약관이 침묵한 필드와 명시한 필드를 구분. `NOT_SPECIFIED` / `AMBIGUOUS` / `INFERRED` / `CONFIRMED`.

비용: 모든 필드가 1-depth 더 깊어진다. 대신 downstream 처리(검증/UI/diff)가 단순해진다.

### 2.3 enum + description 이중 구조

정규화된 값은 enum, 자유 서술은 별도 `*_description: str` 필드로 분리한다.

- **enum**: cross-document 매칭, 필터링, 검색에 사용 (예: `billing_cycle == MONTHLY` 인 모든 구독)
- **description**: 평문 번역, UI 표시, 미세한 뉘앙스 보존

예: `cancellation.penalty_present: FieldValue[bool]` + `cancellation.penalty_description: FieldValue[str]`

### 2.4 의사표시 의제는 enum 값 + flag 이중 표시

`ConsentMechanism.DEEMED_AGREED`가 발견되면 자동으로 `unfair_clause_flags`에 `"의사표시_의제"` 태그가 추가된다. 단일 사실의 이중 표시는 의도된 설계: enum은 데이터, flags는 경고 뷰. UI에서 "불공정 신호"만 모아서 보여줄 때 flags만 읽으면 된다.

---

## 3. Type System

### 3.1 공통 타입

```python
# schemas/common.py
from enum import Enum
from pydantic import BaseModel

class Uncertainty(str, Enum):
    CONFIRMED = "confirmed"          # 문서에 명시
    INFERRED = "inferred"            # 관련 조항에서 유추
    AMBIGUOUS = "ambiguous"          # 다중 해석 가능
    NOT_SPECIFIED = "not_specified"  # 문서가 침묵

class Citation(BaseModel):
    page: int
    section: str | None = None
    bbox: tuple[float, float, float, float] | None = None  # [x0, y0, x1, y1]
    quote: str                                              # 원문 정확 substring
    pain_point_id: str | None = None                        # PainPointID 참조

class FieldValue[T](BaseModel):  # Python 3.12+ generic syntax
    value: T | None
    uncertainty: Uncertainty
    citation: Citation | None = None
```

### 3.2 도메인 enum

```python
# schemas/enums.py
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
    WEB_NOTICE = "web_notice"      # 웹사이트 공지
    IN_APP_BANNER = "in_app_banner"

class ConsentMechanism(str, Enum):
    OPT_IN_EXPLICIT = "opt_in_explicit"      # 명시적 동의 필요
    OPT_OUT_AVAILABLE = "opt_out_available"  # 거부 가능
    DEEMED_AGREED = "deemed_agreed"          # 의사표시 의제 (불공정 신호)

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

---

## 4. Pain Point Taxonomy

기획서 1-3절의 pain point를 ID로 정규화. `Citation.pain_point_id`가 이 ID를 참조한다.

| ID | Pain Point | 단계 |
|---|---|---|
| `PRE-01` | 약관 분량/난이도 압박 | 가입 전 |
| `PRE-02` | 혜택-약관 보장 범위 괴리 | 가입 전 |
| `PRE-03` | 무료체험 → 자동 유료 전환 미인지 | 가입 전 |
| `PRE-04` | 개인정보 활용 범위 불투명 | 가입 전 |
| `MID-01` | 약관 변경 형식적 고지 (실질 인지 누락) | 가입 중 |
| `MID-02` | 의사표시 의제 (무응답 = 동의) | 가입 중 |
| `POST-01` | 위약금 미인지 | 가입 후 |
| `POST-02` | 해지 절차 복잡성 | 가입 후 |
| `POST-03` | 보장/혜택 청구권 미인지 | 가입 후 |
| `POST-04` | 면책 광범위 / 손해배상 제한 | 가입 후 |
| `POST-05` | 분쟁 절차 불투명 / 집단소송 포기 | 가입 후 |

`schemas/pain_points.py`에서 `PainPointID` enum으로 정의 (또는 string ID + dict 매핑).

---

## 5. Section Schema

### 5.1 Pricing

```python
class Pricing(BaseModel):
    base_price_krw: FieldValue[int]
    billing_cycle: FieldValue[BillingCycle]
    auto_renewal_enabled: FieldValue[bool]
    auto_renewal_consent: FieldValue[ConsentMechanism]
    price_change_notice_days: FieldValue[int]
    price_change_notice_channels: FieldValue[list[NoticeChannel]]
```

**Pain Points**: `PRE-02` (혜택-약관 괴리), `PRE-03` (자동결제 미인지)

### 5.2 FreeTrial

```python
class FreeTrial(BaseModel):
    offered: FieldValue[bool]
    duration_days: FieldValue[int]
    auto_convert_to_paid: FieldValue[bool]
    cancel_required_before_end: FieldValue[bool]
    payment_method_required_upfront: FieldValue[bool]
    notice_before_conversion_days: FieldValue[int]
```

**Pain Points**: `PRE-03` (무료체험 → 유료 전환)

### 5.3 Cancellation

```python
class Cancellation(BaseModel):
    method: FieldValue[CancellationMethod]
    method_description: FieldValue[str]
    notice_period_days: FieldValue[int]
    penalty_present: FieldValue[bool]
    penalty_description: FieldValue[str]
    proration_policy: FieldValue[ProrationPolicy]
    blackout_periods: FieldValue[list[str]]   # 해지 불가 기간 (있는 경우)
```

**Pain Points**: `POST-01` (위약금), `POST-02` (해지 절차)

### 5.4 TermsChanges

```python
class TermsChanges(BaseModel):
    notice_channels: FieldValue[list[NoticeChannel]]
    notice_lead_time_days: FieldValue[int]
    user_consent_mechanism: FieldValue[ConsentMechanism]
    user_right_to_terminate_on_change: FieldValue[bool]
    silent_acceptance_clause: FieldValue[bool]  # 의사표시 의제 명시 여부
```

**Pain Points**: `MID-01` (형식적 고지), `MID-02` (의사표시 의제)

### 5.5 DataUsage

```python
class DataUsage(BaseModel):
    collected_categories: FieldValue[list[str]]    # ["device_id", "viewing_history", ...]
    third_party_sharing: FieldValue[bool]
    third_party_recipients: FieldValue[list[str]]
    third_party_purposes: FieldValue[list[str]]
    retention_period_months: FieldValue[int]
    marketing_use: FieldValue[bool]
    marketing_consent: FieldValue[ConsentMechanism]
    cross_border_transfer: FieldValue[bool]
```

**Pain Points**: `PRE-04` (개인정보 활용)

### 5.6 Liability

```python
class Liability(BaseModel):
    service_disruption_compensation: FieldValue[bool]
    compensation_description: FieldValue[str]
    damages_cap_present: FieldValue[bool]
    damages_cap_description: FieldValue[str]
    force_majeure_scope: FieldValue[str]
    indirect_damages_excluded: FieldValue[bool]
```

**Pain Points**: `POST-04` (면책/손배 제한)

### 5.7 Disputes

```python
class Disputes(BaseModel):
    governing_law: FieldValue[str]
    jurisdiction_clause: FieldValue[str]
    arbitration_required: FieldValue[bool]
    class_action_waiver: FieldValue[bool]
```

**Pain Points**: `POST-05` (분쟁 절차)

### 5.8 Root

```python
# schemas/subscription.py
from pydantic import BaseModel, Field

class SubscriptionTerms(BaseModel):
    schema_version: str = "1.0.0"
    domain: str = "subscription"

    # 서비스 메타
    service_name: str
    service_provider: str
    document_url: str | None = None
    effective_date: str | None = None      # ISO date
    extraction_date: str                    # ISO datetime

    # 섹션
    pricing: Pricing
    free_trial: FreeTrial
    cancellation: Cancellation
    terms_changes: TermsChanges
    data_usage: DataUsage
    liability: Liability
    disputes: Disputes

    # Cross-cutting
    unfair_clause_flags: list[str] = Field(default_factory=list)
    raw_document_hash: str | None = None    # 변경 추적용 SHA256
```

---

## 6. Cross-Cutting Concerns

### 6.1 Schema Versioning

`schema_version`은 SemVer 준수:

- **MAJOR**: 필드 제거 또는 의미 변경 (breaking)
- **MINOR**: 필드 추가 (backward compatible)
- **PATCH**: enum 값 추가, description 변경

저장된 `SubscriptionTerms` 인스턴스는 자신의 schema_version을 보유. 마이그레이션은 `migrations/` 모듈로 처리 (v1.1+).

### 6.2 변경 추적 호환성

가입 중 단계의 약관 변경 분석은 동일 스키마로 재추출 후 필드별 diff를 수행한다. 핵심:

- **Stable field identity**: 섹션.필드명이 곧 diff 키 (예: `pricing.base_price_krw`)
- **Citation 비교 제외**: 위치/quote는 문서마다 다르므로 `value` + `uncertainty`만 비교
- **의미적 변경 판정**: enum 값 변경, 숫자 변경, bool 변경은 명백; `*_description` 변경은 임베딩 유사도로 판정 (`services/diff.py`, v1.1)

### 6.3 도메인 확장 호환성

다음 도메인 추가 시 호환성 평가:

| 도메인 | 재사용 섹션 | 신규 섹션 |
|---|---|---|
| 보험 | TermsChanges, Disputes, DataUsage | `Coverage`, `Exclusions`, `ClaimProcess`, `Premium` |
| 은행/금융 | Pricing, TermsChanges, DataUsage, Disputes | `InterestRate`, `FeeStructure`, `AccountClosure` |
| 가전 렌탈 | Pricing, Cancellation, TermsChanges, Liability | `Equipment`, `Maintenance`, `Ownership` |

신규 도메인 = 신규 Root 모델 + 신규 섹션. 공통 섹션은 import 재사용.

---

## 7. Open Questions

- [ ] Pain point taxonomy를 Python enum으로 만들지 string ID로 둘지? 현재는 string. enum 전환 시 PATCH 영향.
- [ ] `unfair_clause_flags`의 표준 태그 목록은 별도 `unfair_taxonomy.py`에서 관리 (권장).
- [ ] FieldValue의 `citation`이 list로 갈 수도 있다 (한 필드가 여러 조항에서 결정되는 경우). v1.1에서 검토.
- [ ] Korean labels(i18n)는 별도 매핑 모듈로 분리 vs Field description으로 임베드. 현재는 description.

---

## 8. Next Steps

이 스펙 승인 후 `writing-plans` 스킬로 전환하여 다음을 구체화:

1. 디렉토리 구조 (`schemas/`, `services/`, `tests/`, `prompts/`, `data/fixtures/`)
2. Pydantic 모델 파일 분할 전략
3. Document Parse → Information Extraction → Schema 인스턴스 변환 파이프라인
4. Fixture 약관 3건 (Netflix, Spotify, Wavve) + Golden 추출 결과
5. Unit/Integration 테스트 계획
6. `POST /v1/terms/analyze` FastAPI 엔드포인트 설계
