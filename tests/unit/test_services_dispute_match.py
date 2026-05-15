"""dispute_service.find_similar_disputes — boost / threshold / top_k 검증.

DB·임베딩 호출은 모킹. 알고리즘 자체만 단위 테스트.
"""

from __future__ import annotations

import uuid

import pytest

from app.services.dispute_service import (
    _CandidateRow,
    DEFAULT_MIN_SCORE,
    _apply_boosts_and_filter,
)


def _row(
    pain_points: list[str] | None = None,
    flags: list[str] | None = None,
    domain: str = "OTT",
    cosine_distance: float = 0.2,  # 1 - 0.2 = base 0.8
    title: str = "t",
) -> _CandidateRow:
    return _CandidateRow(
        id=uuid.uuid4(),
        title=title,
        summary="s",
        outcome="o",
        source="src",
        source_url=None,
        pain_point_ids=pain_points or [],
        unfair_flags=flags or [],
        domain=domain,
        cosine_distance=cosine_distance,
    )


def test_pain_point_boost_adds_0_10():
    rows = [_row(pain_points=["POST-03"])]
    out = _apply_boosts_and_filter(
        rows,
        clause_pain_point="POST-03",
        term_unfair_flags=[],
        term_domain="OTT",
        top_k=5,
        min_score=DEFAULT_MIN_SCORE,
    )
    assert len(out) == 1
    # base 0.8 + pain_point 0.10 + domain 0.05 = 0.95
    assert out[0].score == pytest.approx(0.95, abs=1e-6)
    assert "pain_point:POST-03" in out[0].matched_signals
    assert "domain:OTT" in out[0].matched_signals


def test_unfair_flag_boost_adds_0_05_canonical():
    rows = [_row(flags=["POST-03"])]  # canonical of "환불 거부"
    out = _apply_boosts_and_filter(
        rows,
        clause_pain_point=None,
        term_unfair_flags=["환불 거부"],  # alias of POST-03
        term_domain="OTT",
        top_k=5,
        min_score=DEFAULT_MIN_SCORE,
    )
    assert len(out) == 1
    # base 0.8 + flag 0.05 + domain 0.05 = 0.90
    assert out[0].score == pytest.approx(0.90, abs=1e-6)
    assert any(s.startswith("flag:") for s in out[0].matched_signals)


def test_domain_all_matches_any_term_domain():
    rows = [_row(domain="ALL")]
    out = _apply_boosts_and_filter(
        rows,
        clause_pain_point=None,
        term_unfair_flags=[],
        term_domain="FINANCE",
        top_k=5,
        min_score=DEFAULT_MIN_SCORE,
    )
    assert len(out) == 1
    assert "domain:ALL" in out[0].matched_signals


def test_threshold_cut_drops_below_min_score():
    # base 0.5 + 어떤 boost 도 없으면 0.65 미달
    rows = [_row(cosine_distance=0.5, domain="OTHER")]
    out = _apply_boosts_and_filter(
        rows,
        clause_pain_point=None,
        term_unfair_flags=[],
        term_domain="OTT",
        top_k=5,
        min_score=DEFAULT_MIN_SCORE,
    )
    assert out == []


def test_top_k_limits_output():
    rows = [_row(title=f"t{i}", cosine_distance=0.1) for i in range(10)]
    out = _apply_boosts_and_filter(
        rows,
        clause_pain_point=None,
        term_unfair_flags=[],
        term_domain="OTT",
        top_k=3,
        min_score=DEFAULT_MIN_SCORE,
    )
    assert len(out) == 3


def test_results_sorted_by_score_descending():
    rows = [
        _row(title="low", cosine_distance=0.3, domain="OTHER"),    # base 0.7
        _row(title="high", cosine_distance=0.1, pain_points=["POST-01"]),  # 0.9 + 0.10 + 0.05 = 1.05
        _row(title="mid", cosine_distance=0.2, domain="OTHER"),    # base 0.8
    ]
    out = _apply_boosts_and_filter(
        rows,
        clause_pain_point="POST-01",
        term_unfair_flags=[],
        term_domain="OTT",
        top_k=5,
        min_score=DEFAULT_MIN_SCORE,
    )
    titles = [r.title for r in out]
    assert titles == ["high", "mid", "low"]


def test_no_signals_no_boosts_no_match():
    # 모든 boost 0, base 0.6 → 0.65 미달
    rows = [_row(cosine_distance=0.4, domain="OTHER")]
    out = _apply_boosts_and_filter(
        rows,
        clause_pain_point=None,
        term_unfair_flags=[],
        term_domain="OTT",
        top_k=5,
        min_score=DEFAULT_MIN_SCORE,
    )
    assert out == []
