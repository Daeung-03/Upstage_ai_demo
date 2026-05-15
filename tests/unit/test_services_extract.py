import json

import pytest

from ai.schemas.common import Uncertainty
from ai.schemas.enums import BillingCycle, ConsentMechanism
from ai.schemas.subscription import SubscriptionTerms
from ai.services.extract import (
    _find_element_for_quote,
    extract_subscription,
    extract_subscription_with_voting,
)
from ai.services.parse import ParsedElement
from ai.services.settings import Settings
from ai.services.upstage import UpstageClient


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


def test_find_element_for_quote_skips_empty_text_elements():
    """회귀 가드: elem.text=='' 인 element가 첫 자리에 있어도 매칭되면 안 된다.

    이전 버그: step 3 의 `en in qn` 이 en=='' 일 때 항상 True 라 모든 quote 가
    첫 번째 빈 element 의 bbox 로 매핑되어, 다른 페이지/위치의 citation 들이
    전부 동일한 좌측 상단 헤더 좌표를 가지게 되었다.
    """
    elements = [
        # 빈 텍스트 (Upstage 응답이 content.text 가 항상 "" 인 경우)
        ParsedElement(id=0, page=1, category="header", text="", bbox=(0.0, 0.0, 0.1, 0.1)),
        ParsedElement(id=1, page=1, category="paragraph", text="", bbox=(0.2, 0.2, 0.3, 0.3)),
        # 진짜 매칭돼야 할 element
        ParsedElement(
            id=2, page=3, category="paragraph",
            text="구독 기간의 일부 또는 이용하지 않은 콘텐츠에 대한 환불은 제공되지 않습니다.",
            bbox=(0.5, 0.5, 0.9, 0.6),
        ),
    ]
    match = _find_element_for_quote("환불은 제공되지 않습니다.", page=3, elements=elements)
    assert match is not None
    assert match.id == 2
    assert match.bbox == (0.5, 0.5, 0.9, 0.6)


def test_find_element_for_quote_returns_none_when_all_empty():
    """매칭 후보가 전혀 없으면 잘못된 fallback 대신 None."""
    elements = [
        ParsedElement(id=0, page=1, category="header", text="", bbox=(0.0, 0.0, 0.1, 0.1)),
        ParsedElement(id=1, page=1, category="paragraph", text="", bbox=(0.2, 0.2, 0.3, 0.3)),
    ]
    assert _find_element_for_quote("어떤 문장이든", page=1, elements=elements) is None


def test_find_element_for_quote_rejects_short_reverse_substring():
    """회귀 가드 (C2): 짧은 element 가 긴 quote 의 substring 인 케이스에서 오매칭 차단.

    이전 버그: step 3 의 `en in qn` 방향이 길이 가드 없이 매칭돼, 4자 제목 element
    가 28자짜리 quote 와 매칭되며 bbox 가 제목 영역으로 attach 됨. 가드 후 MIN
    (16자) 미만의 element 는 reverse 방향에서 제외돼, anchor (step 4) 로 폴백.
    """
    elements = [
        # 짧은 제목 element — 이전엔 quote 에 "제3조" 가 포함됐다는 이유로 매칭
        ParsedElement(id=1, page=1, category="heading", text="제3조", bbox=(0.0, 0.0, 0.1, 0.1)),
        # 실제 본문 단락 — quote 의 prefix 가 여기 들어있으므로 anchor 폴백으로 잡힘
        ParsedElement(
            id=2, page=1, category="paragraph",
            text="제3조 (개인정보 보호) 회사는 사용자의 개인정보를 수집하고 보호합니다. 자세한 사항은 ...",
            bbox=(0.2, 0.2, 0.9, 0.4),
        ),
    ]
    quote = "제3조 (개인정보 보호) 회사는 사용자의 개인정보를 수집합니다."
    match = _find_element_for_quote(quote, page=1, elements=elements)
    assert match is not None
    # 짧은 제목 element(id=1) 가 아니라 실제 본문(id=2) 에 매칭돼야 함
    assert match.id == 2
    assert match.bbox == (0.2, 0.2, 0.9, 0.4)


def test_find_element_for_quote_still_matches_long_reverse_substring():
    """C2 가드가 *과보호*하지 않는지 확인: 충분히 긴 element 는 reverse 방향 매칭 유지.

    LLM 이 element.text 외에 추가 문구를 붙여 quote 를 확장한 정상 케이스.
    """
    elements = [
        ParsedElement(
            id=1, page=2, category="paragraph",
            text="구독은 결제 주기 종료일에 자동으로 갱신됩니다.",  # 24자 (>=16) → 가드 통과
            bbox=(0.1, 0.1, 0.9, 0.3),
        ),
    ]
    # quote 가 element.text 를 그대로 포함 + 추가 컨텍스트
    quote = "구독은 결제 주기 종료일에 자동으로 갱신됩니다. 사용자는 결제일 전까지 해지할 수 있습니다."
    match = _find_element_for_quote(quote, page=2, elements=elements)
    assert match is not None
    assert match.id == 1
