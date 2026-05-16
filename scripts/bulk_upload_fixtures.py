"""HTML/PDF fixture 를 `/terms/upload` 엔드포인트로 자동 업로드 (15개; toss/spotify 는 수동).

각 fixture 의 5개 form 필드 (service_name / subscribed_at / effective_date /
domain / sub_category) 를 미리 매핑해두고 multipart 요청을 전송한다. 파이프라인이
동기 실행이라 한 건당 30s~수분 걸리므로 default 는 **순차 처리**.

사용:
    # default = Railway production
    .venv/bin/python scripts/bulk_upload_fixtures.py
    # 로컬 dev 서버로 보내고 싶을 때
    .venv/bin/python scripts/bulk_upload_fixtures.py --base-url http://localhost:8000
    .venv/bin/python scripts/bulk_upload_fixtures.py --only netflix,spotify
    .venv/bin/python scripts/bulk_upload_fixtures.py --concurrency 3
    .venv/bin/python scripts/bulk_upload_fixtures.py --subscribed-at 2026-01-15
    # ↑ 전체 fixture 의 subscribed_at 을 일괄 override
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path
from typing import TypedDict

import httpx

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = ROOT / "data" / "fixtures"


class FixtureSpec(TypedDict):
    stem: str            # data/fixtures/<stem>_terms.html
    service_name: str
    domain: str          # FINANCE/OTT/INSURANCE/APP/AI/MEDICAL/TELECOM/ETC
    sub_category: str | None
    subscribed_at: str | None  # ISO date YYYY-MM-DD
    effective_date: str | None  # ISO date YYYY-MM-DD (약관 시행일)


# 데모용 default — 약관 시행일은 서비스 공개 약관 페이지 기준 대략치.
# 모르면 None 두고 프론트 fallback (created_at) 에 맡겨도 됨.
FIXTURES: list[FixtureSpec] = [
    # OTT — 동영상 스트리밍
    {"stem": "netflix",      "service_name": "Netflix",     "domain": "OTT",
     "sub_category": "동영상 스트리밍", "subscribed_at": "2025-09-01", "effective_date": "2024-11-01"},
    {"stem": "disney_plus",  "service_name": "Disney+",     "domain": "OTT",
     "sub_category": "동영상 스트리밍", "subscribed_at": "2025-09-01", "effective_date": "2024-06-01"},
    {"stem": "wavve",        "service_name": "wavve",       "domain": "OTT",
     "sub_category": "동영상 스트리밍", "subscribed_at": "2025-09-01", "effective_date": "2024-12-01"},
    {"stem": "tving",        "service_name": "TVING",       "domain": "OTT",
     "sub_category": "동영상 스트리밍", "subscribed_at": "2025-09-01", "effective_date": "2024-10-01"},
    {"stem": "watcha",       "service_name": "왓챠",         "domain": "OTT",
     "sub_category": "동영상 스트리밍", "subscribed_at": "2025-09-01", "effective_date": "2024-08-01"},
    {"stem": "coupang_play", "service_name": "쿠팡플레이",   "domain": "OTT",
     "sub_category": "동영상 스트리밍", "subscribed_at": "2025-09-01", "effective_date": "2025-01-01"},
    # spotify 는 수동 업로드용으로 제외
    # AI — 범용 어시스턴트
    {"stem": "claude",       "service_name": "Claude",      "domain": "AI",
     "sub_category": "범용 AI 어시스턴트", "subscribed_at": "2025-09-01", "effective_date": "2025-01-15"},
    {"stem": "gpt",          "service_name": "ChatGPT",     "domain": "AI",
     "sub_category": "범용 AI 어시스턴트", "subscribed_at": "2025-09-01", "effective_date": "2024-12-11"},
    {"stem": "gemini",       "service_name": "Gemini",      "domain": "AI",
     "sub_category": "범용 AI 어시스턴트", "subscribed_at": "2025-09-01", "effective_date": "2024-09-16"},
    {"stem": "deepseek",     "service_name": "DeepSeek",    "domain": "AI",
     "sub_category": "범용 AI 어시스턴트", "subscribed_at": "2025-09-01", "effective_date": "2024-11-01"},
    {"stem": "upstage",      "service_name": "Upstage",     "domain": "AI",
     "sub_category": "특화 모델", "subscribed_at": "2025-09-01", "effective_date": "2024-10-01"},
    # FINANCE  (toss 는 수동 업로드용으로 제외)
    {"stem": "kakaopay",     "service_name": "카카오페이",   "domain": "FINANCE",
     "sub_category": "PG/결제대행", "subscribed_at": "2025-09-01", "effective_date": "2025-01-01"},
    {"stem": "banksalad",    "service_name": "뱅크샐러드",   "domain": "FINANCE",
     "sub_category": "PFM/자산관리", "subscribed_at": "2025-09-01", "effective_date": "2024-11-15"},
    # INSURANCE — 캐롯손해보험 상품 약관 (PDF fixture). service_name 은 상품명이지만
    # vendors.py 의 carrot alias 에 등록돼 vendor_slug=carrot + domain=INSURANCE 로 매핑됨.
    {"stem": "carrot_auto",   "service_name": "캐롯 자동차보험",   "domain": "INSURANCE",
     "sub_category": "자동차보험", "subscribed_at": "2025-09-01", "effective_date": "2024-07-01"},
    {"stem": "carrot_travel", "service_name": "캐롯 해외여행보험", "domain": "INSURANCE",
     "sub_category": "여행자보험", "subscribed_at": "2025-09-01", "effective_date": "2023-08-10"},
]


# 확장자 → multipart content-type. .html 우선 — Netflix 처럼 둘 다 있으면
# parse 단을 우회하는 HTML 을 쓰고, 보험 약관처럼 PDF 만 있으면 PDF 로 fallback.
_FIXTURE_EXTS: list[tuple[str, str]] = [
    (".html", "text/html"),
    (".pdf", "application/pdf"),
]


def _resolve_fixture(stem: str) -> tuple[Path, str] | None:
    """<stem>_terms.{html,pdf} 중 존재하는 파일 + multipart content-type 반환."""
    for ext, content_type in _FIXTURE_EXTS:
        p = FIXTURE_DIR / f"{stem}_terms{ext}"
        if p.exists():
            return p, content_type
    return None


async def _upload_one(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    base_url: str,
    spec: FixtureSpec,
) -> dict:
    """단일 fixture 업로드. 결과 dict 반환 — main 에서 집계."""
    resolved = _resolve_fixture(spec["stem"])
    if resolved is None:
        return {"fixture": spec["stem"], "ok": False, "error": "fixture not found (.html/.pdf)"}
    fixture_path, content_type = resolved

    # data: 5개 form 필드 — None 인 optional 은 생략 (FastAPI Form(None) 매칭).
    data: dict[str, str] = {
        "service_name": spec["service_name"],
        "domain": spec["domain"],
    }
    if spec["sub_category"]:
        data["sub_category"] = spec["sub_category"]
    if spec["subscribed_at"]:
        data["subscribed_at"] = spec["subscribed_at"]
    if spec["effective_date"]:
        data["effective_date"] = spec["effective_date"]

    files = {"file": (fixture_path.name, fixture_path.read_bytes(), content_type)}
    url = f"{base_url.rstrip('/')}/terms/upload"

    async with sem:
        t0 = time.perf_counter()
        try:
            resp = await client.post(url, data=data, files=files, timeout=600.0)
        except httpx.HTTPError as exc:
            return {"fixture": spec["stem"], "ok": False, "error": f"transport: {exc}"}
        dt = time.perf_counter() - t0

    if resp.status_code != 201:
        return {
            "fixture": spec["stem"], "ok": False,
            "status": resp.status_code, "body": resp.text[:400], "elapsed": dt,
        }

    payload = resp.json()
    return {
        "fixture": spec["stem"], "ok": True,
        "term_id": payload.get("id"),
        "service_name": payload.get("service_name"),
        "domain": payload.get("domain"),
        "sub_category": payload.get("sub_category"),
        "version": payload.get("version"),
        "elapsed": dt,
    }


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--base-url",
        default="https://upstageaidemo-production.up.railway.app",
        help="FastAPI 서버 base URL "
             "(default: https://upstageaidemo-production.up.railway.app). "
             "로컬 dev 면 http://localhost:8000",
    )
    parser.add_argument("--concurrency", type=int, default=1,
                        help="동시 업로드 개수 (default: 1 = 순차). Upstage rate-limit 주의.")
    parser.add_argument("--only", default="",
                        help="콤마로 구분된 fixture stem 만 업로드 (예: netflix,spotify)")
    parser.add_argument("--subscribed-at", default=None,
                        help="모든 fixture 의 subscribed_at 을 이 값으로 override (YYYY-MM-DD)")
    parser.add_argument("--effective-date", default=None,
                        help="모든 fixture 의 effective_date 를 이 값으로 override (YYYY-MM-DD)")
    args = parser.parse_args()

    targets = FIXTURES
    if args.only:
        wanted = {s.strip() for s in args.only.split(",") if s.strip()}
        targets = [row for row in FIXTURES if row["stem"] in wanted]
        missing = wanted - {row["stem"] for row in targets}
        if missing:
            print(f"WARN: unknown fixture(s) skipped: {sorted(missing)}", flush=True)

    if args.subscribed_at:
        targets = [{**row, "subscribed_at": args.subscribed_at} for row in targets]
    if args.effective_date:
        targets = [{**row, "effective_date": args.effective_date} for row in targets]

    if not targets:
        print("ERROR: no fixtures to upload.", file=sys.stderr)
        return 1

    print(f"Uploading {len(targets)} fixtures → {args.base_url}/terms/upload "
          f"(concurrency={args.concurrency})", flush=True)

    sem = asyncio.Semaphore(args.concurrency)
    results: list[dict] = []
    async with httpx.AsyncClient() as client:
        tasks = [_upload_one(client, sem, args.base_url, spec) for spec in targets]
        for coro in asyncio.as_completed(tasks):
            r = await coro
            results.append(r)
            if r["ok"]:
                print(f"  OK   {r['fixture']:<14} → term_id={r['term_id']} "
                      f"({r['elapsed']:.1f}s)", flush=True)
            else:
                err = r.get("error") or f"HTTP {r.get('status')}: {r.get('body', '')[:200]}"
                print(f"  FAIL {r['fixture']:<14} → {err}", flush=True)

    ok = sum(1 for r in results if r["ok"])
    fail = len(results) - ok
    print(f"\nDone: {ok}/{len(results)} succeeded, {fail} failed.", flush=True)
    return 0 if fail == 0 else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
