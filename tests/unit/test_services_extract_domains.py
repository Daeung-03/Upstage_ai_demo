"""Finance / Insurance 도메인 extract 진입점 단위 테스트.

OTT extract 와 동일한 패턴 — Solar Pro 3 응답을 mock 으로 주입하고 schema
검증 + bbox 후처리가 동작하는지 확인. 실제 API 호출 없음.
"""

import json

import pytest

from ai.schemas.finance import FinanceTerms
from ai.schemas.insurance import InsuranceTerms
from ai.services.extract import (
    extract_finance,
    extract_finance_with_voting,
    extract_insurance,
    extract_insurance_with_voting,
)
from ai.services.parse import ParsedElement
from ai.services.settings import Settings
from ai.services.upstage import UpstageClient


@pytest.fixture
def settings(sample_api_key, sample_base_url):
    return Settings(upstage_api_key=sample_api_key, upstage_base_url=sample_base_url)


def _ns(field_names):
    return {n: {"value": None, "uncertainty": "not_specified", "citation": None} for n in field_names}


@pytest.fixture
def fake_finance_payload():
    return {
        "schema_version": "0.1.0",
        "domain": "finance",
        "service_name": "Toss",
        "service_provider": "비바리퍼블리카",
        "extraction_date": "2026-05-15",
        "fees": {
            "has_transaction_fees": {"value": True, "uncertainty": "confirmed",
                                      "citation": {"page": 2, "quote": "송금 수수료가 부과될 수 있습니다"}},
            "transaction_fees_description": _ns(["transaction_fees_description"])["transaction_fees_description"],
            "fee_change_notice_days": {"value": 30, "uncertainty": "confirmed",
                                        "citation": {"page": 4, "quote": "30일 전 통지"}},
            "fee_change_notice_channels": {"value": ["email"], "uncertainty": "confirmed",
                                            "citation": {"page": 4, "quote": "이메일로 통지"}},
        },
        "transaction_limits": _ns([
            "per_transaction_limit_krw", "daily_limit_krw",
            "monthly_limit_krw", "limits_description",
        ]),
        "liability_allocation": {
            "responsibility_pattern": {"value": "user_gross_negligence_only", "uncertainty": "confirmed",
                                        "citation": {"page": 7, "quote": "회원의 고의 또는 중과실"}},
            "user_burden_description": _ns(["user_burden_description"])["user_burden_description"],
            "company_compensation_scope": _ns(["company_compensation_scope"])["company_compensation_scope"],
            "user_notification_deadline_hours": _ns(["user_notification_deadline_hours"])["user_notification_deadline_hours"],
            "company_response_deadline_days": _ns(["company_response_deadline_days"])["company_response_deadline_days"],
        },
        "deposit_protection": {
            "status": {"value": "separately_deposited", "uncertainty": "confirmed",
                        "citation": {"page": 5, "quote": "선불충전금은 별도 예치됩니다"}},
            "description": _ns(["description"])["description"],
            "coverage_limit_krw": _ns(["coverage_limit_krw"])["coverage_limit_krw"],
        },
        "account_termination": _ns([
            "method", "method_description",
            "dormancy_period_months", "balance_handling_description",
        ]),
        "terms_changes": _ns([
            "notice_channels", "notice_lead_time_days", "user_consent_mechanism",
            "user_right_to_terminate_on_change", "silent_acceptance_clause",
        ]),
        "data_usage": {
            "privacy_policy_externally_delegated": {"value": True, "uncertainty": "confirmed",
                                                      "citation": {"page": 8, "quote": "별도 개인정보처리방침에 따릅니다"}},
            **_ns([
                "collected_categories", "third_party_sharing", "third_party_recipients",
                "cross_border_transfer", "marketing_use", "marketing_consent",
            ]),
        },
        "disputes": _ns([
            "governing_law", "jurisdiction_clause",
            "financial_supervisor_complaint_channel", "complaint_channel_description",
        ]),
        "unfair_clause_flags": [],
    }


