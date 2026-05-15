"""ai.services.diff.compute_semantic_diff 단위 테스트.

embed_passages 를 monkeypatch 해서 결정론적 벡터를 주입하고 cosine 분류 로직
(phrasing_only / substantive / added / removed) 이 임계값 기준에 맞게 동작
하는지 확인. 실제 Upstage 호출 없음.
"""

from __future__ import annotations

import pytest

from ai.services import diff as diff_mod


def _patch_embeddings(monkeypatch, mapping: dict[str, list[float]]):
    """embed_passages 호출 시 입력 텍스트를 보고 mapping 에서 벡터 반환."""
    async def fake_embed(_client, texts):
        out = []
        for t in texts:
            if t not in mapping:
                raise AssertionError(f"unexpected text in embed: {t!r}")
            out.append(mapping[t])
        return out

    monkeypatch.setattr(diff_mod, "embed_passages", fake_embed)


async def test_compute_semantic_diff_phrasing_only(monkeypatch):
    """같은 의미의 두 조항 (cosine ~ 1) → phrasing_only."""
    _patch_embeddings(monkeypatch, {
        "회사는 30일 전에 통지합니다": [1.0, 0.0],
        "회사는 30일 전 통지합니다.": [0.999, 0.045],  # 거의 동일
    })
    out = await diff_mod.compute_semantic_diff(
        client=None,
        old_clauses=["회사는 30일 전에 통지합니다"],
        new_clauses=["회사는 30일 전 통지합니다."],
    )
    assert out.counts == {"phrasing_only": 1, "substantive": 0, "added": 0, "removed": 0}
    change = out.changes[0]
    assert change.kind == "phrasing_only"
    assert change.similarity > diff_mod.NEAR_DUP_THRESHOLD


async def test_compute_semantic_diff_substantive(monkeypatch):
    """비슷한 주제지만 실질이 다른 두 조항 (cosine 중간) → substantive."""
    _patch_embeddings(monkeypatch, {
        "위약금 30% 부과": [1.0, 0.0],
        "위약금 50% 부과": [0.85, 0.5],  # 같은 주제, 다른 수치 → 0.85
    })
    out = await diff_mod.compute_semantic_diff(
        client=None,
        old_clauses=["위약금 30% 부과"],
        new_clauses=["위약금 50% 부과"],
    )
    assert out.counts["substantive"] == 1
    assert out.changes[0].kind == "substantive"


async def test_compute_semantic_diff_added(monkeypatch):
    """매칭되는 old 조항이 없는 new 조항 → added."""
    _patch_embeddings(monkeypatch, {
        "기존 조항 X": [1.0, 0.0],
        "완전히 무관한 새 조항 Y": [0.0, 1.0],  # 직교 → 매칭 점수 0
    })
    out = await diff_mod.compute_semantic_diff(
        client=None,
        old_clauses=["기존 조항 X"],
        new_clauses=["완전히 무관한 새 조항 Y"],
    )
    # new 0 의 best match (old 0) cosine 0 < SUBSTANTIVE → added
    assert out.counts["added"] == 1
    assert out.counts["removed"] == 1
    assert {c.kind for c in out.changes} == {"added", "removed"}


async def test_compute_semantic_diff_removed(monkeypatch):
    """매칭되지 않은 old 조항 → removed."""
    _patch_embeddings(monkeypatch, {
        "삭제될 old 조항 A": [1.0, 0.0],
        "유지되는 old 조항 B": [0.0, 1.0],
        "새 조항 B-prime": [0.0, 1.0],
    })
    out = await diff_mod.compute_semantic_diff(
        client=None,
        old_clauses=["삭제될 old 조항 A", "유지되는 old 조항 B"],
        new_clauses=["새 조항 B-prime"],
    )
    # new B-prime ↔ old B (cosine 1) → phrasing_only
    # old A 는 매칭 못 받음 → removed
    assert out.counts["phrasing_only"] == 1
    assert out.counts["removed"] == 1


async def test_compute_semantic_diff_empty_old(monkeypatch):
    """old 가 빈 list → 모두 added (embed 호출 안 됨)."""
    called = {"hit": False}

    async def should_not_call(_c, _t):
        called["hit"] = True
        return []

    monkeypatch.setattr(diff_mod, "embed_passages", should_not_call)

    out = await diff_mod.compute_semantic_diff(
        client=None, old_clauses=[], new_clauses=["새 조항 1", "새 조항 2"],
    )
    assert called["hit"] is False
    assert out.counts == {"phrasing_only": 0, "substantive": 0, "added": 2, "removed": 0}


async def test_compute_semantic_diff_empty_both(monkeypatch):
    out = await diff_mod.compute_semantic_diff(
        client=None, old_clauses=[], new_clauses=[],
    )
    assert all(v == 0 for v in out.counts.values())
    assert out.changes == []


async def test_compute_semantic_diff_greedy_one_to_one(monkeypatch):
    """이미 매칭에 사용된 old 조항은 재사용 안 됨 (1:1 greedy)."""
    _patch_embeddings(monkeypatch, {
        "old A": [1.0, 0.0],
        "new 1": [1.0, 0.0],  # A 와 cosine 1
        "new 2": [0.95, 0.05],  # A 와 cosine 매우 가깝지만 이미 used → added
    })
    out = await diff_mod.compute_semantic_diff(
        client=None, old_clauses=["old A"], new_clauses=["new 1", "new 2"],
    )
    # new 1 → A (phrasing_only)
    # new 2 → A 가 used, 매칭 가능한 old 없음 → added
    assert out.counts["phrasing_only"] == 1
    assert out.counts["added"] == 1
