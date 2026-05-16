"""지원 서비스 (vendor) 의 canonical slug + alias + 도메인 매핑.

Single source of truth. 프론트는 `GET /vendors` 로 받아서 카테고리 드롭다운에
사용. 백엔드는 업로드 시 `service_name` 을 alias 로 보고 canonical slug + domain
자동 매핑.

총 16 vendor: OTT 6 + FINANCE 3 + APP 1 + AI 5 + INSURANCE 1
(그 외 = ETC, vendor_slug=None).

slug 규칙: 소문자 + `-` 구분 (kebab-case). 프론트의 NAME_ALIASES 와 동일.
"""
from __future__ import annotations

from typing import TypedDict


class VendorDef(TypedDict):
    display_name: str
    aliases: list[str]
    domain: str  # TermDomain enum value (OTT / FINANCE / APP / ...)


# 명시적으로 dict 의 삽입 순서 = canonical 카탈로그 정렬 (도메인별 묶음).
VENDORS: dict[str, VendorDef] = {
    # ── OTT (5) ─────────────────────────────────────────
    "netflix": {
        "display_name": "Netflix",
        "aliases": ["넷플릭스", "netflix"],
        "domain": "OTT",
    },
    "disney-plus": {
        "display_name": "Disney+",
        "aliases": ["디즈니+", "디즈니플러스", "disney+", "disneyplus", "disney plus"],
        "domain": "OTT",
    },
    "coupang-play": {
        "display_name": "쿠팡 플레이",
        "aliases": ["쿠팡플레이", "쿠팡 플레이", "coupangplay", "coupang play"],
        "domain": "OTT",
    },
    "tving": {
        "display_name": "티빙",
        "aliases": ["티빙", "tving"],
        "domain": "OTT",
    },
    "watcha": {
        "display_name": "왓챠",
        "aliases": ["왓챠", "watcha"],
        "domain": "OTT",
    },
    "wavve": {
        "display_name": "Wavve",
        "aliases": ["웨이브", "wavve"],
        "domain": "OTT",
    },
    # ── FINANCE (3) ─────────────────────────────────────
    "kakao-pay": {
        "display_name": "카카오페이",
        "aliases": ["카카오페이", "kakaopay", "kakao pay"],
        "domain": "FINANCE",
    },
    "toss": {
        "display_name": "토스",
        "aliases": ["토스", "toss"],
        "domain": "FINANCE",
    },
    "bank-salad": {
        "display_name": "뱅크샐러드",
        "aliases": ["뱅크샐러드", "banksalad", "bank salad"],
        "domain": "FINANCE",
    },
    # ── APP (1) — Spotify 만 ────────────────────────────
    "spotify": {
        "display_name": "Spotify",
        "aliases": ["스포티파이", "spotify"],
        "domain": "APP",
    },
    # ── AI 어시스턴트 (5) ────────────────────────────────
    "chatgpt": {
        "display_name": "ChatGPT",
        "aliases": ["챗gpt", "챗GPT", "chat gpt", "chatgpt", "gpt"],
        "domain": "AI",
    },
    "claude": {
        "display_name": "Claude",
        "aliases": ["클로드", "claude"],
        "domain": "AI",
    },
    "deepseek": {
        "display_name": "DeepSeek",
        "aliases": ["딥시크", "deepseek"],
        "domain": "AI",
    },
    "gemini": {
        "display_name": "Gemini",
        "aliases": ["제미나이", "제미니", "gemini"],
        "domain": "AI",
    },
    "upstage": {
        "display_name": "Upstage",
        "aliases": ["업스테이지", "upstage"],
        "domain": "AI",
    },
    # ── INSURANCE (1) ───────────────────────────────────
    # 캐롯손해보험 — 단일 보험사 vendor. 상품(자동차/해외여행)별 약관은 같은
    # vendor_slug 아래 sub_category 로 구분. 상품명도 alias 에 포함해 상품명으로
    # 업로드해도 canonical slug 로 매핑되게 함.
    "carrot": {
        "display_name": "캐롯손해보험",
        "aliases": [
            "캐롯", "캐롯손해보험", "캐롯손보", "carrot",
            "캐롯 자동차보험", "캐롯 해외여행보험",
        ],
        "domain": "INSURANCE",
    },
}


# ── 역인덱스 (조회 빠르게) ──────────────────────────────
# alias(소문자, strip) → canonical slug. slug 자체도 키로 포함 (자기 자신 매핑).
_ALIAS_INDEX: dict[str, str] = {}
for _slug, _meta in VENDORS.items():
    _ALIAS_INDEX[_slug] = _slug
    for _a in _meta["aliases"]:
        _ALIAS_INDEX[_a.strip().lower()] = _slug


def canonical_vendor_slug(name: str | None) -> str | None:
    """service_name (사용자 입력) → canonical slug.

    매칭 못 찾으면 None. 호출자는 None 일 때 vendor_slug 컬럼에 NULL 저장 +
    domain 은 사용자 입력 (또는 'ETC') 그대로 둠.

    정규화: strip + lowercase. 한국어 alias 는 그대로 (소문자 무관),
    영문 alias 는 lowercase 매칭.
    """
    if not name:
        return None
    key = name.strip().lower()
    return _ALIAS_INDEX.get(key)


def vendor_domain(slug: str) -> str | None:
    """vendor slug 의 권장 도메인 (TermDomain enum value).

    slug 가 VENDORS 에 없으면 None — 호출자가 ETC 등으로 fallback.
    """
    meta = VENDORS.get(slug)
    return meta["domain"] if meta else None
