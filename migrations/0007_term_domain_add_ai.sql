-- 0007_term_domain_add_ai.sql
-- TermDomain enum 에 'AI' 값 추가.
-- AI 어시스턴트 서비스(Claude, ChatGPT, Gemini, DeepSeek, Upstage) 를 APP 에서
-- 분리해 별도 카테고리로 노출 — 사용자/시연 흐름에서 OTT/금융/AI 3대 도메인 강조.
--
-- ALTER TYPE ... ADD VALUE 는 PG 12+ 에서 idempotent (IF NOT EXISTS) 지원.
-- 트랜잭션 안에서도 실행 가능 (PG 12+).

ALTER TYPE term_domain ADD VALUE IF NOT EXISTS 'AI';
