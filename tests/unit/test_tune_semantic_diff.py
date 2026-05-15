"""tune_semantic_diff_thresholds 의 synthesis / 통계 헬퍼 단위 테스트.

Upstage API 호출 없이 순수 함수만 검증. 실제 cosine 측정은 별도 e2e (수동 실행).
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


@pytest.fixture
def mod():
    ROOT = Path(__file__).resolve().parent.parent.parent
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    return importlib.import_module("scripts.tune_semantic_diff_thresholds")


def test_synth_phrasing_only_replaces_synonyms(mod):
    src = "회사는 약관을 변경할 수 있습니다."
    out = mod.synth_phrasing_only(src)
    assert "사업자" in out
    assert "이용약관" in out
    assert "수정" in out
    # 원문과 다르되 짧은 길이 차이 (의미 동일 가정)
    assert out != src


def test_synth_phrasing_only_no_match_keeps_text(mod):
    src = "XYZ ABC 123 — 매칭할 키워드 없음."
    out = mod.synth_phrasing_only(src)
    assert out == src


def test_synth_value_change_modifies_numbers(mod):
    src = "회사는 30일 전에 통지하고, 10일 이내 해지 가능."
    out = mod.synth_value_change(src)
    # 30일·10일 둘 중 하나 이상 변경되어야 함
    assert ("30일" not in out) or ("10일" not in out)
    assert out != src


def test_synth_value_change_fallback_when_no_number(mod):
    src = "본 약관은 무기한 유효합니다."
    out = mod.synth_value_change(src)
    # 숫자가 없으면 부정문 prefix 가 붙어 의미 다른 변형 생성
    assert "적용되지 않습니다" in out


def test_synth_unrelated_uses_other_clauses(mod):
    other = ["다른 조항 A", "다른 조항 B"]
    assert mod.synth_unrelated(other, 0) == "다른 조항 A"
    assert mod.synth_unrelated(other, 1) == "다른 조항 B"
    # idx 가 길이 초과해도 wrap (modulo)
    assert mod.synth_unrelated(other, 2) == "다른 조항 A"


def test_summarize_returns_percentiles(mod):
    s = mod.summarize("test", [0.1 * i for i in range(1, 11)])  # 0.1..1.0
    assert s["n"] == 10
    assert s["min"] == pytest.approx(0.1, abs=1e-3)
    assert s["max"] == pytest.approx(1.0, abs=1e-3)
    assert s["p50"] == pytest.approx(0.55, abs=1e-3)
    assert 0.1 <= s["p10"] <= 0.2
    assert 0.8 <= s["p90"] <= 1.0


def test_summarize_empty(mod):
    s = mod.summarize("empty", [])
    assert s == {"label": "empty", "n": 0}


def test_recommend_midpoint_between_categories(mod):
    cats = {
        "phrasing_only": {"p10": 0.95, "p50": 0.97, "p90": 0.99, "n": 10},
        "value_change": {"p10": 0.65, "p50": 0.72, "p90": 0.85, "n": 10},
        "unrelated": {"p10": 0.20, "p50": 0.30, "p90": 0.45, "n": 10},
    }
    rec = mod.recommend(cats)
    # NEAR_DUP: midpoint(value_change.p90, phrasing_only.p10) = (0.85 + 0.95)/2 = 0.90
    assert rec["NEAR_DUP_THRESHOLD"] == pytest.approx(0.90, abs=1e-3)
    # SUBSTANTIVE: midpoint(unrelated.p90, value_change.p10) = (0.45 + 0.65)/2 = 0.55
    assert rec["SUBSTANTIVE_THRESHOLD"] == pytest.approx(0.55, abs=1e-3)


def test_recommend_missing_categories_returns_partial(mod):
    """unrelated 데이터 없으면 SUBSTANTIVE_THRESHOLD 권장 생략."""
    cats = {
        "phrasing_only": {"p10": 0.95, "p50": 0.97, "p90": 0.99, "n": 5},
        "value_change": {"p10": 0.65, "p50": 0.72, "p90": 0.85, "n": 5},
    }
    rec = mod.recommend(cats)
    assert "NEAR_DUP_THRESHOLD" in rec
    assert "SUBSTANTIVE_THRESHOLD" not in rec
