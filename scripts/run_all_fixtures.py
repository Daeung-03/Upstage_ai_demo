"""모든 fixture에 대해 BC+prompt#1 default config로 N회 실행 + 채점 + 비교.

병렬화: 키 풀 정적 분배. K개의 API 키가 있으면 FIXTURES를 K 그룹으로 라운드로빈
나누고, 각 그룹은 자기 키 + Semaphore(per_key_concurrency)로 독립 병렬 실행.
키 1개 → 기존과 동일. 키 3개 → 동시 fixture 수 ~3배.

사용:
    .venv/bin/python scripts/run_all_fixtures.py [runs_per_fixture] [per_key_concurrency]

기본: runs=2, per_key_concurrency=3 (키 1개면 동시 3, 3개면 동시 9)
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ai.pipeline import run_pipeline
from ai.services.settings import Settings
from ai.services.upstage import UpstageClient

FIXTURE_DIR = ROOT / "data" / "fixtures"
RESULTS_DIR = ROOT / "data" / "experiments"

FIXTURES_OTT = ["netflix", "spotify", "wavve", "coupang_play", "tving", "disney_plus", "watcha"]
FIXTURES_AI = ["claude", "deepseek", "gemini", "gpt", "upstage"]
FIXTURES_FINTECH = ["banksalad", "kakaopay", "toss"]

# 기본은 OTT 7개. 환경변수 EXTRA_FIXTURES로 ai/fintech/all 지정 가능.
_extra = os.environ.get("EXTRA_FIXTURES", "").lower()
if _extra == "all":
    FIXTURES = FIXTURES_OTT + FIXTURES_AI + FIXTURES_FINTECH
elif _extra == "ai":
    FIXTURES = FIXTURES_OTT + FIXTURES_AI
elif _extra == "fintech":
    FIXTURES = FIXTURES_OTT + FIXTURES_FINTECH
elif _extra == "non-ott":
    FIXTURES = FIXTURES_AI + FIXTURES_FINTECH
else:
    FIXTURES = FIXTURES_OTT


def _resolve_fixture(name: str) -> Path | None:
    for ext in (".pdf", ".html"):
        p = FIXTURE_DIR / f"{name}_terms{ext}"
        if p.exists():
            return p
    return None


def _parse_score(text: str) -> dict:
    out: dict = {}
    m = re.search(r"accuracy = .* = (\d+)%", text)
    if m: out["overall_pct"] = int(m.group(1))
    for cat in ["ok", "ok_null", "missed", "wrong", "over_extracted"]:
        m = re.search(rf"{cat}.*?:\s+(\d+)", text)
        if m: out[cat] = int(m.group(1))
    for t in ["int", "enum", "bool", "list", "str"]:
        m = re.search(rf"  {t:<6}.*acc=\s*([\d.]+)%", text)
        if m: out[f"type_{t}"] = float(m.group(1))
    norm = re.findall(r"precision=([\d.]+)\s+recall=([\d.]+)\s+\(normalized", text)
    strict = re.findall(r"precision=([\d.]+)\s+recall=([\d.]+)\s+\(strict", text)
    if norm:
        out["flag_p_norm"], out["flag_r_norm"] = float(norm[0][0]), float(norm[0][1])
    if strict:
        out["flag_p"], out["flag_r"] = float(strict[0][0]), float(strict[0][1])
    return out


async def run_one_fixture(
    fixture: str,
    runs: int,
    sem: asyncio.Semaphore,
    api_key: str,
    key_label: str,
    settings: Settings,
) -> dict:
    """한 fixture를 N회 실행 + 채점. 지정된 api_key를 사용."""
    fixture_pdf = _resolve_fixture(fixture)
    if fixture_pdf is None:
        print(f"  [{key_label}/{fixture}] SKIP — fixture not found", flush=True)
        return {"fixture": fixture, "runs": [], "error": "no fixture"}
    golden = FIXTURE_DIR / f"{fixture}_golden.json"
    if not golden.exists():
        print(f"  [{key_label}/{fixture}] SKIP — golden not found", flush=True)
        return {"fixture": fixture, "runs": [], "error": "no golden"}

    results: list[dict] = []
    file_bytes = fixture_pdf.read_bytes()
    filename = fixture_pdf.name

    for i in range(1, runs + 1):
        async with sem:
            print(f"  [{key_label}/{fixture}] run {i}/{runs} starting...", flush=True)
            t0 = time.perf_counter()
            try:
                async with UpstageClient(settings, api_key=api_key) as client:
                    result = await run_pipeline(
                        client,
                        file_bytes=file_bytes,
                        filename=filename,
                        service_name=fixture.replace("_", " ").title(),
                        service_provider=fixture.replace("_", " ").title(),
                    )
                elapsed = time.perf_counter() - t0
            except Exception as e:
                print(f"  [{key_label}/{fixture}] run {i} ERROR: {str(e)[:120]}", flush=True)
                results.append({"run": i, "error": str(e)[:200]})
                continue

        run_path = RESULTS_DIR / f"all_fixtures_{fixture}_run{i}.json"
        with open(run_path, "w", encoding="utf-8") as f:
            json.dump(result.model_dump(), f, ensure_ascii=False)

        s_strict = subprocess.run(
            [".venv/bin/python", "scripts/score_against_golden.py", str(run_path), str(golden)],
            capture_output=True, text=True, cwd=ROOT,
        ).stdout
        s_semantic = subprocess.run(
            [".venv/bin/python", "scripts/score_against_golden.py", str(run_path), str(golden), "--semantic"],
            capture_output=True, text=True, cwd=ROOT,
        ).stdout

        entry = {
            "run": i,
            "elapsed_s": round(elapsed, 1),
            "tokens": sum(u.total_tokens for u in result.usage),
            "grounded": result.grounded,
            "strict": _parse_score(s_strict),
            "semantic": _parse_score(s_semantic),
            "key": key_label,
        }
        results.append(entry)
        print(
            f"  [{key_label}/{fixture}] run {i}: strict={entry['strict'].get('overall_pct', '?')}% "
            f"semantic={entry['semantic'].get('overall_pct', '?')}% "
            f"({elapsed:.0f}s, {entry['tokens']:,}t)",
            flush=True,
        )

    return {"fixture": fixture, "runs": results, "key": key_label}


async def run_one_group(
    fixtures: list[str],
    runs: int,
    api_key: str,
    key_label: str,
    per_key_concurrency: int,
    settings: Settings,
) -> list[dict]:
    """한 키에 할당된 fixture 그룹을 그룹 내부 Semaphore로 병렬 실행."""
    sem = asyncio.Semaphore(per_key_concurrency)
    return await asyncio.gather(
        *[run_one_fixture(f, runs, sem, api_key, key_label, settings) for f in fixtures]
    )


async def main():
    runs_per = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    per_key_concurrency = int(sys.argv[2]) if len(sys.argv) > 2 else 3

    settings = Settings()
    api_keys = settings.api_keys
    n_keys = len(api_keys)

    # 라운드로빈 분배 — fixture별 latency 차이를 키 간에 분산
    groups: list[list[str]] = [FIXTURES[i::n_keys] for i in range(n_keys)]
    total_concurrency = n_keys * per_key_concurrency

    print(
        f"Running {len(FIXTURES)} fixtures × {runs_per} runs across {n_keys} key(s); "
        f"per-key concurrency={per_key_concurrency}, total≈{total_concurrency}",
        flush=True,
    )
    for idx, (g, k) in enumerate(zip(groups, api_keys)):
        label = f"key{idx + 1}"
        tail = k[-4:] if len(k) >= 4 else "????"
        print(f"  {label} (…{tail}): {g}", flush=True)
    print(f"Defaults: extract N=2 medium, summarize=high, ground=medium, prompt #1", flush=True)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    t_start = time.perf_counter()
    group_results = await asyncio.gather(
        *[
            run_one_group(g, runs_per, k, f"key{i + 1}", per_key_concurrency, settings)
            for i, (g, k) in enumerate(zip(groups, api_keys))
        ]
    )
    fixture_results = [fr for group in group_results for fr in group]
    total = time.perf_counter() - t_start
    print(f"\nAll done in {total/60:.1f} min wall clock\n", flush=True)

    ts = time.strftime("%Y%m%d_%H%M%S")
    out_json = RESULTS_DIR / f"all_fixtures_{ts}.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(fixture_results, f, ensure_ascii=False, indent=2)

    md = [f"# All Fixtures — BC + prompt #1 (2026-05-15 {time.strftime('%H:%M')})\n\n"]
    md.append(f"Defaults: extract N=2 medium, summarize=high, ground=medium, prompt #1\n")
    md.append(
        f"Keys: {n_keys}, per-key concurrency: {per_key_concurrency}, "
        f"total concurrency: {total_concurrency}, runs per fixture: {runs_per}, "
        f"wall clock: {total/60:.1f} min\n\n"
    )
    md.append("## Per-fixture averages (strict / semantic)\n\n")
    md.append("| Fixture | Key | Runs | Strict avg | Semantic avg | Range strict | Sec avg | Tokens avg | Grounded |\n")
    md.append("|---|---|---|---|---|---|---|---|---|\n")
    for fr in fixture_results:
        fname = fr["fixture"]
        key_lbl = fr.get("key", "—")
        rs = [r for r in fr["runs"] if "strict" in r]
        if not rs:
            md.append(f"| {fname} | {key_lbl} | 0 | ERR | — | — | — | — | — |\n")
            continue
        strict = [r["strict"].get("overall_pct", 0) for r in rs]
        semantic = [r["semantic"].get("overall_pct", 0) for r in rs]
        sec = [r["elapsed_s"] for r in rs]
        toks = [r["tokens"] for r in rs]
        grounded = sum(1 for r in rs if r["grounded"]) / len(rs) * 100
        md.append(
            f"| {fname} | {key_lbl} | {len(rs)} | {sum(strict)/len(strict):.1f}% | {sum(semantic)/len(semantic):.1f}% | "
            f"{min(strict)}-{max(strict)} | {sum(sec)/len(sec):.0f} | {sum(toks)/len(toks):,.0f} | {grounded:.0f}% |\n"
        )

    out_md = RESULTS_DIR / f"all_fixtures_{ts}.md"
    out_md.write_text("".join(md), encoding="utf-8")
    print(f"Aggregate report: {out_md}")


if __name__ == "__main__":
    asyncio.run(main())
