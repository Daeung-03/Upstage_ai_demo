"""전 fixture 의 fixture × field × category 매트릭스 자동 산출.

목적: 어느 fixture 의 어느 필드가 *반복적으로* missed/wrong/over_extracted 인지
정량. 모델/프롬프트 개선 후보 우선순위 결정용.

데이터 소스: data/experiments/all_fixtures_<fixture>_run<i>.json (각 fixture 의
최근 5 runs raw output). diagnose_golden_vs_model 의 카테고리 분류 재사용.

출력:
  - data/experiments/per_field_breakdown.md (사람 보기용)
  - data/experiments/per_field_breakdown.json (재사용/분석용)
  - 글로벌 ranking: D 가 가장 많은 필드 / B 가 가장 많은 필드 / E 가 가장 많은 필드

사용:
  PYTHONPATH=. .venv/bin/python scripts/per_field_breakdown.py
"""

from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

# diagnose 의 분류 로직 재사용
from scripts.diagnose_golden_vs_model import diagnose  # type: ignore

ROOT = Path(__file__).resolve().parent.parent
EXP_DIR = ROOT / "data" / "experiments"
FIXTURE_DIR = ROOT / "data" / "fixtures"


ALL_FIXTURES = [
    # OTT
    "netflix", "spotify", "wavve", "coupang_play", "tving", "disney_plus", "watcha",
    # AI
    "claude", "deepseek", "gemini", "gpt", "upstage",
    # Fintech
    "banksalad", "kakaopay", "toss",
]


