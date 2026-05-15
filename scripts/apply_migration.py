"""asyncpg 로 SQL 마이그레이션 파일을 그대로 실행 (psql 없는 로컬 환경 대응).

사용:
    .venv/bin/python scripts/apply_migration.py migrations/0003_term_sub_category.sql

DATABASE_URL 은 .env 또는 환경변수에서 읽음 (`postgresql+asyncpg://...` 형태).
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import asyncpg
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _to_asyncpg_url(url: str) -> str:
    """SQLAlchemy 형식 `postgresql+asyncpg://...` 의 driver suffix 제거."""
    return url.replace("postgresql+asyncpg://", "postgresql://", 1)


async def run(sql_path: Path) -> None:
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise SystemExit("DATABASE_URL not set")
    sql = sql_path.read_text()

    print(f"→ Connecting to DB...")
    conn = await asyncpg.connect(_to_asyncpg_url(db_url))
    try:
        print(f"→ Running {sql_path.name} ({len(sql)} bytes)...")
        # 전체 파일을 한 번에 — BEGIN/COMMIT 이 안에 있다고 가정
        await conn.execute(sql)
        print("✓ Done")
    finally:
        await conn.close()


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: python scripts/apply_migration.py <migration.sql>", file=sys.stderr)
        sys.exit(2)
    asyncio.run(run(Path(sys.argv[1])))


if __name__ == "__main__":
    main()
