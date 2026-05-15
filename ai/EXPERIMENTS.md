# AI 파이프라인 실험 트래커

이 파일은 추출(Extract) / 요약(Summarize) / 그라운드네스(Ground) 파이프라인의 성능 실험을 **한 곳에 누적 기록**하는 마스터 로그입니다. 새 실험을 돌릴 때마다 이 파일에 결과를 추가하고, **현재 베스트 케이스** 블록을 갱신합니다. 그 베스트 케이스가 README에 소개될 후보입니다.

상세 결과 파일 (per-run JSON / md)은 `data/experiments/` 아래에 그대로 두고, 여기서는 그 파일을 링크합니다.

---

## 평가 기준 (`CLAUDE.md` 최적화 우선순위와 일치)

1. **Accuracy** — strict(엄격 일치) / semantic(의미 일치) / grounded(요약 검증 통과율). **항상 최우선.**
2. **Latency** — fixture당 평균 wall-clock 초. accuracy 동률일 때만 우선순위 부여.
3. **Tokens** — 가시성 목적의 보고 항목. **trade-off 의사결정 기준 아님.**

베스트 케이스는 (1) → (2) 순서로 비교합니다. 토큰은 비교 표에 그대로 노출하지만 채택을 좌우하지 않습니다.

> 챗봇 (`app/services/chat_service.py`)은 별도 latency 제약이 있으므로 이 트래커의 베스트 케이스와는 분리해서 다룹니다. 챗봇 실험은 아래 "Chatbot 실험" 섹션에 따로 기록.

---

## 🏆 현재 베스트 케이스 (README 소개 후보)

| 항목 | 값 |
|---|---|
| **Config** | Solar Pro 3, `reasoning_effort=high`, voting `N=2` medium |
| **Scope** | 전 fixture (12개 OTT/구독 서비스) — BC + prompt #1 |
| **Strict accuracy (avg)** | 55.3% |
| **Semantic accuracy (avg)** | 60.5% |
| **Fixture별 최고** | netflix 85.0% semantic (75.5% strict) |
| **Latency (avg / fixture)** | ~800s |
| **Tokens (avg / fixture)** | ~198K |
| **Date** | 2026-05-15 |
| **Source** | [`data/experiments/all_fixtures_20260515_180018.md`](../data/experiments/all_fixtures_20260515_180018.md) |

**선정 사유**: 12개 fixture에 걸친 가장 광범위한 평가에서 가장 안정적인 strict/semantic 평균을 보임. Netflix 단일 fixture에서는 `N=2 medium`(config G)이 71.6% strict까지 도달했으므로, 단일 도메인 최적화 시 그 config를 베이스라인으로 사용.

---

## 실험 로그 (시간 역순)

새 실험 결과는 이 표 최상단에 한 줄로 추가하고, 상세는 그 아래 "실험 상세" 섹션에 블록으로 기록합니다.

| Date | Scope | Config | Strict | Semantic | Latency (s) | Tokens | Grounded | Detail |
|---|---|---|---|---|---|---|---|---|
| 2026-05-15 | 12 fixtures × 2 runs | BC + prompt #1, N=2 medium | 55.3% avg | 60.5% avg | ~800 | ~198K | 12.5% | [all_fixtures_20260515_180018.md](../data/experiments/all_fixtures_20260515_180018.md) |
| 2026-05-14 | Netflix only, 3 rounds, 23 runs | **G: N=2 medium, prompt mini-fix** | 71.6% (max 80%) | – | 222 | 70K | – | [aggregate_summary.md](../data/experiments/aggregate_summary.md) |

### 실험 상세

#### 2026-05-15 · 전 fixture BC + prompt #1

- **Defaults**: extract N=2 medium, summarize=high, ground=medium, prompt #1
- **Infra**: 3 API keys, per-key concurrency 3, total concurrency 9, runs per fixture 2, wall clock 49.5 min
- **Per-fixture (strict / semantic)**:
  - netflix 75.5 / 85.0 · claude 59.0 / 65.0 · wavve 62.5 / 65.0 · disney_plus 54.5 / 63.5 · spotify 55.5 / 64.0
  - deepseek 59.0 / 62.5 · tving 55.5 / 59.0 · gpt 55.5 / 59.0 · watcha 52.0 / 55.5 · gemini 44.5 / 49.5
  - coupang_play 47.5 / 53.0 · upstage 42.5 / 44.5
- **관찰**: 같은 config라도 fixture별 편차가 큼(netflix 85% ↔ upstage 44.5%). golden label 품질과 도메인 어휘 차이가 주요 변동 요인.

#### 2026-05-14 · Netflix 단일 winner 탐색

- **Configs 비교 (전 round 합산)**: G(N=2 medium) **71.6%** > F(N=5 medium) 66.0% > C(N=3 medium) 65.8% > B(N=1 high) 63.5% > A(N=3 high) 61.5% > D(N=1 medium) 59.8% > E(N=3 low) 45.0%
- **Voting 효과**: N=2 medium이 N=1 medium 대비 +11.8%p — voting의 실측 효과 확인.
- **`reasoning_effort`**: high가 medium보다 항상 더 좋지는 않음 (A: N=3 high 61.5% vs C: N=3 medium 65.8%). medium + N≥2가 최적점.
- **Prompt mini-fix**: 별도 정책 참조 → `not_specified`로 답하라는 미세 수정으로 평균 +4.3%p, 최고점 80% 달성.

---

## 채택 룰

1. **단일 fixture 실험**으로 새 winner config가 나오면, 같은 config를 **전 fixture 스윕**으로 검증 후 베스트 케이스 갱신.
2. **전 fixture 평균 strict가 현재 베스트보다 +2%p 이상** 좋아지면 베스트 케이스 교체.
3. Strict 동률 (±1%p) 일 때는 **semantic 우선**, 그래도 동률이면 **latency**로 결정.
4. 채택된 베스트 케이스는 README의 성능 섹션에 반영. 직전 베스트는 이 파일 로그에 남겨두기만 한다.

---

## Backlog (다음 실험 후보)

이 섹션은 자유롭게 메모. 실험 돌리고 결과 채워지면 위 로그로 옮긴다.

- [ ] `N=3 medium`을 전 fixture 스윕에 다시 돌려서 N=2와 직접 비교 (Netflix single fixture에서는 N=2가 이김; 전 도메인으로 일반화되는지 확인)
- [ ] 도메인별 prompt few-shot (특히 upstage/gemini/coupang_play 같은 저점 fixture)
- [ ] `summarize=high` ↔ `summarize=medium` ablation — 최종 사용자가 보는 텍스트의 품질 차이가 정량 점수에 잡히는지
- [ ] **Finance / Insurance 도메인 평가** — 스키마 정의 완료 (`ai/schemas/finance.py`, `ai/schemas/insurance.py`), voting 폴리모픽 동작 확인. 다음 단계: (1) `ai/prompts/extract_finance.py`·`extract_insurance.py` 프롬프트, (2) `extract.py` 에 도메인 라우팅, (3) `data/fixtures/{toss,kakaopay,banksalad}_golden.json` 을 v0.3 finance 스키마로 재라벨, (4) insurance fixture 1-2건 추가, (5) BC + voting N=2 평가.

---

## Chatbot 실험 (별도 latency 제약)

| Date | Config | 답변 품질 | p95 latency | Notes |
|---|---|---|---|---|
| _아직 기록 없음_ | | | | |

챗봇은 사용자가 실시간으로 기다리는 채널이므로, multi-pass voting / 30s+ reasoning 체인은 후보에서 제외. 품질 평가 기준이 결정되면 여기 표에 채워 넣는다.
