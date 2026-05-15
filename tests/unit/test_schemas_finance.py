"""FinanceTerms schema validation 테스트."""

from __future__ import annotations

from ai.schemas.common import Citation, FieldValue, Uncertainty  # noqa: F401  (used in indirect tests)
from ai.schemas.enums import (
    CancellationMethod,
    ConsentMechanism,
    DepositProtectionStatus,
    FraudResponsibilityPattern,
    NoticeChannel,
)
from ai.schemas.finance import (
    AccountTermination,
    DepositProtection,
    Fees,
    FinanceDataUsage,
    FinanceDisputes,
    FinanceTerms,
    LiabilityAllocation,
    TransactionLimits,
)
from ai.schemas.subscription import TermsChanges


def _fv(value, page=1, quote="..."):
    """헬퍼 — dict 반환. pydantic v2 generic strict 검증에서 비-파라미터화된
    `FieldValue(...)` 인스턴스는 `FieldValue[int]` 등 typed 필드에 거부되므로,
    dict 로 넘겨 외부 모델이 올바른 generic 타입으로 재검증하게 한다.
    """
    if value is None:
        return {"value": None, "uncertainty": Uncertainty.NOT_SPECIFIED, "citation": None}
    # enum 인스턴스도 그대로 dict 안에 넣으면 pydantic 이 .value 로 직렬화
    return {
        "value": value,
        "uncertainty": Uncertainty.CONFIRMED,
        "citation": {"page": page, "quote": quote},
    }


def _build_finance_terms(*, service_name: str = "Toss") -> FinanceTerms:
    return FinanceTerms(
        service_name=service_name,
        service_provider="비바리퍼블리카",
        extraction_date="2026-05-15",
        fees=Fees(
            has_transaction_fees=_fv(True),
            transaction_fees_description=_fv("송금 수수료 무료, PG 수수료는 가맹점에 부과"),
            fee_change_notice_days=_fv(30),
            fee_change_notice_channels=_fv([NoticeChannel.EMAIL, NoticeChannel.APP_PUSH]),
        ),
        transaction_limits=TransactionLimits(
            per_transaction_limit_krw=_fv(2_000_000),
            daily_limit_krw=_fv(5_000_000),
            monthly_limit_krw=_fv(None),
            limits_description=_fv("일반 회원 기준; 본인인증 시 상향 가능"),
        ),
        liability_allocation=LiabilityAllocation(
            responsibility_pattern=_fv(FraudResponsibilityPattern.USER_GROSS_NEGLIGENCE_ONLY),
            user_burden_description=_fv("회원의 고의 또는 중과실"),
            company_compensation_scope=_fv("회사의 고의·중과실로 인한 손해"),
            user_notification_deadline_hours=_fv(48),
            company_response_deadline_days=_fv(15),
        ),
        deposit_protection=DepositProtection(
            status=_fv(DepositProtectionStatus.SEPARATELY_DEPOSITED),
            description=_fv("선불 충전금은 별도 예치 (예금자보호법 비적용)"),
            coverage_limit_krw=_fv(None),
        ),
        account_termination=AccountTermination(
            method=_fv(CancellationMethod.ONLINE),
            method_description=_fv("앱 내 계정 탈퇴 메뉴"),
            dormancy_period_months=_fv(12),
            balance_handling_description=_fv("탈퇴 시 잔액은 7일 내 환급 계좌로 송금"),
        ),
        terms_changes=TermsChanges(
            notice_channels=_fv([NoticeChannel.EMAIL, NoticeChannel.APP_PUSH]),
            notice_lead_time_days=_fv(30),
            user_consent_mechanism=_fv(ConsentMechanism.DEEMED_AGREED),
            user_right_to_terminate_on_change=_fv(True),
            silent_acceptance_clause=_fv(True),
        ),
        data_usage=FinanceDataUsage(
            privacy_policy_externally_delegated=_fv(True),
            collected_categories=_fv([]),
            third_party_sharing=_fv(None),
            third_party_recipients=_fv([]),
            cross_border_transfer=_fv(False),
            marketing_use=_fv(False),
            marketing_consent=_fv(ConsentMechanism.OPT_IN_EXPLICIT),
        ),
        disputes=FinanceDisputes(
            governing_law=_fv("대한민국 법률"),
            jurisdiction_clause=_fv("민사소송법상 관할법원"),
            financial_supervisor_complaint_channel=_fv(True),
            complaint_channel_description=_fv("금융감독원 분쟁조정 신청 가능"),
        ),
        unfair_clause_flags=["의사표시_의제"],
    )


def test_finance_terms_validates():
    terms = _build_finance_terms()
    assert terms.domain == "finance"
    assert terms.schema_version == "0.1.0"
    assert terms.fees.has_transaction_fees.value is True
    assert (
        terms.liability_allocation.responsibility_pattern.value
        == FraudResponsibilityPattern.USER_GROSS_NEGLIGENCE_ONLY
    )
    assert terms.deposit_protection.status.value == DepositProtectionStatus.SEPARATELY_DEPOSITED


def test_finance_terms_roundtrip_json():
    terms = _build_finance_terms()
    data = terms.model_dump_json()
    restored = FinanceTerms.model_validate_json(data)
    assert restored.service_name == "Toss"
    assert restored.transaction_limits.daily_limit_krw.value == 5_000_000


def test_finance_terms_json_schema_has_sections():
    schema = FinanceTerms.model_json_schema()
    props = schema["properties"]
    for section in (
        "fees", "transaction_limits", "liability_allocation",
        "deposit_protection", "account_termination", "terms_changes",
        "data_usage", "disputes",
    ):
        assert section in props
