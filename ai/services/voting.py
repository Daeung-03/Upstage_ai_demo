"""다회 extract 결과를 필드별로 majority voting 집계.

도메인-폴리모픽 구현 — `SubscriptionTerms`/`FinanceTerms`/`InsuranceTerms` 등
모든 도메인 스키마에 동작한다. 동작 조건:

- root model 의 sub-model 필드 (`pricing`, `coverage` 등) 는 `FieldValue` 필드로
  채워져 있다.
- root model 에 `unfair_clause_flags: list[str]` 가 있으면 N 회 결과를 union.
- 그 외 scalar/str 메타데이터 (`service_name`, `extraction_date` 등) 는 첫 번째
  결과 그대로 보존.

자유 텍스트 필드(description 등)는 paraphrase variance가 있으므로 같은 의미라도
다른 값으로 카운트됨 — voting 효과는 enum/bool/int 필드에서 가장 크고, 자유
텍스트는 사실상 첫 비-null 값을 그대로 씀.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, TypeVar

from pydantic import BaseModel

from ai.schemas.common import FieldValue
from ai.schemas.subscription import SubscriptionTerms

T = TypeVar("T", bound=BaseModel)

UNFAIR_FLAGS_FIELD = "unfair_clause_flags"


def _scalar_key(value: Any) -> Any:
    """단일 값 정규화 — enum은 .value로 풀어 string과 비교 가능하게."""
    if value is None:
        return None
    if hasattr(value, "value") and not isinstance(value, (str, int, bool, float)):
        return value.value
    return value


def _value_key(value: Any) -> Any:
    """voting 비교용 정규화 — list 원소까지 enum.value 풀어서 정렬된 tuple."""
    if value is None:
        return None
    if isinstance(value, list):
        return tuple(sorted(_scalar_key(x) for x in value))
    return _scalar_key(value)


def _is_empty(value: Any) -> bool:
    """voting에서 "데이터 없음"으로 취급할 기준.

    None만 해당. 빈 list([]) / 빈 str("")는 의미 있는 값일 수 있음
    (예: blackout_periods=[]은 "해지 불가 기간 없음"이라는 confirmed 정보).
    """
    return value is None


def _vote_field(fvs: list[FieldValue]) -> FieldValue:
    """N개의 FieldValue 중 다수결 선택. 동률 시 non-null 우선."""
    if not fvs:
        raise ValueError("vote_field called with empty list")
    if len(fvs) == 1:
        return fvs[0]

    non_empty = [fv for fv in fvs if not _is_empty(fv.value)]
    if not non_empty:
        # 모두 비어있으면 첫 번째 그대로
        return fvs[0]

    # 가장 많이 등장한 non-empty value 키 선정
    counter = Counter(_value_key(fv.value) for fv in non_empty)
    winning_key, _winning_count = counter.most_common(1)[0]
    # 그 값을 가진 첫 번째 FieldValue 반환 — citation 보존
    for fv in non_empty:
        if _value_key(fv.value) == winning_key:
            return fv
    return non_empty[0]  # 실질적으로 도달 안 함


def _is_section_model(obj: Any) -> bool:
    """sub-model 판정 — pydantic BaseModel 이면서 FieldValue 인 필드를 적어도
    하나 가진 경우. root model 자체나 scalar/list 는 False.
    """
    if not isinstance(obj, BaseModel):
        return False
    cls = type(obj)
    for name in cls.model_fields:
        if isinstance(getattr(obj, name), FieldValue):
            return True
    return False


def vote_terms(terms_list: list[T]) -> T:
    """도메인-폴리모픽 majority voting.

    root model 의 각 필드를 다음 룰로 처리:
    - sub-model (FieldValue 필드를 가진 BaseModel) → 내부 FieldValue 별로 `_vote_field`
    - `unfair_clause_flags` list[str] 필드 → 모든 run union, sorted
    - 그 외 scalar/str/None → 첫 번째 run 의 값 그대로
    """
    if not terms_list:
        raise ValueError("terms_list is empty")
    if len(terms_list) == 1:
        return terms_list[0]

    base = terms_list[0]
    cls = type(base)

    kwargs: dict[str, Any] = {}
    for field_name in cls.model_fields:
        attrs = [getattr(t, field_name) for t in terms_list]
        first_attr = attrs[0]

        if _is_section_model(first_attr):
            section_cls = type(first_attr)
            voted_inner: dict[str, Any] = {}
            for inner_name in section_cls.model_fields:
                fvs = [getattr(a, inner_name) for a in attrs]
                voted_inner[inner_name] = _vote_field(fvs)
            kwargs[field_name] = section_cls(**voted_inner)
        elif field_name == UNFAIR_FLAGS_FIELD and isinstance(first_attr, list):
            merged: set[str] = set()
            for a in attrs:
                merged.update(a)
            kwargs[field_name] = sorted(merged)
        else:
            kwargs[field_name] = getattr(base, field_name)

    return cls(**kwargs)


def vote_subscription_terms(terms_list: list[SubscriptionTerms]) -> SubscriptionTerms:
    """OTT (SubscriptionTerms) 전용 alias — 기존 호출부 호환 유지."""
    return vote_terms(terms_list)
