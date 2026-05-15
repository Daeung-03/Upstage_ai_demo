"""DisputeCase ORM 스모크 — instance 생성 + 컬럼 기본값 확인."""

from __future__ import annotations

from app.models.dispute import DisputeCase


def test_dispute_case_instance_defaults():
    case = DisputeCase(
        title="OTT 자동결제 환불 거부 — 한소원 2024-1234",
        summary="…",
        outcome="환불 100%",
        source="한국소비자원",
        pain_point_ids=["POST-03"],
        unfair_flags=["refund_denial"],
        domain="OTT",
    )
    assert case.title.startswith("OTT")
    assert case.pain_point_ids == ["POST-03"]
    assert case.unfair_flags == ["refund_denial"]
    assert case.domain == "OTT"
    # embedding 은 NULL 허용
    assert case.embedding is None


def test_dispute_case_tablename():
    assert DisputeCase.__tablename__ == "dispute_cases"


def test_dispute_case_id_factory_callable():
    """id 가 클라이언트-side 에서도 채워지도록 default=uuid.uuid4 보장."""
    id_col = DisputeCase.__table__.c.id
    assert id_col.default is not None
    assert callable(id_col.default.arg)
