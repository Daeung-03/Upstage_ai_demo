-- 0006_term_vendor_slug.sql
-- Term 에 vendor_slug 컬럼 추가 — 15 서비스 카탈로그의 canonical slug.
--
-- app/models/vendors.py 의 VENDORS 키 (예: "netflix", "disney-plus", "chatgpt"...) 와 1:1.
-- 매칭 안 되는 케이스(unsupported vendor) 는 NULL.
--
-- 도메인(TermDomain enum) 과는 별도 — vendor 가 더 세분화된 단위.
-- 예: netflix/disney-plus/tving 셋 다 domain=OTT 이지만 vendor_slug 로 구분.
--
-- nullable + IF NOT EXISTS 로 기존 row + 머지 안전.

BEGIN;

ALTER TABLE terms
    ADD COLUMN IF NOT EXISTS vendor_slug TEXT NULL;

CREATE INDEX IF NOT EXISTS terms_vendor_slug_idx ON terms (vendor_slug);

COMMIT;
