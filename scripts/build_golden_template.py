"""파이프라인 1회 결과를 베이스로 골든 라벨 템플릿 생성.

사용:
    .venv/bin/python scripts/build_golden_template.py [pipeline_result.json] [output.json]

기본:
    input  = /tmp/variance_run_1.json (가장 최근 eval run)
    output = data/fixtures/netflix_golden.json

이후 사람이 `expected` 필드를 정답으로 편집. 다른 필드는 참고용.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = Path("/tmp/variance_run_1.json")
DEFAULT_OUTPUT = ROOT / "data" / "fixtures" / "netflix_golden.json"

SECTIONS = (
    "pricing", "free_trial", "cancellation", "terms_changes",
    "data_usage", "liability", "disputes",
)


def _enum_value(v):
    """Pydantic dump 결과의 enum을 plain 값으로."""
    if hasattr(v, "value"):
        return v.value
    return v


def build_template(run: dict) -> dict:
    """파이프라인 결과 dict → 골든 템플릿 dict."""
    template: dict = {
        "_meta": {
            "service_name": run["terms"]["service_name"],
            "instructions": (
                "각 필드의 'expected' 값을 약관 원문 기준으로 정답으로 편집하세요. "
                "model_value/source_quote는 참고용. "
                "정답이 약관에 없으면 null 유지, 모호하면 'AMBIGUOUS'로 기록 후 별도 노트. "
                "리스트는 정렬된 형태로 입력. enum 값은 schema/enums.py 참조."
            ),
        },
    }
    for section in SECTIONS:
        for field, fv in run["terms"][section].items():
            key = f"{section}.{field}"
            cit = fv.get("citation") or {}
            template[key] = {
                "expected": _enum_value(fv["value"]),  # 사용자가 편집할 자리
                "model_value": _enum_value(fv["value"]),
                "model_uncertainty": fv["uncertainty"],
                "source_quote": (cit.get("quote") or "")[:120],
                "source_page": cit.get("page"),
            }
    # unfair_clause_flags 별도
    template["unfair_clause_flags"] = {
        "expected": list(run["terms"].get("unfair_clause_flags") or []),
        "model_value": list(run["terms"].get("unfair_clause_flags") or []),
    }
    return template


def main():
    in_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_INPUT
    out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_OUTPUT
    if not in_path.exists():
        print(f"ERROR: input {in_path} not found")
        sys.exit(1)
    with open(in_path) as f:
        run = json.load(f)
    template = build_template(run)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(template, f, ensure_ascii=False, indent=2)
    field_count = sum(1 for k in template if k not in ("_meta", "unfair_clause_flags"))
    print(f"Template written to {out_path}")
    print(f"  - {field_count} fields to verify (plus unfair_clause_flags)")
    print(f"  - edit each entry's 'expected' to ground truth")


if __name__ == "__main__":
    main()