@pytest.fixture
def fake_insurance_payload():
    return {
        "schema_version": "0.1.0",
        "domain": "insurance",
        "service_name": "삼성 실손의료보험",
        "service_provider": "삼성화재",
        "extraction_date": "2026-05-15",
        "coverage": {
            "insurance_type": {"value": "실손의료보험", "uncertainty": "confirmed",
                                "citation": {"page": 1, "quote": "실손의료보험 약관"}},
            "covered_items": {"value": ["입원 의료비"], "uncertainty": "confirmed",
                              "citation": {"page": 3, "quote": "입원 의료비를 보상"}},
            "total_coverage_limit_krw": _ns(["total_coverage_limit_krw"])["total_coverage_limit_krw"],
            "per_event_limit_krw": _ns(["per_event_limit_krw"])["per_event_limit_krw"],
            "coverage_description": _ns(["coverage_description"])["coverage_description"],
        },
        "exclusions": _ns([
            "exclusion_items", "waiting_period_days", "immunity_period_days",
            "pre_existing_conditions_excluded",
        ]),
        "premium": _ns([
            "payment_cycle", "base_premium_krw",
            "premium_adjustment_description", "payment_waiver_conditions",
        ]),
        "claims": {
            "claim_methods": _ns(["claim_methods"])["claim_methods"],
            "claim_filing_deadline_years": {"value": 3, "uncertainty": "inferred",
                                              "citation": {"page": 15, "quote": "보험법 §662 기준"}},
            "payout_deadline_days": _ns(["payout_deadline_days"])["payout_deadline_days"],
            "required_documents": _ns(["required_documents"])["required_documents"],
            "claim_denial_grounds": _ns(["claim_denial_grounds"])["claim_denial_grounds"],
        },
        "cancellation_refund": _ns([
            "cancellation_allowed", "cancellation_method", "refund_formula",
            "refund_description", "cooling_off_days",
        ]),
        "renewal": _ns([
            "auto_renewal", "renewal_premium_change_possible",
            "renewal_refusal_grounds", "renewal_description",
        ]),
        "terms_changes": _ns([
            "notice_channels", "notice_lead_time_days", "user_consent_mechanism",
            "user_right_to_terminate_on_change", "silent_acceptance_clause",
        ]),
        "data_usage": _ns([
            "privacy_policy_externally_delegated", "medical_data_collected",
            "collected_categories", "third_party_sharing", "third_party_recipients",
            "marketing_use", "marketing_consent",
        ]),
        "disputes": _ns([
            "governing_law", "jurisdiction_clause",
            "financial_supervisor_complaint_channel", "dispute_mediation_described",
        ]),
        "unfair_clause_flags": [],
    }


async def test_extract_finance_validates_and_enriches_bbox(
    httpx_mock, settings, fake_finance_payload
):
    httpx_mock.add_response(
        url=f"{settings.upstage_base_url}/chat/completions",
        json={"choices": [{"message": {"content": json.dumps(fake_finance_payload)}}]},
    )
    elements = [
        ParsedElement(id=1, page=7, category="paragraph",
                       text="회원의 고의 또는 중과실로 인한 손해", bbox=(0.1, 0.2, 0.5, 0.25)),
    ]
    async with UpstageClient(settings) as client:
        terms = await extract_finance(
            client,
            parsed_markdown="(toss markdown)",
            parsed_elements=elements,
            service_name="Toss",
            service_provider="비바리퍼블리카",
        )
    assert isinstance(terms, FinanceTerms)
    assert terms.fees.has_transaction_fees.value is True
    # bbox 후처리 — liability_allocation.responsibility_pattern.citation 의 page 7 quote 가 매칭됨
    assert terms.liability_allocation.responsibility_pattern.citation.bbox == (0.1, 0.2, 0.5, 0.25)


async def test_extract_finance_with_voting_n1_short_circuits(
    httpx_mock, settings, fake_finance_payload
):
    httpx_mock.add_response(
        url=f"{settings.upstage_base_url}/chat/completions",
        json={"choices": [{"message": {"content": json.dumps(fake_finance_payload)}}]},
    )
    async with UpstageClient(settings) as client:
        terms = await extract_finance_with_voting(
            client,
            parsed_markdown="(toss markdown)",
            parsed_elements=[],
            service_name="Toss",
            service_provider="비바리퍼블리카",
            n=1,
        )
    # N=1 이면 voting 우회 → extract_finance 한 번 호출
    assert isinstance(terms, FinanceTerms)
    assert len(httpx_mock.get_requests()) == 1


async def test_extract_insurance_validates(httpx_mock, settings, fake_insurance_payload):
    httpx_mock.add_response(
        url=f"{settings.upstage_base_url}/chat/completions",
        json={"choices": [{"message": {"content": json.dumps(fake_insurance_payload)}}]},
    )
    async with UpstageClient(settings) as client:
        terms = await extract_insurance(
            client,
            parsed_markdown="(보험 약관 markdown)",
            parsed_elements=[],
            service_name="삼성 실손의료보험",
            service_provider="삼성화재",
        )
    assert isinstance(terms, InsuranceTerms)
    assert terms.coverage.insurance_type.value == "실손의료보험"
    assert terms.claims.claim_filing_deadline_years.value == 3


async def test_extract_insurance_with_voting_two_runs(
    httpx_mock, settings, fake_insurance_payload
):
    httpx_mock.add_response(
        url=f"{settings.upstage_base_url}/chat/completions",
        json={"choices": [{"message": {"content": json.dumps(fake_insurance_payload)}}]},
    )
    httpx_mock.add_response(
        url=f"{settings.upstage_base_url}/chat/completions",
        json={"choices": [{"message": {"content": json.dumps(fake_insurance_payload)}}]},
    )
    async with UpstageClient(settings) as client:
        terms = await extract_insurance_with_voting(
            client,
            parsed_markdown="(보험 약관 markdown)",
            parsed_elements=[],
            service_name="삼성 실손의료보험",
            service_provider="삼성화재",
            n=2,
        )
    assert isinstance(terms, InsuranceTerms)
    # 두 run 이 동일하므로 voted 결과도 동일
    assert terms.coverage.insurance_type.value == "실손의료보험"
    assert len(httpx_mock.get_requests()) == 2


