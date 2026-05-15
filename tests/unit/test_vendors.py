"""vendor 카탈로그 + canonicalization + /vendors 엔드포인트 테스트."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.vendors import (
    VENDORS,
    canonical_vendor_slug,
    vendor_domain,
)


client = TestClient(app)


def test_vendors_catalog_has_15_services():
    assert len(VENDORS) == 15


def test_vendors_catalog_domain_distribution():
    counts: dict[str, int] = {}
    for meta in VENDORS.values():
        counts[meta["domain"]] = counts.get(meta["domain"], 0) + 1
    assert counts == {"OTT": 6, "FINANCE": 3, "APP": 1, "AI": 5}


def test_all_slugs_are_kebab_case():
    for slug in VENDORS:
        assert slug == slug.lower(), f"non-lowercase slug: {slug}"
        assert " " not in slug, f"slug has space: {slug}"
        assert "_" not in slug, f"slug has underscore: {slug}"


def test_each_vendor_has_at_least_one_alias():
    for slug, meta in VENDORS.items():
        assert len(meta["aliases"]) >= 1, f"{slug} has no aliases"


@pytest.mark.parametrize("user_input,expected", [
    ("넷플릭스", "netflix"),
    ("Netflix", "netflix"),
    ("NETFLIX", "netflix"),
    ("netflix", "netflix"),
    ("  넷플릭스  ", "netflix"),
    ("디즈니+", "disney-plus"),
    ("디즈니플러스", "disney-plus"),
    ("Disney+", "disney-plus"),
    ("DISNEY PLUS", "disney-plus"),
    ("쿠팡 플레이", "coupang-play"),
    ("쿠팡플레이", "coupang-play"),
    ("coupangplay", "coupang-play"),
    ("카카오페이", "kakao-pay"),
    ("kakaopay", "kakao-pay"),
    ("토스", "toss"),
    ("티빙", "tving"),
    ("왓챠", "watcha"),
    ("스포티파이", "spotify"),
    ("챗gpt", "chatgpt"),
    ("CHAT GPT", "chatgpt"),
    ("GPT", "chatgpt"),
    ("클로드", "claude"),
    ("딥시크", "deepseek"),
    ("업스테이지", "upstage"),
    ("뱅크샐러드", "bank-salad"),
    ("banksalad", "bank-salad"),
    ("제미나이", "gemini"),
    ("제미니", "gemini"),
    ("Gemini", "gemini"),
    ("웨이브", "wavve"),
    ("WAVVE", "wavve"),
])
def test_canonical_vendor_slug_matches(user_input, expected):
    assert canonical_vendor_slug(user_input) == expected


@pytest.mark.parametrize("unknown", [
    "넷플릭스 코리아",
    "Apple TV",
    "유튜브",
    "random vendor",
    "",
])
def test_canonical_vendor_slug_unknown_returns_none(unknown):
    assert canonical_vendor_slug(unknown) is None


def test_canonical_vendor_slug_handles_none():
    assert canonical_vendor_slug(None) is None


def test_vendor_domain_returns_enum_value():
    assert vendor_domain("netflix") == "OTT"
    assert vendor_domain("kakao-pay") == "FINANCE"
    assert vendor_domain("claude") == "AI"
    assert vendor_domain("spotify") == "APP"
    assert vendor_domain("unknown-slug") is None


def test_get_vendors_returns_15():
    r = client.get("/vendors")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 15
    assert len(body["vendors"]) == 15


def test_get_vendors_each_item_shape():
    r = client.get("/vendors")
    body = r.json()
    for v in body["vendors"]:
        assert set(v.keys()) == {"slug", "display_name", "domain", "aliases"}
        assert v["domain"] in ("OTT", "FINANCE", "APP", "AI")
        assert len(v["aliases"]) >= 1


def test_get_vendors_includes_known_slugs():
    r = client.get("/vendors")
    slugs = {v["slug"] for v in r.json()["vendors"]}
    assert {"netflix", "claude", "kakao-pay", "spotify", "wavve"}.issubset(slugs)
