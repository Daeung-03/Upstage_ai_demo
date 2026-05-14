"""다회 extract 결과를 필드별로 majority voting 집계.

N=3 ensemble의 핵심 로직. 각 필드에 대해 N개의 FieldValue 중 가장 자주 나타난
non-null 값을 선택. null/not_specified만 있으면 그대로 null 유지.

자유 텍스트 필드(description 등)는 본질적으로 paraphrase variance가 있으므로
같은 의미라도 다른 값으로 카운트됨 — 그래서 voting 효과는 enum/bool/int 필드에서
가장 크고, 자유 텍스트는 사실상 첫 비-null 값을 그대로 씀.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from schemas.common import FieldValue
from schemas.subscription import SubscriptionTerms

SECTION_NAMES = (
    "pricing", "free_trial", "cancellation", "terms_changes",
    "data_usage", "liability", "disputes",
)


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


def vote_subscription_terms(terms_list: list[SubscriptionTerms]) -> SubscriptionTerms:
    """N개의 SubscriptionTerms를 필드별 다수결로 한 개로 합성.

    - 7개 섹션 × 모든 필드: `_vote_field` 적용
    - unfair_clause_flags: union (한 번이라도 검출되면 포함)
    - 메타데이터 (service_name, schema_version 등): 첫 번째 결과 그대로
    """
    if not terms_list:
        raise ValueError("terms_list is empty")
    if len(terms_list) == 1:
        return terms_list[0]

    base = terms_list[0]
    section_kwargs: dict[str, Any] = {}
    for section_name in SECTION_NAMES:
        sections = [getattr(t, section_name) for t in terms_list]
        section_class = type(sections[0])
        voted_fields = {}
        for field_name in section_class.model_fields:
            fvs = [getattr(s, field_name) for s in sections]
            voted_fields[field_name] = _vote_field(fvs)
        section_kwargs[section_name] = section_class(**voted_fields)

    flags: set[str] = set()
    for t in terms_list:
        flags.update(t.unfair_clause_flags)

    return SubscriptionTerms(
        schema_version=base.schema_version,
        domain=base.domain,
        service_name=base.service_name,
        service_provider=base.service_provider,
        document_url=base.document_url,
        effective_date=base.effective_date,
        extraction_date=base.extraction_date,
        unfair_clause_flags=sorted(flags),
        raw_document_hash=base.raw_document_hash,
        **section_kwargs,
    )
