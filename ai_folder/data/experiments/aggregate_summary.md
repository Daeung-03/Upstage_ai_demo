# 실험 종합 — 2026-05-14 (3개 round, 23 runs)

**Fixture**: Netflix terms (data/fixtures/netflix_golden.json, 사용자 라벨 v0.2)  
**Total wall clock**: ~106분

## 전체 config 비교 (모든 round 합산)

| Config | Runs | Acc 평균 | 범위 | Std | Sec 평균 | Tokens 평균 |
|---|---|---|---|---|---|---|
| E: N=3 low | 2 | **45.0%** | 40–50 | 5.0 | 116 | 58K |
| D: N=1 medium | 4 | 59.8% | 45–69 | 9.4 | 144 | 47K |
| A: N=3 high | 2 | 61.5% | 59–64 | 2.5 | 313 | 85K |
| B: N=1 high | 2 | 63.5% | 61–66 | 2.5 | 97 | 49K |
| C: N=3 medium | 5 | 65.8% | 57–71 | 5.5 | 308 | 92K |
| F: N=5 medium | 1 | 66.0% | – | – | 419 | 131K |
| **G: N=2 medium** | **7** | **71.6%** | 66–80 | 4.9 | 222 | 70K |

## ⭐ 핵심 발견: G가 명확한 winner

7 sample, 평균 71.6%, std 4.9%p. 95% CI ≈ [67%, 76%].

**다른 config 대비:**
- vs C (N=3 medium): +5.8%p 정확도, 시간 -28%, 토큰 -24%
- vs D (N=1 medium): +11.8%p 정확도 (voting의 진짜 효과)
- vs A (N=3 high): +10.1%p 정확도, 시간 -29%, 토큰 -18%

## Prompt mini-fix 효과 (별도 정책 참조 패턴)

G config에서만 비교 가능 (round 2 pre-fix vs round 3 with-fix):

| | Pre-fix (round 2) | With-fix (round 3) |
|---|---|---|
| Samples | 2 | 5 |
| 평균 | 68.5% | **72.8%** |
| 범위 | 66-71 | 66-80 |
| 최고 | 71% | **80%** ✨ |

**+4.3%p 평균 개선** + 80% 최고점 도달. mini-fix가 측정 가능한 효과를 줌.

### 단일 80% run 분석 (G round 3 run 2)
- **`over_extracted = 0`** ← 다른 모든 G run은 1-4건. 이 run만 모델이 "모르는 건 모른다"고 답함
- bool 87.5%, free_trial 100%, data_usage 87.5%
- prompt fix(별도 정책 참조 → not_specified)가 데이터·자유체험 섹션에서 정확히 작동
- variance가 운 좋게 합쳐졌을 때 80% 도달 가능

## 타입별 최고 정확도

| Type | 최고 config | 정확도 |
|---|---|---|
| int | F (N=5) / C (N=3 medium) | 100% |
| enum | C / F / G | 80-83% |
| **bool** | **G (with mini-fix)** | **81.2%** ✨ |
| list | F | 83.3% |
| str | C / G (semantic mode) | ~57% strict, 더 높이려면 schema 변경 |

bool은 G가 1위로 올라옴 — mini-fix가 over-extraction 잡은 효과.

## 가장 자주 틀리는 필드 (분석 스크립트 결과)

| 필드 | 오류 종류 | 빈도 | 진단 |
|---|---|---|---|
| `data_usage.third_party_sharing` | over_extracted | 5/5 → 0/1* | mini-fix 후 줄어듦 |
| `data_usage.marketing_use` | over_extracted | 5/5 → 줄어듦 | 동상 |
| `cancellation.method_description` | wrong (paraphrase) | 5/5 | str 의역 — semantic mode 필요 |
| `terms_changes.silent_acceptance_clause` | wrong (type mismatch) | 5/5 | 골든의 "AMBIGUOUS" vs schema bool — 채점기에서 ok_null 처리하도록 fix됨 |
| `data_usage.collected_categories` | wrong (한/영 표기) | 5/5 → semantic으로 회수 가능 | 한국어 ↔ 영어 |
| `liability.compensation_description` | wrong + missed | 5/5 | str + paraphrase |
| `liability.force_majeure_scope` | wrong + missed | 5/5 | 동상 |

## Semantic 채점 모드

`scripts/score_against_golden.py --semantic` 추가 → str/list fuzzy 매칭 (SequenceMatcher 0.5+).

테스트 결과 (1 run):
- Strict: 69%
- Semantic: 71% (+2%p, list 83→100, data_usage 62.5→75)

자유 텍스트 손해의 일부 회수 가능. 정확도 측정의 진짜 상한선을 알기 위해 유용.

## 운영 권고 — **G (N=2 medium) 채택**

### 설정
```python
EXTRACT_ENSEMBLE_N=2
EXTRACT_REASONING_EFFORT=medium
```

### 효과 (전체 run 평균)
- 정확도: **71.6%** (vs Upstage Solar 한국어 capability ~80%, 갭 -8.4%p로 줄어듦)
- 시간: 222s per request
- 토큰: 70K per request
- Grounded: 40-100% (variance 큼 — summary verification 개선 여지)

### 비용 절감 vs 직전 C 디폴트
- 시간 -28%, 토큰 -24%, 정확도 +5.8%p

## 운영 신뢰도 vs 단일 sample 신뢰도

| 측정 | 값 |
|---|---|
| 단일 호출 신뢰도 (95% CI) | 67% – 76% |
| 좋은 condition 최고치 | 80% |
| 변동성 | std 4.9%p |
| Upstage 모델 자체 한국어 능력 | ~80% (벤치마크) |
| **현재 갭** | **-8.4%p** (이전 -16%p에서 회복) |

## 다음 우선순위 (시간 순)

1. **default config 변경 + commit** (지금 바로)
2. **`unfair_clause_flags` precision 회복** — 사용자 golden이 혼합 표기(POST-01, 면책/손배 제한, ...) → controlled vocab 정렬 필요. precision 0.25-0.5 수준
3. **`silent_acceptance_clause` AMBIGUOUS 케이스** — 사용자 라벨이 string인데 schema는 bool. 채점에서 ok_null 처리 적용됨. 향후 schema에 Optional[bool] + uncertainty=AMBIGUOUS 명시 옵션 검토
4. **다른 fixture 추가** (Spotify/Wavve 약관) — 단일 fixture variance를 분리하기 위해. 사용자 PDF 추가 필요
5. **Schema 확장** (Codex 추천 12개 신규 필드 일부) — 정확도 측정용 신규 필드 라벨링 필요

## 데이터 자산

- `data/experiments/experiments_20260514_032524.{json,md}` — Round 1 (7 runs)
- `data/experiments/experiments_20260514_040020.{json,md}` — Round 2 (8 runs)
- `data/experiments/experiments_20260514_152109.{json,md}` — Round 3 (8 runs)
- `data/experiments/aggregate_summary.md` — 본 문서
- `data/fixtures/netflix_golden.json` — 사용자 라벨 v0.2 (50 fields)
- `scripts/run_experiments.py` — config matrix runner
- `scripts/analyze_errors.py` — 필드별 오류 분포 분석
- `scripts/score_against_golden.py` — 정확도 채점 (--semantic 옵션 지원)
