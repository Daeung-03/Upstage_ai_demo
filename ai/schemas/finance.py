"""Finance 도메인 추출 스키마.

대상: 전자금융거래, 송금, PG/결제대행, PFM, 선불전자지급수단, 카드모집 등.
OTT 중심의 `SubscriptionTerms`가 fit 하지 않아 별도 정의 (toss_golden.json 의
`schema_fit_note`: "pricing.*, free_trial.* 등은 의미 없음"). 정기 구독 모델
대신 거래별 수수료·책임 분배·예금자보호가 핵심.

공통 구조 (`TermsChanges`)는 OTT 스키마에서 재사용 — 약관 변경 통지 규제는
도메인과 무관하게 동일 패턴.
"""

from pydantic import BaseModel, Field

from ai.schemas.common import FieldValue
from ai.schemas.enums import (
    CancellationMethod,
    ConsentMechanism,
    DepositProtectionStatus,
    FraudResponsibilityPattern,
    NoticeChannel,
)
from ai.schemas.subscription import TermsChanges  # 공통 재사용


class Fees(BaseModel):
    has_transaction_fees: FieldValue[bool]
    transaction_fees_description: FieldValue[str]
    fee_change_notice_days: FieldValue[int]
    fee_change_notice_channels: FieldValue[list[NoticeChannel]]


class TransactionLimits(BaseModel):
    per_transaction_limit_krw: FieldValue[int]
    daily_limit_krw: FieldValue[int]
    monthly_limit_krw: FieldValue[int]
    limits_description: FieldValue[str]


class LiabilityAllocation(BaseModel):
    """사고·부정사용 책임 분배. 전자금융거래법 §9 패턴 매핑."""
    responsibility_pattern: FieldValue[FraudResponsibilityPattern]
    user_burden_description: FieldValue[str]
    company_compensation_scope: FieldValue[str]
    user_notification_deadline_hours: FieldValue[int]
    company_response_deadline_days: FieldValue[int]


class DepositProtection(BaseModel):
    status: FieldValue[DepositProtectionStatus]
    description: FieldValue[str]
    coverage_limit_krw: FieldValue[int]


class AccountTermination(BaseModel):
    """서비스 탈퇴 / 휴면 / 잔액 처리. OTT 의 cancellation 과 의미가 다름."""
    method: FieldValue[CancellationMethod]
    method_description: FieldValue[str]
    dormancy_period_months: FieldValue[int]
    balance_handling_description: FieldValue[str]


class FinanceDataUsage(BaseModel):
    """본 약관 본문 안에 명시된 개인정보 관련 진술. 별도 처리방침 위임은
    `privacy_policy_externally_delegated=True` 로 표현."""
    privacy_policy_externally_delegated: FieldValue[bool]
    collected_categories: FieldValue[list[str]]
    third_party_sharing: FieldValue[bool]
    third_party_recipients: FieldValue[list[str]]
    cross_border_transfer: FieldValue[bool]
    marketing_use: FieldValue[bool]
    marketing_consent: FieldValue[ConsentMechanism]


class FinanceDisputes(BaseModel):
    governing_law: FieldValue[str]
    jurisdiction_clause: FieldValue[str]
    financial_supervisor_complaint_channel: FieldValue[bool]
    complaint_channel_description: FieldValue[str]


class FinanceTerms(BaseModel):
    schema_version: str = "0.1.0"
    domain: str = "finance"

    service_name: str
    service_provider: str
    document_url: str | None = None
    effective_date: str | None = None
    extraction_date: str

    fees: Fees
    transaction_limits: TransactionLimits
    liability_allocation: LiabilityAllocation
    deposit_protection: DepositProtection
    account_termination: AccountTermination
    terms_changes: TermsChanges
    data_usage: FinanceDataUsage
    disputes: FinanceDisputes

    unfair_clause_flags: list[str] = Field(default_factory=list)
    raw_document_hash: str | None = None
