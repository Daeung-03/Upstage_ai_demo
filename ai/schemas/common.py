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
