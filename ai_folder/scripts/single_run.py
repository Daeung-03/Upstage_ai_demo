"""약관 1회 파이프라인 실행 — 골든 템플릿용 베이스라인 생성.

사용:
    .venv/bin/python scripts/single_run.py [fixture_name]

기본: netflix (data/fixtures/netflix_terms.pdf)
지정 시: data/fixtures/<fixture_name>_terms.pdf 사용
환경변수 EXTRACT_FIXTURE 로도 지정 가능 (run_experiments.py 에서 사용).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.pipeline import run_pipeline
from services.settings import Settings
from services.upstage import UpstageClient

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = ROOT / "data" / "fixtures"
DEFAULT_FIXTURE = "netflix"


def _resolve_fixture(name: str) -> Path:
    """fixture name → 파일 경로. .pdf 우선, 없으면 .html 시도."""
    for ext in (".pdf", ".html"):
        candidate = FIXTURE_DIR / f"{name}_terms{ext}"
        if candidate.exists():
            return candidate
    return FIXTURE_DIR / f"{name}_terms.pdf"  # 디폴트 (없는 경우 에러용)


async def main():
    fixture_name = sys.argv[1] if len(sys.argv) > 1 else os.getenv("EXTRACT_FIXTURE", DEFAULT_FIXTURE)
    fixture_pdf = _resolve_fixture(fixture_name)
    if not fixture_pdf.exists():
        print(f"ERROR: fixture not found: {fixture_pdf}")
        print(f"Run scripts/setup_fixture.py first or check fixture name.")
        sys.exit(1)
    out_path = Path(os.getenv("SINGLE_RUN_OUT", f"/tmp/variance_run_1.json"))

    settings = Settings()
    print(f"Running 1 pipeline call against {fixture_pdf.name}...", flush=True)
    t0 = time.perf_counter()
    async with UpstageClient(settings) as client:
        result = await run_pipeline(
            client,
            file_bytes=fixture_pdf.read_bytes(),
            filename=fixture_pdf.name,
            service_name=fixture_name.capitalize(),
            service_provider=fixture_name.capitalize(),
        )
    elapsed = time.perf_counter() - t0
    print(f"\nDone in {elapsed:.1f}s | grounded={result.grounded}", flush=True)
    print(f"Timings: {[(t.stage, round(t.seconds, 2)) for t in result.timings]}", flush=True)
    print(f"Usage: total={sum(u.total_tokens for u in result.usage):,} tokens", flush=True)
    for u in result.usage:
        parts = []
        if u.pages: parts.append(f"pages={u.pages}")
        if u.total_tokens: parts.append(f"tokens={u.total_tokens:,}")
        if u.reasoning_tokens: parts.append(f"reasoning={u.reasoning_tokens:,}")
        print(f"  {u.stage:12s} calls={u.calls} {' '.join(parts)}", flush=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result.model_dump(), f, ensure_ascii=False)
    print(f"\nWritten to {out_path}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
