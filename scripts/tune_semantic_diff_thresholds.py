"""semantic diff (`compute_semantic_diff`) 의 cosine 임계값 튜닝.

대상: ai/services/diff.py 의 NEAR_DUP_THRESHOLD (기본 0.92) /
SUBSTANTIVE_THRESHOLD (0.70). 환경변수로 조정 가능하지만 권장값은 실 데이터
기반 분포에서 도출해야 함.

방법:
1. fixture (`<service>_terms.html`) 의 본문을 조항 단위로 split.
2. 각 조항에 세 변형 적용:
   - phrasing_only: 동의어 치환 ("구독"→"정기 결제" 등). 의미 동일.
   - value_change: 숫자/일수 변경. 의미 다름.
   - unrelated: 다른 도메인 fixture 의 조항으로 교체. 무관.
3. 모든 (원본, 변형) pair 의 cosine similarity 를 Upstage embedding 으로 계산.
4. 카테고리별 평균/percentile 출력. 권장 임계값 제안:
   - NEAR_DUP_THRESHOLD: phrasing_only.p10 과 value_change.p90 사이.
   - SUBSTANTIVE_THRESHOLD: value_change.p10 과 unrelated.p90 사이.

사용:
    PYTHONPATH=. .venv/bin/python scripts/tune_semantic_diff_thresholds.py
    PYTHONPATH=. .venv/bin/python scripts/tune_semantic_diff_thresholds.py --fixtures toss banksalad
"""

from __future__ import annotations

import argparse
import asyncio
import re
import statistics
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = ROOT / "data" / "fixtures"


# 동의어 치환 — phrasing_only 변형 (의미 동일)
SYNONYM_MAP: dict[str, str] = {
    "구독": "정기 결제",
    "통지": "공지",
    "회사": "사업자",
    "회원": "이용자",
    "약관": "이용약관",
    "동의": "승인",
    "해지": "탈퇴",
    "변경": "수정",
    "이용": "사용",
    "제공": "지원",
    "서비스를": "서비스 내용을",
    "신청": "요청",
}


_NUM_REGEX = re.compile(r"(\d+)(\s*(?:일|개월|원|건|회|년))")


def synth_phrasing_only(text: str) -> str:
    """동의어 치환만 — 의미 동일.

    순서-의존 버그 회피: 단일 정규식 패스로 모든 치환을 한 번에. 긴 키 먼저 매칭
    되도록 길이 내림차순으로 alternation 구성 ("약관" 이 "이용" 보다 먼저 적용
    되어 "이용약관" → "사용이용약관" 같은 의도치 않은 치환 방지).
    """
    keys = sorted(SYNONYM_MAP.keys(), key=len, reverse=True)
    pattern = re.compile("|".join(re.escape(k) for k in keys))
    return pattern.sub(lambda m: SYNONYM_MAP[m.group(0)], text)


def synth_value_change(text: str) -> str:
    """숫자 1~3 자리만 임의 변경 (배수/감수). 의미 다름."""
    def _replace(m: re.Match[str]) -> str:
        num = int(m.group(1))
        unit = m.group(2).strip()
        if num <= 3:
            new = num * 5
        elif num <= 30:
            new = num // 2 if num >= 14 else num * 2
        else:
            new = num * 2
        return f"{new}{unit}"
    new_text = _NUM_REGEX.sub(_replace, text, count=2)  # 최대 2개만 변경
    # 숫자가 전혀 없으면 fallback: 첫 명사구에 부정 표현 삽입
    if new_text == text:
        new_text = "위 조항은 적용되지 않습니다. " + text
    return new_text


def synth_unrelated(other_clauses: list[str], idx: int) -> str:
    """다른 fixture 조항으로 교체."""
    return other_clauses[idx % len(other_clauses)]


# ── fixture 로더 ──────────────────────────────────────────


class _HTMLText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data):
        if self._skip_depth == 0:
            self.parts.append(data)

    @classmethod
    def extract(cls, html: str) -> str:
        p = cls()
        p.feed(html)
        return "\n".join(p.parts)


def load_clauses(fixture_name: str) -> list[str]:
    """fixture HTML 을 평문화 후 조항 단위 split."""
    path = FIXTURE_DIR / f"{fixture_name}_terms.html"
    if not path.exists():
        return []
    html = path.read_text(encoding="utf-8", errors="ignore")
    text = _HTMLText.extract(html)
    # 빈 줄 또는 \n 단위 split, 너무 짧은 건 (<30자) drop
    parts = [p.strip() for p in re.split(r"\n\s*\n|\n", text) if len(p.strip()) >= 30]
    return parts


# ── 분포 분석 ─────────────────────────────────────────────


def summarize(label: str, sims: list[float]) -> dict:
    if not sims:
        return {"label": label, "n": 0}
    sims_sorted = sorted(sims)
    p10 = sims_sorted[int(len(sims) * 0.1)]
    p50 = statistics.median(sims_sorted)
    p90 = sims_sorted[int(len(sims) * 0.9)]
    return {
        "label": label,
        "n": len(sims),
        "min": round(min(sims), 4),
        "p10": round(p10, 4),
        "p50": round(p50, 4),
        "p90": round(p90, 4),
        "max": round(max(sims), 4),
        "mean": round(statistics.mean(sims), 4),
    }


