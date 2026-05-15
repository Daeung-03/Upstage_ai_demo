import pytest

from ai.services import embed
from ai.services.settings import Settings
from ai.services.upstage import UpstageClient, UpstreamResponseError


@pytest.fixture
def settings(sample_api_key, sample_base_url) -> Settings:
    return Settings(upstage_api_key=sample_api_key, upstage_base_url=sample_base_url)


def _emb_response(vectors: list[list[float]]) -> dict:
    return {
        "object": "list",
        "data": [
            {"object": "embedding", "index": i, "embedding": v}
            for i, v in enumerate(vectors)
        ],
        "model": "embedding-passage",
        "usage": {"prompt_tokens": 10, "total_tokens": 10},
    }


async def test_embed_passages_single_batch(httpx_mock, settings):
    httpx_mock.add_response(
        url=f"{settings.upstage_base_url}{embed.EMBEDDINGS_PATH}",
        json=_emb_response([[0.1, 0.2], [0.3, 0.4]]),
    )
    async with UpstageClient(settings) as client:
        vecs = await embed.embed_passages(client, ["a", "b"])
    assert vecs == [[0.1, 0.2], [0.3, 0.4]]
    req = httpx_mock.get_request()
    import json
    body = json.loads(req.content)
    assert body["model"] == embed.PASSAGE_MODEL
    assert body["input"] == ["a", "b"]


async def test_embed_passages_empty_skips_api(httpx_mock, settings):
    async with UpstageClient(settings) as client:
        vecs = await embed.embed_passages(client, [])
    assert vecs == []
    assert httpx_mock.get_requests() == []


async def test_embed_passages_batches_over_max(httpx_mock, settings, monkeypatch):
    monkeypatch.setattr(embed, "MAX_BATCH", 2)
    httpx_mock.add_response(
        url=f"{settings.upstage_base_url}{embed.EMBEDDINGS_PATH}",
        json=_emb_response([[1.0], [2.0]]),
    )
    httpx_mock.add_response(
        url=f"{settings.upstage_base_url}{embed.EMBEDDINGS_PATH}",
        json=_emb_response([[3.0]]),
    )
    async with UpstageClient(settings) as client:
        vecs = await embed.embed_passages(client, ["x", "y", "z"])
    assert vecs == [[1.0], [2.0], [3.0]]
    assert len(httpx_mock.get_requests()) == 2


async def test_embed_passages_handles_unordered_index(httpx_mock, settings):
    """API가 index 순서를 흐트러뜨려도 정렬하여 입력 순서를 보존."""
    httpx_mock.add_response(
        url=f"{settings.upstage_base_url}{embed.EMBEDDINGS_PATH}",
        json={
            "data": [
                {"index": 1, "embedding": [9.0]},
                {"index": 0, "embedding": [1.0]},
            ],
            "usage": {"total_tokens": 4},
        },
    )
    async with UpstageClient(settings) as client:
        vecs = await embed.embed_passages(client, ["first", "second"])
    assert vecs == [[1.0], [9.0]]


async def test_embed_passages_raises_on_shape_mismatch(httpx_mock, settings):
    httpx_mock.add_response(
        url=f"{settings.upstage_base_url}{embed.EMBEDDINGS_PATH}",
        json={"data": [{"index": 0, "embedding": [0.5]}], "usage": {}},  # 1 returned, 2 expected
    )
    async with UpstageClient(settings) as client:
        with pytest.raises(UpstreamResponseError, match="shape unexpected"):
            await embed.embed_passages(client, ["a", "b"])


async def test_embed_query_uses_query_model(httpx_mock, settings):
    httpx_mock.add_response(
        url=f"{settings.upstage_base_url}{embed.EMBEDDINGS_PATH}",
        json=_emb_response([[0.7, 0.8, 0.9]]),
    )
    async with UpstageClient(settings) as client:
        vec = await embed.embed_query(client, "검색어")
    assert vec == [0.7, 0.8, 0.9]
    import json
    body = json.loads(httpx_mock.get_request().content)
    assert body["model"] == embed.QUERY_MODEL
    assert body["input"] == ["검색어"]
