"""여러 fixture를 *각각 다른 API 키*로 동시 실행.

`settings.eval_api_keys` 의 i번째 키를 i번째 fixture의 UpstageClient 에 주입해서
`asyncio.gather` 로 병렬 실행. 같은 키에 두 pipeline이 몰리지 않으므로
Upstage 429 rate limit 충돌 없음 (N=2 voting + ground 5~6회 호출/pipeline 기준).

사용:
    .venv/bin/python scripts/parallel_run.py toss kakaopay banksalad
        → data/fixtures/{name}_terms.{html,pdf}
        → /tmp/{name}_parallel_run.json (각각 별도)

옵션:
    --out-dir DIR    출력 디렉토리 (기본 /tmp)
    --suffix STR     출력 파일 접미사 (기본 "_parallel_run.json")

키 부족 시 동작:
    fixture 개수 > 키 개수 인 경우 *남은 fixture를 첫 키부터 round-robin* 으로 재할당.
    같은 키에 두 작업이 붙으면 rate limit 우려 → 일반적으로 fixture <= 키 권장.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai.pipeline import run_pipeline
from ai.services.settings import Settings
from ai.services.upstage import UpstageClient

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = ROOT / "data" / "fixtures"


def _resolve_fixture(name: str) -> Path:
    for ext in (".pdf", ".html"):
        candidate = FIXTURE_DIR / f"{name}_terms{ext}"
        if candidate.exists():
            return candidate
    return FIXTURE_DIR / f"{name}_terms.pdf"  # error sentinel


async def _run_one(
    fixture_name: str,
    fixture_path: Path,
    settings: Settings,
    api_key: str,
    key_idx: int,
    out_path: Path,
) -> dict:
    """파이프라인 1회 실행 + 결과 저장. dict로 메타 반환."""
    print(f"[{fixture_name}] start (key #{key_idx + 1})", flush=True)
    t0 = time.perf_counter()
    try:
        async with UpstageClient(settings, api_key=api_key) as client:
            result = await run_pipeline(
                client,
                file_bytes=fixture_path.read_bytes(),
                filename=fixture_path.name,
                service_name=fixture_name.replace("_", " ").title(),
                service_provider=fixture_name.replace("_", " ").title(),
            )
        elapsed = time.perf_counter() - t0
        total_tokens = sum(u.total_tokens for u in result.usage)
        out_path.write_text(
            json.dumps(result.model_dump(), ensure_ascii=False),
            encoding="utf-8",
        )
        print(
            f"[{fixture_name}] done in {elapsed:.1f}s  grounded={result.grounded}  "
            f"tokens={total_tokens:,}  → {out_path}",
            flush=True,
        )
        return {
            "fixture": fixture_name,
            "key_idx": key_idx,
            "elapsed_s": elapsed,
            "tokens": total_tokens,
            "grounded": result.grounded,
            "out_path": str(out_path),
            "timings": [(t.stage, round(t.seconds, 2)) for t in result.timings],
            "error": None,
        }
    except Exception as e:
        elapsed = time.perf_counter() - t0
        print(f"[{fixture_name}] FAILED after {elapsed:.1f}s: {type(e).__name__}: {e}", flush=True)
        return {
            "fixture": fixture_name,
            "key_idx": key_idx,
            "elapsed_s": elapsed,
            "tokens": 0,
            "grounded": None,
            "out_path": None,
            "timings": [],
            "error": f"{type(e).__name__}: {e}",
        }


async def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("fixtures", nargs="+", help="fixture 이름 (예: toss kakaopay banksalad)")
    ap.add_argument("--out-dir", default="/tmp", help="출력 디렉토리 (기본 /tmp)")
    ap.add_argument("--suffix", default="_parallel_run.json", help="출력 파일 접미사")
    ap.add_argument(
        "--start-key",
        type=int,
        default=0,
        help="키 할당 시작 인덱스 (다른 프로세스가 key #1 사용 중이면 1)",
    )
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    settings = Settings()
    keys = settings.eval_api_keys
    if not keys:
        print(
            "ERROR: no eval API keys configured. 평가 스크립트는 UPSTAGE_API_KEY_2/3/4 "
            "중 최소 한 개 필요 (key #1 은 서비스 dev 전용으로 분리).",
            file=sys.stderr,
        )
        sys.exit(1)

    # Resolve fixtures + assign keys (round-robin if N > len(keys))
    jobs = []
    for i, name in enumerate(args.fixtures):
        path = _resolve_fixture(name)
        if not path.exists():
            print(f"ERROR: fixture not found: {path}")
            sys.exit(1)
        key_idx = (i + args.start_key) % len(keys)
        out_path = out_dir / f"{name}{args.suffix}"
        jobs.append((name, path, keys[key_idx], key_idx, out_path))

    # Warn if collision
    if len(args.fixtures) > len(keys):
        print(
            f"⚠️  WARNING: {len(args.fixtures)} fixtures vs {len(keys)} keys → "
            f"round-robin (같은 키에 여러 작업 → rate limit 우려)"
        )

    print(f"Running {len(jobs)} pipeline(s) in parallel across {len(keys)} key(s)...")
    print(f"  Keys available: {len(keys)}")
    print(f"  Assignments: {[(name, f'key#{k+1}') for name, _, _, k, _ in jobs]}")
    print()

    t0 = time.perf_counter()
    tasks = [
        _run_one(name, path, settings, key, key_idx, out_path)
        for name, path, key, key_idx, out_path in jobs
    ]
    results = await asyncio.gather(*tasks, return_exceptions=False)
    wall_time = time.perf_counter() - t0

    # Summary
    print()
    print("=" * 78)
    print(f"  PARALLEL RUN SUMMARY  ({wall_time:.1f}s wall time)")
    print("=" * 78)
    print(f"{'Fixture':<18} {'Key':<6} {'Time':<8} {'Tokens':<10} {'Grounded':<10} Status")
    print("-" * 78)
    total_seq = 0.0
    total_tokens = 0
    for r in results:
        status = "OK" if r["error"] is None else f"FAIL ({r['error'][:30]})"
        total_seq += r["elapsed_s"]
        total_tokens += r["tokens"]
        print(
            f"{r['fixture']:<18} #{r['key_idx']+1:<5} {r['elapsed_s']:>5.1f}s   "
            f"{r['tokens']:>8,}    {str(r['grounded']):<10} {status}"
        )
    print("-" * 78)
    speedup = total_seq / wall_time if wall_time > 0 else 1.0
    print(f"  Wall time:      {wall_time:>6.1f}s")
    print(f"  Sequential eq.: {total_seq:>6.1f}s")
    print(f"  Speedup:        {speedup:>6.2f}×")
    print(f"  Total tokens:   {total_tokens:>10,}")


if __name__ == "__main__":
    asyncio.run(main())
