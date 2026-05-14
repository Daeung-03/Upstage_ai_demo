"""공개된 약관 페이지에서 텍스트 추출 → data/fixtures/<service>_terms.html 저장.

각 서비스마다 SPA 구조가 달라 fetch 로직 분리.
HTML 파일은 .gitignore 되어 있어 각 환경에서 이 스크립트로 재현 가능.

사용:
    .venv/bin/python scripts/fetch_public_terms.py netflix    # (수동: PDF 다운로드 안내만 출력)
    .venv/bin/python scripts/fetch_public_terms.py spotify    # Spotify Korea ToS 자동 추출
    .venv/bin/python scripts/fetch_public_terms.py wavve      # Wavve API 직접 호출
    .venv/bin/python scripts/fetch_public_terms.py all        # spotify + wavve
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = ROOT / "data" / "fixtures"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def fetch_spotify() -> None:
    """Spotify Korea EUA — Next.js __NEXT_DATA__.props.pageProps.document HTML."""
    url = "https://www.spotify.com/kr-ko/legal/end-user-agreement/"
    html = _get(url).decode("utf-8", errors="ignore")
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.+?)</script>', html, re.DOTALL)
    if not m:
        raise RuntimeError("Spotify: __NEXT_DATA__ not found (page structure changed?)")
    data = json.loads(m.group(1))
    doc = data["props"]["pageProps"]["document"]
    wrapped = (
        '<!DOCTYPE html>\n<html lang="ko"><head><meta charset="UTF-8">'
        f'<title>Spotify 이용약관 (KR) — fetched from {url}</title></head>'
        f'<body>\n{doc}\n</body></html>\n'
    )
    out = FIXTURE_DIR / "spotify_terms.html"
    out.write_text(wrapped, encoding="utf-8")
    print(f"  → spotify_terms.html ({len(doc):,} chars)")


def fetch_wavve() -> None:
    """Wavve 약관 — service + payment 두 문서를 결합해 저장.

    Wavve는 `서비스 이용약관`과 `유료상품 이용약관`이 분리되어 있어
    한 쪽만 가져오면 pricing/refund 조항을 못 찾음 (실측: 결합 시 pricing 17%→50%).
    """
    docs = []
    for term_type, title in (("service", "서비스 이용약관"), ("payment", "유료상품 이용약관")):
        raw = _get(f"https://apis.wavve.com/terms?type={term_type}&version=last")
        data = json.loads(raw)
        content = data.get("content", "")
        if not content:
            raise RuntimeError(f"Wavve {term_type}: content field empty (API changed?)")
        docs.append((title, data.get("version", "?"), data.get("effectivedate", "?"), content))

    body_parts = []
    for title, version, effective, content in docs:
        body_parts.append(
            f"<hr><h1>Wavve {title} (v{version}, effective {effective})</h1>\n{content}\n"
        )
    wrapped = (
        '<!DOCTYPE html>\n<html lang="ko"><head><meta charset="UTF-8">'
        '<title>Wavve 이용약관 (서비스 + 유료상품)</title></head>'
        f'<body>\n{"".join(body_parts)}\n</body></html>\n'
    )
    out = FIXTURE_DIR / "wavve_terms.html"
    out.write_text(wrapped, encoding="utf-8")
    total = sum(len(c) for _, _, _, c in docs)
    versions = " + ".join(f"{t} v{v}" for t, v, _, _ in docs)
    print(f"  → wavve_terms.html ({versions}, total {total:,} chars)")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    service = sys.argv[1].lower()
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    if service == "netflix":
        print("Netflix: PDF 다운로드 필요 (https://help.netflix.com/ko/legal/termsofuse).")
        print("브라우저에서 출력 → PDF 저장 후 data/fixtures/netflix_terms.pdf 로 두시면 됩니다.")
        return
    if service == "spotify":
        print("Fetching Spotify Korea ToS...")
        fetch_spotify()
    elif service == "wavve":
        print("Fetching Wavve service agreement...")
        fetch_wavve()
    elif service == "all":
        print("Fetching Spotify + Wavve...")
        fetch_spotify()
        fetch_wavve()
    else:
        print(f"Unknown service: {service}")
        sys.exit(1)


if __name__ == "__main__":
    main()
