# ai/ 파이프라인 QA 발견사항 (2026-05-16)

코드 리뷰 범위: `ai/pipeline.py`, `ai/services/*`, `ai/prompts/*`, `ai/schemas/*`.
정렬 기준 — 운영 영향 큰 순.

---

## C1. 429 (rate limit) retry 없음 — `ai/services/upstage.py:72`

```python
if resp.status_code >= 500:
    ...
    await self._backoff_if_more_attempts(...)
    continue

if resp.status_code >= 400:  # 429 도 여기 — 즉시 raise_for_status
    logger.error("upstage error body: %s", resp.text)
resp.raise_for_status()
```

5xx 만 backoff. **429 도 동일 분기에 들어가서 retry 없이 즉시 실패**. CLAUDE.md
가 명시한 "Parallel calls hit Upstage 429 rate limits, so calls are serial" 의
직접 원인 — voting N=2~3 sequential 호출 사이에도 burst 로 429 가 나면 그대로
파이프라인 중단.

**수정안**: `status_code == 429` 분기를 5xx 위에 추가. backoff 시 `Retry-After`
헤더 우선, 없으면 exponential (1s/2s/4s) 로 5xx 보다 길게.

```python
if resp.status_code == 429:
    retry_after = float(resp.headers.get("retry-after", 0))
    delay = max(retry_after, self.RETRY_BACKOFF_S * (2 ** (attempt + 2)))
    if attempt < self.MAX_RETRIES - 1:
        await asyncio.sleep(delay)
        continue
```

**영향**: 평가 스크립트 timeout / 정밀도 측정 안정성. accuracy-first 우선순위에
정합 (실패한 run 은 score 0 이라 평균 떨어뜨림).

---

## C2. `_find_element_for_quote` 양방향 substring 매칭이 짧은 element 에 오매칭 — `ai/services/extract.py:228`

```python
# step 3: 정규화 후 양방향 substring
if qn in en or en in qn:    # ← en in qn 방향이 위험
    return elem
```

재현:
- elements: `[{id=1, text="제3조"}, {id=2, text="개인정보 수집은 ..."}]`
- quote: `"제3조 (개인정보 보호) 회사는 사용자의 개인정보를 수집합니다."`
- 결과: id=1 (제목, 4자) 매칭 → bbox 가 *제목 영역* 으로 잡힘. 실제 인용
  텍스트가 있는 paragraph 2 가 아님.

**수정안**: `en in qn` 방향에 최소 길이 가드. step 4 anchor (앞 20자) 가 이미
있으므로 이 방향은 제거하거나 `len(en) >= 16` 이상에서만 허용:

```python
if qn in en:
    return elem
# en in qn 방향: element 가 quote 의 일부일 수도 있음 (LLM 이 인용 확장)
# 그러나 너무 짧은 element 는 generic 매칭 → 거부
if len(en) >= 16 and en in qn:
    return elem
```

**영향**: bbox 정확도 (UI 의 PDF 하이라이트 위치). golden 스코어 직접 영향
없으나 사용자 demo 품질.

---

## C3. `pipeline.chat()` 가 `client.snapshot_usage()` 안 부름 — `ai/pipeline.py:163-251`

`run_pipeline` 은 시작 시 + 단계마다 `client.snapshot_usage()` 로 버퍼 비움.
`chat()` 은 호출하지 않아서 **같은 `UpstageClient` 인스턴스가 chat → pipeline
순으로 재사용되면 chat 의 usage 가 다음 pipeline 의 `parse` 단계에 합산**.

FastAPI 가 per-request fresh client 면 무해 — 현 코드 흐름 확인 필요.

**수정안**: `chat()` 진입 직후 `client.snapshot_usage()` 1줄, 종료 직전 1줄
(원하면 사용량 로그). 또는 `chat` 의 usage 가 의미 있으면 별도 로깅.

---

## C4. docs ↔ 코드 불일치: ENSEMBLE_N — `ai/services/extract.py:174` vs `CLAUDE.md:106`

- 코드: `ENSEMBLE_N = int(os.getenv("EXTRACT_ENSEMBLE_N", "2"))` (default 2)
- CLAUDE.md: "**N=3 sequential** calls (`ENSEMBLE_N`)"

