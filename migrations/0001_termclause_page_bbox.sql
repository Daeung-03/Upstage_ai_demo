-- 0001_termclause_page_bbox.sql
-- TermClause 에 원문 위치 컬럼 추가 — UI 에서 PDF 원문 하이라이트용.
--
-- page : 1-based 페이지 번호 (NULL = 미지정 / 비-PDF 입력)
-- bbox : [x1, y1, x2, y2] (0-1 정규화). Upstage Document Parse 좌표 그대로 저장.
--        뷰어 측에서 페이지 픽셀 크기 곱해 절대 좌표로 변환.
--
-- 둘 다 nullable — 기존 row 와 비-PDF 인 HTML 입력 모두 영향 없음.

BEGIN;

ALTER TABLE term_clauses
    ADD COLUMN IF NOT EXISTS page INTEGER NULL,
    ADD COLUMN IF NOT EXISTS bbox JSONB NULL;

COMMIT;
