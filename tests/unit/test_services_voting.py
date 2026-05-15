"""voting.py 단위 테스트 — 필드별 majority voting 로직 검증."""

from __future__ import annotations

import pytest

from ai.schemas.common import Citation, FieldValue, Uncertainty
from ai.schemas.enums import (
    BillingCycle, CancellationMethod, ConsentMechanism, NoticeChannel, ProrationPolicy,
)
from ai.schemas.subscription import (
    Cancellation, DataUsage, Disputes, FreeTrial, Liability,
    Pricing, SubscriptionTerms, TermsChanges,
)
from ai.services.voting import _scalar_key, _vote_field, vote_subscription_terms


def _fv(value, page=1, quote="..."):
    """_vote_field 가 직접 받는 FieldValue 객체 — .value 등 attr 접근 필요."""
    return FieldValue(
        value=value,
        uncertainty=Uncertainty.CONFIRMED if value is not None else Uncertainty.NOT_SPECIFIED,
        citation=Citation(page=page, quote=quote) if value is not None else None,
    )


def _fv_dict(value, page=1, quote="..."):
    """SubscriptionTerms 의 FieldValue[T] 필드 채울 때 — Pydantic v2 generic 은
    invariant 라 FieldValue 객체로 넘기면 검증 실패. dict 로 넘기면 coerce 됨."""
    if value is None:
        return {"value": None, "uncertainty": "not_specified", "citation": None}
    return {"value": value, "uncertainty": "confirmed",
            "citation": {"page": page, "quote": quote}}


# ============ _vote_field 단위 ============


def test_vote_field_majority_wins():
    fvs = [_fv(True), _fv(True), _fv(False)]
    assert _vote_field(fvs).value is True


def test_vote_field_prefers_non_null_over_null():
    # 같은 빈도라도 non-null 우선
    fvs = [_fv(30), _fv(None), _fv(None)]
    assert _vote_field(fvs).value == 30


def test_vote_field_all_null_returns_first():
    fvs = [_fv(None), _fv(None), _fv(None)]
    assert _vote_field(fvs).value is None


def test_vote_field_enum_values_grouped_correctly():
    fvs = [
        _fv(ConsentMechanism.DEEMED_AGREED),
        _fv(ConsentMechanism.OPT_OUT_AVAILABLE),
        _fv(ConsentMechanism.DEEMED_AGREED),
    ]
    assert _vote_field(fvs).value == ConsentMechanism.DEEMED_AGREED


def test_vote_field_lists_compared_as_sets():
    # 같은 원소 다른 순서는 같은 것으로 카운트
    fvs = [
        _fv(["email", "sms"]),
        _fv(["sms", "email"]),
        _fv(["email"]),
    ]
    voted = _vote_field(fvs)
    # 첫 두 개가 같은 카테고리, 그게 다수
    assert sorted(voted.value) == ["email", "sms"]


def test_vote_field_lists_of_enums_normalized_via_value():
    """list 안의 enum 원소도 .value로 비교 — 'email' string과 NoticeChannel.EMAIL이 같은 것으로 인식."""
    fvs = [
        _fv([NoticeChannel.EMAIL, NoticeChannel.SMS]),  # enum form
        _fv(["email", "sms"]),                            # plain str form (e.g. from JSON dump)
        _fv([NoticeChannel.EMAIL]),                       # different content
    ]
    voted = _vote_field(fvs)
    # 첫 두 개는 의미적으로 같은 list — voting 시 다수가 되어야 함
    assert sorted([_scalar_key(x) for x in voted.value]) == ["email", "sms"]


def test_vote_field_empty_list_can_be_majority():
    """`[]` 도 의미 있는 confirmed 값일 수 있음 (예: blackout_periods=[] = 해지 불가 기간 없음).
    다수가 빈 list면 그것이 winning value여야 함."""
    fvs = [
        _fv([]),         # confirmed empty list
        _fv([]),
        _fv(["whenever"]),
    ]
    voted = _vote_field(fvs)
    assert voted.value == []  # 다수가 [] 이므로 [] 이 winning


def test_vote_field_empty_string_can_be_majority():
    """빈 문자열도 동등 — penalty_description='' (위약금 없음 명시) 같은 케이스."""
    fvs = [
        _fv(""),
        _fv(""),
        _fv("위약금 30%"),
    ]
    voted = _vote_field(fvs)
    assert voted.value == ""


