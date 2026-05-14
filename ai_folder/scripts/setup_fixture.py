"""신규 fixture 1건 셋업 → 골든 템플릿 생성 + 라벨링 가이드 출력.

사용:
    .venv/bin/python scripts/setup_fixture.py <서비스명> <PDF경로>

예:
    .venv/bin/python scripts/setup_fixture.py spotify ~/Downloads/Spotify\\ 약관.pdf

수행 작업:
    1. PDF를 data/fixtures/<service>_terms.pdf 로 복사
    2. 1회 pipeline 실행 (현재 default config: N=2 medium)
    3. 결과를 data/fixtures/<service>_run_baseline.json 으로 저장
    4. 골든 템플릿을 data/fixtures/<service>_golden.json 으로 생성
    5. 사용자에게 라벨링 가이드 출력
"""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.build_golden_template import build_template  # noqa: E402
from services.pipeline import run_pipeline  # noqa: E402
from services.settings import Settings  # noqa: E402
from services.upstage import UpstageClient  # noqa: E402

FIXTURE_DIR = ROOT / "data" / "fixtures"


async def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    service_name = sys.argv[1]
    src_pdf = Path(sys.argv[2]).expanduser()
    if not src_pdf.exists():
        print(f"ERROR: source file not found: {src_pdf}")
        sys.exit(1)

    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    # 원본 확장자 보존 (pdf 또는 html — Document Parse 둘 다 지원)
    ext = src_pdf.suffix.lower() or ".pdf"
    fixture_pdf = FIXTURE_DIR / f"{service_name}_terms{ext}"
    baseline_run = FIXTURE_DIR / f"{service_name}_run_baseline.json"
    golden_path = FIXTURE_DIR / f"{service_name}_golden.json"

    # 1) PDF 복사
    print(f"[1/4] Copying PDF → {fixture_pdf.name}")
    shutil.copy(src_pdf, fixture_pdf)

    # 2) Pipeline 1회 실행
    print(f"[2/4] Running pipeline on {service_name}... (3-5min 예상)")
    t0 = time.perf_counter()
    settings = Settings()
    async with UpstageClient(settings) as client:
        result = await run_pipeline(
            client,
            file_bytes=fixture_pdf.read_bytes(),
            filename=fixture_pdf.name,
            service_name=service_name.capitalize(),
            service_provider=service_name.capitalize(),
        )
    elapsed = time.perf_counter() - t0
    print(f"      Done in {elapsed:.0f}s | grounded={result.grounded}")
    print(f"      Tokens: {sum(u.total_tokens for u in result.usage):,}")

    # 3) baseline run 저장
    print(f"[3/4] Saving baseline run → {baseline_run.name}")
    with open(baseline_run, "w", encoding="utf-8") as f:
        json.dump(result.model_dump(), f, ensure_ascii=False, indent=2)

    # 4) 골든 템플릿 생성
    print(f"[4/4] Building golden template → {golden_path.name}")
    template = build_template(result.model_dump())
    template["_meta"]["service_name"] = service_name.capitalize()
    template["_meta"]["fixture_pdf"] = fixture_pdf.name
    template["_meta"]["baseline_run"] = baseline_run.name
    with open(golden_path, "w", encoding="utf-8") as f:
        json.dump(template, f, ensure_ascii=False, indent=2)

    print()
    print("=" * 70)
    print(f"✅ {service_name} fixture setup 완료")
    print("=" * 70)
    print()
    print("다음 단계 (사용자 작업):")
    print(f"  1. 편집기에서 {golden_path.relative_to(ROOT)} 열기")
    print("  2. 각 항목의 'expected' 필드를 약관 원문 기준 정답으로 수정")
    print("     - model_value/source_quote는 참고용")
    print("     - 약관에 없으면 null 유지")
    print("     - 모호하면 'AMBIGUOUS' + note")
    print("  3. 라벨링 후:")
    print(f"     .venv/bin/python scripts/score_against_golden.py \\")
    print(f"       {baseline_run.relative_to(ROOT)} {golden_path.relative_to(ROOT)}")
    print()
    print(f"  현재 default config: N=2 voting + medium reasoning")
    print(f"  예상 라벨링 시간: ~30분 (42 필드)")


if __name__ == "__main__":
    asyncio.run(main())
