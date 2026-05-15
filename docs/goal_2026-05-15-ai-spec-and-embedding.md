# Goal: AI specialization + str embedding 통합 검증 (2026-05-15)

> **상태: COMPLETED (2026-05-15 07:54 KST)**
> 결과 요약은 [완료 요약](#완료-요약-2026-05-15-0754) 섹션 참조.

## 완료 요약 (2026-05-15 07:54)

### 최종 결정

| 변경 | 결정 | 근거 |
|---|---|---|
| str embedding (MiniLM, cosine ≥ 0.7) | ✅ 유지 | sanity check 통과, AI semantic +1.8 |
| flag canonical alias (POST-XX ↔ 한글) | ✅ 유지 | Watcha precision 0.00 → 0.17 |
| list vocab AI 도메인 확장 | ✅ 유지 | 부작용 없는 정규화 |
| enum alias (governing law) | ✅ 유지 | str 정규화에만 영향 |
| LLM-4 강화 (Free Plan 7가지 패턴) | ❌ Rollback | OTT 회귀 + claude -5.5 |
| LLM-6 매핑 추가 (silent_acceptance 등) | ❌ Rollback | OTT 회귀 의심 |

### 측정 결과 (15 fixture × 2 runs × 3 keys)

- OTT (7): 64.7% / 70.8% (semantic 벤치마크 -9.2%p)
- Fintech (3): 64.3% / 71.3% (semantic 벤치마크 -8.7%p) ⭐ 가장 잘됨
- AI (5): 47.9% / 52.0% (semantic 벤치마크 -28%p) ⚠️ 도메인 본질적 갭

### 완료 조건 vs 결과

- ❌ AI 평균 ≥ 55% strict (47.9, 미달) — sample noise 영향
- ⚠️ 모든 도메인 회귀 없이 +2%p (prompt 보강 회귀로 rollback 결정)

### 핵심 학습

1. **15 fixture × N=2 sample noise > prompt 룰 효과** — 같은 prompt+fixture로 ±5-13%p 변동
2. **Scoring layer > prompt tuning (안전성 측면)** — embedding/flag canonical은 회귀 없이 누적 가능
3. **AI specialization은 trade-off** — 한 fixture 회복이 다른 fixture 회귀 가져옴

### 관련 commits

- `5a35244` feat: scoring embedding + flag canonical, rollback LLM-4/LLM-6 prompt boost
- `68590ba` wip: AI domain specialization (pending measurement)

### 다음 단계 후보 (별도 goal로 진행)

- N=5 runs로 variance 안정화 (~1.5-3시간)
- AI sub-domain 분리 (Claude/GPT는 글로벌 영문, Upstage/DeepSeek는 한국어판)
- Coupang Wow 별도 도메인 (전자상거래 구독)

---

## 작업 이력 (Archive)

## 현재 상태 (2026-05-15 05:07 KST 작성)

### 완료된 작업

1. ✅ Coupang Play 통합본 fixture (64KB) + golden v0.3
2. ✅ Scoring normalization (enum aliases + list vocab + str token Jaccard) — commit `eb62f58`
3. ✅ Multi-API-key + parallel runner — commit `667dafe`
4. ✅ Domain-aware prompt split (OTT/Fintech/AI) — commit `d296322`
5. ✅ Generalization test (15 fixture × 2 runs): OTT 64.7 / Fintech 64.3 / AI 47.9
6. ✅ AI 도메인 fail 진단 (top 15 fail 필드 식별)
7. ✅ AI specialization 처방 적용 (LLM-4 강화 + LLM-6 매핑 추가 + scoring vocab 확장)
   - `prompts/extract_subscription.py` 수정 (미커밋)
   - `scripts/score_against_golden.py` 추가 vocab (미커밋)

### 진행 중

- 🔄 **AI specialization 측정 (5 fixture × 2 runs)** — 백그라운드 ID `b08h1jnz2`
  - 출력 파일: `/private/tmp/claude-501/-Users-ehho-Desktop-upstage-ai/.../tasks/b08h1jnz2.output`
  - 결과 JSON: `data/experiments/ai_spec_{fixture}_run{1,2}.json`

## 재개 시 작업 순서

### Phase 1: AI 결과 분석 + 통합 (cron fire 시 여기서부터)

1. **AI 측정 결과 확인**
   ```bash
   cat /private/tmp/claude-501/-Users-ehho-Desktop-upstage-ai/d4a712f8-4361-4227-879b-3e9dad0e9e97/tasks/b08h1jnz2.output
   ls data/experiments/ai_spec_*.json
   ```
   - 5 fixture (claude, gpt, deepseek, upstage, gemini) × 2 runs 결과 확인
   - baseline 대비 (claude 57.5, gpt 53, deepseek 45, upstage 46, gemini 38) 회복 측정

2. **README 업데이트** — `README.md`
   - "Round 7: AI domain specialization" 섹션 추가
   - 15 fixture 도메인별 평균 (OTT 64.7 / Fintech 64.3 / AI 47.9 → ?)
   - 처방 효과 명시 (LLM-4 강화 / LLM-6 매핑 / scoring vocab)

3. **unfair_clause_flags POST-XX ↔ 한글 매핑 추가** — `scripts/score_against_golden.py`
   - 현재: `_normalize_flag()`가 괄호/언더스코어만 제거
   - 추가 그룹:
     - `POST-01` ↔ `약관 일방 변경권` ↔ `unilateral_change`
     - `POST-02` ↔ `다크패턴 — 해지 절차 복잡화` ↔ `complex_cancellation`
     - `POST-03` ↔ `환불 거부` ↔ `refund_denial`
     - `POST-04` ↔ `면책/손배 제한` ↔ `liability_cap`
     - `POST-05` ↔ `분쟁/집단소송 포기` ↔ `arbitration_class_waiver` ↔ `의사표시_의제`
   - watcha precision 0.0 → recall +30~40%p 예상

4. **7 fixture 재채점** — flags 매핑 + AI prompt + scoring vocab 적용 결과
   ```bash
   .venv/bin/python scripts/run_all_fixtures.py 2 3
   ```

5. **Phase 1 통합 commit**
   - `prompts/extract_subscription.py` (LLM-4 강화 + LLM-6 매핑 추가)
   - `scripts/score_against_golden.py` (vocab 확장 + flags 매핑)
   - `README.md` 업데이트
   - 커밋 메시지: `feat: AI domain specialization (LLM-4/LLM-6) + unfair_flags vocab`

### Phase 2: str embedding 도입

6. **의존성 추가** — `pyproject.toml`
   ```toml
   sentence-transformers = "^3.0.0"
   ```
   - `uv pip install sentence-transformers` 또는 `uv sync`

7. **`_str_embedding_similar` 함수** — `scripts/score_against_golden.py`
   - 모델: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`
   - lazy import (라이브러리 없으면 기존 휴리스틱만 사용 fallback)
   - 캐시: 같은 string 임베딩 재사용
   - 임계값: `SEMANTIC_EMBEDDING_THRESHOLD = 0.7` (실험 후 조정)

8. **`classify()` 통합** — 기존 SequenceMatcher/Jaccard/substring 셋 중 하나 만족 OR embedding ≥ 0.7
   - 점진적 도입 (기존 룰 비활성화 안 함)

### Phase 3: 전체 도메인 검증

9. **15 fixture × 2 runs × 3 keys 측정**
   ```bash
   EXTRA_FIXTURES=all .venv/bin/python scripts/run_all_fixtures.py 2 3
   ```
   - 예상 시간: 47.5분 (이전 generalization test와 동일)

10. **도메인별 결과 분석**
    - OTT / Fintech / AI 평균 모두 개선 → 유지
    - 한 도메인이라도 회귀 → 임계값 0.7 → 0.75 조정 또는 롤백
    - 회귀 fixture 찾아서 false positive 케이스 sample 검토

11. **commit + README "Round 8: str embedding" 추가** (효과 있을 시)

## 완료 조건

- [ ] AI 평균 ≥ 55% strict (현재 47.9%)
- [ ] str embedding 도입 후 모든 도메인 회귀 없이 평균 +2%p 이상
- [ ] 모든 변경사항 git commit 완료 (push-ready)

## 사용 명령어 cheatsheet

```bash
# 7 fixture (OTT만) × 2 runs × 3 keys
.venv/bin/python scripts/run_all_fixtures.py 2 3

# 15 fixture (OTT + AI + Fintech) × 2 runs × 3 keys
EXTRA_FIXTURES=all .venv/bin/python scripts/run_all_fixtures.py 2 3

# 단일 fixture 채점
.venv/bin/python scripts/score_against_golden.py \
  data/experiments/ai_spec_claude_run1.json \
  data/fixtures/claude_golden.json --semantic
```

## 변경 파일 목록 (미커밋)

- `prompts/extract_subscription.py` — LLM-4 강화 + LLM-6 매핑 추가
- `scripts/score_against_golden.py` — AI vocab 추가, governing law alias 추가
- `scripts/run_all_fixtures.py` — EXTRA_FIXTURES env 지원 (15 fixture 옵션)
- `docs/goal_2026-05-15-ai-spec-and-embedding.md` — 본 문서
