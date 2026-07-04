"""Tests for SearchService (Stage 5.2).

SearchService is an orchestrator that fans out to BM25 (LocalCache.search_fts),
vector (EmbeddingEngine + VectorIndex), RRF (rrf_merger), and optional Reranker.
Each collaborator is mocked here; the goal is to validate mode routing and the
RRF/rerank wiring, not the underlying retrieval quality (that's Stage 8).
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from mcp_memory.services.search_service import SearchService
from mcp_memory.storage.local_cache import LocalCache


@pytest.fixture
def cache(tmp_path):
    db = LocalCache(tmp_path / "test.sqlite", scope="memory")
    yield db
    db.close()


@pytest.fixture
def vector_index():
    v = MagicMock()
    v.search = AsyncMock(return_value=[("rec_1", 0.9), ("rec_2", 0.7)])
    return v


@pytest.fixture
def service(cache, vector_index):
    embed = MagicMock()
    embed.embed_query = AsyncMock(return_value=[0.1, 0.2, 0.3])
    return SearchService(
        local_cache=cache,
        embedding_engine=embed,
        vector_index=vector_index,
        reranker=None,
        default_top_k=5,
        default_rerank=False,
    )


async def test_query_runs_hybrid_path(service, cache):
    """Hybrid path should call both BM25 and vector search, then assemble results."""
    r1 = MagicMock()
    r1.id = "rec_1"
    r1.text = "hello world"
    r1.title = "Greeting"
    r1.preview = "hello world"
    r1.content_ref = None
    r1.metadata.tags = ["hi"]
    r1.source = MagicMock()
    r1.source.value = "agent_add"
    r1.metadata.source_agent = "test-agent"
    r1.created_at = 12345

    cache.get_record = MagicMock(return_value=r1)
    cache.list_by_filter = MagicMock(return_value=["rec_1"])
    cache.search_fts = MagicMock(return_value=[("rec_1", -1.0)])

    results = await service.query("hello", mode="hybrid")
    assert isinstance(results, list)
    # Hybrid path produced at least one assembled entry from the mock record
    assert len(results) >= 1
    assert results[0]["record_id"] == "rec_1"
    assert results[0]["title"] == "Greeting"
