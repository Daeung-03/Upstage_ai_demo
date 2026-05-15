"""TermDomain 안의 권장 sub-category 정의.

DB 컬럼 (terms.sub_category) 은 자유 TEXT — 새 카테고리 추가 시 마이그레이션 없이
바로 사용 가능. 본 모듈은 *권장 vocab* 만 정의하므로 사이드바 UI 가 도메인 선택 시
드롭다운 채울 때 참고.

도메인 외 sub-category 가 들어와도 차단하지 않음 (서비스 운영 중 새 분야 발견 시
대응 비용 0). 단 잘못 입력된 vocab 은 사이드바 그룹 미스 될 수 있음.
"""

from __future__ import annotations

from app.models.enums import TermDomain

# 도메인별 권장 sub-category 리스트. UI 드롭다운 채울 때 사용.
RECOMMENDED_SUB_CATEGORIES: dict[TermDomain, list[str]] = {
    TermDomain.INSURANCE: [
        "실손의료보험", "생명보험", "암보험", "여행자보험",
        "자동차보험", "연금보험", "화재보험", "단체보험",
    ],
    TermDomain.FINANCE: [
        "PG/결제대행", "송금", "선불전자지급수단",
        "PFM/자산관리", "카드모집", "P2P/대출중개",
    ],
    TermDomain.OTT: [
        "동영상 스트리밍", "음악 스트리밍", "오디오북",
        "웹툰/웹소설", "라이브 방송",
    ],
    TermDomain.TELECOM: [
        "이동통신", "인터넷", "IPTV", "결합상품",
    ],
    TermDomain.MEDICAL: [
        "원격진료", "건강검진", "병원 예약/접수",
    ],
    TermDomain.APP: [
        "SaaS", "AI 어시스턴트", "유틸리티/생산성",
        "게임", "소셜/커뮤니티",
    ],
    TermDomain.ETC: [],
}


def is_recommended_sub_category(domain: TermDomain | str, sub: str) -> bool:
    """주어진 sub-category 가 해당 도메인의 권장 vocab 에 속하는지."""
    if not sub:
        return False
    try:
        d = TermDomain(domain) if isinstance(domain, str) else domain
    except ValueError:
        return False
    return sub in RECOMMENDED_SUB_CATEGORIES.get(d, [])


def recommendations_for(domain: TermDomain | str) -> list[str]:
    """도메인 권장 sub-category 리스트 — UI 드롭다운 채움용."""
    try:
        d = TermDomain(domain) if isinstance(domain, str) else domain
    except ValueError:
        return []
    return list(RECOMMENDED_SUB_CATEGORIES.get(d, []))
