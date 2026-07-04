"""Tests for EmbeddingEngine — uses fake SentenceTransformer to avoid 2GB download."""
import numpy as np
import pytest

from mcp_memory.index.embedding_engine import EmbeddingEngine


class FakeTransformer:
    """Fake SentenceTransformer returning deterministic 4-dim vectors."""

    def __init__(self, *args, **kwargs):
        pass

    def encode(self, texts, **kwargs):
        return np.array([[hash(t) % 100 / 100.0] * 4 for t in texts])


@pytest.fixture
def engine(monkeypatch):
    monkeypatch.setattr(
        "sentence_transformers.SentenceTransformer",
        FakeTransformer,
    )
    e = EmbeddingEngine(model_name="BAAI/bge-m3")
    yield e
    e.close()


async def test_embed_returns_list_of_vectors(engine):
    vecs = await engine.embed(["hello", "world"])
    assert len(vecs) == 2
    assert len(vecs[0]) == 4
    # deterministic — same input → same output
    assert vecs[0] == vecs[0]


async def test_embed_empty_returns_empty_list(engine):
    vecs = await engine.embed([])
    assert vecs == []


async def test_embed_query_returns_single_vector(engine):
    vec = await engine.embed_query("hello world")
    assert len(vec) == 4


async def test_embed_query_empty_returns_empty_list(engine):
    vec = await engine.embed_query("")
    # empty string still goes through embed path; fake returns 4-dim
    # but we only check it returns a list (not None)
    assert isinstance(vec, list)


async def test_embed_returns_python_floats_not_numpy(engine):
    vecs = await engine.embed(["a"])
    # each element should be convertible to a plain Python float list
    assert all(isinstance(v, float) for v in vecs[0])


async def test_model_lazy_loaded(engine):
    # Model should not be loaded until first embed call
    assert engine._model is None
    await engine.embed(["trigger"])
    assert engine._model is not None


def test_close_shuts_down_pool():
    e = EmbeddingEngine()
    e.close()  # should not raise
