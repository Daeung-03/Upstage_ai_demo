"""공개된 약관 페이지에서 텍스트 추출 → data/fixtures/<service>_terms.html 저장.

각 서비스마다 SPA 구조가 달라 fetch 로직 분리.
HTML 파일은 .gitignore 되어 있어 각 환경에서 이 스크립트로 재현 가능.

사용:
    .venv/bin/python scripts/fetch_public_terms.py netflix    # (수동: PDF 다운로드 안내만 출력)
    .venv/bin/python scripts/fetch_public_terms.py spotify    # Spotify Korea ToS 자동 추출
    .venv/bin/python scripts/fetch_public_terms.py wavve      # Wavve API 직접 호출
    .venv/bin/python scripts/fetch_public_terms.py claude     # Anthropic consumer + privacy
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
    import gzip

    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            body = gzip.decompress(body)
        return body


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


def _extract_anthropic_article(html: str, url: str) -> str:
    """Anthropic 법무 페이지에서 <article class="...legal-page"> 본문만 추출."""
    m = re.search(
        r'(<article[^>]*LegalPageDetail-module[^>]*legal-page[^>]*>.*?</article>)',
        html,
        re.DOTALL,
    )
    if not m:
        raise RuntimeError(f"Anthropic: legal-page article not found at {url} (page structure changed?)")
    return m.group(1)


def _get_via_wayback(url: str) -> bytes:
    """Cloudflare 차단 등으로 직접 접근 불가한 도메인은 Wayback `id_` raw snapshot 사용.

    availability API로 최신 스냅샷 timestamp를 찾고 `<ts>id_/` 모드로 받음 (toolbar 제거).
    """
    import gzip

    avail_url = f"http://archive.org/wayback/available?url={url}"
    avail_req = urllib.request.Request(avail_url, headers={"User-Agent": UA})
    with urllib.request.urlopen(avail_req, timeout=30) as resp:
        avail = json.loads(resp.read())
    snap = avail.get("archived_snapshots", {}).get("closest")
    if not snap or snap.get("status") != "200":
        raise RuntimeError(f"Wayback: no usable snapshot for {url}")
    ts = snap["timestamp"]
    raw_url = f"https://web.archive.org/web/{ts}id_/{url}"
    req = urllib.request.Request(
        raw_url,
        headers={"User-Agent": UA, "Accept-Encoding": "gzip"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            body = gzip.decompress(body)
        return body


def _extract_openai_article(html: str, url: str) -> str:
    """OpenAI 정책 페이지의 본문 `<article class="gap-lg...">` 영역만 추출."""
    m = re.search(
        r'(<article class="gap-lg[^"]*">.*?</article>)',
        html,
        re.DOTALL,
    )
    if not m:
        raise RuntimeError(f"OpenAI: gap-lg article not found at {url} (page structure changed?)")
    return m.group(1)


def fetch_gemini() -> None:
    """Google 일반 약관 + 개인정보 + Gemini Apps 추가 약관 결합 (한국어 변형)."""
    docs = [
        ("https://policies.google.com/terms?hl=ko", "Google 서비스 약관"),
        ("https://policies.google.com/privacy?hl=ko", "Google 개인정보처리방침"),
        ("https://policies.google.com/terms/generative-ai?hl=ko", "Gemini Apps 추가 서비스 약관"),
    ]
    body_parts = []
    total = 0
    for url, title in docs:
        html = _get(url).decode("utf-8", errors="ignore")
        # Google 정책 페이지의 본문 컨테이너 `<div id="main-content" class="vwhFIf">`.
        # 페이지에 footer/main 클로징 태그가 없어 main-content 이후 trailing script까지 포함.
        m = re.search(r'<div id="main-content"[^>]*>(.*)</body>', html, re.DOTALL)
        if not m:
            raise RuntimeError(f"Gemini: #main-content not found at {url}")
        article = m.group(1)
        # 끝부분 script 블록 정리
        article = re.sub(r"<script[^>]*>.*?</script>", "", article, flags=re.DOTALL)
        body_parts.append(f"<hr><h1>{title}</h1>\n<p><em>Source: {url}</em></p>\n{article}\n")
        total += len(article)
    wrapped = (
        '<!DOCTYPE html>\n<html lang="ko"><head><meta charset="UTF-8">'
        '<title>Google + Gemini Apps 약관</title></head>'
        f'<body>\n{"".join(body_parts)}\n</body></html>\n'
    )
    out = FIXTURE_DIR / "gemini_terms.html"
    out.write_text(wrapped, encoding="utf-8")
    print(f"  → gemini_terms.html ({len(docs)} docs, total {total:,} chars)")


def fetch_upstage() -> None:
    """Upstage 서비스 약관 + 개인정보처리방침 결합."""
    docs = [
        ("https://www.upstage.ai/terms-of-service", "Upstage 서비스 이용약관"),
        ("https://www.upstage.ai/privacy-policy", "Upstage 개인정보처리방침"),
    ]
    body_parts = []
    total = 0
    for url, title in docs:
        html = _get(url).decode("utf-8", errors="ignore")
        # blog-ko-rich-text 가 여러 개 — KO/EN 탭. 가장 긴 것을 사용 (한국어 본문).
        matches = re.findall(
            r'<div class="[^"]*blog-ko-rich-text[^"]*w-richtext[^"]*"[^>]*>(.*?)</div>\s*</div>',
            html,
            re.DOTALL,
        )
        if not matches:
            # fallback: 모든 rich-text
            matches = re.findall(
                r'<div class="[^"]*w-richtext[^"]*"[^>]*>(.*?)</div>',
                html,
                re.DOTALL,
            )
        if not matches:
            raise RuntimeError(f"Upstage: rich-text wrapper not found at {url}")
        article = max(matches, key=len)
        body_parts.append(f"<hr><h1>{title}</h1>\n<p><em>Source: {url}</em></p>\n{article}\n")
        total += len(article)
    wrapped = (
        '<!DOCTYPE html>\n<html lang="ko"><head><meta charset="UTF-8">'
        '<title>Upstage 이용약관 + 개인정보처리방침</title></head>'
        f'<body>\n{"".join(body_parts)}\n</body></html>\n'
    )
    out = FIXTURE_DIR / "upstage_terms.html"
    out.write_text(wrapped, encoding="utf-8")
    print(f"  → upstage_terms.html ({len(docs)} docs, total {total:,} chars)")


def fetch_deepseek() -> None:
    """DeepSeek 이용약관 + 개인정보보호정책 결합 (cdn.deepseek.com 한국어 호스팅).

    경로는 `/en-US/` 이지만 실제 콘텐츠는 한국어로 서빙됨 (확인됨, 2026-05).
    """
    docs = [
        (
            "https://cdn.deepseek.com/policies/en-US/deepseek-terms-of-use.html",
            "DeepSeek 이용약관",
        ),
        (
            "https://cdn.deepseek.com/policies/en-US/deepseek-privacy-policy.html",
            "DeepSeek 개인정보보호정책",
        ),
    ]
    body_parts = []
    total = 0
    for url, title in docs:
        html = _get(url).decode("utf-8", errors="ignore")
        m = re.search(r'(<div id="write"[^>]*>.*?</div>)\s*</body>', html, re.DOTALL)
        if not m:
            # fallback: div#write 끝 매칭 실패 시 시작부터 body 끝까지
            m = re.search(r'(<div id="write"[^>]*>.*)', html, re.DOTALL)
        if not m:
            raise RuntimeError(f"DeepSeek: #write block not found at {url}")
        article = m.group(1)
        body_parts.append(f"<hr><h1>{title}</h1>\n<p><em>Source: {url}</em></p>\n{article}\n")
        total += len(article)
    wrapped = (
        '<!DOCTYPE html>\n<html lang="ko"><head><meta charset="UTF-8">'
        '<title>DeepSeek 이용약관 + 개인정보보호정책</title></head>'
        f'<body>\n{"".join(body_parts)}\n</body></html>\n'
    )
    out = FIXTURE_DIR / "deepseek_terms.html"
    out.write_text(wrapped, encoding="utf-8")
    print(f"  → deepseek_terms.html ({len(docs)} docs, total {total:,} chars)")


def fetch_gpt() -> None:
    """OpenAI ROW Terms of Use + ROW Privacy Policy 결합.

    openai.com이 Cloudflare로 직접 fetch를 차단 → Wayback raw snapshot 경유.
    ROW (Rest of World) 약관이 한국 거주자에게 적용됨.
    """
    docs = []
    for slug, title in (
        ("row-terms-of-use", "Terms of Use (ROW)"),
        ("row-privacy-policy", "Privacy Policy (ROW)"),
    ):
        url = f"https://openai.com/policies/{slug}/"
        html = _get_via_wayback(url).decode("utf-8", errors="ignore")
        article = _extract_openai_article(html, url)
        docs.append((title, url, article))

    body_parts = [
        f"<hr><h1>OpenAI {title}</h1>\n<p><em>Source: {url}</em></p>\n{article}\n"
        for title, url, article in docs
    ]
    wrapped = (
        '<!DOCTYPE html>\n<html lang="en"><head><meta charset="UTF-8">'
        '<title>OpenAI ROW Terms + Privacy Policy</title></head>'
        f'<body>\n{"".join(body_parts)}\n</body></html>\n'
    )
    out = FIXTURE_DIR / "gpt_terms.html"
    out.write_text(wrapped, encoding="utf-8")
    total = sum(len(a) for _, _, a in docs)
    print(f"  → gpt_terms.html ({len(docs)} docs, total {total:,} chars)")


def fetch_claude() -> None:
    """Anthropic Consumer Terms + Privacy Policy 결합.

    Wavve 패턴과 동일 — 구독 조항(consumer terms §6)과 데이터 학습/보존 조항
    (privacy §1, §6)이 다른 문서에 분산. 한쪽만 가져오면 data_usage 섹션 손실.
    """
    docs = []
    for slug, title in (
        ("consumer-terms", "Consumer Terms of Service"),
        ("privacy", "Privacy Policy"),
    ):
        url = f"https://www.anthropic.com/legal/{slug}"
        html = _get(url).decode("utf-8", errors="ignore")
        article = _extract_anthropic_article(html, url)
        docs.append((title, url, article))

    body_parts = [
        f"<hr><h1>Anthropic {title}</h1>\n<p><em>Source: {url}</em></p>\n{article}\n"
        for title, url, article in docs
    ]
    wrapped = (
        '<!DOCTYPE html>\n<html lang="en"><head><meta charset="UTF-8">'
        '<title>Anthropic Consumer Terms + Privacy Policy</title></head>'
        f'<body>\n{"".join(body_parts)}\n</body></html>\n'
    )
    out = FIXTURE_DIR / "claude_terms.html"
    out.write_text(wrapped, encoding="utf-8")
    total = sum(len(a) for _, _, a in docs)
    print(f"  → claude_terms.html ({len(docs)} docs, total {total:,} chars)")


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
    elif service == "claude":
        print("Fetching Anthropic Consumer Terms + Privacy Policy...")
        fetch_claude()
    elif service == "gpt":
        print("Fetching OpenAI ROW Terms + Privacy (via Wayback)...")
        fetch_gpt()
    elif service == "gemini":
        print("Fetching Google ToS + Privacy + Gemini Apps additional terms...")
        fetch_gemini()
    elif service == "upstage":
        print("Fetching Upstage ToS + Privacy Policy...")
        fetch_upstage()
    elif service == "deepseek":
        print("Fetching DeepSeek ToS + Privacy Policy...")
        fetch_deepseek()
    elif service == "all":
        print("Fetching Spotify + Wavve...")
        fetch_spotify()
        fetch_wavve()
    else:
        print(f"Unknown service: {service}")
        sys.exit(1)


if __name__ == "__main__":
    main()