def test_vote_field_preserves_citation_from_winning_run():
    fvs = [
        FieldValue(value=True, uncertainty=Uncertainty.CONFIRMED,
                    citation=Citation(page=2, quote="winning citation")),
        FieldValue(value=False, uncertainty=Uncertainty.CONFIRMED,
                    citation=Citation(page=99, quote="losing citation")),
        FieldValue(value=True, uncertainty=Uncertainty.CONFIRMED,
                    citation=Citation(page=2, quote="another winning")),
    ]
    voted = _vote_field(fvs)
    assert voted.value is True
    assert voted.citation is not None
    assert voted.citation.quote == "winning citation"


# ============ vote_subscription_terms 통합 ============


def _build_terms(
    auto_renewal_consent: ConsentMechanism,
    notice_days: int | None,
    flags: list[str] | None = None,
) -> SubscriptionTerms:
    # SubscriptionTerms 필드는 _fv_dict (Pydantic v2 generic invariant 회피용 dict)
    return SubscriptionTerms(
        service_name="Netflix", service_provider="N", extraction_date="2026-05-13",
        pricing=Pricing(
            base_price_krw=_fv_dict(None),
            billing_cycle=_fv_dict(BillingCycle.MONTHLY),
            auto_renewal_enabled=_fv_dict(True),
            auto_renewal_consent=_fv_dict(auto_renewal_consent),
            price_change_notice_days=_fv_dict(notice_days),
            price_change_notice_channels=_fv_dict([NoticeChannel.EMAIL]),
        ),
        free_trial=FreeTrial(offered=_fv_dict(False), duration_days=_fv_dict(0),
                              auto_convert_to_paid=_fv_dict(False), cancel_required_before_end=_fv_dict(False),
                              payment_method_required_upfront=_fv_dict(False),
                              notice_before_conversion_days=_fv_dict(0)),
        cancellation=Cancellation(method=_fv_dict(CancellationMethod.ONLINE),
                                   method_description=_fv_dict(""), notice_period_days=_fv_dict(0),
                                   penalty_present=_fv_dict(False), penalty_description=_fv_dict(""),
                                   proration_policy=_fv_dict(ProrationPolicy.NO_REFUND),
                                   blackout_periods=_fv_dict([])),
        terms_changes=TermsChanges(notice_channels=_fv_dict([NoticeChannel.EMAIL]),
                                    notice_lead_time_days=_fv_dict(30),
                                    user_consent_mechanism=_fv_dict(ConsentMechanism.DEEMED_AGREED),
                                    user_right_to_terminate_on_change=_fv_dict(True),
                                    silent_acceptance_clause=_fv_dict(True)),
        data_usage=DataUsage(collected_categories=_fv_dict([]), third_party_sharing=_fv_dict(False),
                              third_party_recipients=_fv_dict([]), third_party_purposes=_fv_dict([]),
                              retention_period_months=_fv_dict(0), marketing_use=_fv_dict(False),
                              marketing_consent=_fv_dict(ConsentMechanism.OPT_OUT_AVAILABLE),
                              cross_border_transfer=_fv_dict(False)),
        liability=Liability(service_disruption_compensation=_fv_dict(False), compensation_description=_fv_dict(""),
                             damages_cap_present=_fv_dict(False), damages_cap_description=_fv_dict(""),
                             force_majeure_scope=_fv_dict(""), indirect_damages_excluded=_fv_dict(False)),
        disputes=Disputes(governing_law=_fv_dict("대한민국"), jurisdiction_clause=_fv_dict("서울"),
                           arbitration_required=_fv_dict(False), class_action_waiver=_fv_dict(False)),
        unfair_clause_flags=flags or [],
    )


def test_vote_subscription_terms_picks_majority_per_field():
    """3개 runs 중 2개가 OPT_OUT, 1개가 DEEMED → OPT_OUT 이김."""
    runs = [
        _build_terms(ConsentMechanism.OPT_OUT_AVAILABLE, notice_days=30),
        _build_terms(ConsentMechanism.OPT_OUT_AVAILABLE, notice_days=None),
        _build_terms(ConsentMechanism.DEEMED_AGREED, notice_days=None),
    ]
    voted = vote_subscription_terms(runs)
    # auto_renewal_consent: OPT_OUT 2회 > DEEMED 1회
    assert voted.pricing.auto_renewal_consent.value == ConsentMechanism.OPT_OUT_AVAILABLE
    # price_change_notice_days: 30 1회 > None 2회 (non-null 우선)
    assert voted.pricing.price_change_notice_days.value == 30


