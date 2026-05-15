-- 0003_termclause_risk_and_reasoning.sql
-- TermClause 에 4 컬럼 추가:
--
--   risk_level         : KeyClause.risk_level ("high" / "medium" / "low") 저장.
--                        지금까지는 _parse_result_to_clauses 에서 떨어져 나가서
--                        프론트에 노출 못 했음.
--   pain_point_id      : KeyClause.pain_point_id (PRE-01 ~ POST-05 등). 분쟁 사례
--                        매칭 시 pain_point boost 활성화에 사용.
--   dispute_reasoning  : LLM 으로 생성한 "왜 위험한가" 자연어 reasoning. lazy cache
--                        — 첫 /disputes 조회 시 생성/저장, 이후 hit.
--   disputes_signature : 캐시 무효화 키. dispute_cases 테이블의 최신 updated_at
--                        max 를 hash 해 저장. 다음 조회에서 signature 가 다르면
--                        cache miss 처리해 reasoning 재생성.
--
-- 모두 NULL 허용 — 기존 row 무영향. IF NOT EXISTS 로 idempotent.

BEGIN;

ALTER TABLE term_clauses
    ADD COLUMN IF NOT EXISTS risk_level         TEXT NULL,
    ADD COLUMN IF NOT EXISTS pain_point_id      TEXT NULL,
    ADD COLUMN IF NOT EXISTS dispute_reasoning  TEXT NULL,
    ADD COLUMN IF NOT EXISTS disputes_signature TEXT NULL;

COMMIT;
