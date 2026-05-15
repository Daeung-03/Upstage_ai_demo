-- 0005_termversion_effective_date.sql
-- TermVersion 에 약관 시행일(effective_date) 추가.
--
-- 의미:
--   - 약관 자체에 적힌 "이 약관은 YYYY-MM-DD 부터 시행" 날짜.
--   - 버전별로 다름 (v1 시행 2024-01-01 → 개정 v2 시행 2025-03-15).
--   - 사용자가 가입한 날 (Term.subscribed_at) 과 의미 다름.
--
-- nullable — 기존 row + effective_date 미입력 업로드 호환.
-- 프론트는 NULL 일 때 TermVersion.created_at 로 fallback.

BEGIN;

ALTER TABLE term_versions
    ADD COLUMN IF NOT EXISTS effective_date DATE NULL;

COMMIT;
