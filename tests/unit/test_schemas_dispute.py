"""Dispute 응답 스키마 — validation roundtrip."""

from __future__ import annotations

import uuid

from app.schemas.dispute import (
    DisputeMatch, ClauseDisputeMatches, TermDisputesResponse, DisputeCaseDetail,
)


def test_dispute_match_minimal():
    m = DisputeMatch(
        case_id=uuid.uuid4(),
        title="t", summary="s", outcome="o", source="한국소비자원",
        source_url=None, score=0.82,
        matched_signals=["pain_point:POST-03"],
    )
    dumped = m.model_dump()
    assert dumped["score"] == 0.82
    assert dumped["matched_signals"] == ["pain_point:POST-03"]


def test_clause_disputes_matches_empty_array_allowed():
    cm = ClauseDisputeMatches(
        clause_id=uuid.uuid4(),
        clause_title="자동결제 환불",
        matches=[],
    )
    assert cm.matches == []


def test_term_disputes_response_structure():
    resp = TermDisputesResponse(
        term_id=uuid.uuid4(),
        clauses=[
            ClauseDisputeMatches(
                clause_id=uuid.uuid4(),
                clause_title="A",
                matches=[],
            )
        ],
    )
    assert len(resp.clauses) == 1


def test_dispute_case_detail_optional_source_url():
    d = DisputeCaseDetail(
        id=uuid.uuid4(),
        title="t", summary="s", outcome="o", source="언론",
        source_url=None,
        pain_point_ids=["POST-01"],
        unfair_flags=["unilateral_change"],
        domain="OTT",
    )
    assert d.source_url is None
