from fastapi.testclient import TestClient

from app.main import app
from schemas.common import Citation, FieldValue, Uncertainty
from schemas.enums import BillingCycle, ConsentMechanism, NoticeChannel
from schemas.subscription import (
    Cancellation, DataUsage, Disputes, FreeTrial, Liability,
    Pricing, SubscriptionTerms, TermsChanges,
)
from services.pipeline import AnalysisResult, StageTiming, StageUsage
from services.summarize import KeyClause, KeyClauseCitation


def _fv(v, page=1, quote="..."):
    return FieldValue(value=v, uncertainty=Uncertainty.CONFIRMED, citation=Citation(page=page, quote=quote))


def _fake_result() -> AnalysisResult:
    terms = SubscriptionTerms(
        service_name="TestStream", service_provider="TestCo", extraction_date="2026-05-13T00:00:00Z",
        pricing=Pricing(base_price_krw=_fv(9900), billing_cycle=_fv(BillingCycle.MONTHLY),
                         auto_renewal_enabled=_fv(True),
                         auto_renewal_consent=_fv(ConsentMechanism.OPT_OUT_AVAILABLE),
                         price_change_notice_days=_fv(30),
                         price_change_notice_channels=_fv([NoticeChannel.EMAIL])),
        free_trial=FreeTrial(offered=_fv(False), duration_days=_fv(0), auto_convert_to_paid=_fv(False),
                              cancel_required_before_end=_fv(False), payment_method_required_upfront=_fv(False),
                              notice_before_conversion_days=_fv(0)),
        cancellation=Cancellation(method=_fv("online"), method_description=_fv(""), notice_period_days=_fv(0),
                                   penalty_present=_fv(False), penalty_description=_fv(""),
                                   proration_policy=_fv("no_refund"), blackout_periods=_fv([])),
        terms_changes=TermsChanges(notice_channels=_fv([NoticeChannel.EMAIL]), notice_lead_time_days=_fv(30),
                                    user_consent_mechanism=_fv(ConsentMechanism.OPT_OUT_AVAILABLE),
                                    user_right_to_terminate_on_change=_fv(True),
                                    silent_acceptance_clause=_fv(False)),
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
    )
    clause = KeyClause(title="자동갱신", description="...", risk_level="high",
                       pain_point_id="MID-02", citation=KeyClauseCitation(page=1, quote="..."))
    return AnalysisResult(
        terms=terms, summary="요약", key_clauses=[clause], ungrounded_clauses=[],
        grounded=True,
        timings=[StageTiming(stage="parse", seconds=0.1)],
        usage=[StageUsage(stage="parse", calls=1, pages=3),
               StageUsage(stage="extract", calls=1, prompt_tokens=1000, total_tokens=1500)],
    )


def test_analyze_endpoint_happy_path(monkeypatch):
    async def fake_run_pipeline(*args, **kwargs):
        return _fake_result()

    monkeypatch.setattr("app.routes.terms.run_pipeline", fake_run_pipeline)
    monkeypatch.setenv("UPSTAGE_API_KEY", "test-key")

    client = TestClient(app)
    response = client.post(
        "/v1/terms/analyze",
        files={"file": ("netflix.pdf", b"%PDF fake", "application/pdf")},
        data={"service_name": "Netflix", "service_provider": "Netflix Inc."},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["summary"] == "요약"
    assert body["grounded"] is True
    assert len(body["key_clauses"]) == 1
    assert body["terms"]["service_name"] == "TestStream"
    # usage 필드가 timings 옆에 노출되는지
    assert len(body["usage"]) == 2
    assert body["usage"][0]["stage"] == "parse"
    assert body["usage"][0]["pages"] == 3
    assert body["usage"][1]["total_tokens"] == 1500


def test_analyze_endpoint_missing_file_returns_422():
    client = TestClient(app)
    response = client.post(
        "/v1/terms/analyze",
        data={"service_name": "Netflix", "service_provider": "Netflix Inc."},
    )
    assert response.status_code == 422