def recommend(cats: dict[str, dict]) -> dict[str, float]:
    """카테고리별 분포에서 NEAR_DUP / SUBSTANTIVE threshold 권장.

    NEAR_DUP: phrasing_only.p10 ↔ value_change.p90 사이.
    SUBSTANTIVE: value_change.p10 ↔ unrelated.p90 사이.
    """
    pp = cats.get("phrasing_only", {})
    vc = cats.get("value_change", {})
    un = cats.get("unrelated", {})

    def _midpoint(low: float, high: float) -> float:
        return round((low + high) / 2, 3)

    out: dict[str, float] = {}
    if pp and vc:
        out["NEAR_DUP_THRESHOLD"] = _midpoint(vc.get("p90", 0.0), pp.get("p10", 1.0))
    if vc and un:
        out["SUBSTANTIVE_THRESHOLD"] = _midpoint(un.get("p90", 0.0), vc.get("p10", 1.0))
    return out


# ── 메인 흐름 ────────────────────────────────────────────


async def run(fixture_names: list[str], max_clauses_per_fixture: int) -> None:
    from ai.services.embed import embed_passages
    from ai.services.diff import _cosine
    from ai.services.settings import Settings
    from ai.services.upstage import UpstageClient
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")

    # 모든 fixture 의 조항 로드
    all_clauses: dict[str, list[str]] = {}
    for name in fixture_names:
        clauses = load_clauses(name)[:max_clauses_per_fixture]
        if clauses:
            all_clauses[name] = clauses
            print(f"  ✓ {name}: {len(clauses)} 조항")
        else:
            print(f"  ✗ {name}: fixture 없거나 조항 0")
    if not all_clauses:
        print("로드된 조항이 없어 중단")
        return

    # 변형 생성
    originals: list[str] = []
    phrased: list[str] = []
    valued: list[str] = []
    unrelated: list[str] = []

    fixture_list = list(all_clauses.items())
    for fi, (name, clauses) in enumerate(fixture_list):
        # 다른 fixture 조항을 unrelated source 로 (없으면 다음 fixture 의 일부)
        other = []
        for fj, (oname, oc) in enumerate(fixture_list):
            if fj != fi:
                other.extend(oc)
        for ci, c in enumerate(clauses):
            originals.append(c)
            phrased.append(synth_phrasing_only(c))
            valued.append(synth_value_change(c))
            unrelated.append(synth_unrelated(other, ci) if other else c[::-1])

    # 임베딩
    settings = Settings()
    print(f"\n→ Embedding {len(originals)} originals + 3 × {len(originals)} variants = "
          f"{4 * len(originals)} passages...")
    async with UpstageClient(settings) as client:
        v_orig = await embed_passages(client, originals)
        v_phra = await embed_passages(client, phrased)
        v_vc = await embed_passages(client, valued)
        v_un = await embed_passages(client, unrelated)

    # cosine 계산
    sims_phrasing = [_cosine(a, b) for a, b in zip(v_orig, v_phra)]
    sims_value = [_cosine(a, b) for a, b in zip(v_orig, v_vc)]
    sims_unrelated = [_cosine(a, b) for a, b in zip(v_orig, v_un)]

    # 분포 출력
    cats = {
        "phrasing_only": summarize("phrasing_only", sims_phrasing),
        "value_change": summarize("value_change", sims_value),
        "unrelated": summarize("unrelated", sims_unrelated),
    }

    print("\n=== cosine similarity 분포 ===")
    for label, s in cats.items():
        if s.get("n"):
            print(
                f"  {label:15} n={s['n']:3} mean={s['mean']:.4f} "
                f"p10={s['p10']:.4f} p50={s['p50']:.4f} p90={s['p90']:.4f} "
                f"(min={s['min']:.4f} max={s['max']:.4f})"
            )

    rec = recommend(cats)
    print("\n=== 권장 임계값 ===")
    if "NEAR_DUP_THRESHOLD" in rec:
        print(f"  NEAR_DUP_THRESHOLD     = {rec['NEAR_DUP_THRESHOLD']} "
              f"(현재 default 0.92)")
    if "SUBSTANTIVE_THRESHOLD" in rec:
        print(f"  SUBSTANTIVE_THRESHOLD  = {rec['SUBSTANTIVE_THRESHOLD']} "
              f"(현재 default 0.70)")
    print("\n적용:")
    print("  export DIFF_NEAR_DUP_THRESHOLD=…   DIFF_SUBSTANTIVE_THRESHOLD=…")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--fixtures", nargs="+",
        default=["toss", "banksalad", "kakaopay", "claude", "netflix"],
        help="사용할 fixture 이름 (data/fixtures/<name>_terms.html)",
    )
    parser.add_argument(
        "--max-clauses", type=int, default=15,
        help="fixture 당 최대 조항 수 (속도/토큰 절약)",
    )
    args = parser.parse_args()
    asyncio.run(run(args.fixtures, args.max_clauses))


if __name__ == "__main__":
    main()
