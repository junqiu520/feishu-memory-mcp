import pytest
from mcp_memory.storage.local_cache import LocalCache
from mcp_memory.models.record import (
    MemoryRecord,
    MemoryMetadata,
    SourceType,
    FeishuRef,
)


@pytest.fixture
def cache(tmp_path):
    db = LocalCache(tmp_path / "test.sqlite", scope="memory")
    yield db
    db.close()


def _make_record(text: str = "hello", tags: list[str] | None = None) -> MemoryRecord:
    return MemoryRecord(
        source=SourceType.AGENT_ADD,
        title="Test",
        preview=text[:20],
        text=text,
        content_hash="abc123",
        content_ref=FeishuRef(type="docx", token="docx_xxx", url="https://..."),
        metadata=MemoryMetadata(tags=tags or []),
    )


def test_upsert_and_get(cache):
    r = _make_record("first", tags=["alpha", "beta"])
    cache.upsert(r)
    got = cache.get_record(r.id)
    assert got is not None
    assert got.id == r.id
    assert got.title == "Test"
    assert got.text == "first"
    assert got.metadata.tags == ["alpha", "beta"]
    assert got.content_ref is not None
    assert got.content_ref.token == "docx_xxx"


def test_upsert_overwrites(cache):
    r = _make_record("v1")
    cache.upsert(r)
    r.text = "v2"
    cache.upsert(r)
    got = cache.get_record(r.id)
    assert got.text == "v2"


def test_delete(cache):
    r = _make_record()
    cache.upsert(r)
    assert cache.get_record(r.id) is not None
    cache.delete(r.id)
    assert cache.get_record(r.id) is None


def test_list_by_filter_tags_any(cache):
    r1 = _make_record("a", tags=["x", "y"])
    r2 = _make_record("b", tags=["y", "z"])
    r3 = _make_record("c", tags=["w"])
    for r in [r1, r2, r3]:
        cache.upsert(r)

    result = cache.list_by_filter({"tags_any": ["x"]})
    assert len(result) == 1
    assert result[0] == r1.id

    result = cache.list_by_filter({"tags_any": ["y"]})
    assert len(result) == 2


def test_list_by_filter_tags_all(cache):
    r1 = _make_record("a", tags=["x", "y"])
    r2 = _make_record("b", tags=["x"])
    for r in [r1, r2]:
        cache.upsert(r)

    result = cache.list_by_filter({"tags_all": ["x", "y"]})
    assert len(result) == 1
    assert result[0] == r1.id


def test_count_by_filter(cache):
    for i in range(5):
        cache.upsert(_make_record(f"r{i}", tags=["x"]))
    assert cache.count_by_filter({"tags_any": ["x"]}) == 5
    assert cache.count_by_filter({}) == 5


def test_update_metadata(cache):
    r = _make_record("text", tags=["old"])
    cache.upsert(r)
    updated = cache.update_metadata(
        record_id=r.id,
        title="New Title",
        tags=["new1", "new2"],
    )
    assert updated is not None
    assert updated.title == "New Title"
    assert updated.metadata.tags == ["new1", "new2"]
    assert updated.text == "text"


def test_update_metadata_only_some_fields(cache):
    r = _make_record("text", tags=["old"])
    cache.upsert(r)
    updated = cache.update_metadata(record_id=r.id, title="Just Title")
    assert updated.title == "Just Title"
    assert updated.metadata.tags == ["old"]


def test_update_metadata_clear_tags(cache):
    r = _make_record("text", tags=["a", "b"])
    cache.upsert(r)
    updated = cache.update_metadata(record_id=r.id, tags=[])
    assert updated.metadata.tags == []


def test_update_metadata_not_found(cache):
    result = cache.update_metadata(record_id="non_exist", title="X")
    assert result is None


def test_clear_all_records_empties_records_and_tags(cache):
    """clear_all_records removes every record and tag without touching sync_state."""
    cache.upsert(_make_record("a", tags=["t1"]))
    cache.upsert(_make_record("b", tags=["t2"]))
    assert cache.count_by_filter({}) == 2

    cache.clear_all_records()

    assert cache.count_by_filter({}) == 0
    assert cache.list_by_filter({}) == []
    # sync_state must remain intact — it's not a record.
    state = cache.get_sync_state()
    assert state.get("id") == 1
    assert state.get("local_instance_id")


def test_clear_all_records_on_empty_cache_is_noop(cache):
    """Calling clear_all_records on an empty cache must not raise."""
    cache.clear_all_records()
    assert cache.count_by_filter({}) == 0


def test_clear_all_records_does_not_drop_underlying_db(cache):
    """After clear_all_records, the cache is still usable (re-insert works)."""
    cache.upsert(_make_record("first"))
    cache.clear_all_records()
    r = _make_record("second", tags=["fresh"])
    cache.upsert(r)
    assert cache.count_by_filter({}) == 1
    got = cache.get_record(r.id)
    assert got is not None
    assert got.text == "second"
