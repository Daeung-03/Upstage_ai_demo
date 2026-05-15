from pydantic import BaseModel, Field

from ai.schemas.common import FieldValue, empty_fv
from ai.schemas.enums import (
    AccountSharingPolicy,
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
    # v1.1.0 확장 (golden 라벨러가 자주 추가하는 OTT 표준 필드들).
    # backwards-compat: empty_fv() dict default + validate_default=True 로 pydantic
    # 이 dict 를 typed FieldValue 로 coerce. 안 그러면 raw dict 가 저장돼 voting/
    # bbox enrichment 에서 .value attribute 접근 시 깨짐.
    third_party_cancellation_required: FieldValue[bool] = Field(
        default_factory=empty_fv, validate_default=True
    )
    cooling_off_refund_days: FieldValue[int] = Field(
        default_factory=empty_fv, validate_default=True
    )
    cooling_off_conditions: FieldValue[str] = Field(
        default_factory=empty_fv, validate_default=True
    )


class TermsChanges(BaseModel):
    notice_channels: FieldValue[list[NoticeChannel]]
    notice_lead_time_days: FieldValue[int]
    user_consent_mechanism: FieldValue[ConsentMechanism]
    user_right_to_terminate_on_change: FieldValue[bool]
    silent_acceptance_clause: FieldValue[bool]
    # v1.1.0 확장 — 가격 변경 시 별도 동의 명시 여부 (한국 OTT 일반적으로 True 라벨).
    # backwards-compat default — TermsChanges 가 finance/insurance 도 공유함.
    price_change_explicit_consent: FieldValue[bool] = Field(
        default_factory=empty_fv, validate_default=True
    )


# === v1.1.0 새 섹션 — Account 정책 ===
class Account(BaseModel):
    """가입·계정 정책. OTT 표준 라벨링에 자주 등장 (gemini/coupang/watcha).

    필드 모두 backwards-compat default — 기존 fixture 가 account 섹션 없이도
    construction 가능.
    """
    minimum_age: FieldValue[int] = Field(default_factory=empty_fv, validate_default=True)
    sharing_restrictions: FieldValue[AccountSharingPolicy] = Field(
        default_factory=empty_fv, validate_default=True
    )


def _default_account() -> "Account":
    return Account()


# === v1.1.0 새 섹션 — 서비스 가용성 ===
class ServiceAvailability(BaseModel):
    """서비스 중단 / 지역 제한 정책."""
    availability_disclaimer: FieldValue[bool] = Field(
        default_factory=empty_fv, validate_default=True
    )
    regional_content_restriction: FieldValue[bool] = Field(
        default_factory=empty_fv, validate_default=True
    )


def _default_service_availability() -> "ServiceAvailability":
    return ServiceAvailability()


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
    schema_version: str = "1.1.0"
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
    # v1.1.0 확장 — 새 섹션 backwards-compat default (모든 필드 not_specified).
    account: Account = Field(default_factory=_default_account)
    service_availability: ServiceAvailability = Field(default_factory=_default_service_availability)

    unfair_clause_flags: list[str] = Field(default_factory=list)
    raw_document_hash: str | None = None
