from enum import Enum
from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Uncertainty(str, Enum):
    CONFIRMED = "confirmed"
    INFERRED = "inferred"
    AMBIGUOUS = "ambiguous"
    NOT_SPECIFIED = "not_specified"


class Citation(BaseModel):
    page: int
    section: str | None = None
    bbox: tuple[float, float, float, float] | None = None
    quote: str
    pain_point_id: str | None = None


class FieldValue(BaseModel, Generic[T]):
    value: T | None
    uncertainty: Uncertainty
    citation: Citation | None = None


def empty_fv() -> dict:
    """기본 `not_specified` FieldValue 의 dict 형태 — v1.1.0 schema 확장 시 새 필드의
    backwards-compatible default. dict 로 반환해 pydantic v2 generic strict 검증을
    회피 (비-파라미터화된 `FieldValue` 인스턴스는 `FieldValue[bool]` 같은 typed 필드에
    안 들어감 — generic invariance)."""
    return {"value": None, "uncertainty": Uncertainty.NOT_SPECIFIED, "citation": None}
