"""sub_category 권장 vocab 헬퍼 단위 테스트."""

from app.models.enums import TermDomain
from app.models.sub_category import (
    RECOMMENDED_SUB_CATEGORIES,
    is_recommended_sub_category,
    recommendations_for,
)


def test_recommendations_for_known_domain_enum():
    sub_list = recommendations_for(TermDomain.INSURANCE)
    assert "실손의료보험" in sub_list
    assert "생명보험" in sub_list


def test_recommendations_for_string_domain():
    """문자열 도메인 (router 가 'INSURANCE' 식으로 받음) 도 동작."""
    sub_list = recommendations_for("FINANCE")
    assert "PG/결제대행" in sub_list
    assert "송금" in sub_list


def test_recommendations_for_unknown_domain_returns_empty():
    assert recommendations_for("UNKNOWN") == []


def test_recommendations_for_etc_is_empty_by_design():
    """ETC 도메인은 권장 vocab 없음."""
    assert recommendations_for(TermDomain.ETC) == []


def test_is_recommended_sub_category_match():
    assert is_recommended_sub_category(TermDomain.OTT, "동영상 스트리밍") is True


def test_is_recommended_sub_category_not_match():
    """권장 vocab 에 없으면 False — DB 는 자유 TEXT 라 입력 자체는 가능."""
    assert is_recommended_sub_category(TermDomain.OTT, "비정상_카테고리") is False


def test_is_recommended_sub_category_empty_or_none():
    assert is_recommended_sub_category(TermDomain.OTT, "") is False


def test_is_recommended_sub_category_invalid_domain():
    """도메인이 유효하지 않으면 안전 False (예외 던지지 않음)."""
    assert is_recommended_sub_category("BOGUS", "anything") is False


def test_all_term_domains_present_in_recommendations():
    """RECOMMENDED_SUB_CATEGORIES 키가 TermDomain 전부 커버해야 함 (UI 가 도메인 선택 시
    빈 드롭다운 받아도 명시적으로 알도록)."""
    for d in TermDomain:
        assert d in RECOMMENDED_SUB_CATEGORIES, f"{d} missing in recommendations"