def test_vote_subscription_terms_unions_unfair_flags():
    """한 번이라도 flag 검출되면 voted 결과에 포함 (union)."""
    runs = [
        _build_terms(ConsentMechanism.OPT_OUT_AVAILABLE, notice_days=30, flags=["의사표시_의제"]),
        _build_terms(ConsentMechanism.OPT_OUT_AVAILABLE, notice_days=30, flags=[]),
        _build_terms(ConsentMechanism.OPT_OUT_AVAILABLE, notice_days=30, flags=["면책/손배_제한"]),
    ]
    voted = vote_subscription_terms(runs)
    assert set(voted.unfair_clause_flags) == {"의사표시_의제", "면책/손배_제한"}


def test_vote_subscription_terms_single_run_returns_input():
    runs = [_build_terms(ConsentMechanism.DEEMED_AGREED, notice_days=30)]
    voted = vote_subscription_terms(runs)
    assert voted.pricing.auto_renewal_consent.value == ConsentMechanism.DEEMED_AGREED


def test_vote_subscription_terms_empty_raises():
    with pytest.raises(ValueError, match="empty"):
        vote_subscription_terms([])


# ============ 폴리모픽 vote_terms — Finance/Insurance ============


def test_vote_terms_works_on_finance_terms():
    """FinanceTerms 3개를 폴리모픽 vote_terms 로 합치고 sub-model 별 majority 확인."""
    from ai.schemas.enums import (
        DepositProtectionStatus, FraudResponsibilityPattern,
    )
    from ai.services.voting import vote_terms
    from tests.unit.test_schemas_finance import _build_finance_terms

    a = _build_finance_terms()
    b = _build_finance_terms()
    c = _build_finance_terms()
    # b 만 다른 책임분배 패턴 → 다수결은 a/c 의 USER_GROSS_NEGLIGENCE_ONLY
    b.liability_allocation.responsibility_pattern = _fv(
        FraudResponsibilityPattern.COMPANY_UNLIMITED
    )
    # c 의 deposit_protection.status 를 다르게 바꿔도 a/b 가 동일하면 a/b 가 이김
    c.deposit_protection.status = _fv(DepositProtectionStatus.PROTECTED)
    # flag union 동작 확인
    a.unfair_clause_flags = ["의사표시_의제"]
    b.unfair_clause_flags = ["면책_손배_제한"]
    c.unfair_clause_flags = ["의사표시_의제"]

    voted = vote_terms([a, b, c])

    assert (
        voted.liability_allocation.responsibility_pattern.value
        == FraudResponsibilityPattern.USER_GROSS_NEGLIGENCE_ONLY
    )
    assert (
        voted.deposit_protection.status.value
        == DepositProtectionStatus.SEPARATELY_DEPOSITED  # a/b 다수
    )
    assert set(voted.unfair_clause_flags) == {"의사표시_의제", "면책_손배_제한"}


def test_vote_terms_works_on_insurance_terms():
    from ai.schemas.enums import RefundFormula
    from ai.services.voting import vote_terms
    from tests.unit.test_schemas_insurance import _build_insurance_terms

    a = _build_insurance_terms()
    b = _build_insurance_terms()
    c = _build_insurance_terms()
    # 2 vs 1 분기
    b.cancellation_refund.refund_formula = _fv(RefundFormula.PROPORTIONAL)
    c.coverage.total_coverage_limit_krw = _fv(30_000_000)

    voted = vote_terms([a, b, c])

    # refund_formula: a/c = SURRENDER_VALUE_TABLE 다수
    assert (
        voted.cancellation_refund.refund_formula.value
        == RefundFormula.SURRENDER_VALUE_TABLE
    )
    # total_coverage_limit_krw: a/b = 50M 다수
    assert voted.coverage.total_coverage_limit_krw.value == 50_000_000


def test_vote_terms_preserves_metadata_scalars():
    """root model 의 str/None 스칼라 메타데이터는 첫 번째 결과 그대로 보존."""
    from ai.services.voting import vote_terms
    from tests.unit.test_schemas_finance import _build_finance_terms

    a = _build_finance_terms(service_name="Toss")
    b = _build_finance_terms(service_name="Toss")
    # 다른 service_name 으로 바꿔도 base 의 값 유지 (메타데이터는 voting 대상 아님)
    b.service_name = "DIFFERENT"

    voted = vote_terms([a, b])
    assert voted.service_name == "Toss"
    assert voted.extraction_date == "2026-05-15"
