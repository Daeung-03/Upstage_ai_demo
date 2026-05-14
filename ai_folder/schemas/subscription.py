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
