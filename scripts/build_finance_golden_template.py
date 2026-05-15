"""FinanceTerms 기준 golden 라벨 템플릿 생성기. (insurance 와 동일한 패턴.)

기존 fintech golden 의 v0.3 자동 재매핑은 scripts/remap_fintech_golden_v03.py
에 있음. 이 스크립트는 *새* fintech 약관을 처음부터 라벨링할 때 사용.

사용:
    .venv/bin/python scripts/build_finance_golden_template.py
    → data/fixtures/sample_finance_golden_template.json 생성
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from ai.schemas.common import FieldValue
from ai.schemas.finance import FinanceTerms

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = ROOT / "data" / "fixtures"


def _is_fieldvalue_annotation(annotation) -> bool:
    origin = getattr(annotation, "__origin__", None)
    if origin is FieldValue:
        return True
    return isinstance(annotation, type) and issubclass(annotation, FieldValue)


def _walk_field_paths(model_cls) -> list[str]:
    paths: list[str] = []
    for field_name, field_info in model_cls.model_fields.items():
        annotation = field_info.annotation
        if (
            isinstance(annotation, type)
            and issubclass(annotation, BaseModel)
            and any(
                _is_fieldvalue_annotation(annotation.model_fields[inner].annotation)
                for inner in annotation.model_fields
            )
        ):
            for inner_name in annotation.model_fields:
                if _is_fieldvalue_annotation(annotation.model_fields[inner_name].annotation):
                    paths.append(f"{field_name}.{inner_name}")
        elif field_name == "unfair_clause_flags":
            paths.append("unfair_clause_flags")
    return paths


def main() -> None:
    paths = _walk_field_paths(FinanceTerms)
    out: dict = {
        "_meta": {
            "service_name": "<채워주세요>",
            "service_provider": "<발행 사업자>",
            "schema_version": "v0.3-finance",
            "domain": "finance",
            "labeler": "TBD",
            "extraction_date": "YYYY-MM-DD",
            "document_source_url": "<약관 원본 URL>",
            "instructions": (
                "각 필드의 'expected' 값을 약관 원문 기준 정답으로 채우세요. "
                "enum 값은 ai/schemas/enums.py 참조 — FraudResponsibilityPattern, "
                "DepositProtectionStatus, NoticeChannel, ConsentMechanism 등."
            ),
            "note": "scripts/build_finance_golden_template.py 로 자동 생성된 빈 템플릿.",
        }
    }
    for path in paths:
        if path == "unfair_clause_flags":
            out[path] = {"expected": [], "_source_quote": "", "_source_page": None, "note": ""}
        else:
            out[path] = {"expected": None, "_source_quote": "", "_source_page": None, "note": ""}

    dst = FIXTURE_DIR / "sample_finance_golden_template.json"
    with open(dst, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"✓ {dst.name}: {len(paths)} 필드 (모두 expected=null)")


if __name__ == "__main__":
    main()
