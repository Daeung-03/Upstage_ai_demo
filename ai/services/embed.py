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

# embedding-passage / -query 모델의 입력당 컨텍스트 한도는 4000 토큰.
# 한국어는 최악의 경우 ~2 char/token 이므로 4000 토큰 ≈ 8000 자. 안전 마진을
# 두고 6000 자에서 자른다 (한국어 ~3000 토큰, 영어는 훨씬 여유). 초과 입력을
# 그대로 보내면 400 (maximum context length) 으로 호출 전체가 실패하므로,
# 임베딩 단계에서 방어적으로 truncate 한다. _split_chunks(500자) 경로엔 무영향.
MAX_INPUT_CHARS = 6000


def _cap(texts: list[str]) -> list[str]:
    """각 입력을 토큰 한도 안에 들도록 char 기준으로 truncate."""
    return [t[:MAX_INPUT_CHARS] for t in texts]


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
    capped = _cap(texts)
    for start in range(0, len(capped), MAX_BATCH):
        batch = capped[start : start + MAX_BATCH]
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
        json={"model": QUERY_MODEL, "input": [text[:MAX_INPUT_CHARS]]},
    )
    return _parse_response(raw, expected=1)[0]
