"""다중 config 실험 자동 실행 + 정확도/시간/토큰 기록.

각 config 별로 N회 실행 → score_against_golden 으로 채점 → JSON + md 리포트.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

GOLDEN = ROOT / "data" / "fixtures" / "netflix_golden.json"
RESULTS_DIR = ROOT / "data" / "experiments"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)
LOG_JSON = RESULTS_DIR / f"experiments_{time.strftime('%Y%m%d_%H%M%S')}.json"
LOG_MD = RESULTS_DIR / f"experiments_{time.strftime('%Y%m%d_%H%M%S')}.md"

# (config_name, env_overrides, num_runs)
CONFIGS = [
    # Round 6: BC + prompt fix #1 (Korean OTT bool default inferred=False) 검증 3 runs
    # Defaults: extract N=2 medium, summarize high, ground medium
    ("BC_plus_korean_bool_fix", {"EXTRACT_FIXTURE": "netflix"}, 3),
]


def _parse_score(text: str) -> dict:
    """score_against_golden 출력에서 핵심 metric 추출."""
    out: dict = {}
    m = re.search(r"accuracy = .* = (\d+)%", text)
    if m: out["overall_pct"] = int(m.group(1))
    for cat in ["ok", "ok_null", "missed", "wrong", "over_extracted"]:
        m = re.search(rf"{cat}.*?:\s+(\d+)", text)
        if m: out[cat] = int(m.group(1))
    for t in ["int", "enum", "bool", "list", "str"]:
        m = re.search(rf"  {t:<6}.*acc=\s*([\d.]+)%", text)
        if m: out[f"type_{t}"] = float(m.group(1))
    for s in ["pricing", "free_trial", "cancellation", "terms_changes",
              "data_usage", "liability", "disputes"]:
        m = re.search(rf"  {s}.*acc=\s*([\d.]+)%", text)
        if m: out[f"section_{s}"] = float(m.group(1))
    m = re.search(r"precision=([\d.]+)\s+recall=([\d.]+)", text)
    if m: out["flag_p"], out["flag_r"] = float(m.group(1)), float(m.group(2))
    return out


def _parse_run_meta(text: str) -> dict:
    """single_run 출력에서 timing/token 추출."""
    out: dict = {}
    m = re.search(r"Done in ([\d.]+)s \| grounded=(\w+)", text)
    if m:
        out["seconds"] = float(m.group(1))
        out["grounded"] = m.group(2) == "True"
    m = re.search(r"Timings:\s*\[(.*?)\]", text)
    if m: out["timings_raw"] = m.group(1)
    m = re.search(r"Usage: total=([\d,]+) tokens", text)
    if m: out["total_tokens"] = int(m.group(1).replace(",", ""))
    return out


def run_single(env_overrides: dict) -> tuple[dict, dict]:
    """single_run.py + score 1회. (run_meta, score_metrics) 반환."""
    env = {**os.environ, **env_overrides}
    r = subprocess.run(
        [".venv/bin/python", "scripts/single_run.py"],
        env=env, capture_output=True, text=True, cwd=ROOT,
    )
    run_out = r.stdout + "\n" + r.stderr
    run_meta = _parse_run_meta(run_out)
    if r.returncode != 0 or "Written to" not in run_out:
        return run_meta, {"error": "single_run failed", "stderr": r.stderr[-500:]}
    s = subprocess.run(
        [".venv/bin/python", "scripts/score_against_golden.py"],
        capture_output=True, text=True, cwd=ROOT,
    )
    score_out = s.stdout
    return run_meta, _parse_score(score_out)


def main():
    print(f"Starting experiments → {LOG_JSON.name}", flush=True)
    all_results = []
    t_start = time.perf_counter()
    for name, env, n_runs in CONFIGS:
        for i in range(1, n_runs + 1):
            label = f"{name}_run{i}"
            print(f"\n=== {label} (env={env}) ===", flush=True)
            t0 = time.perf_counter()
            try:
                run_meta, score = run_single(env)
                elapsed = time.perf_counter() - t0
                entry = {
                    "config": name,
                    "run": i,
                    "env": env,
                    "wallclock_s": round(elapsed, 1),
                    **run_meta,
                    **score,
                }
                all_results.append(entry)
                print(
                    f"  → {entry.get('overall_pct', '?')}% "
                    f"({entry.get('seconds', '?')}s, {entry.get('total_tokens', '?'):,} tokens)",
                    flush=True,
                )
            except Exception as e:
                print(f"  ERROR: {e}", flush=True)
                all_results.append({"config": name, "run": i, "error": str(e)})
            # 결과 적립 (중간 저장)
            with open(LOG_JSON, "w") as f:
                json.dump(all_results, f, ensure_ascii=False, indent=2)
    print(f"\n\nDone in {(time.perf_counter() - t_start) / 60:.1f} min.", flush=True)

    # === 요약 markdown ===
    md = [f"# Experiments {time.strftime('%Y-%m-%d %H:%M')}\n"]
    md.append(f"Fixture: Netflix terms ({GOLDEN.name})\n")
    md.append(f"Total runs: {len(all_results)}\n\n")

    by_config: dict[str, list[dict]] = {}
    for r in all_results:
        by_config.setdefault(r["config"], []).append(r)

    md.append("## Summary (per config, averaged)\n\n")
    md.append("| Config | Runs | Acc (avg) | Acc (range) | Seconds (avg) | Tokens (avg) | Grounded |\n")
    md.append("|---|---|---|---|---|---|---|\n")
    for cfg, runs in by_config.items():
        valid = [r for r in runs if "overall_pct" in r]
        if not valid:
            md.append(f"| {cfg} | {len(runs)} | ERROR | - | - | - | - |\n")
            continue
        acc = [r["overall_pct"] for r in valid]
        sec = [r["seconds"] for r in valid if "seconds" in r]
        tok = [r["total_tokens"] for r in valid if "total_tokens" in r]
        grounded = sum(1 for r in valid if r.get("grounded")) / len(valid) * 100
        md.append(
            f"| {cfg} | {len(valid)} | {sum(acc)/len(acc):.1f}% | "
            f"{min(acc)}–{max(acc)}% | {sum(sec)/len(sec):.0f} | "
            f"{sum(tok)/len(tok):,.0f} | {grounded:.0f}% |\n"
        )

    md.append("\n## Per-run detail\n\n")
    md.append("| Config | Run | Acc | Sec | Tokens | Grounded | ok | ok_null | missed | wrong | over |\n")
    md.append("|---|---|---|---|---|---|---|---|---|---|---|\n")
    for r in all_results:
        if "overall_pct" not in r:
            md.append(f"| {r['config']} | {r['run']} | ERROR | - | - | - | - | - | - | - | - |\n")
            continue
        md.append(
            f"| {r['config']} | {r['run']} | {r['overall_pct']}% | "
            f"{r.get('seconds', '?'):.0f} | {r.get('total_tokens', '?'):,} | "
            f"{'✓' if r.get('grounded') else '✗'} | "
            f"{r.get('ok', '?')} | {r.get('ok_null', '?')} | {r.get('missed', '?')} | "
            f"{r.get('wrong', '?')} | {r.get('over_extracted', '?')} |\n"
        )

    md.append("\n## Per-type accuracy (avg per config)\n\n")
    md.append("| Config | int | enum | bool | list | str |\n|---|---|---|---|---|---|\n")
    for cfg, runs in by_config.items():
        valid = [r for r in runs if "type_int" in r]
        if not valid:
            md.append(f"| {cfg} | - | - | - | - | - |\n")
            continue
        avg = lambda k: sum(r.get(k, 0) for r in valid) / len(valid)
        md.append(
            f"| {cfg} | {avg('type_int'):.1f}% | {avg('type_enum'):.1f}% | "
            f"{avg('type_bool'):.1f}% | {avg('type_list'):.1f}% | {avg('type_str'):.1f}% |\n"
        )

    LOG_MD.write_text("".join(md), encoding="utf-8")
    print(f"Report: {LOG_MD}", flush=True)


if __name__ == "__main__":
    main()
