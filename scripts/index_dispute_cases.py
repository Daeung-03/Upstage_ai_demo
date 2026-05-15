#!/usr/bin/env python
"""data/fixtures/dispute_cases.json → DB 인덱싱.

1. JSON 로드
2. upsert_dispute_cases (external_id 키)
3. 각 row 에 대해 title + summary + outcome 합쳐 embedding-passage 호출
4. embedding 컬럼 update

Idempotent — 같은 fixture 재실행 시 외부 시스템 영향 없음.

사용: `PYTHONPATH=. python scripts/index_dispute_cases.py`
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

from app.database import AsyncSessionLocal
from app.services import dispute_service
from app.services.ai_client import embed_chunks


logger = logging.getLogger("index_dispute_cases")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


FIXTURE_PATH = Path("data/fixtures/dispute_cases.json")


def _embedding_text(case: dict) -> str:
    """임베딩 입력 텍스트 — title + summary + outcome 결합."""
    return "\n".join(filter(None, [
        case.get("title", ""),
        case.get("summary", ""),
        case.get("outcome", ""),
    ])).strip()


async def main() -> int:
    if not FIXTURE_PATH.exists():
        logger.error("fixture not found: %s", FIXTURE_PATH)
        return 1

    cases: list[dict] = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    logger.info("loaded %d dispute cases from %s", len(cases), FIXTURE_PATH)

    async with AsyncSessionLocal() as db:
        # 1) upsert (embedding 제외)
        ids = await dispute_service.upsert_dispute_cases(db, cases)
        await db.commit()
        logger.info("upserted %d rows", len(ids))

        # 2) 임베딩 — 일괄 호출 (embed_passages 가 batch 처리)
        texts = [_embedding_text(c) for c in cases]
        logger.info("embedding %d passages...", len(texts))
        vectors = await embed_chunks(texts)
        logger.info("got %d vectors (dim=%d)", len(vectors), len(vectors[0]) if vectors else 0)

        # 3) row 별 embedding update
        for case_id, vec in zip(ids, vectors):
            await dispute_service.set_dispute_embedding(db, case_id, vec)
        await db.commit()
        logger.info("indexed %d embeddings", len(ids))

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