EXPERIMENTS.md 가 N=2 winner 라고 명시하므로 코드가 맞고 docs 가 stale.
CLAUDE.md "N=3" 를 "N=2" 로 동기화.

---

## C5. Groundedness Stage clause-by-clause 직렬 호출 — `ai/services/ground.py:93`

```python
for clause in summary.key_clauses:
    is_grounded, score = await _check_one(client, context=..., answer=...)
```

clause N개 + summary 1번 = N+1 호출 모두 직렬. 5개 clause = ~50s. **정확도
영향 없이 latency 만 단축 가능** (accuracy-first 정책 위반 없음).

**수정안**: `asyncio.gather` 로 N 호출 병렬화 + summary 는 별도. 429 retry
(C1) 가 함께 들어가야 안전.

```python
results = await asyncio.gather(*[
    _check_one(client, context=source_markdown, answer=...)
    for clause in summary.key_clauses
])
```

**영향**: 정확도 동일, latency 약 30~50% 단축 추정.

---

## C6. 스타일/PEP 8 — `ai/services/extract.py`

- `from ai.schemas.common import ...` (line 160) 가 함수 정의 사이에 끼어있음.
- `from ai.prompts.extract_ai import ...` 등 finance/insurance/ai (line 375~390)
  도 동일.
- `# noqa: E402` 주석으로 lint 끔.

→ 모듈 top 으로 이동. `_select_system_prompt` 가 다른 import 보다 위에 와야 하는
순서 dependency 없음.

---

## C7. `HEADING_TAGS_ALONE` 정의 위치 — `ai/services/parse.py:80, 83`

`class _HTMLTextExtractor.get_text` 가 `HEADING_TAGS_ALONE` 참조 → 그 변수는
class 정의 아래 (line 83) 에 module-level 로 정의. 메서드 호출 시점에 lookup
되므로 runtime 작동은 함. 다만 lint 경고 가능 + 가독성 떨어짐.

**수정안**: class 위로 이동.

---

## C8. `pipeline.chat()` 함수 안 `import json` 중복 — `ai/pipeline.py:240`

파일 top (line 5) 에 이미 `import json` 있음. function-scope 중복 제거.

---

## C9. `ground.py` quote_anchored 케이스의 LLM grounded=false 무시 — `ai/services/ground.py:104`

```python
if quote_anchored and score >= 0.4:
    grounded.append(clause)
```

quote 원문 매칭됐으면 LLM 이 `grounded=False, score=0.9` 같은 모순적 응답을
줘도 통과. 의도된 안전 룰 (인용은 검증됨 → 설명만 합리적이면 됨) 이지만,
score >= 0.4 임계가 매직 넘버. **주석으로 의도 명시 권장**.

---

## C10. `dispute_reasoning.py` 입력 자르기 600/400자 하드코딩 — `ai/services/dispute_reasoning.py:70-71`

```python
clause_quote=(clause_quote or "")[:600] or "(원문 없음)",
clause_description=(clause_description or "")[:400] or "(설명 없음)",
```

CLAUDE.md 정책: 토큰 비용 제약 아님 + dispute reasoning 은 DB 캐시 → latency
부담 없음. **truncation 제거 또는 환경변수로 빼고 default 무제한** 권장.

---

# 우선순위 요약

| Tier | 항목 | 가치 | 노력 |
|---|---|---|---|
| 🔴 High | C1 (429 retry) | 운영 안정성 | 30분 |
| 🔴 High | C2 (substring 오매칭) | bbox 정확도 | 15분 |
| 🟡 Med | C3 (chat snapshot_usage) | hidden state 제거 | 5분 |
| 🟡 Med | C4 (docs N=3→N=2) | docs 정합성 | 5분 |
| 🟡 Med | C5 (ground 병렬화) | latency -30% | 30분 |
| 🟢 Low | C6, C7, C8 | 가독성/lint | 10분 |
| 🟢 Low | C9 (주석) | docs | 5분 |
| 🟢 Low | C10 (truncation 제거) | 품질 미세 | 10분 |
