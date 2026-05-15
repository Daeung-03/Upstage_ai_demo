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

-- pgvector ANN 인덱스(HNSW/IVFFlat) 는 4000차원이 한계 — halfvec(4096) 미지원.
-- 분쟁 사례 데이터는 수십~수백 row 규모라 linear cosine scan 으로 충분 (HNSW 없이도
-- 1ms 미만). row 가 만 개 이상으로 늘면:
--   1) embedding 차원 축소 후 halfvec(2000) 재인덱싱, 또는
--   2) sparsevec 으로 인덱스 가능한 형태로 변환.
-- 둘 다 별도 마이그레이션 + 임베딩 재산출 필요.

COMMIT;
