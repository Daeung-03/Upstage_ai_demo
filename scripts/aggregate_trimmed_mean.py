"""기존 all_fixtures_*.json 들을 한꺼번에 trimmed-mean 으로 집계.

배경: hackathon 환경 + Solar API 의 내재 비결정성으로 동일 config 가 ±10%p 까지
진동. 단일 measurement 로 winner 결정하면 noise 가 시그널을 덮음. 본 스크립트는
같은 config 의 multi-run JSON 들을 모아:
  1. fixture 당 모든 individual run score 모음 (1 JSON 안에 N=2 inner runs 포함)
  2. trim 정책 적용 (default: 위·아래 1 개씩 제외)
  3. trimmed mean / std / 원래 min-max range 출력
  4. 전체 fixture 평균 = per-fixture trimmed mean 들의 평균

trim 정책:
  --trim drop1  : min 1 + max 1 제거 (default, 사용자 직관에 가장 가까움)
  --trim p10    : 위·아래 10% percentile 제거
  --trim p20    : 위·아래 20% percentile 제거

사용:
  PYTHONPATH=. .venv/bin/python scripts/aggregate_trimmed_mean.py
  PYTHONPATH=. .venv/bin/python scripts/aggregate_trimmed_mean.py --trim p10
  PYTHONPATH=. .venv/bin/python scripts/aggregate_trimmed_mean.py \\
      --pattern 'all_fixtures_2026051*.json'

기본은 data/experiments/all_fixtures_*.json 전부.
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import statistics
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXP_DIR = ROOT / "data" / "experiments"


def _trim(values: list[float], policy: str) -> list[float]:
    if len(values) < 3:
        return values  # trim 의미 없음
    s = sorted(values)
    if policy == "drop1":
        if len(s) < 3:
            return s
        return s[1:-1]
    elif policy == "p10":
        k = max(1, int(round(len(s) * 0.1)))
        return s[k:-k] if len(s) > 2 * k else s
    elif policy == "p20":
        k = max(1, int(round(len(s) * 0.2)))
        return s[k:-k] if len(s) > 2 * k else s
    else:
        raise ValueError(f"Unknown trim policy: {policy}")


def _summary(values: list[float], policy: str) -> dict:
    if not values:
        return {"n": 0}
    trimmed = _trim(values, policy)
    return {
        "n": len(values),
        "n_trimmed": len(trimmed),
        "mean": round(statistics.mean(values), 2),
        "trimmed_mean": round(statistics.mean(trimmed), 2),
        "std_trimmed": round(statistics.stdev(trimmed), 2) if len(trimmed) > 1 else 0.0,
        "min": round(min(values), 1),
        "max": round(max(values), 1),
        "raw": values,
    }


def aggregate(json_files: list[Path], policy: str) -> dict:
    """fixture 별로 모든 run 수집 → trim 통계."""
    from collections import defaultdict

    per_fixture: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: {"strict": [], "semantic": [], "elapsed_s": [], "tokens": [],
                 "grounded": []}
    )
    file_count = 0
    measurement_count = 0

    for fp in json_files:
        try:
            data = json.load(open(fp))
        except Exception as e:
            print(f"⚠️  skip {fp.name}: {e}")
            continue
        file_count += 1
        for fr in data:
            fixture = fr["fixture"]
            for r in fr.get("runs", []):
                if "strict" not in r:
                    continue
                per_fixture[fixture]["strict"].append(r["strict"].get("overall_pct", 0))
                per_fixture[fixture]["semantic"].append(
                    r["semantic"].get("overall_pct", 0)
                )
                per_fixture[fixture]["elapsed_s"].append(float(r.get("elapsed_s", 0)))
                per_fixture[fixture]["tokens"].append(float(r.get("tokens", 0)))
                per_fixture[fixture]["grounded"].append(1.0 if r.get("grounded") else 0.0)
                measurement_count += 1

    fixture_summary: dict[str, dict] = {}
    for fixture, metrics in per_fixture.items():
        fixture_summary[fixture] = {
            "strict": _summary(metrics["strict"], policy),
            "semantic": _summary(metrics["semantic"], policy),
            "elapsed_s": _summary(metrics["elapsed_s"], policy),
            "tokens": _summary(metrics["tokens"], policy),
            "grounded_rate": round(statistics.mean(metrics["grounded"]) * 100, 1)
            if metrics["grounded"] else 0.0,
        }

    # 전체 평균 = per-fixture trimmed mean 들의 평균
    strict_means = [v["strict"]["trimmed_mean"] for v in fixture_summary.values()
                    if v["strict"].get("n", 0) > 0]
    semantic_means = [v["semantic"]["trimmed_mean"] for v in fixture_summary.values()
                      if v["semantic"].get("n", 0) > 0]
    elapsed_means = [v["elapsed_s"]["trimmed_mean"] for v in fixture_summary.values()
                     if v["elapsed_s"].get("n", 0) > 0]
    token_means = [v["tokens"]["trimmed_mean"] for v in fixture_summary.values()
                   if v["tokens"].get("n", 0) > 0]

    return {
        "policy": policy,
        "files_aggregated": file_count,
        "total_measurements": measurement_count,
        "fixture_count": len(fixture_summary),
        "overall": {
            "strict_avg_trimmed": round(statistics.mean(strict_means), 2)
            if strict_means else None,
            "semantic_avg_trimmed": round(statistics.mean(semantic_means), 2)
            if semantic_means else None,
            "elapsed_s_avg": round(statistics.mean(elapsed_means), 1)
            if elapsed_means else None,
            "tokens_avg": round(statistics.mean(token_means), 0)
            if token_means else None,
        },
        "per_fixture": fixture_summary,
    }


def render_markdown(result: dict, source_files: list[Path]) -> str:
    overall = result["overall"]
    lines: list[str] = []
    lines.append(f"# Trimmed-mean Aggregate ({datetime.now().strftime('%Y-%m-%d %H:%M')})\n\n")
    lines.append(
        f"**Policy**: `{result['policy']}` (각 fixture 의 multi-run score 에서 "
    )
    if result["policy"] == "drop1":
        lines.append("min 1 + max 1 제외 후 평균)\n\n")
    elif result["policy"] == "p10":
        lines.append("위·아래 10% percentile 제외 후 평균)\n\n")
    elif result["policy"] == "p20":
        lines.append("위·아래 20% percentile 제외 후 평균)\n\n")

    lines.append(
        f"**Source**: {result['files_aggregated']} JSON 파일 / "
        f"{result['total_measurements']} 개별 measurement / "
        f"{result['fixture_count']} fixture\n\n"
    )

    lines.append("## 🏆 전체 평균 (per-fixture trimmed mean 의 산술평균)\n\n")
    lines.append("| 메트릭 | 값 |\n|---|---|\n")
    lines.append(f"| **Strict avg (trimmed)** | **{overall['strict_avg_trimmed']}%** |\n")
    lines.append(f"| **Semantic avg (trimmed)** | **{overall['semantic_avg_trimmed']}%** |\n")
    lines.append(f"| Latency avg / fixture | {overall['elapsed_s_avg']:.0f}s |\n")
    lines.append(f"| Tokens avg / fixture | {overall['tokens_avg']:,.0f} |\n\n")

    lines.append("## Per-fixture (n=원래 measurement / 트림 후 평균 / std / 원본 range)\n\n")
    lines.append(
        "| Fixture | n | Strict trim | Strict std | Strict range | "
        "Semantic trim | Semantic std | Semantic range |\n"
    )
    lines.append(
        "|---|---|---|---|---|---|---|---|\n"
    )
    # 정렬: strict trimmed mean 내림차순
    items = sorted(
        result["per_fixture"].items(),
        key=lambda x: x[1]["strict"].get("trimmed_mean", 0) or 0,
        reverse=True,
    )
    for fixture, s in items:
        st = s["strict"]
        sem = s["semantic"]
        lines.append(
            f"| {fixture} | {st['n']} | "
            f"**{st['trimmed_mean']:.1f}%** | ±{st['std_trimmed']:.1f} | "
            f"{st['min']:.0f}-{st['max']:.0f} | "
            f"**{sem['trimmed_mean']:.1f}%** | ±{sem['std_trimmed']:.1f} | "
            f"{sem['min']:.0f}-{sem['max']:.0f} |\n"
        )

    lines.append("\n## Source files\n\n")
    for fp in source_files:
        lines.append(f"- `{fp.name}`\n")

    return "".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--pattern",
        default="all_fixtures_2026051*.json",
        help="data/experiments 내 glob 패턴",
    )
    parser.add_argument(
        "--trim", choices=["drop1", "p10", "p20"], default="drop1",
        help="trim 정책",
    )
    parser.add_argument(
        "--out", default=None,
        help="출력 markdown 파일명 (없으면 timestamp 자동)",
    )
    args = parser.parse_args()

    files = sorted(EXP_DIR.glob(args.pattern))
    if not files:
        raise SystemExit(f"No files matched: {args.pattern}")
    print(f"→ Aggregating {len(files)} files (policy={args.trim})...")

    result = aggregate(files, args.trim)
    print(f"  files: {result['files_aggregated']}, "
          f"measurements: {result['total_measurements']}, "
          f"fixtures: {result['fixture_count']}")
    print(f"  overall strict trimmed: {result['overall']['strict_avg_trimmed']}%")
    print(f"  overall semantic trimmed: {result['overall']['semantic_avg_trimmed']}%")

    # markdown 출력
    md = render_markdown(result, files)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_md = EXP_DIR / (args.out or f"trimmed_mean_{args.trim}_{ts}.md")
    out_md.write_text(md, encoding="utf-8")
    print(f"  → {out_md}")

    # JSON 도 같이 저장 (재사용 가능)
    out_json = out_md.with_suffix(".json")
    out_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  → {out_json}")


if __name__ == "__main__":
    main()
