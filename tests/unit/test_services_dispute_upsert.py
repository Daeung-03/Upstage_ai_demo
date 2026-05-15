"""dispute_service.upsert_dispute_cases — idempotency + 정규화."""

from __future__ import annotations

from app.services.dispute_service import (
    DisputeCaseInput,
    _canonical_flags,
    _normalize_pain_points,
)


def test_canonical_flags_dedupes_via_alias():
    # POST-03 과 "환불 거부" 와 "refund_denial" 은 같은 canonical
    out = _canonical_flags(["POST-03", "환불 거부", "refund_denial"])
    assert len(out) == 1


def test_canonical_flags_preserves_unknown():
    # 알려지지 않은 flag 는 underscore→space normalize 만 적용되어 보존.
    out = _canonical_flags(["unknown_flag", "POST-03"])
    assert len(out) == 2
    assert "unknown flag" in out  # underscore → space normalize
    assert "POST-03" in out  # canonical of POST-03 group


def test_normalize_pain_points_uppercases_and_strips():
    out = _normalize_pain_points([" post-01 ", "MID-02"])
    assert out == ["POST-01", "MID-02"]


def test_normalize_pain_points_filters_empty():
    out = _normalize_pain_points(["", None, "PRE-01"])  # type: ignore[list-item]
    assert out == ["PRE-01"]


def test_dispute_case_input_typed_dict_shape():
    payload: DisputeCaseInput = {
        "external_id": "한소원-2024-1",
        "title": "t", "summary": "s", "outcome": "o",
        "source": "한국소비자원", "source_url": None,
        "pain_point_ids": ["POST-03"],
        "unfair_flags": ["refund_denial"],
        "domain": "OTT",
    }
    assert payload["title"] == "t"
