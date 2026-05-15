"""Unfair clause flag canonical 정규화 — eval 스크립트와 dispute 서비스 공용."""

from __future__ import annotations

from ai.schemas.flag_canonical import flag_canonical, FLAG_ALIAS_GROUPS


def test_canonical_maps_post_code_to_group_canonical():
    # POST-03 그룹 (환불 거부)의 canonical 은 그룹 sorted 첫 원소
    assert flag_canonical("POST-03") == flag_canonical("환불 거부")
    assert flag_canonical("POST-03") == flag_canonical("refund_denial")


def test_canonical_strips_parenthetical_and_underscore():
    # 괄호 부연 + underscore 제거
    assert flag_canonical("환불 거부 (시청 시 청약철회 권리 소멸)") == flag_canonical("POST-03")
    assert flag_canonical("의사표시_의제") == flag_canonical("POST-05")


def test_canonical_returns_normalized_when_no_group_match():
    # 알려지지 않은 flag 는 normalize 만 적용 (괄호/언더스코어/공백 정리)
    assert flag_canonical("새로운_플래그 ") == "새로운 플래그"


def test_canonical_empty_returns_empty():
    assert flag_canonical("") == ""
    assert flag_canonical(None) == ""  # 방어적: None 입력도 빈 문자열


def test_alias_groups_cover_all_post_codes():
    # POST-01 ~ POST-05 모두 그룹에 존재
    all_members = set().union(*FLAG_ALIAS_GROUPS)
    for code in ("POST-01", "POST-02", "POST-03", "POST-04", "POST-05"):
        assert code in all_members, f"{code} not in any alias group"
