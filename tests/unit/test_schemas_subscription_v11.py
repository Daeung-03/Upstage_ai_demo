"""SubscriptionTerms v1.1.0 확장 단위 테스트 — backwards-compat + 새 섹션.

핵심:
- 기존 fixture (Account/ServiceAvailability 없이) 도 SubscriptionTerms 생성 가능 (default_factory)
- 새 섹션 명시 시에도 정상 동작
- 새 enum (AccountSharingPolicy) 동작
"""

from __future__ import annotations

from ai.schemas.common import Citation, FieldValue, Uncertainty, empty_fv
from ai.schemas.enums import (
    AccountSharingPolicy,
    BillingCycle,
    CancellationMethod,
    ConsentMechanism,
    NoticeChannel,
    ProrationPolicy,
)
from ai.schemas.subscription import (
    Account,
    Cancellation,
    DataUsage,
    Disputes,
    FreeTrial,
    Liability,
    Pricing,
    ServiceAvailability,
    SubscriptionTerms,
    TermsChanges,
)


def _fv(value, page=1, quote="..."):
    """dict 반환 — pydantic v2 generic strict 회피."""
    if value is None:
        return {"value": None, "uncertainty": Uncertainty.NOT_SPECIFIED, "citation": None}
    return {
        "value": value,
        "uncertainty": Uncertainty.CONFIRMED,
        "citation": {"page": page, "quote": quote},
    }


def _build_minimal_terms_legacy() -> SubscriptionTerms:
    """v1.0 호환 — account / service_availability 안 줘도 default 채워짐."""
    return SubscriptionTerms(
        service_name="Test", service_provider="TestCo", extraction_date="2026-05-16",
        pricing=Pricing(
            base_price_krw=_fv(None), billing_cycle=_fv(BillingCycle.MONTHLY),
            auto_renewal_enabled=_fv(True),
            auto_renewal_consent=_fv(ConsentMechanism.OPT_OUT_AVAILABLE),
            price_change_notice_days=_fv(30),
            price_change_notice_channels=_fv([NoticeChannel.EMAIL]),
        ),
        free_trial=FreeTrial(
            offered=_fv(False), duration_days=_fv(None),
            auto_convert_to_paid=_fv(False), cancel_required_before_end=_fv(False),
            payment_method_required_upfront=_fv(False),
            notice_before_conversion_days=_fv(None),
        ),
        cancellation=Cancellation(
            method=_fv(CancellationMethod.ONLINE), method_description=_fv("앱 내 해지"),
            notice_period_days=_fv(0), penalty_present=_fv(False),
            penalty_description=_fv(""), proration_policy=_fv(ProrationPolicy.NO_REFUND),
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
            collected_categories=_fv([]), third_party_sharing=_fv(False),
            third_party_recipients=_fv([]), third_party_purposes=_fv([]),
            retention_period_months=_fv(None), marketing_use=_fv(False),
            marketing_consent=_fv(ConsentMechanism.OPT_OUT_AVAILABLE),
            cross_border_transfer=_fv(False),
        ),
        liability=Liability(
            service_disruption_compensation=_fv(False), compensation_description=_fv(""),
            damages_cap_present=_fv(False), damages_cap_description=_fv(""),
            force_majeure_scope=_fv(""), indirect_damages_excluded=_fv(False),
        ),
        disputes=Disputes(
            governing_law=_fv("대한민국 법률"), jurisdiction_clause=_fv("민사소송법상 관할법원"),
            arbitration_required=_fv(False), class_action_waiver=_fv(False),
        ),
    )


def test_legacy_subscription_terms_compatible():
    """v1.0 호환 — account / service_availability 안 줘도 생성 가능."""
    terms = _build_minimal_terms_legacy()
    assert terms.schema_version == "1.1.0"  # 자동 갱신
    # default account: 모든 필드 not_specified
    assert terms.account.minimum_age.value is None
    assert terms.account.minimum_age.uncertainty == Uncertainty.NOT_SPECIFIED
    assert terms.account.sharing_restrictions.value is None
    # default service_availability
    assert terms.service_availability.availability_disclaimer.value is None
    assert terms.service_availability.regional_content_restriction.value is None


def test_legacy_cancellation_v11_fields_default_not_specified():
    """v1.1 추가 cancellation 필드 (third_party_cancellation_required 등) 도
    backwards-compat default."""
    c = Cancellation(
        method=_fv(CancellationMethod.ONLINE), method_description=_fv("x"),
        notice_period_days=_fv(0), penalty_present=_fv(False),
        penalty_description=_fv(""), proration_policy=_fv(ProrationPolicy.NO_REFUND),
        blackout_periods=_fv([]),
    )
    assert c.third_party_cancellation_required.value is None
    assert c.cooling_off_refund_days.value is None
    assert c.cooling_off_conditions.value is None


def test_terms_changes_price_change_explicit_consent_default():
    tc = TermsChanges(
        notice_channels=_fv([]), notice_lead_time_days=_fv(30),
        user_consent_mechanism=_fv(ConsentMechanism.DEEMED_AGREED),
        user_right_to_terminate_on_change=_fv(True),
        silent_acceptance_clause=_fv(True),
    )
    assert tc.price_change_explicit_consent.value is None
    assert tc.price_change_explicit_consent.uncertainty == Uncertainty.NOT_SPECIFIED


def test_account_with_explicit_values():
    a = Account(
        minimum_age=_fv(19),
        sharing_restrictions=_fv(AccountSharingPolicy.HOUSEHOLD_ONLY),
    )
    assert a.minimum_age.value == 19
    assert a.sharing_restrictions.value == AccountSharingPolicy.HOUSEHOLD_ONLY


def test_service_availability_with_explicit_values():
    sa = ServiceAvailability(
        availability_disclaimer=_fv(True),
        regional_content_restriction=_fv(True),
    )
    assert sa.availability_disclaimer.value is True


def test_full_v11_subscription_terms_with_new_sections():
    """v1.1 새 섹션을 명시적으로 채워서 SubscriptionTerms 생성."""
    base = _build_minimal_terms_legacy()
    full = base.model_copy(update={
        "account": Account(
            minimum_age=_fv(14),
            sharing_restrictions=_fv(AccountSharingPolicy.PERSONAL_ONLY),
        ),
        "service_availability": ServiceAvailability(
            availability_disclaimer=_fv(True),
            regional_content_restriction=_fv(False),
        ),
    })
    assert full.account.minimum_age.value == 14
    assert full.service_availability.availability_disclaimer.value is True


def test_round_trip_json():
    """v1.1 SubscriptionTerms JSON 직렬화·역직렬화."""
    terms = _build_minimal_terms_legacy()
    data = terms.model_dump_json()
    restored = SubscriptionTerms.model_validate_json(data)
    assert restored.schema_version == "1.1.0"
    # account 가 빈 default 로 round-trip
    assert restored.account.minimum_age.value is None


def test_empty_fv_returns_dict():
    """common.empty_fv() 가 dict 반환 (pydantic generic 회피용)."""
    e = empty_fv()
    assert isinstance(e, dict)
    assert e == {"value": None, "uncertainty": Uncertainty.NOT_SPECIFIED, "citation": None}
