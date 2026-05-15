"""AITerms schema validation 테스트."""

from __future__ import annotations

from ai.schemas.common import Citation, FieldValue, Uncertainty  # noqa: F401
from ai.schemas.enums import (
    BillingCycle,
    CancellationMethod,
    ConsentMechanism,
    OutputIPOwnership,
    TrainingDataPolicy,
)
from ai.schemas.ai_terms import (
    AICancellation,
    AIDataUsage,
    AIDisputes,
    AILiability,
    AITerms,
    ExportAndRegional,
    OutputAndIP,
    ProhibitedUse,
    ServiceTier,
    TrainingDataUse,
    UsageLimits,
)
from ai.schemas.subscription import TermsChanges


def _fv(value, page=1, quote="..."):
    """dict 반환 — pydantic v2 generic strict 회피용."""
    if value is None:
        return {"value": None, "uncertainty": Uncertainty.NOT_SPECIFIED, "citation": None}
    return {
        "value": value,
        "uncertainty": Uncertainty.CONFIRMED,
        "citation": {"page": page, "quote": quote},
    }


def _build_ai_terms() -> AITerms:
    return AITerms(
        service_name="Claude",
        service_provider="Anthropic",
        extraction_date="2026-05-16",
        service_tier=ServiceTier(
            free_tier_offered=_fv(True),
            free_tier_description=_fv("ChatGPT Free / Claude Free 같은 영구 무료"),
            paid_tier_offered=_fv(True),
            pricing_externally_delegated=_fv(True),
            base_price_description=_fv("Pricing Page 별도 안내"),
            billing_cycle=_fv(BillingCycle.MONTHLY),
            auto_renewal_enabled=_fv(True),
        ),
        training_data_use=TrainingDataUse(
            input_used_for_training=_fv(TrainingDataPolicy.OPT_OUT_AVAILABLE),
            output_used_for_training=_fv(TrainingDataPolicy.OPT_OUT_AVAILABLE),
            training_use_description=_fv("Inputs/Outputs 학습 활용, 옵트아웃 가능"),
            opt_out_available=_fv(True),
            opt_out_mechanism_description=_fv("Privacy 설정에서 거부"),
        ),
        output_and_ip=OutputAndIP(
            output_ip_ownership=_fv(OutputIPOwnership.USER),
            output_use_restrictions=_fv([]),
            user_verification_obligation=_fv(True),
            accuracy_disclaimer=_fv(True),
        ),
        usage_limits=UsageLimits(
            rate_limit_described=_fv(True),
            rate_limit_description=_fv("tokens-per-minute 제한"),
            quota_described=_fv(True),
            api_key_management_described=_fv(True),
            api_key_security_user_burden=_fv(True),
        ),
        prohibited_use=ProhibitedUse(
            illegal_content_prohibited=_fv(True),
            harmful_content_prohibited=_fv(True),
            high_risk_use_prohibited=_fv(True),
            prohibited_use_categories=_fv(["불법 활동", "혐오 발언", "의료 자문"]),
        ),
        export_and_regional=ExportAndRegional(
            export_control_clause=_fv(True),
            restricted_regions=_fv(["Russia", "Iran"]),
            governing_law_foreign=_fv(True),
        ),
        cancellation=AICancellation(
            cancellation_method=_fv(CancellationMethod.ONLINE),
            cancellation_description=_fv("계정 설정에서 해지"),
            korea_residents_7day_refund=_fv(True),
            non_refundable_clause=_fv(False),
            refund_policy_description=_fv("한국 거주자 7일 환불, 그 외 환불 없음"),
        ),
        terms_changes=TermsChanges(
            notice_channels=_fv([]),
            notice_lead_time_days=_fv(30),
            user_consent_mechanism=_fv(ConsentMechanism.DEEMED_AGREED),
            user_right_to_terminate_on_change=_fv(True),
            silent_acceptance_clause=_fv(True),
        ),
        data_usage=AIDataUsage(
            privacy_policy_externally_delegated=_fv(True),
            collected_categories=_fv([]),
            third_party_sharing=_fv(False),
            cross_border_transfer=_fv(True),
            marketing_use=_fv(False),
            marketing_consent=_fv(ConsentMechanism.OPT_OUT_AVAILABLE),
        ),
        liability=AILiability(
            indirect_damages_excluded=_fv(True),
            damages_cap_present=_fv(True),
            damages_cap_description=_fv("최근 6개월 결제액 또는 $100 중 큰 금액"),
            service_disruption_compensation=_fv(False),
            compensation_description=_fv("회사 면책"),
        ),
        disputes=AIDisputes(
            governing_law=_fv("California law"),
            jurisdiction_clause=_fv("San Francisco (binding arbitration)"),
            arbitration_required=_fv(True),
            class_action_waiver=_fv(True),
        ),
        unfair_clause_flags=["면책_손배_제한", "강제 중재", "집단소송 포기",
                              "AI 학습 데이터 활용", "준거법 외국법", "수출통제 제한"],
    )


def test_ai_terms_validates():
    terms = _build_ai_terms()
    assert terms.domain == "ai"
    assert terms.training_data_use.opt_out_available.value is True
    assert terms.output_and_ip.output_ip_ownership.value == OutputIPOwnership.USER
    assert terms.disputes.arbitration_required.value is True


def test_ai_terms_roundtrip_json():
    terms = _build_ai_terms()
    data = terms.model_dump_json()
    restored = AITerms.model_validate_json(data)
    assert restored.service_name == "Claude"
    assert (
        restored.training_data_use.input_used_for_training.value
        == TrainingDataPolicy.OPT_OUT_AVAILABLE
    )


def test_ai_terms_json_schema_has_sections():
    schema = AITerms.model_json_schema()
    props = schema["properties"]
    for section in (
        "service_tier", "training_data_use", "output_and_ip", "usage_limits",
        "prohibited_use", "export_and_regional", "cancellation",
        "terms_changes", "data_usage", "liability", "disputes",
    ):
        assert section in props


def test_ai_terms_unfair_flags_korean_only():
    """unfair_clause_flags vocabulary lock — 한국어 키워드만."""
    terms = _build_ai_terms()
    for flag in terms.unfair_clause_flags:
        # 영문 ascii-only 단어 금지 (보통 발명된 LLM 키워드)
        assert not flag.isascii() or " " in flag, f"flag '{flag}' looks like ad-hoc English"
