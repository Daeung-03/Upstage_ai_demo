"""Unfair clause flag canonical 정규화.

eval 스크립트 (`scripts/score_against_golden.py`) 와 dispute matching 서비스
(`app/services/dispute_service.py`) 가 같은 alias 그룹을 공유한다. 새 alias 가
추가되면 여기 한 곳만 수정.
"""

from __future__ import annotations

import re

# 같은 그룹에 속한 flag 는 비교 시 동일 취급. canonical 은 sorted 첫 원소.
FLAG_ALIAS_GROUPS: list[set[str]] = [
    {"POST-01", "약관 일방 변경권", "unilateral_change", "약관 일방 변경",
     "일방적 약관 변경", "회사의 일방적 변경권"},
    {"POST-02", "다크패턴 — 해지 절차 복잡화", "complex_cancellation",
     "해지 절차 복잡화", "다크패턴 해지", "해지 어려움"},
    {"POST-03", "환불 거부", "refund_denial", "환불 불가",
     "환불 거부 (시청 시 청약철회 권리 소멸)", "no_refund"},
    {"POST-04", "면책/손배 제한", "liability_cap", "면책_손배_제한",
     "손해배상 한도", "책임 제한"},
    {"POST-05", "분쟁/집단소송 포기", "arbitration_class_waiver",
     "의사표시_의제", "의사표시 의제", "강제 중재", "집단소송 포기",
     "준거법 외국법", "분쟁 해결 포기"},
    # AI 학습 데이터 — POST 카테고리에 없는 LLM-specific flag
    {"AI 학습 데이터 활용", "AI 학습 데이터 활용 (옵트아웃)", "ai_training_data",
     "model training opt-in", "학습 데이터 사용"},
]


def flag_canonical(s: str | None) -> str:
    """flag 정규화: 괄호/언더스코어 제거 + alias 그룹 canonical 매핑."""
    if not s:
        return ""
    # 1차: 괄호 내 부연 / underscore / 공백 정리
    base = re.sub(r"\s*\([^)]*\)", "", s).strip()
    base = base.replace("_", " ")
    base = re.sub(r"\s+", " ", base).strip()
    # 2차: alias 그룹 lookup (원본 + 정규화된 형태 둘 다 시도)
    for group in FLAG_ALIAS_GROUPS:
        if s in group or base in group:
            return sorted(group)[0]
    return base
