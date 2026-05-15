# Migrations

Raw SQL migrations to run against the Postgres database manually. There is no
Alembic in this repo — the schema is managed externally.

Apply migrations in numeric order. Each file is idempotent (`IF NOT EXISTS` /
`IF EXISTS`) so re-running is safe.

## Apply

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f migrations/0001_termclause_page_bbox.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f migrations/0002_dispute_cases.sql
```

또는 Supabase SQL Editor 에 파일 내용 붙여넣고 Run. 적용 후 분쟁 사례 데이터 시드는:

```bash
PYTHONPATH=. python scripts/index_dispute_cases.py
```

## Rollback

Rollback steps are not stored as separate files — recover from the comment at
the top of each migration if needed.

For `0001`:
```sql
ALTER TABLE term_clauses DROP COLUMN IF EXISTS page;
ALTER TABLE term_clauses DROP COLUMN IF EXISTS bbox;
```

For `0002`:
```sql
DROP TABLE IF EXISTS dispute_cases;
```

## Files

| # | Description |
|---|---|
| 0001 | `term_clauses.page (int)` + `term_clauses.bbox (jsonb)` — PDF 원문 하이라이트용 |
| 0002 | `dispute_cases` 테이블 (분쟁 사례 데이터) — title/summary/outcome/source/pain_point_ids/unfair_flags/domain/embedding(halfvec 4096). pgvector ANN 인덱스는 4000-d 한계로 미생성 — linear cosine scan 으로 동작 (수십~수백 row 규모 적합) |
