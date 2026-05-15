"""특정 fixture 에서 모델 N runs 의 consensus 와 golden expected 의 mismatch 진단.

목적:
  단일 run 의 wrong/missed 가 *모델 실수* 인지 *golden 라벨 품질* 문제인지 구분.

알고리즘:
  1. all_fixtures_<fixture>_run<1..N>.json 들 모두 읽어 추출 결과 모음
  2. golden 의 각 필드별 (expected) 와 비교
  3. 필드별 분류:
     - **A. 모델 consensus = golden**: 통과
     - **B. 모델 consensus ≠ golden**: golden 의심 (모델이 *반복* 다른 값)
     - **C. 모델 흔들림**: N runs 가 서로 다름 (모델 uncertainty)
     - **D. 모델 모두 null + golden 값 있음**: 모델 추출 실패 (golden 가 맞을 가능성 高)
     - **E. 모델 모두 값 + golden null**: over-extraction (모델 환각)

사용:
  PYTHONPATH=. .venv/bin/python scripts/diagnose_golden_vs_model.py coupang_play watcha
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXP_DIR = ROOT / "data" / "experiments"
FIXTURE_DIR = ROOT / "data" / "fixtures"


def _navigate(obj: dict, dotted: str):
    """dotted path 로 nested dict 접근. 'pricing.base_price_krw' → obj['pricing']['base_price_krw']."""
    cur = obj
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
        if cur is None:
            return None
    return cur


def _value_from_run(run_json: dict, field: str):
    """raw run JSON 에서 field 의 value 추출. terms.<section>.<field>.value path."""
    terms = run_json.get("terms", {})
    fv = _navigate(terms, field)
    if isinstance(fv, dict) and "value" in fv:
        return fv["value"]
    # unfair_clause_flags 같은 root level list
    if field == "unfair_clause_flags":
        return terms.get("unfair_clause_flags", [])
    return None


# score_against_golden 의 enum 동의어 그룹 — 진단도 같은 정규화를 거쳐야
# false positive ('prorated' vs 'prorated_refund' 같은 별칭) 제거.
_ENUM_ALIAS_GROUPS = [
    {"silent_acceptance", "deemed_agreed"},
    {"prorated", "prorated_refund"},
    {"opt_out_available", "opt_out"},
    {"opt_in_explicit", "opt_in_required"},
]


def _enum_canonical(v):
    if not isinstance(v, str):
        return v
    s = v.strip()
    for group in _ENUM_ALIAS_GROUPS:
        if s in group:
            return sorted(group)[0]
    return s


def _value_key(value):
    """비교용 정규화 — list 는 정렬된 tuple, enum 은 .value, 동의어는 canonical 로 압축."""
    if value is None:
        return None
    if isinstance(value, list):
        return tuple(sorted(_enum_canonical(str(x)) for x in value))
    if isinstance(value, str):
        return _enum_canonical(value)
    return value


def _is_null(v) -> bool:
    if v is None:
        return True
    if isinstance(v, (list, dict, str)) and len(v) == 0:
        return True
    return False


def diagnose(fixture: str, max_runs: int = 5) -> dict:
    """fixture 의 N runs raw output 모아 golden 과 비교."""
    runs = []
    for i in range(1, max_runs + 1):
        p = EXP_DIR / f"all_fixtures_{fixture}_run{i}.json"
        if not p.exists():
            continue
        with open(p) as f:
            runs.append(json.load(f))
    if not runs:
        return {"fixture": fixture, "error": "no run files found"}

    golden_path = FIXTURE_DIR / f"{fixture}_golden.json"
    if not golden_path.exists():
        return {"fixture": fixture, "error": "no golden file"}
    with open(golden_path) as f:
        golden = json.load(f)

    # 필드 리스트: golden 의 모든 키 중 _meta 제외
    field_keys = [k for k in golden.keys() if k != "_meta"]

    diagnoses: list[dict] = []
    cat_counts = Counter()

    for field in field_keys:
        g_entry = golden[field]
        expected = g_entry.get("expected") if isinstance(g_entry, dict) else None

        # N runs 의 모델 값 모음
        model_values = [_value_from_run(r, field) for r in runs]
        # consensus value (가장 자주 나오는 값)
        keys = [_value_key(v) for v in model_values]
        counter = Counter(keys)
        most_common_key, most_common_n = counter.most_common(1)[0]
        agreement = most_common_n / len(model_values)
        # 첫 번째 그 키를 가진 model value 그대로
        consensus_value = next(
            (v for v, k in zip(model_values, keys) if k == most_common_key), None
        )

        # 분류
        if _is_null(expected) and all(_is_null(v) for v in model_values):
            cat = "A. both null"
        elif _value_key(expected) == most_common_key and agreement >= 0.6:
            cat = "A. consensus matches golden"
        elif not _is_null(expected) and all(_is_null(v) for v in model_values):
            cat = "D. model never extracted (golden has value)"
        elif _is_null(expected) and all(not _is_null(v) for v in model_values):
            cat = "E. over-extraction (golden null, model invents)"
        elif agreement < 0.5:
            cat = "C. model variance (no consensus)"
        elif not _is_null(consensus_value) and _value_key(consensus_value) != _value_key(expected):
            cat = "B. consensus disagrees with golden"
        else:
            cat = "X. ambiguous"
        cat_counts[cat] += 1

        diagnoses.append({
            "field": field,
            "expected": expected,
            "model_values": model_values,
            "consensus_value": consensus_value,
            "agreement": round(agreement, 2),
            "category": cat,
        })

    return {
        "fixture": fixture,
        "n_runs": len(runs),
        "categories": dict(cat_counts),
        "diagnoses": diagnoses,
    }


def render(report: dict) -> str:
    lines = [f"# Diagnosis — {report['fixture']} ({report['n_runs']} runs)\n\n"]
    if "error" in report:
        lines.append(f"ERROR: {report['error']}\n")
        return "".join(lines)

    lines.append("## Category counts\n\n| 분류 | 카운트 |\n|---|---|\n")
    for cat, n in sorted(report["categories"].items(), key=lambda x: -x[1]):
        lines.append(f"| {cat} | {n} |\n")

    lines.append("\n## ⚠️ Category B (golden 의심 — 모델 consensus ≠ golden)\n\n")
    bs = [d for d in report["diagnoses"] if d["category"].startswith("B")]
    if not bs:
        lines.append("_없음_\n")
    else:
        lines.append("| 필드 | golden expected | 모델 consensus | agreement | runs |\n|---|---|---|---|---|\n")
        for d in bs:
            mv = ", ".join(repr(v)[:40] for v in d["model_values"])
            lines.append(
                f"| `{d['field']}` | `{d['expected']!r}` | `{d['consensus_value']!r}` | "
                f"{d['agreement']:.0%} | {mv} |\n"
            )

    lines.append("\n## D. 모델 추출 실패 (golden 정답일 가능성 高 — 모델/프롬프트 개선 후보)\n\n")
    ds = [d for d in report["diagnoses"] if d["category"].startswith("D")]
    if not ds:
        lines.append("_없음_\n")
    else:
        lines.append("| 필드 | golden expected |\n|---|---|\n")
        for d in ds:
            lines.append(f"| `{d['field']}` | `{d['expected']!r}` |\n")

    lines.append("\n## E. Over-extraction (golden null + 모델 값)\n\n")
    es = [d for d in report["diagnoses"] if d["category"].startswith("E")]
    if not es:
        lines.append("_없음_\n")
    else:
        lines.append("| 필드 | 모델 consensus | agreement |\n|---|---|---|\n")
        for d in es:
            lines.append(f"| `{d['field']}` | `{d['consensus_value']!r}` | {d['agreement']:.0%} |\n")

    lines.append("\n## C. 모델 흔들림 (variance, no consensus < 50%)\n\n")
    cs = [d for d in report["diagnoses"] if d["category"].startswith("C")]
    if not cs:
        lines.append("_없음_\n")
    else:
        lines.append("| 필드 | golden | 모델 5 runs |\n|---|---|---|\n")
        for d in cs:
            mv = " · ".join(repr(v)[:30] for v in d["model_values"])
            lines.append(f"| `{d['field']}` | `{d['expected']!r}` | {mv} |\n")

    return "".join(lines)


def main():
    fixtures = sys.argv[1:] or ["coupang_play", "watcha"]
    all_reports = {}
    for f in fixtures:
        report = diagnose(f)
        all_reports[f] = report
        out_path = EXP_DIR / f"diagnosis_{f}.md"
        out_path.write_text(render(report), encoding="utf-8")
        print(f"✓ {f}: {report.get('n_runs', 0)} runs analyzed → {out_path.name}")
        if "categories" in report:
            for cat, n in sorted(report["categories"].items(), key=lambda x: -x[1]):
                print(f"    {cat:50} n={n}")
        print()

    # JSON 도 저장
    out_json = EXP_DIR / "diagnosis_all.json"
    out_json.write_text(json.dumps(all_reports, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"All reports: {out_json.name}")


if __name__ == "__main__":
    main()
