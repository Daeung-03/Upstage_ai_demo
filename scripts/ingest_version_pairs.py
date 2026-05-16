"""약관 변경점(diff) 데모용 — 한 서비스의 과거→현재 버전을 시간 순으로 업로드.

`/terms/upload` 의 diff 는 항상 (직전 latest 버전) → (방금 올린 버전) 방향이라,
진짜 과거 버전을 먼저 올리고 현재 버전을 `/{term_id}/update` 로 이어 올려야
diff_summary 가 과거→현재 방향으로 정확히 계산된다 (역방향 업로드 시 "추가"와
"삭제"가 뒤집힘).

각 서비스마다:
  1. (기본) 같은 service_name 의 기존 term 을 DELETE — bulk 업로드본 정리
  2. v_past 를 POST /terms/upload  → term_id 확보
  3. v_current 를 POST /terms/{term_id}/update (include_user_impact=true) → diff 생성

사용:
    .venv/bin/python scripts/ingest_version_pairs.py
    .venv/bin/python scripts/ingest_version_pairs.py --only banksalad,netflix
    .venv/bin/python scripts/ingest_version_pairs.py --no-delete
    .venv/bin/python scripts/ingest_version_pairs.py --base-url http://localhost:8000

사전조건: 대상 서버에 DELETE /terms/{id} 엔드포인트가 배포돼 있어야 함.
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


class VersionPair(TypedDict):
    key: str               # --only 필터용 식별자
    service_name: str
    domain: str
    sub_category: str
    subscribed_at: str          # ISO date — v_past 가입 시점 가정값
    past_file: str              # data/fixtures/<past_file>
    past_effective: str         # 과거 버전 시행일 ISO date
    current_file: str
    current_effective: str      # 현재 버전 시행일 ISO date


# 출처: banksalad=policies.banksalad.com 버전별 URL, netflix/youtube/twitch=
# Open Terms Archive (github.com/OpenTermsArchive/contrib-versions) git history.
PAIRS: list[VersionPair] = [
    {
        "key": "banksalad",
        "service_name": "뱅크샐러드", "domain": "FINANCE", "sub_category": "PFM/자산관리",
        "subscribed_at": "2022-01-15",
        "past_file": "banksalad_terms_v1.html", "past_effective": "2021-12-14",
        "current_file": "banksalad_terms_v2.html", "current_effective": "2024-09-15",
    },
    {
        "key": "netflix",
        "service_name": "Netflix", "domain": "OTT", "sub_category": "동영상 스트리밍",
        "subscribed_at": "2024-10-01",
        "past_file": "netflix_terms_past.html", "past_effective": "2024-09-01",
        "current_file": "netflix_terms_current.html", "current_effective": "2026-04-19",
    },
    {
        "key": "youtube",
        "service_name": "YouTube", "domain": "APP", "sub_category": "소셜/커뮤니티",
        "subscribed_at": "2025-01-15",
        "past_file": "youtube_terms_past.html", "past_effective": "2024-12-12",
        "current_file": "youtube_terms_current.html", "current_effective": "2026-05-15",
    },
    {
        "key": "twitch",
        "service_name": "Twitch", "domain": "APP", "sub_category": "소셜/커뮤니티",
        "subscribed_at": "2022-10-01",
        "past_file": "twitch_terms_past.html", "past_effective": "2022-08-27",
        "current_file": "twitch_terms_current.html", "current_effective": "2024-08-14",
    },
]


async def _delete_existing(
    client: httpx.AsyncClient, base_url: str, service_name: str
) -> list[str]:
    """같은 service_name 의 기존 term 을 모두 DELETE. 삭제된 term_id 리스트 반환."""
    resp = await client.get(f"{base_url}/terms", timeout=60.0)
    resp.raise_for_status()
    items = resp.json().get("items", [])
    deleted: list[str] = []
    for it in items:
        if it.get("service_name") == service_name:
            tid = it["id"]
            d = await client.delete(f"{base_url}/terms/{tid}", timeout=120.0)
            if d.status_code in (204, 404):
                deleted.append(tid)
            else:
                raise RuntimeError(
                    f"DELETE /terms/{tid} 실패: {d.status_code} {d.text[:200]}"
                )
    return deleted


async def _ingest_one(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    base_url: str,
    pair: VersionPair,
    do_delete: bool,
    user_impact: bool,
) -> dict:
    """한 서비스의 과거→현재 버전 시퀀스 처리. 결과 dict 반환."""
    past = FIXTURE_DIR / pair["past_file"]
    cur = FIXTURE_DIR / pair["current_file"]
    if not past.exists() or not cur.exists():
        return {"key": pair["key"], "ok": False,
                "error": f"fixture 없음 ({past.name} / {cur.name})"}

    async with sem:
        t0 = time.perf_counter()
        try:
            deleted: list[str] = []
            if do_delete:
                deleted = await _delete_existing(client, base_url, pair["service_name"])

            # 1) v_past → POST /terms/upload
            up_data = {
                "service_name": pair["service_name"],
                "domain": pair["domain"],
                "sub_category": pair["sub_category"],
                "subscribed_at": pair["subscribed_at"],
                "effective_date": pair["past_effective"],
            }
            up_files = {"file": (past.name, past.read_bytes(), "text/html")}
            up = await client.post(
                f"{base_url}/terms/upload", data=up_data, files=up_files, timeout=1000.0
            )
            if up.status_code != 201:
                return {"key": pair["key"], "ok": False,
                        "error": f"upload {up.status_code}: {up.text[:300]}"}
            term_id = up.json()["id"]

            # 2) v_current → POST /terms/{id}/update (diff 생성)
            upd_data = {
                "effective_date": pair["current_effective"],
                "include_user_impact": "true" if user_impact else "false",
            }
            upd_files = {"file": (cur.name, cur.read_bytes(), "text/html")}
            upd = await client.post(
                f"{base_url}/terms/{term_id}/update",
                data=upd_data, files=upd_files, timeout=1000.0,
            )
            if upd.status_code != 201:
                return {"key": pair["key"], "ok": False, "term_id": term_id,
                        "error": f"update {upd.status_code}: {upd.text[:300]}"}
        except Exception as exc:
            # httpx.HTTPError 외에 raw ssl.SSLError 등도 잡아 한 서비스 실패가
            # 다른 서비스 task 를 죽이지 않게 격리.
            return {"key": pair["key"], "ok": False,
                    "error": f"transport: {type(exc).__name__}: {exc}"}
        dt = time.perf_counter() - t0

    payload = upd.json()
    return {
        "key": pair["key"], "ok": True,
        "term_id": term_id,
        "deleted": deleted,
        "new_version": payload.get("new_version"),
        "diff_summary": payload.get("diff_summary"),
        "user_impact": payload.get("user_impact"),
        "elapsed": dt,
    }


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--base-url",
        default="https://upstageaidemo-production.up.railway.app",
        help="FastAPI 서버 base URL (default: Railway production)",
    )
    parser.add_argument("--concurrency", type=int, default=2,
                        help="동시 처리 서비스 수 (default: 2)")
    parser.add_argument("--only", default="",
                        help="콤마 구분 key 만 처리 (예: banksalad,netflix)")
    parser.add_argument("--no-delete", action="store_true",
                        help="기존 동일 service_name term 삭제 단계 건너뜀")
    parser.add_argument("--user-impact", action="store_true",
                        help="/update 시 include_user_impact=true (개별 사용자 영향 자유문 생성)")
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    targets = PAIRS
    if args.only:
        wanted = {s.strip() for s in args.only.split(",") if s.strip()}
        targets = [p for p in PAIRS if p["key"] in wanted]
        missing = wanted - {p["key"] for p in targets}
        if missing:
            print(f"WARN: unknown key(s) skipped: {sorted(missing)}", flush=True)
    if not targets:
        print("ERROR: 처리할 pair 없음.", file=sys.stderr)
        return 1

    print(f"Ingesting {len(targets)} version-pair(s) → {base_url} "
          f"(concurrency={args.concurrency}, delete={'no' if args.no_delete else 'yes'})",
          flush=True)

    sem = asyncio.Semaphore(args.concurrency)
    results: list[dict] = []
    async with httpx.AsyncClient() as client:
        tasks = [
            _ingest_one(client, sem, base_url, p, not args.no_delete, args.user_impact)
            for p in targets
        ]
        for coro in asyncio.as_completed(tasks):
            r = await coro
            results.append(r)
            if r["ok"]:
                diff = (r.get("diff_summary") or "").replace("\n", " ")
                print(f"  OK   {r['key']:<12} term={r['term_id']} v{r['new_version']} "
                      f"({r['elapsed']:.0f}s)", flush=True)
                print(f"       diff: {diff[:160]}", flush=True)
            else:
                print(f"  FAIL {r['key']:<12} → {r.get('error')}", flush=True)

    ok = sum(1 for r in results if r["ok"])
    print(f"\nDone: {ok}/{len(results)} succeeded.", flush=True)
    return 0 if ok == len(results) else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
