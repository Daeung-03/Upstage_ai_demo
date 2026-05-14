import json

import pytest

from schemas.common import Citation, FieldValue, Uncertainty
from schemas.enums import BillingCycle, ConsentMechanism, NoticeChannel
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
from services.settings import Settings
from services.summarize import KeyClause, SummaryResult, summarize_risks
from services.upstage import UpstageClient


@pytest.fixture
def settings(sample_api_key, sample_base_url):
    return Settings(upstage_api_key=sample_api_key, upstage_base_url=sample_base_url)


def _fv(v, u=Uncertainty.CONFIRMED, page=1, quote="...", pain_point_id=None):
    return FieldValue(value=v, uncertainty=u, citation=Citation(page=page, quote=quote, pain_point_id=pain_point_id))


@pytest.fixture
def sample_terms():
    return SubscriptionTerms(
        service_name="TestStream", service_provider="TestCo",
        extraction_date="2026-05-13T00:00:00Z",
        pricing=Pricing(
            base_price_krw=_fv(9900),
            billing_cycle=_fv(BillingCycle.MONTHLY),
            auto_renewal_enabled=_fv(True, pain_point_id="PRE-03"),
            auto_renewal_consent=_fv(ConsentMechanism.DEEMED_AGREED, pain_point_id="MID-02"),
            price_change_notice_days=_fv(30),
            price_change_notice_channels=_fv([NoticeChannel.EMAIL]),
        ),
        free_trial=FreeTrial(offered=_fv(False), duration_days=_fv(0), auto_convert_to_paid=_fv(False),
                             cancel_required_before_end=_fv(False), payment_method_required_upfront=_fv(False),
                             notice_before_conversion_days=_fv(0)),
        cancellation=Cancellation(method=_fv("online"), method_description=_fv(""), notice_period_days=_fv(0),
                                   penalty_present=_fv(False), penalty_description=_fv(""),
                                   proration_policy=_fv("no_refund"), blackout_periods=_fv([])),
        terms_changes=TermsChanges(notice_channels=_fv([NoticeChannel.EMAIL]), notice_lead_time_days=_fv(30),
                                    user_consent_mechanism=_fv(ConsentMechanism.DEEMED_AGREED),
                                    user_right_to_terminate_on_change=_fv(True), silent_acceptance_clause=_fv(True)),
        data_usage=DataUsage(collected_categories=_fv([]), third_party_sharing=_fv(False),
                              third_party_recipients=_fv([]), third_party_purposes=_fv([]),
                              retention_period_months=_fv(0), marketing_use=_fv(False),
                              marketing_consent=_fv(ConsentMechanism.OPT_OUT_AVAILABLE),
                              cross_border_transfer=_fv(False)),
        liability=Liability(service_disruption_compensation=_fv(False), compensation_description=_fv(""),
                             damages_cap_present=_fv(False), damages_cap_description=_fv(""),
                             force_majeure_scope=_fv(""), indirect_damages_excluded=_fv(False)),
        disputes=Disputes(governing_law=_fv(""), jurisdiction_clause=_fv(""),
                           arbitration_required=_fv(False), class_action_waiver=_fv(False)),
        unfair_clause_flags=["의사표시_의제"],
    )


async def test_summarize_risks_returns_top_clauses(httpx_mock, settings, sample_terms):
    fake_response = {
        "summary": "본 약관은 자동결제 + 의사표시 의제 조항으로 소비자 불이익 가능성이 있습니다.",
        "key_clauses": [
            {
                "title": "자동 갱신 + 무응답 동의 간주",
                "description": "이의 없으면 약관 변경 동의로 간주되며 자동 결제됩니다.",
                "risk_level": "high",
                "pain_point_id": "MID-02",
                "citation": {"page": 2, "quote": "이의 없으면 동의로 간주"},
            },
            {
                "title": "가격 인상 시 이메일 통지만 제공",
                "description": "30일 전 이메일 통지가 유일한 채널입니다. 이메일 미확인 시 인지 곤란.",
                "risk_level": "medium",
                "pain_point_id": "MID-01",
                "citation": {"page": 3, "quote": "30일 전 이메일로 통지"},
            },
        ],
    }
    httpx_mock.add_response(
        url=f"{settings.upstage_base_url}/chat/completions",
        json={"choices": [{"message": {"content": json.dumps(fake_response)}}]},
    )
    async with UpstageClient(settings) as client:
        result = await summarize_risks(client, terms=sample_terms)
    assert isinstance(result, SummaryResult)
    assert len(result.key_clauses) == 2
    assert isinstance(result.key_clauses[0], KeyClause)
    assert result.key_clauses[0].risk_level == "high"
    assert "의사표시 의제" in result.summary
