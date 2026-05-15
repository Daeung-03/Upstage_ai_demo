# Migrations

Raw SQL migrations to run against the Postgres database manually. There is no
Alembic in this repo — the schema is managed externally.

Apply migrations in numeric order. Each file is idempotent (`IF NOT EXISTS` /
`IF EXISTS`) so re-running is safe.

## Apply

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f migrations/0001_termclause_page_bbox.sql
```

## Rollback

Rollback steps are not stored as separate files — recover from the comment at
the top of each migration if needed. For `0001`:

```sql
ALTER TABLE term_clauses DROP COLUMN IF EXISTS page;
ALTER TABLE term_clauses DROP COLUMN IF EXISTS bbox;
```

## Files

| # | Description |
|---|---|
| 0001 | `term_clauses.page (int)` + `term_clauses.bbox (jsonb)` — PDF 원문 하이라이트용 |
