from __future__ import annotations
from uuid import UUID
from datetime import date, timedelta
from calendar import monthrange
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.calendar import CalendarEvent
from app.models.enums import EventType


async def get_calendar_events(
    db: AsyncSession,
    user_id: UUID,
    month: str,          # "YYYY-MM"
) -> list[CalendarEvent]:
    year, mon = map(int, month.split("-"))
    start = date(year, mon, 1)
    end = date(year, mon, monthrange(year, mon)[1])

    result = await db.execute(
        select(CalendarEvent)
        .where(
            CalendarEvent.user_id == user_id,
            CalendarEvent.event_date >= start,
            CalendarEvent.event_date <= end,
        )
        .order_by(CalendarEvent.event_date)
    )
    return result.scalars().all()


# ── 캘린더 이벤트 산출 ───────────────────────────────────
#
# 약관 본문에서 LLM 으로 절대 날짜를 뽑는 대신, 이미 구조화된 SubscriptionTerms
# (무료 체험 일수, 결제 주기, 통지 기간 등) + 사용자 가입일을 결합해 결정론적으로
# 계산한다. OTT/구독 도메인의 모든 핵심 이벤트(가입, 무료체험 종료, 해지 마감,
# 다음 결제)는 모두 상대적이라 LLM 호출이 불필요하고 hallucination 가능성도 0.

_BILLING_CYCLE_TO_MONTHS = {
    "monthly": 1,
    "quarterly": 3,
    "semi_annual": 6,
    "annual": 12,
}


def _add_months(d: date, months: int) -> date:
    """date + N months — 월말 보정 (예: 1/31 + 1month = 2/28 또는 2/29)."""
    total = d.month - 1 + months
    year = d.year + total // 12
    month = total % 12 + 1
    day = min(d.day, monthrange(year, month)[1])
    return date(year, month, day)


def _enum_value(v) -> str | None:
    """FieldValue.value 가 enum 인스턴스일 수도, 원시 문자열일 수도. 정규화."""
    if v is None:
        return None
    return v.value if hasattr(v, "value") else str(v)


def _field_value(field) -> Any:
    """FieldValue 객체에서 .value 를 안전하게 꺼냄. None 이거나 필드 자체가 없으면 None."""
    if field is None:
        return None
    return getattr(field, "value", None)


def compute_calendar_events(
    terms,
    subscribed_at: date | None,
) -> list[dict]:
    """SubscriptionTerms + 사용자 가입일 → CalendarEvent 후보 dict 리스트.

    비-subscription terms(InsuranceTerms/FinanceTerms 등)는 free_trial/pricing
    필드가 없어 getattr 가드에 모두 걸러지고 SUBSCRIBED_AT 만 반환된다 (크래시 없음).

    가입일이 없으면 무료 체험 종료/해지 마감/다음 결제는 계산 불가 → 빈 리스트.
    절대 날짜가 약관 본문에 나오는 케이스(프로모션 종료 등)는 향후 별도
    LLM-기반 추출로 보강 가능 — 현재는 구조화된 데이터만 사용.

    반환 dict shape: {"event_type": EventType, "date": "YYYY-MM-DD"}
    """
    if subscribed_at is None or terms is None:
        return []

    events: list[dict] = [
        {"event_type": EventType.SUBSCRIBED_AT.value, "date": subscribed_at.isoformat()},
    ]

    # 1) 무료 체험 종료 + 해지 마감
    free_trial = getattr(terms, "free_trial", None)
    if free_trial is not None and _field_value(getattr(free_trial, "offered", None)) is True:
        days = _field_value(getattr(free_trial, "duration_days", None))
        if isinstance(days, int) and days > 0:
            trial_end = subscribed_at + timedelta(days=days)
            events.append({
                "event_type": EventType.TRIAL_END.value,
                "date": trial_end.isoformat(),
            })
            # 해지해야 자동 결제 안 됨 + 사전 통지 기간
            cancel_required = _field_value(
                getattr(free_trial, "cancel_required_before_end", None)
            )
            notice = _field_value(
                getattr(free_trial, "notice_before_conversion_days", None)
            )
            if cancel_required is True:
                lead = notice if isinstance(notice, int) and notice > 0 else 1
                events.append({
                    "event_type": EventType.CANCEL_DEADLINE.value,
                    "date": (trial_end - timedelta(days=lead)).isoformat(),
                })

    # 2) 다음 결제 (RENEWAL_AT)
    pricing = getattr(terms, "pricing", None)
    cycle = _enum_value(_field_value(getattr(pricing, "billing_cycle", None))) if pricing else None
    months = _BILLING_CYCLE_TO_MONTHS.get(cycle)
    if months:
        events.append({
            "event_type": EventType.RENEWAL_AT.value,
            "date": _add_months(subscribed_at, months).isoformat(),
        })
    # billing_cycle 이 "lifetime"/"other"/None 이면 갱신 이벤트 생성 안 함.

    return events