# === AI 도메인 ===

from ai.schemas.ai_terms import AITerms
from ai.services.extract import extract_ai_terms, extract_ai_terms_with_voting


@pytest.fixture
def fake_ai_payload():
    return {
        "schema_version": "0.1.0",
        "domain": "ai",
        "service_name": "Claude",
        "service_provider": "Anthropic",
        "extraction_date": "2026-05-16",
        "service_tier": {
            "free_tier_offered": {"value": True, "uncertainty": "confirmed",
                                   "citation": {"page": 1, "quote": "Claude Free is permanently free"}},
            **_ns(["free_tier_description", "paid_tier_offered"]),
            "pricing_externally_delegated": {"value": True, "uncertainty": "confirmed",
                                              "citation": {"page": 2, "quote": "see Model Pricing Page"}},
            **_ns(["base_price_description", "billing_cycle", "auto_renewal_enabled"]),
        },
        "training_data_use": {
            "input_used_for_training": {"value": "opt_out_available", "uncertainty": "confirmed",
                                         "citation": {"page": 7, "quote": "Inputs may be used... unless you opt out"}},
            **_ns(["output_used_for_training", "training_use_description"]),
            "opt_out_available": {"value": True, "uncertainty": "confirmed",
                                   "citation": {"page": 7, "quote": "opt out via privacy settings"}},
            **_ns(["opt_out_mechanism_description"]),
        },
        "output_and_ip": {
            "output_ip_ownership": {"value": "user", "uncertainty": "confirmed",
                                     "citation": {"page": 8, "quote": "You retain ownership of Output"}},
            **_ns(["output_use_restrictions", "user_verification_obligation", "accuracy_disclaimer"]),
        },
        "usage_limits": _ns([
            "rate_limit_described", "rate_limit_description",
            "quota_described", "api_key_management_described",
            "api_key_security_user_burden",
        ]),
        "prohibited_use": _ns([
            "illegal_content_prohibited", "harmful_content_prohibited",
            "high_risk_use_prohibited", "prohibited_use_categories",
        ]),
        "export_and_regional": _ns([
            "export_control_clause", "restricted_regions", "governing_law_foreign",
        ]),
        "cancellation": _ns([
            "cancellation_method", "cancellation_description",
            "korea_residents_7day_refund", "non_refundable_clause",
            "refund_policy_description",
        ]),
        "terms_changes": _ns([
            "notice_channels", "notice_lead_time_days", "user_consent_mechanism",
            "user_right_to_terminate_on_change", "silent_acceptance_clause",
        ]),
        "data_usage": _ns([
            "privacy_policy_externally_delegated", "collected_categories",
            "third_party_sharing", "cross_border_transfer",
            "marketing_use", "marketing_consent",
        ]),
        "liability": _ns([
            "indirect_damages_excluded", "damages_cap_present", "damages_cap_description",
            "service_disruption_compensation", "compensation_description",
        ]),
        "disputes": _ns([
            "governing_law", "jurisdiction_clause",
            "arbitration_required", "class_action_waiver",
        ]),
        "unfair_clause_flags": ["AI 학습 데이터 활용"],
    }


async def test_extract_ai_terms_validates(httpx_mock, settings, fake_ai_payload):
    httpx_mock.add_response(
        url=f"{settings.upstage_base_url}/chat/completions",
        json={"choices": [{"message": {"content": json.dumps(fake_ai_payload)}}]},
    )
    elements = [
        ParsedElement(id=1, page=7, category="paragraph",
                       text="Inputs may be used... unless you opt out", bbox=(0.1, 0.2, 0.5, 0.25)),
    ]
    async with UpstageClient(settings) as client:
        terms = await extract_ai_terms(
            client,
            parsed_markdown="(AI 약관 markdown)",
            parsed_elements=elements,
            service_name="Claude",
            service_provider="Anthropic",
        )
    assert isinstance(terms, AITerms)
    assert terms.service_tier.free_tier_offered.value is True
    assert terms.training_data_use.opt_out_available.value is True
    # bbox enrich 검증
    assert terms.training_data_use.input_used_for_training.citation.bbox == (0.1, 0.2, 0.5, 0.25)


async def test_extract_ai_terms_with_voting_n2(httpx_mock, settings, fake_ai_payload):
    httpx_mock.add_response(
        url=f"{settings.upstage_base_url}/chat/completions",
        json={"choices": [{"message": {"content": json.dumps(fake_ai_payload)}}]},
    )
    httpx_mock.add_response(
        url=f"{settings.upstage_base_url}/chat/completions",
        json={"choices": [{"message": {"content": json.dumps(fake_ai_payload)}}]},
    )
    async with UpstageClient(settings) as client:
        terms = await extract_ai_terms_with_voting(
            client,
            parsed_markdown="(AI 약관 markdown)",
            parsed_elements=[],
            service_name="Claude",
            service_provider="Anthropic",
            n=2,
        )
    assert isinstance(terms, AITerms)
    assert "AI 학습 데이터 활용" in terms.unfair_clause_flags
    assert len(httpx_mock.get_requests()) == 2
