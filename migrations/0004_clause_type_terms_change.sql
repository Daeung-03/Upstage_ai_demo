-- 0004_clause_type_terms_change.sql
-- ClauseType enum 에 'TERMS_CHANGE' 값 추가.
-- 배경: 모든 KeyClause 가 ETC 로 저장되던 버그 — 약관 변경 / 의사표시 의제 같은
-- 카테고리가 enum 에 부재. v1.1 에서 TERMS_CHANGE 추가하고 term_service 의
-- _derive_clause_type 이 pain_point_id (MID-01/02) 또는 title 키워드 ("약관 변경",
-- "통지 기간") 로 자동 분류.
--
-- Postgres ALTER TYPE ADD VALUE 는 9.6+ 에서 idempotent (IF NOT EXISTS).
-- 트랜잭션 안에서 못 돌리는 enum 도 있으므로 commit 분리.

ALTER TYPE clause_type ADD VALUE IF NOT EXISTS 'TERMS_CHANGE';
