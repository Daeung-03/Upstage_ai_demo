"""InsuranceTerms 기준 golden 라벨 템플릿 생성기.

InsuranceTerms 스키마의 모든 필드를 `expected: null` 인 라벨 entry 로 풀어
JSON 으로 저장한다. 라벨러가 실제 보험약관을 보고 expected 값을 채워 넣는
시작점.

사용:
    .venv/bin/python scripts/build_insurance_golden_template.py
    → data/fixtures/sample_insurance_golden_template.json 생성

라벨링 가이드:
- expected: 약관 원문 기준 정답. 없으면 null 유지.
- _source_quote / _source_page: 정답 근거 발췌와 페이지.
- enum 필드는 ai/schemas/enums.py 의 string value 그대로 사용
  (InsuranceClaimMethod / PremiumCycle / RefundFormula / CancellationMethod /
   ConsentMechanism / NoticeChannel).
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from ai.schemas.common import FieldValue
from ai.schemas.insurance import InsuranceTerms

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = ROOT / "data" / "fixtures"


def _walk_field_paths(model_cls, prefix: str = "") -> list[str]:
    """root model 의 sub-model 필드를 reflection 으로 순회 → dotted path 리스트."""
    paths: list[str] = []
    for field_name, field_info in model_cls.model_fields.items():
        annotation = field_info.annotation
        if (
            isinstance(annotation, type)
            and issubclass(annotation, BaseModel)
            and any(
                getattr(annotation, "model_fields").get(inner) is not None
                and _is_fieldvalue_annotation(annotation.model_fields[inner].annotation)
                for inner in annotation.model_fields
            )
        ):
            for inner_name in annotation.model_fields:
                if _is_fieldvalue_annotation(annotation.model_fields[inner_name].annotation):
                    paths.append(f"{field_name}.{inner_name}")
        elif field_name == "unfair_clause_flags":
            paths.append("unfair_clause_flags")
    return paths


def _is_fieldvalue_annotation(annotation) -> bool:
    """annotation 이 FieldValue[...] 인지 확인."""
    origin = getattr(annotation, "__origin__", None)
    if origin is FieldValue:
        return True
    return isinstance(annotation, type) and issubclass(annotation, FieldValue)


def main() -> None:
    paths = _walk_field_paths(InsuranceTerms)

    out: dict = {
        "_meta": {
            "service_name": "<채워주세요>",
            "service_provider": "<보험사 이름>",
            "schema_version": "v0.3-insurance",
            "domain": "insurance",
            "labeler": "TBD",
            "extraction_date": "YYYY-MM-DD",
            "document_source_url": "<약관 원본 URL>",
            "instructions": (
                "각 필드의 'expected' 값을 약관 원문 기준 정답으로 채우세요. "
                "enum 값은 ai/schemas/enums.py 참조 — InsuranceClaimMethod, "
                "PremiumCycle, RefundFormula 등."
            ),
            "note": "scripts/build_insurance_golden_template.py 로 자동 생성된 빈 템플릿.",
        }
    }
    for path in paths:
        if path == "unfair_clause_flags":
            out[path] = {"expected": [], "_source_quote": "", "_source_page": None, "note": ""}
        else:
            out[path] = {
                "expected": None,
                "_source_quote": "",
                "_source_page": None,
                "note": "",
            }

    dst = FIXTURE_DIR / "sample_insurance_golden_template.json"
    with open(dst, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"✓ {dst.name}: {len(paths)} 필드 (모두 expected=null)")


if __name__ == "__main__":
    main()
