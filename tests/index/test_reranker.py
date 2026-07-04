"""Tests for Reranker (bge-reranker-base) — uses fake CrossEncoder."""
import numpy as np
import pytest

from mcp_memory.index.reranker import Reranker


class FakeCrossEncoder:
    """Fake CrossEncoder: returns 1.0 if doc contains 'good', else 0.0."""

    def __init__(self, *args, **kwargs):
        pass

    def predict(self, pairs):
        return np.array([1.0 if "good" in doc else 0.0 for _, doc in pairs])


@pytest.fixture
def reranker(monkeypatch):
    monkeypatch.setattr("sentence_transformers.CrossEncoder", FakeCrossEncoder)
    r = Reranker()
    yield r
    r.close()


async def test_rerank_returns_indexed_scores(reranker):
    docs = ["good morning", "bad day", "good night"]
    result = await reranker.rerank("good things", docs)
    assert len(result) == 3
    # Top 2 should be the "good" docs (indices 0 and 2)
    top_indices = [idx for idx, _ in result[:2]]
    assert set(top_indices) == {0, 2}
    # The "bad" doc should be last
    assert result[-1][0] == 1


async def test_rerank_empty_docs(reranker):
    result = await reranker.rerank("query", [])
    assert result == []


async def test_rerank_top_k(reranker):
    docs = ["good a", "bad b", "good c", "bad d"]
    result = await reranker.rerank("query", docs, top_k=2)
    assert len(result) == 2
    # Both should be "good" docs
    for idx, score in result:
        assert "good" in docs[idx]
        assert score == 1.0


async def test_rerank_scores_descending(reranker):
    docs = ["good 1", "good 2", "bad 1", "bad 2"]
    result = await reranker.rerank("query", docs)
    scores = [s for _, s in result]
    for i in range(len(scores) - 1):
        assert scores[i] >= scores[i + 1]


async def test_rerank_model_lazy_loaded(reranker):
    assert reranker._model is None
    await reranker.rerank("q", ["d1"])
    assert reranker._model is not None


def test_rerank_close_shuts_down_pool():
    r = Reranker()
    r.close()  # should not raise


def test_rerank_constructs_with_custom_name():
    r = Reranker(model_name="custom/model", device="cpu", max_workers=1)
    assert r.model_name == "custom/model"
    assert r.device == "cpu"
    r.close()
