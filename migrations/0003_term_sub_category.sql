-- 0003_term_sub_category.sql
-- Term.sub_category 컬럼 추가. 1단계 domain enum (FINANCE/INSURANCE/OTT 등) 안에서
-- 다시 sub-category 로 분류 (예: INSURANCE 안에 실손/생명/여행, FINANCE 안에 PG/송금/PFM).
-- 기획안 2-3 사이드바 시나리오 ("계약 카테고리별 약관 창 분리 + 세부 섹터 단위 정렬").
--
-- 자유 텍스트 컬럼 — 도메인별 권장값은 ai/services/sub_category.py 에 enum 으로 정의되지만
-- DB 는 단순 TEXT 로 두어 향후 확장 자유롭게.

BEGIN;

ALTER TABLE terms
    ADD COLUMN IF NOT EXISTS sub_category TEXT NULL;

-- 도메인별 sub_category 조회를 위한 보조 인덱스
CREATE INDEX IF NOT EXISTS terms_domain_sub_category_idx
    ON terms (domain, sub_category);

COMMIT;
