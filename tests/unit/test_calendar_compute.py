"""calendar_service.compute_calendar_events 단위 테스트.

SubscriptionTerms + subscribed_at 으로부터 결정론적 캘린더 이벤트 생성. LLM 호출 없음.
"""
from __future__ import annotations

from datetime import date

import pytest
from pydantic import BaseModel

from ai.schemas.common import Citation, FieldValue, Uncertainty
from ai.schemas.enums import BillingCycle
from app.models.enums import EventType
from app.services.calendar_service import _add_months, compute_calendar_events


FVBool = FieldValue[bool]
FVInt = FieldValue[int]
FVCycle = FieldValue[BillingCycle]


def _fv_bool(value: bool | None) -> FVBool:
    return FVBool(value=value, uncertainty=Uncertainty.CONFIRMED, citation=None)


def _fv_int(value: int | None) -> FVInt:
    return FVInt(value=value, uncertainty=Uncertainty.CONFIRMED, citation=None)


def _fv_cycle(value: BillingCycle | None) -> FVCycle:
    return FVCycle(value=value, uncertainty=Uncertainty.CONFIRMED, citation=None)


class _FreeTrial(BaseModel):
    offered: FVBool
    duration_days: FVInt
    cancel_required_before_end: FVBool
    notice_before_conversion_days: FVInt


class _Pricing(BaseModel):
    billing_cycle: FVCycle


class _Terms(BaseModel):
    pricing: _Pricing
    free_trial: _FreeTrial


def _ev_types(events: list[dict]) -> list[str]:
    return [e["event_type"] for e in events]


def _ev_date(events: list[dict], etype: str) -> str:
    for e in events:
        if e["event_type"] == etype:
            return e["date"]
    raise AssertionError(f"event type {etype} not in {events}")


# ── _add_months ──────────────────────────────────────────


def test_add_months_basic():
    assert _add_months(date(2026, 1, 15), 1) == date(2026, 2, 15)
    assert _add_months(date(2026, 1, 15), 3) == date(2026, 4, 15)
    assert _add_months(date(2026, 1, 15), 12) == date(2027, 1, 15)


def test_add_months_clamps_end_of_month():
    """1/31 + 1month 는 2/28 또는 2/29 로 잘려야."""
    assert _add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert _add_months(date(2028, 1, 31), 1) == date(2028, 2, 29)  # leap


# ── compute_calendar_events ──────────────────────────────


def _make_terms(
    *, offered=False, duration=0, cancel_required=False, notice_days=0,
    cycle: BillingCycle | None = None,
) -> _Terms:
    return _Terms(
        pricing=_Pricing(billing_cycle=_fv_cycle(cycle)),
        free_trial=_FreeTrial(
            offered=_fv_bool(offered),
            duration_days=_fv_int(duration),
            cancel_required_before_end=_fv_bool(cancel_required),
            notice_before_conversion_days=_fv_int(notice_days),
        ),
    )


def test_compute_returns_empty_when_no_subscribed_at():
    terms = _make_terms(offered=True, duration=30, cycle=BillingCycle.MONTHLY)
    assert compute_calendar_events(terms, None) == []


def test_compute_returns_empty_when_terms_none():
    assert compute_calendar_events(None, date(2026, 5, 15)) == []


def test_compute_subscribed_at_only_when_no_trial_no_cycle():
    """무료 체험 없고 결제 주기도 없으면 SUBSCRIBED_AT 만."""
    terms = _make_terms(offered=False, cycle=None)
    events = compute_calendar_events(terms, date(2026, 5, 15))
    assert _ev_types(events) == [EventType.SUBSCRIBED_AT.value]
    assert _ev_date(events, EventType.SUBSCRIBED_AT.value) == "2026-05-15"


def test_compute_free_trial_end_only_when_no_cancel_required():
    """무료 체험 있되 사전 해지 의무 없으면 TRIAL_END 만 (CANCEL_DEADLINE 없음)."""
    terms = _make_terms(offered=True, duration=30, cancel_required=False)
    events = compute_calendar_events(terms, date(2026, 5, 15))
    types = _ev_types(events)
    assert EventType.SUBSCRIBED_AT.value in types
    assert EventType.TRIAL_END.value in types
    assert EventType.CANCEL_DEADLINE.value not in types
    assert _ev_date(events, EventType.TRIAL_END.value) == "2026-06-14"


def test_compute_cancel_deadline_when_required_with_notice_days():
    """사전 해지 의무 + 통지 기간이 있으면 CANCEL_DEADLINE = TRIAL_END - notice."""
    terms = _make_terms(offered=True, duration=30,
                        cancel_required=True, notice_days=3)
    events = compute_calendar_events(terms, date(2026, 5, 15))
    assert _ev_date(events, EventType.TRIAL_END.value) == "2026-06-14"
    # 3일 사전 → 6/11
    assert _ev_date(events, EventType.CANCEL_DEADLINE.value) == "2026-06-11"


def test_compute_cancel_deadline_defaults_lead_to_one_day_when_unknown():
    """사전 해지 의무 True 인데 통지 일수 미지정 → 보수적으로 하루 전."""
    terms = _make_terms(offered=True, duration=14,
                        cancel_required=True, notice_days=0)
    events = compute_calendar_events(terms, date(2026, 5, 15))
    # 14일 → 5/29 trial end, 1일 전 → 5/28
    assert _ev_date(events, EventType.TRIAL_END.value) == "2026-05-29"
    assert _ev_date(events, EventType.CANCEL_DEADLINE.value) == "2026-05-28"


def test_compute_renewal_for_each_billing_cycle():
    base = date(2026, 1, 15)
    # monthly
    assert _ev_date(
        compute_calendar_events(_make_terms(cycle=BillingCycle.MONTHLY), base),
        EventType.RENEWAL_AT.value,
    ) == "2026-02-15"
    # quarterly
    assert _ev_date(
        compute_calendar_events(_make_terms(cycle=BillingCycle.QUARTERLY), base),
        EventType.RENEWAL_AT.value,
    ) == "2026-04-15"
    # semi_annual
    assert _ev_date(
        compute_calendar_events(_make_terms(cycle=BillingCycle.SEMI_ANNUAL), base),
        EventType.RENEWAL_AT.value,
    ) == "2026-07-15"
    # annual
    assert _ev_date(
        compute_calendar_events(_make_terms(cycle=BillingCycle.ANNUAL), base),
        EventType.RENEWAL_AT.value,
    ) == "2027-01-15"


@pytest.mark.parametrize("cycle", [BillingCycle.LIFETIME, BillingCycle.OTHER, None])
def test_compute_no_renewal_for_lifetime_or_other(cycle):
    terms = _make_terms(cycle=cycle)
    events = compute_calendar_events(terms, date(2026, 5, 15))
    assert EventType.RENEWAL_AT.value not in _ev_types(events)


def test_compute_event_type_is_string_value_not_enum():
    """DB SAEnum 은 둘 다 받지만, 호환성 위해 dict 값은 enum.value 문자열."""
    terms = _make_terms(offered=True, duration=7, cycle=BillingCycle.MONTHLY)
    for e in compute_calendar_events(terms, date(2026, 5, 15)):
        assert isinstance(e["event_type"], str)
        assert e["event_type"] in {x.value for x in EventType}
