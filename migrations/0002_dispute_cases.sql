-- 0002_dispute_cases.sql
-- 분쟁 사례 데이터 (pain_point/unfair_flag/도메인 별 매칭용).
-- pgvector HALFVEC(4096) — TermChunk 와 같은 임베딩 공간.
--
-- 마이그레이션 0001 과 마찬가지로 IF NOT EXISTS 로 idempotent.

BEGIN;

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS dispute_cases (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    external_id     TEXT NULL,
    title           TEXT NOT NULL,
    summary         TEXT NOT NULL,
    outcome         TEXT NOT NULL,
    source          TEXT NOT NULL,
    source_url      TEXT NULL,
    pain_point_ids  TEXT[] NOT NULL DEFAULT '{}'::TEXT[],
    unfair_flags    TEXT[] NOT NULL DEFAULT '{}'::TEXT[],
    domain          TEXT NOT NULL DEFAULT 'ALL',
    embedding       halfvec(4096) NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- external_id 중복 방지 (NULL 은 unique 검사 제외)
CREATE UNIQUE INDEX IF NOT EXISTS dispute_cases_external_id_unique
    ON dispute_cases (external_id) WHERE external_id IS NOT NULL;

-- 도메인 필터 빠른 조회
CREATE INDEX IF NOT EXISTS dispute_cases_domain_idx
    ON dispute_cases (domain);

-- 배열 교집합 boost 가속 (GIN)
CREATE INDEX IF NOT EXISTS dispute_cases_pain_point_ids_gin
    ON dispute_cases USING GIN (pain_point_ids);

CREATE INDEX IF NOT EXISTS dispute_cases_unfair_flags_gin
    ON dispute_cases USING GIN (unfair_flags);

-- pgvector cosine 유사도 ANN 인덱스 (HNSW)
CREATE INDEX IF NOT EXISTS dispute_cases_embedding_hnsw
    ON dispute_cases USING hnsw (embedding halfvec_cosine_ops);

COMMIT;
