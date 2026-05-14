"""기존 모든 pipeline run JSON을 골든 라벨과 대조해 필드별 오류 빈도 분석.

목적: 가장 자주 틀리는 필드 + 오류 종류 식별 → 타겟 prompt fix.

사용:
    .venv/bin/python scripts/analyze_errors.py
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

GOLDEN = ROOT / "data" / "fixtures" / "netflix_golden.json"
RUN_DIR = Path("/tmp")
EXPERIMENT_RESULTS_DIR = ROOT / "data" / "experiments"

SECTIONS = (
    "pricing", "free_trial", "cancellation", "terms_changes",
    "data_usage", "liability", "disputes",
)


def _enum_value(v):
    if hasattr(v, "value"):
        return v.value
    return v


def _normalize(v):
    v = _enum_value(v)
    if isinstance(v, list):
        return tuple(sorted(str(x) for x in v))
    if isinstance(v, str):
        return v.strip()
    return v


def _is_null(v):
    if v is None:
        return True
    if isinstance(v, (list, str)) and len(v) == 0:
        return True
    return False


def classify(expected, actual) -> str:
    e_null, a_null = _is_null(expected), _is_null(actual)
    if e_null and a_null:
        return "ok_null"
    if e_null and not a_null:
        return "over_extracted"
    if not e_null and a_null:
        return "missed"
    if _normalize(expected) == _normalize(actual):
        return "ok"
    return "wrong"


def main():
    with open(GOLDEN) as f:
        golden = json.load(f)

    # 가능한 run 파일들 수집
    run_files = []
    # /tmp/variance_run_1.json: 가장 최근
    if (RUN_DIR / "variance_run_1.json").exists():
        run_files.append(RUN_DIR / "variance_run_1.json")
    # /tmp/exp_*.json: 별도로 저장된 경우 (없으면 skip)
    run_files.extend(RUN_DIR.glob("variance_run_*.json"))
    run_files = list(set(run_files))

    if not run_files:
        print("No pipeline run files found in /tmp")
        sys.exit(1)

    field_error_counts: dict[str, Counter] = defaultdict(Counter)
    field_total_observed = Counter()

    for rf in run_files:
        try:
            with open(rf) as f:
                run = json.load(f)
        except Exception as e:
            print(f"skip {rf}: {e}")
            continue
        for section in SECTIONS:
            sec = run.get("terms", {}).get(section, {})
            for field, fv in sec.items():
                key = f"{section}.{field}"
                golden_entry = golden.get(key)
                if golden_entry is None:
                    continue
                expected = golden_entry.get("expected")
                actual = _enum_value(fv.get("value"))
                cls = classify(expected, actual)
                field_error_counts[key][cls] += 1
                field_total_observed[key] += 1

    # 가장 자주 틀린 필드 (wrong + missed + over_extracted)
    print(f"=== Aggregate across {len(run_files)} run files ===\n")
    errors_per_field = []
    for f, counts in field_error_counts.items():
        total = field_total_observed[f]
        errs = counts["wrong"] + counts["missed"] + counts["over_extracted"]
        if total > 0:
            err_pct = errs / total * 100
            errors_per_field.append((f, errs, total, err_pct, counts))

    errors_per_field.sort(key=lambda x: x[3], reverse=True)

    print(f"{'Field':<55} {'err%':>6} {'wrong':>6} {'missed':>7} {'over':>5} {'samples':>8}")
    print("-" * 100)
    for f, errs, total, pct, c in errors_per_field[:25]:
        print(f"{f:<55} {pct:>5.0f}% {c['wrong']:>6} {c['missed']:>7} {c['over_extracted']:>5} {total:>8}")

    # 오류 종류 분포
    print("\n=== Error type distribution (top 10 by frequency) ===")
    by_kind = {"wrong": [], "missed": [], "over_extracted": []}
    for f, errs, total, pct, c in errors_per_field:
        for kind in by_kind:
            if c[kind] > 0:
                by_kind[kind].append((f, c[kind], total))
    for kind, items in by_kind.items():
        items.sort(key=lambda x: x[1], reverse=True)
        print(f"\nTop {kind}:")
        for f, n, total in items[:6]:
            print(f"  {f:<55} {n}/{total}")


if __name__ == "__main__":
    main()
