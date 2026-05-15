"""InsuranceTerms schema validation 테스트."""

from __future__ import annotations

from ai.schemas.common import Citation, FieldValue, Uncertainty
from ai.schemas.enums import (
    CancellationMethod,
    ConsentMechanism,
    InsuranceClaimMethod,
    NoticeChannel,
    PremiumCycle,
    RefundFormula,
)
from ai.schemas.insurance import (
    CancellationRefund,
    Claims,
    Coverage,
    Exclusions,
    InsuranceDataUsage,
    InsuranceDisputes,
    InsuranceTerms,
    Premium,
    Renewal,
)
from ai.schemas.subscription import TermsChanges


def _fv(value, page=1, quote="..."):
    """dict 반환 — see test_schemas_finance._fv for rationale."""
    if value is None:
        return {"value": None, "uncertainty": Uncertainty.NOT_SPECIFIED, "citation": None}
    return {
        "value": value,
        "uncertainty": Uncertainty.CONFIRMED,
        "citation": {"page": page, "quote": quote},
    }


def _build_insurance_terms() -> InsuranceTerms:
    return InsuranceTerms(
        service_name="삼성 실손의료보험",
        service_provider="삼성화재",
        extraction_date="2026-05-15",
        coverage=Coverage(
            insurance_type=_fv("실손의료보험"),
            covered_items=_fv(["입원 의료비", "통원 의료비", "처방조제비"]),
            total_coverage_limit_krw=_fv(50_000_000),
            per_event_limit_krw=_fv(50_000_000),
            coverage_description=_fv("국민건강보험 본인부담금 + 비급여 일부"),
        ),
        exclusions=Exclusions(
            exclusion_items=_fv(["미용 목적 수술", "임신·출산", "고지의무 위반"]),
            waiting_period_days=_fv(30),
            immunity_period_days=_fv(730),
            pre_existing_conditions_excluded=_fv(True),
        ),
        premium=Premium(
            payment_cycle=_fv(PremiumCycle.MONTHLY),
            base_premium_krw=_fv(15_000),
            premium_adjustment_description=_fv("3년 단위 갱신 시 손해율 반영"),
            payment_waiver_conditions=_fv("장해등급 50% 이상"),
        ),
        claims=Claims(
            claim_methods=_fv([InsuranceClaimMethod.ONLINE, InsuranceClaimMethod.PHONE]),
            claim_filing_deadline_years=_fv(3),
            payout_deadline_days=_fv(3),
            required_documents=_fv(["진단서", "진료비 영수증", "진료비 세부내역서"]),
            claim_denial_grounds=_fv(["고지의무 위반", "면책 사유 해당"]),
        ),
        cancellation_refund=CancellationRefund(
            cancellation_allowed=_fv(True),
            cancellation_method=_fv(CancellationMethod.PHONE),
            refund_formula=_fv(RefundFormula.SURRENDER_VALUE_TABLE),
            refund_description=_fv("해지환급금 표 기준; 가입 1년 미만은 환급금 없음"),
            cooling_off_days=_fv(15),
        ),
        renewal=Renewal(
            auto_renewal=_fv(True),
            renewal_premium_change_possible=_fv(True),
            renewal_refusal_grounds=_fv(["연령 80세 초과"]),
            renewal_description=_fv("3년 단위 자동 갱신; 보험료 손해율 반영 변경 가능"),
        ),
        terms_changes=TermsChanges(
            notice_channels=_fv([NoticeChannel.EMAIL, NoticeChannel.WEB_NOTICE]),
            notice_lead_time_days=_fv(30),
            user_consent_mechanism=_fv(ConsentMechanism.OPT_IN_EXPLICIT),
            user_right_to_terminate_on_change=_fv(True),
            silent_acceptance_clause=_fv(False),
        ),
        data_usage=InsuranceDataUsage(
            privacy_policy_externally_delegated=_fv(False),
            medical_data_collected=_fv(True),
            collected_categories=_fv(["주민등록번호", "진료기록", "처방내역"]),
            third_party_sharing=_fv(True),
            third_party_recipients=_fv(["의료기관", "재보험사"]),
            marketing_use=_fv(False),
            marketing_consent=_fv(ConsentMechanism.OPT_IN_EXPLICIT),
        ),
        disputes=InsuranceDisputes(
            governing_law=_fv("대한민국 법률"),
            jurisdiction_clause=_fv("계약자 주소지 관할법원"),
            financial_supervisor_complaint_channel=_fv(True),
            dispute_mediation_described=_fv(True),
        ),
        unfair_clause_flags=[],
    )


def test_insurance_terms_validates():
    terms = _build_insurance_terms()
    assert terms.domain == "insurance"
    assert terms.coverage.total_coverage_limit_krw.value == 50_000_000
    assert terms.claims.claim_filing_deadline_years.value == 3
    assert terms.data_usage.medical_data_collected.value is True


def test_insurance_terms_roundtrip_json():
    terms = _build_insurance_terms()
    data = terms.model_dump_json()
    restored = InsuranceTerms.model_validate_json(data)
    assert restored.service_provider == "삼성화재"
    assert restored.cancellation_refund.refund_formula.value == RefundFormula.SURRENDER_VALUE_TABLE


def test_insurance_terms_json_schema_has_sections():
    schema = InsuranceTerms.model_json_schema()
    props = schema["properties"]
    for section in (
        "coverage", "exclusions", "premium", "claims",
        "cancellation_refund", "renewal", "terms_changes",
        "data_usage", "disputes",
    ):
        assert section in props
