"""변동성 평가 — 같은 Netflix 약관을 N회 파이프라인에 통과시키고 필드별 일관성 측정.

사용법:
    .venv/bin/python scripts/eval_variance.py

출력:
- /tmp/variance_run_N.json (N=1..N)
- 콘솔에 필드별 일관성 표 + 요약
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from collections import Counter
from pathlib import Path

# 프로젝트 루트에서 import 가능하도록
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.pipeline import run_pipeline
from services.settings import Settings
from services.upstage import UpstageClient

N_RUNS = 5
FIXTURE = Path(__file__).resolve().parent.parent / "data" / "fixtures" / "netflix_terms.pdf"
SECTION_NAMES = (
    "pricing", "free_trial", "cancellation", "terms_changes",
    "data_usage", "liability", "disputes",
)


async def one_run(idx: int) -> dict:
    settings = Settings()
    print(f"[run {idx}] starting...", flush=True)
    t0 = time.perf_counter()
    async with UpstageClient(settings) as client:
        result = await run_pipeline(
            client,
            file_bytes=FIXTURE.read_bytes(),
            filename=FIXTURE.name,
            service_name="Netflix",
            service_provider="Netflix, Inc.",
        )
    elapsed = time.perf_counter() - t0
    print(f"[run {idx}] done in {elapsed:.1f}s, grounded={result.grounded}", flush=True)
    return result.model_dump()


async def main():
    if not FIXTURE.exists():
        print(f"ERROR: fixture missing at {FIXTURE}")
        sys.exit(1)
    print(f"Running {N_RUNS} SEQUENTIAL pipeline calls against Netflix terms (rate limit avoidance)...")
    t0 = time.perf_counter()
    results = []
    for i in range(N_RUNS):
        results.append(await one_run(i + 1))
    elapsed = time.perf_counter() - t0
    print(f"\nAll {N_RUNS} runs complete in {elapsed:.1f}s (wall clock, sequential)\n")

    # save individual runs
    for i, r in enumerate(results, 1):
        with open(f"/tmp/variance_run_{i}.json", "w") as f:
            json.dump(r, f, ensure_ascii=False)

    # === Field-level variance ===
    print("=" * 100)
    print(f"FIELD-LEVEL VARIANCE (N={N_RUNS})")
    print("=" * 100)
    header = f"{'Field':<55} {'Distinct values':<7} Counts"
    print(header)
    print("-" * 100)

    all_identical = 0
    minor_var = 0  # 2 values
    major_var = 0  # 3+

    for section in SECTION_NAMES:
        for field_name in results[0]["terms"][section].keys():
            values = []
            for r in results:
                fv = r["terms"][section][field_name]
                v = fv.get("value")
                # 정규화: list는 sorted tuple로
                if isinstance(v, list):
                    v = tuple(sorted(str(x) for x in v))
                values.append(v)
            counts = Counter(values)
            distinct = len(counts)
            counts_str = " | ".join(f"{k}×{v}" for k, v in counts.most_common(5))
            if len(counts_str) > 60:
                counts_str = counts_str[:57] + "..."
            marker = "✓" if distinct == 1 else ("~" if distinct == 2 else "✗")
            print(f"{section}.{field_name:<45} {distinct:<7} {marker} {counts_str}")
            if distinct == 1:
                all_identical += 1
            elif distinct == 2:
                minor_var += 1
            else:
                major_var += 1

    total_fields = all_identical + minor_var + major_var
    print()
    print("=" * 100)
    print(f"CONSISTENCY SUMMARY ({total_fields} fields)")
    print(f"  ✓ All 5 runs agree:     {all_identical:>3} ({100*all_identical//total_fields}%)")
    print(f"  ~ 2 distinct values:    {minor_var:>3} ({100*minor_var//total_fields}%)")
    print(f"  ✗ 3+ distinct values:   {major_var:>3} ({100*major_var//total_fields}%)")
    print()

    # Per-stage timings
    print("=" * 100)
    print("TIMING VARIANCE (seconds)")
    stage_timings: dict[str, list[float]] = {}
    for r in results:
        for t in r["timings"]:
            stage_timings.setdefault(t["stage"], []).append(t["seconds"])
    for stage, times in stage_timings.items():
        avg = sum(times) / len(times)
        mn, mx = min(times), max(times)
        print(f"  {stage:12s} avg={avg:.2f}s  min={mn:.2f}s  max={mx:.2f}s  spread={mx-mn:.2f}s")
    print()

    # Token usage variance
    print("=" * 100)
    print("TOKEN USAGE VARIANCE (per stage, totals across N runs)")
    stage_tokens: dict[str, list[int]] = {}
    for r in results:
        for u in r["usage"]:
            stage_tokens.setdefault(u["stage"], []).append(u["total_tokens"])
    for stage, toks in stage_tokens.items():
        avg = sum(toks) / len(toks)
        mn, mx = min(toks), max(toks)
        print(f"  {stage:12s} avg={avg:>8,.0f}  min={mn:>8,}  max={mx:>8,}  spread={mx-mn:>8,}")
    print()

    # Grounded rate
    grounded_count = sum(1 for r in results if r["grounded"])
    print(f"Grounded result: {grounded_count}/{N_RUNS} runs grounded=true")

    # Key clauses comparison
    print()
    print("=" * 100)
    print("KEY CLAUSE COUNT PER RUN")
    for i, r in enumerate(results, 1):
        gc = len(r["key_clauses"])
        uc = len(r["ungrounded_clauses"])
        print(f"  run {i}: {gc} grounded / {uc} ungrounded clauses")


if __name__ == "__main__":
    asyncio.run(main())
