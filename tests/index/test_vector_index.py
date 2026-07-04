"""Tests for VectorIndex interface + LanceDB stub."""
from mcp_memory.index.vector_index import LanceVectorIndex, VectorChunk


def test_vector_chunk_creation():
    c = VectorChunk(record_id="rec_123", text="hello", embedding=[0.1, 0.2, 0.3])
    assert c.chunk_id  # auto-generated uuid
    assert c.record_id == "rec_123"
    assert c.text == "hello"
    assert c.embedding == [0.1, 0.2, 0.3]
    assert c.start_offset == 0
    assert c.end_offset == 0
    assert c.metadata == {}


def test_vector_chunk_each_gets_unique_id():
    c1 = VectorChunk(record_id="r1", text="a", embedding=[1.0])
    c2 = VectorChunk(record_id="r1", text="b", embedding=[2.0])
    assert c1.chunk_id != c2.chunk_id


def test_vector_chunk_with_metadata():
    c = VectorChunk(
        record_id="r1",
        text="x",
        embedding=[0.0],
        start_offset=10,
        end_offset=20,
        metadata={"source": "docx", "page": 3},
    )
    assert c.start_offset == 10
    assert c.end_offset == 20
    assert c.metadata == {"source": "docx", "page": 3}


def test_vector_chunk_default_factory_independent_dicts():
    c1 = VectorChunk(record_id="r1", text="a", embedding=[0.0])
    c2 = VectorChunk(record_id="r2", text="b", embedding=[0.0])
    c1.metadata["k"] = "v"
    assert c2.metadata == {}  # not shared


def test_lance_vector_index_constructs():
    from pathlib import Path
    idx = LanceVectorIndex(path="/tmp/test.lance", scope="memory")
    assert idx.scope == "memory"
    # On Windows, Path('/tmp/test.lance') gets converted to '\\tmp\\test.lance'.
    # Just verify the path is stored as a Path object pointing to the right place.
    assert Path(idx.path) == Path("/tmp/test.lance")
    assert idx._table is None


def test_lance_vector_index_upsert_is_stub():
    import asyncio

    idx = LanceVectorIndex(path="/tmp/x.lance", scope="memory")
    chunks = [VectorChunk(record_id="r1", text="t", embedding=[0.1])]
    # Stub: should not raise, returns None
    result = asyncio.run(idx.upsert(chunks))
    assert result is None


def test_lance_vector_index_delete_by_record_is_stub():
    import asyncio

    idx = LanceVectorIndex(path="/tmp/x.lance", scope="memory")
    result = asyncio.run(idx.delete_by_record("rec_1"))
    assert result is None


def test_lance_vector_index_search_returns_empty():
    import asyncio

    idx = LanceVectorIndex(path="/tmp/x.lance", scope="knowledge")
    result = asyncio.run(idx.search(query_vector=[0.1, 0.2, 0.3], top_k=5))
    assert result == []


def test_lance_vector_index_search_with_filter_returns_empty():
    import asyncio

    idx = LanceVectorIndex(path="/tmp/x.lance", scope="memory")
    result = asyncio.run(
        idx.search(
            query_vector=[0.1, 0.2],
            top_k=10,
            metadata_filter={"tags": ["foo"]},
        )
    )
    assert result == []


def test_lance_vector_index_accepts_pathlib_path():
    from pathlib import Path

    idx = LanceVectorIndex(path=Path("/tmp/abc.lance"), scope="memory")
    assert isinstance(idx.path, Path)