def main() -> None:
    # fixture × field × category
    per_fixture: dict[str, dict] = {}
    # field × category 글로벌 카운트
    global_field: dict[str, Counter] = defaultdict(Counter)
    # category × fixture 글로벌 카운트
    global_cat_fixture: dict[str, Counter] = defaultdict(Counter)

    print("→ Diagnosing 15 fixtures...")
    for f in ALL_FIXTURES:
        report = diagnose(f)
        if "error" in report:
            print(f"  ✗ {f}: {report['error']}")
            continue
        per_fixture[f] = {
            "n_runs": report["n_runs"],
            "categories": report["categories"],
            "diagnoses": report["diagnoses"],
        }
        for d in report["diagnoses"]:
            cat = d["category"][0]  # "A", "B", "C", "D", "E", "X" prefix
            global_field[d["field"]][cat] += 1
            global_cat_fixture[cat][f] += 1
        print(
            f"  ✓ {f:14} ({report['n_runs']} runs) — "
            f"A={report['categories'].get('A. consensus matches golden', 0) + report['categories'].get('A. both null', 0):2} "
            f"B={report['categories'].get('B. consensus disagrees with golden', 0):2} "
            f"C={report['categories'].get('C. model variance (no consensus)', 0):2} "
            f"D={report['categories'].get('D. model never extracted (golden has value)', 0):2} "
            f"E={report['categories'].get('E. over-extraction (golden null, model invents)', 0):2}"
        )

    # ── 글로벌 ranking ──
    # D 가 가장 많은 필드 = 모델이 일관되게 추출 못 하는 필드 (prompt 개선 후보)
    d_ranking = sorted(
        [(field, cnt["D"]) for field, cnt in global_field.items() if cnt["D"] > 0],
        key=lambda x: -x[1],
    )
    # B 가 가장 많은 필드 = 일관된 mismatch (모델 부정확 또는 golden 의심)
    b_ranking = sorted(
        [(field, cnt["B"]) for field, cnt in global_field.items() if cnt["B"] > 0],
        key=lambda x: -x[1],
    )
    # E
    e_ranking = sorted(
        [(field, cnt["E"]) for field, cnt in global_field.items() if cnt["E"] > 0],
        key=lambda x: -x[1],
    )

    # ── markdown ──
    md: list[str] = []
    md.append("# Per-field × Per-fixture Error Breakdown\n\n")
    md.append(
        f"**Source**: 15 fixtures × 5 최근 raw runs (R9 측정) — total ≈ 75 measurements 의\n"
        f"fixture × field × category 매트릭스. diagnose_golden_vs_model.py 의 6 카테고리\n"
        f"분류 (A/B/C/D/E/X) 재사용. alias normalization 적용 (`_ENUM_ALIAS_GROUPS`).\n\n"
    )
    md.append("## 🔴 Top 20 fields by **D** (모델 추출 실패 — 가장 많은 fixture 에서 모델 5/5 not_specified)\n\n")
    md.append("| Rank | Field | D 카운트 (fixture 수) |\n|---|---|---|\n")
    for i, (field, cnt) in enumerate(d_ranking[:20], 1):
        md.append(f"| {i} | `{field}` | **{cnt}** |\n")

    md.append("\n## ⚠️ Top 20 fields by **B** (consensus disagrees with golden — 모델 부정확 또는 golden 의심)\n\n")
    md.append("| Rank | Field | B 카운트 |\n|---|---|---|\n")
    for i, (field, cnt) in enumerate(b_ranking[:20], 1):
        md.append(f"| {i} | `{field}` | **{cnt}** |\n")

    md.append("\n## ➕ Top 10 fields by **E** (over-extraction — golden null, 모델 일관 invent)\n\n")
    md.append("| Rank | Field | E 카운트 |\n|---|---|---|\n")
    for i, (field, cnt) in enumerate(e_ranking[:10], 1):
        md.append(f"| {i} | `{field}` | **{cnt}** |\n")

    md.append("\n## Per-fixture summary\n\n")
    md.append("| Fixture | A | B | C | D | E | total |\n|---|---|---|---|---|---|---|\n")
    for fname in ALL_FIXTURES:
        if fname not in per_fixture:
            continue
        cats = per_fixture[fname]["categories"]
        a = (cats.get("A. consensus matches golden", 0)
             + cats.get("A. both null", 0))
        b = cats.get("B. consensus disagrees with golden", 0)
        c = cats.get("C. model variance (no consensus)", 0)
        d = cats.get("D. model never extracted (golden has value)", 0)
        e = cats.get("E. over-extraction (golden null, model invents)", 0)
        total = sum(cats.values())
        md.append(f"| {fname} | {a} | {b} | {c} | **{d}** | {e} | {total} |\n")

    md.append("\n## 행동 권장\n\n")
    md.append(
        "- **D 상위 필드** (모델이 *반복적으로* 추출 못 하는 필드) 에 prompt 룰 추가 후보.\n"
        "  - 도메인별 default 값 inferred 룰 (예: 한국 OTT 의 `auto_renewal_enabled=True` default).\n"
        "  - 자유텍스트 단축 방지 (penalty_description, force_majeure_scope 같이).\n"
        "- **B 상위 필드** 는 case-by-case. golden 본문 audit + 모델 출력 비교 → 라벨 fix or "
        "    prompt 룰 추가.\n"
        "- **E 상위 필드** 는 모델의 over-inference. 'inferred False' 룰을 *너무 적극적으로* "
        "    적용하는 경우.\n"
    )

    out_md = EXP_DIR / "per_field_breakdown.md"
    out_md.write_text("".join(md), encoding="utf-8")
    print(f"\n→ {out_md.name}")

    # JSON
    aggregate = {
        "per_fixture_summary": {
            f: {
                "n_runs": per_fixture[f]["n_runs"],
                "categories": per_fixture[f]["categories"],
            }
            for f in per_fixture
        },
        "global_field_counts": {
            field: dict(cnt) for field, cnt in global_field.items()
        },
        "d_ranking_top20": d_ranking[:20],
        "b_ranking_top20": b_ranking[:20],
        "e_ranking_top10": e_ranking[:10],
    }
    out_json = EXP_DIR / "per_field_breakdown.json"
    out_json.write_text(json.dumps(aggregate, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"→ {out_json.name}")

    print("\n=== Top 10 D fields (모델 추출 실패 가장 많음) ===")
    for i, (field, cnt) in enumerate(d_ranking[:10], 1):
        print(f"  {i:2}. {field:50} D={cnt}")
    print("\n=== Top 10 B fields ===")
    for i, (field, cnt) in enumerate(b_ranking[:10], 1):
        print(f"  {i:2}. {field:50} B={cnt}")


if __name__ == "__main__":
    main()
