"""term_service 의 KeyClause → TermClause 변환 헬퍼 단위 테스트.

`_parse_result_to_clauses` 가 KeyClauseCitation(page+quote) 와
SubscriptionTerms 의 FieldValue.citation(page+bbox+quote) 를 합쳐
page/bbox 컬럼 값까지 만들어내는지 검증한다. DB 접근은 하지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from ai.schemas.common import Citation, FieldValue, Uncertainty
from app.services import term_service

# 제네릭 파라미터를 구체화. Pydantic 은 FieldValue 와 FieldValue[T] 를 별도 모델로
# 취급하므로 BaseModel 필드에 직접 FieldValue 를 쓰면 invariant 에러가 난다.
FVInt = FieldValue[int]
FVStr = FieldValue[str]


# ── Pydantic 미니 SubscriptionTerms ───────────────────────
# 실제 SubscriptionTerms 의 nested 구조를 그대로 재현하지 않고, 헬퍼가 사용하는
# `__pydantic_fields__` 재귀 + `citation` 속성만 만족하면 충분.
class _Pricing(BaseModel):
    price: FVInt
    plan: FVStr | None = None


class _Section(BaseModel):
    a: FVStr


class _Terms(BaseModel):
    pricing: _Pricing
    section: _Section


# ── KeyClause 미니 (citation page+quote 만) ───────────────
@dataclass
class _MiniCitation:
    page: int
    quote: str


@dataclass
class _MiniKeyClause:
    title: str
    description: str
    citation: _MiniCitation


@dataclass
class _MiniResult:
    key_clauses: list[_MiniKeyClause]
    terms: Any


def _fv_int(value: int, quote: str, page: int = 1, bbox=None) -> FVInt:
    return FVInt(
        value=value,
        uncertainty=Uncertainty.CONFIRMED,
        citation=Citation(page=page, quote=quote, bbox=bbox),
    )


def _fv_str(value: str, quote: str, page: int = 1, bbox=None) -> FVStr:
    return FVStr(
        value=value,
        uncertainty=Uncertainty.CONFIRMED,
        citation=Citation(page=page, quote=quote, bbox=bbox),
    )


def test_collect_field_bboxes_walks_nested_pydantic():
    terms = _Terms(
        pricing=_Pricing(
            price=_fv_int(9900, quote="월 9,900원", page=2, bbox=(0.1, 0.2, 0.3, 0.4)),
            plan=_fv_str("basic", quote="베이직 플랜", page=2),  # bbox 없음
        ),
        section=_Section(a=_fv_str("x", quote="기타 조항", page=3, bbox=(0.5, 0.6, 0.7, 0.8))),
    )
    lookup = term_service._collect_field_bboxes(terms)
    assert lookup["월 9,900원"] == (2, [0.1, 0.2, 0.3, 0.4])
    assert lookup["기타 조항"] == (3, [0.5, 0.6, 0.7, 0.8])
    # bbox 없는 quote 도 등록되되 bbox=None
    assert lookup["베이직 플랜"] == (2, None)


def test_match_bbox_exact_then_substring_then_none():
    lookup = {
        "월 9,900원 부과": (2, [0.1, 0.2, 0.3, 0.4]),
        "환불 불가": (5, [0.5, 0.5, 0.6, 0.6]),
    }
    # exact
    assert term_service._match_bbox("월 9,900원 부과", lookup) == (2, [0.1, 0.2, 0.3, 0.4])
    # keyclause quote 가 lookup quote 를 포함 (lookup 이 부분문자열)
    assert term_service._match_bbox("매월 월 9,900원 부과 됨", lookup) == (2, [0.1, 0.2, 0.3, 0.4])
    # 역방향: lookup quote 가 keyclause quote 를 포함
    assert term_service._match_bbox("환불", lookup) == (5, [0.5, 0.5, 0.6, 0.6])
    # 매칭 없음
    assert term_service._match_bbox("전혀 다른 내용", lookup) == (None, None)
    # 빈 quote
    assert term_service._match_bbox("", lookup) == (None, None)


def test_parse_result_to_clauses_populates_page_and_bbox():
    terms = _Terms(
        pricing=_Pricing(price=_fv_int(9900, quote="월 9,900원", page=2, bbox=(0.1, 0.2, 0.3, 0.4))),
        section=_Section(a=_fv_str("y", quote="해지 시 환불 불가", page=5, bbox=(0.5, 0.5, 0.6, 0.6))),
    )
    result = _MiniResult(
        key_clauses=[
            _MiniKeyClause(
                title="요금",
                description="월 결제",
                citation=_MiniCitation(page=2, quote="월 9,900원"),
            ),
            _MiniKeyClause(
                title="환불",
                description="환불 불가",
                citation=_MiniCitation(page=5, quote="해지 시 환불 불가"),
            ),
            _MiniKeyClause(
                title="미매칭",
                description="bbox 없음",
                citation=_MiniCitation(page=9, quote="아무 데도 없는 인용"),
            ),
        ],
        terms=terms,
    )

    out = term_service._parse_result_to_clauses(result)
    assert len(out) == 3

    assert out[0]["original_text"] == "월 9,900원"
    assert out[0]["page"] == 2
    assert out[0]["bbox"] == [0.1, 0.2, 0.3, 0.4]
    assert out[0]["title"] == "요금"
    assert out[0]["plain_text"] == "월 결제"
    assert out[0]["clause_type"] == "ETC"

    assert out[1]["page"] == 5
    assert out[1]["bbox"] == [0.5, 0.5, 0.6, 0.6]

    # 매칭 실패 → bbox 는 None, page 는 KeyClauseCitation 의 값을 그대로.
    assert out[2]["page"] == 9
    assert out[2]["bbox"] is None
