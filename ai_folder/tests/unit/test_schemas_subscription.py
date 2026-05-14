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
    data = terms.model_dump_json()
    restored = SubscriptionTerms.model_validate_json(data)
    assert restored.service_name == "TestStream"
    assert "의사표시_의제" in restored.unfair_clause_flags
    assert restored.schema_version == "1.0.0"


def test_schema_json_schema_generated():
    schema = SubscriptionTerms.model_json_schema()
    assert schema["type"] == "object"
    assert "pricing" in schema["properties"]
    assert "cancellation" in schema["properties"]
