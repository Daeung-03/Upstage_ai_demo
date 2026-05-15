"""Insurance 도메인 추출 스키마.

대상: 실손/생명/손해/암/여행/자동차 등 한국 보험 약관. 보장범위·면책·청구·
해지환급금이 핵심으로 OTT/Fintech 와 모두 다름.

공통 구조 (`TermsChanges`) 는 OTT 스키마에서 재사용. 보험은 청구·해지 시점이
명확히 분리되므로 별도 섹션 (`Claims`, `CancellationRefund`) 으로 둔다.
"""

from pydantic import BaseModel, Field

from ai.schemas.common import FieldValue
from ai.schemas.enums import (
    CancellationMethod,
    ConsentMechanism,
    InsuranceClaimMethod,
    PremiumCycle,
    RefundFormula,
)
from ai.schemas.subscription import TermsChanges  # 공통 재사용


class Coverage(BaseModel):
    insurance_type: FieldValue[str]          # 실손/생명/암/여행/자동차 등
    covered_items: FieldValue[list[str]]
    total_coverage_limit_krw: FieldValue[int]
    per_event_limit_krw: FieldValue[int]
    coverage_description: FieldValue[str]


class Exclusions(BaseModel):
    exclusion_items: FieldValue[list[str]]
    waiting_period_days: FieldValue[int]         # 가입 후 보장 개시까지
    immunity_period_days: FieldValue[int]        # 자살·기왕증 등 면책기간
    pre_existing_conditions_excluded: FieldValue[bool]


class Premium(BaseModel):
    payment_cycle: FieldValue[PremiumCycle]
    base_premium_krw: FieldValue[int]
    premium_adjustment_description: FieldValue[str]
    payment_waiver_conditions: FieldValue[str]


class Claims(BaseModel):
    claim_methods: FieldValue[list[InsuranceClaimMethod]]
    claim_filing_deadline_years: FieldValue[int]   # 소멸시효 (일반 3년)
    payout_deadline_days: FieldValue[int]          # 보험금 지급 기한
    required_documents: FieldValue[list[str]]
    claim_denial_grounds: FieldValue[list[str]]


class CancellationRefund(BaseModel):
    cancellation_allowed: FieldValue[bool]
    cancellation_method: FieldValue[CancellationMethod]
    refund_formula: FieldValue[RefundFormula]
    refund_description: FieldValue[str]
    cooling_off_days: FieldValue[int]              # 청약철회 기간 (일반 15일)


class Renewal(BaseModel):
    auto_renewal: FieldValue[bool]
    renewal_premium_change_possible: FieldValue[bool]
    renewal_refusal_grounds: FieldValue[list[str]]
    renewal_description: FieldValue[str]


class InsuranceDataUsage(BaseModel):
    privacy_policy_externally_delegated: FieldValue[bool]
    medical_data_collected: FieldValue[bool]    # 보험 핵심 — 민감정보
    collected_categories: FieldValue[list[str]]
    third_party_sharing: FieldValue[bool]
    third_party_recipients: FieldValue[list[str]]
    marketing_use: FieldValue[bool]
    marketing_consent: FieldValue[ConsentMechanism]


class InsuranceDisputes(BaseModel):
    governing_law: FieldValue[str]
    jurisdiction_clause: FieldValue[str]
    financial_supervisor_complaint_channel: FieldValue[bool]
    dispute_mediation_described: FieldValue[bool]


class InsuranceTerms(BaseModel):
    schema_version: str = "0.1.0"
    domain: str = "insurance"

    service_name: str
    service_provider: str           # 보험사 (e.g. 삼성화재, KB손해보험)
    document_url: str | None = None
    effective_date: str | None = None
    extraction_date: str

    coverage: Coverage
    exclusions: Exclusions
    premium: Premium
    claims: Claims
    cancellation_refund: CancellationRefund
    renewal: Renewal
    terms_changes: TermsChanges
    data_usage: InsuranceDataUsage
    disputes: InsuranceDisputes

    unfair_clause_flags: list[str] = Field(default_factory=list)
    raw_document_hash: str | None = None
