import json

import pytest

from schemas.common import Uncertainty
from schemas.enums import BillingCycle, ConsentMechanism
from schemas.subscription import SubscriptionTerms
from services.extract import extract_subscription, extract_subscription_with_voting
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


@pytest.mark.parametrize("bad_n", [0, -1, -5])
async def test_extract_with_voting_rejects_n_below_one(settings, bad_n):
    """n < 1 은 silent fallback 대신 ValueError를 raise."""
    async with UpstageClient(settings) as client:
        with pytest.raises(ValueError, match="n must be >= 1"):
            await extract_subscription_with_voting(
                client, parsed_markdown="...", parsed_elements=[],
                service_name="X", service_provider="Y", n=bad_n,
            )
