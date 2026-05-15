"""Upstage Solar Embedding 호출.

`embedding-passage`로 문서를 인덱싱하고 `embedding-query`로 검색 질의를 임베딩한다.
두 모델 모두 4096차원 벡터를 반환하며 `app.models.TermChunk.embedding`(HALFVEC(4096))과 호환된다.
"""
from __future__ import annotations

from typing import Any

from ai.services.upstage import UpstageClient, UpstreamResponseError

EMBEDDINGS_PATH = "/solar/embeddings"
PASSAGE_MODEL = "embedding-passage"
QUERY_MODEL = "embedding-query"

# Upstage 1회 호출 입력 한도. 문서상 100개까지 허용.
MAX_BATCH = 100


def _parse_response(data: dict[str, Any], expected: int) -> list[list[float]]:
    items = data.get("data") if isinstance(data, dict) else None
    if not isinstance(items, list) or len(items) != expected:
        raise UpstreamResponseError(
            f"embeddings response shape unexpected (got={type(items).__name__}, "
            f"len={len(items) if isinstance(items, list) else 'n/a'}, expected={expected})"
        )
    # API는 index 순서를 보장하지만, 방어적으로 index 정렬.
    items_sorted = sorted(items, key=lambda x: x.get("index", 0))
    vectors: list[list[float]] = []
    for item in items_sorted:
        emb = item.get("embedding")
        if not isinstance(emb, list):
            raise UpstreamResponseError("embeddings item missing 'embedding' list")
        vectors.append(emb)
    return vectors


async def embed_passages(client: UpstageClient, texts: list[str]) -> list[list[float]]:
    """문서/청크 인덱싱용 임베딩. 빈 리스트면 즉시 반환."""
    if not texts:
        return []
    out: list[list[float]] = []
    for start in range(0, len(texts), MAX_BATCH):
        batch = texts[start : start + MAX_BATCH]
        raw = await client.post_json(
            EMBEDDINGS_PATH,
            json={"model": PASSAGE_MODEL, "input": batch},
        )
        out.extend(_parse_response(raw, expected=len(batch)))
    return out


async def embed_query(client: UpstageClient, text: str) -> list[float]:
    """검색 질의용 임베딩."""
    raw = await client.post_json(
        EMBEDDINGS_PATH,
        json={"model": QUERY_MODEL, "input": [text]},
    )
    return _parse_response(raw, expected=1)[0]
