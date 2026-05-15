"""term_service._derive_clause_type 추론 로직 단위 테스트.

A 옵션 (pain_point_id + title 키워드) 및 B 옵션 (LLM explicit clause_type) 모두 검증.
"""

from __future__ import annotations

from app.services.term_service import _derive_clause_type


# === A 옵션: pain_point_id 기반 ===


def test_pre04_privacy():
    assert _derive_clause_type(
        pain_point_id="PRE-04", title="개인정보 수집",
        description="...", explicit=None,
    ) == "PRIVACY"


def test_mid01_terms_change():
    assert _derive_clause_type(
        pain_point_id="MID-01", title="약관 변경 사전 고지",
        description="...", explicit=None,
    ) == "TERMS_CHANGE"


def test_mid02_terms_change():
    assert _derive_clause_type(
        pain_point_id="MID-02", title="의사표시 의제",
        description="...", explicit=None,
    ) == "TERMS_CHANGE"


def test_post01_cancellation():
    assert _derive_clause_type(
        pain_point_id="POST-01", title="위약금",
        description="...", explicit=None,
    ) == "CANCELLATION"


def test_post04_liability():
    assert _derive_clause_type(
        pain_point_id="POST-04", title="면책",
        description="...", explicit=None,
    ) == "LIABILITY"


def test_pre03_cancellation_auto_convert():
    """무료 → 자동 유료 전환 = 결제 전환 관련 → CANCELLATION."""
    assert _derive_clause_type(
        pain_point_id="PRE-03", title="자동 결제 전환",
        description="...", explicit=None,
    ) == "CANCELLATION"


def test_post05_etc():
    """분쟁/집단소송 포기는 schema enum 에 별도 카테고리 없음 → ETC."""
    assert _derive_clause_type(
        pain_point_id="POST-05", title="집단소송 포기",
        description="...", explicit=None,
    ) == "ETC"


# === A 옵션: title 키워드 fallback (pain_point_id 가 None 또는 매핑 안 됨) ===


def test_title_privacy_keyword():
    assert _derive_clause_type(
        pain_point_id=None,
        title="개인정보 제3자 제공",
        description="회원의 정보를 수사기관 등에 제공할 수 있습니다",
        explicit=None,
    ) == "PRIVACY"


def test_title_terms_change_keyword():
    assert _derive_clause_type(
        pain_point_id=None,
        title="약관 변경 사전 고지 기간",
        description="...",
        explicit=None,
    ) == "TERMS_CHANGE"


def test_title_liability_keyword():
    assert _derive_clause_type(
        pain_point_id=None,
        title="서비스 중단 시 배상",
        description="회사가 고의·과실이 없으면 손해를 배상하지 않을 수 있습니다",
        explicit=None,
    ) == "LIABILITY"


def test_title_cancellation_keyword():
    assert _derive_clause_type(
        pain_point_id=None,
        title="중도 해지 위약금",
        description="...",
        explicit=None,
    ) == "CANCELLATION"


def test_title_renewal_keyword():
    assert _derive_clause_type(
        pain_point_id=None,
        title="자동 갱신",
        description="구독은 자동 갱신됩니다",
        explicit=None,
    ) == "RENEWAL"


def test_title_payment_keyword():
    assert _derive_clause_type(
        pain_point_id=None,
        title="월 구독료 인상",
        description="...",
        explicit=None,
    ) == "PAYMENT"


# === A 옵션: 매칭 실패 → ETC ===


def test_unmatched_falls_to_etc():
    assert _derive_clause_type(
        pain_point_id=None,
        title="알 수 없는 조항",
        description="기타 사항",
        explicit=None,
    ) == "ETC"


def test_pain_point_id_none_and_empty_text():
    assert _derive_clause_type(
        pain_point_id=None, title=None, description=None, explicit=None,
    ) == "ETC"


# === B 옵션: explicit clause_type 우선 ===


def test_explicit_overrides_pain_point():
    """LLM 이 직접 clause_type 출력하면 그게 우선."""
    assert _derive_clause_type(
        pain_point_id="PRE-04",   # PRIVACY 로 추론될 것
        title="개인정보",
        description="...",
        explicit="LIABILITY",
    ) == "LIABILITY"


def test_explicit_terms_change_via_pain_point_fallback():
    """LLM 이 빈 문자열 출력 → pain_point_id 매핑으로 폴백."""
    assert _derive_clause_type(
        pain_point_id="MID-02", title="의사표시 의제",
        description="...", explicit="",
    ) == "TERMS_CHANGE"


def test_explicit_invalid_enum_falls_back():
    """LLM 이 schema 외 값 출력 → ETC 로 fallback (pain_point_id 도 unmatched)."""
    assert _derive_clause_type(
        pain_point_id=None, title="기타",
        description="...", explicit="UNKNOWN_TYPE",
    ) == "ETC"


def test_explicit_lowercase_normalized():
    """LLM 이 소문자 또는 dash 포함 출력해도 정규화."""
    assert _derive_clause_type(
        pain_point_id=None, title="개인정보",
        description="...", explicit="terms-change",
    ) == "TERMS_CHANGE"


def test_user_real_case_data_provision():
    """사용자 보고 사례 1 — 개인정보 제3자 제공 (ETC → PRIVACY 회복)."""
    out = _derive_clause_type(
        pain_point_id="PRE-04",
        title="개인정보 제3자 제공",
        description="수집된 회원 정보는 수사기관, 정부기관, 판매자, 배송업체 등에 제공",
        explicit=None,
    )
    assert out == "PRIVACY"


def test_user_real_case_terms_change_notice():
    """사용자 보고 사례 2 — 약관 변경 사전 고지 기간 (ETC → TERMS_CHANGE 회복)."""
    out = _derive_clause_type(
        pain_point_id="MID-01",
        title="약관 변경 사전 고지 기간",
        description="회사는 약관을 개정할 경우 적용일자 7일 전부터 공지합니다",
        explicit=None,
    )
    assert out == "TERMS_CHANGE"


def test_user_real_case_service_disruption():
    """사용자 보고 사례 3 — 서비스 중단 시 배상 (ETC → LIABILITY 회복)."""
    out = _derive_clause_type(
        pain_point_id="POST-04",
        title="서비스 중단 시 배상",
        description="회사가 고의·과실이 없으면 배상하지 않을 수 있습니다",
        explicit=None,
    )
    assert out == "LIABILITY"


def test_user_real_case_deemed_agreed():
    """사용자 보고 사례 4 — 약관 변경 시 자동 동의 (ETC → TERMS_CHANGE 회복)."""
    out = _derive_clause_type(
        pain_point_id="MID-02",
        title="약관 변경 시 자동 동의(Deemed Agreed)",
        description="이용자가 거부의사를 표명하지 않으면 동의로 간주",
        explicit=None,
    )
    assert out == "TERMS_CHANGE"
