"""Tests for MemoryService (Stage 5.1).

Covers spec §4.1 (add), §4.4 (delete), §4.5 (update), list/count.
Feishu SDK calls are mocked; only the local orchestration is validated here.
Stage 8 will add integration tests that exercise the real bitable flow.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from mcp_memory.services.memory_service import MemoryService
from mcp_memory.storage.local_cache import LocalCache


@pytest.fixture
def cache(tmp_path):
    db = LocalCache(tmp_path / "test.sqlite", scope="memory")
    yield db
    db.close()


@pytest.fixture
def bitable():
    """Bitable client mock with async methods.

    create_record returns a fresh unique id per call to simulate real lark-cli
    behavior (where every record gets a server-side id like ``recvogXXXXXXX``).
    """
    import itertools
    counter = itertools.count()

    def make_unique_id(_=None):
        idx = next(counter)
        return MagicMock(id=f"remote_{idx:04d}")

    b = MagicMock()
    b.create_record = AsyncMock(side_effect=make_unique_id)
    b.batch_update = AsyncMock(side_effect=make_unique_id)
    b.delete_record = AsyncMock(return_value=True)
    return b


@pytest.fixture
def service(cache, bitable):
    return MemoryService(local_cache=cache, bitable_client=bitable, agent_id="test-agent")


async def test_add_creates_local_record(service, cache):
    r = await service.add(text="hello world", tags=["greeting"])
    assert r.id
    assert r.text == "hello world"
    assert r.metadata.tags == ["greeting"]
    assert r.metadata.source_agent == "test-agent"

    got = cache.get_record(r.id)
    assert got is not None
    assert got.text == "hello world"


async def test_add_empty_text_raises(service):
    with pytest.raises(ValueError):
        await service.add(text="")


async def test_add_too_long_text_raises(service):
    with pytest.raises(ValueError):
        await service.add(text="x" * 200_000)


async def test_get_existing(service):
    r = await service.add(text="foo", title="MyFoo")
    got = service.get(r.id)
    assert got is not None
    assert got.title == "MyFoo"


async def test_get_missing_returns_none(service):
    assert service.get("nonexistent") is None


async def test_delete(service):
    r = await service.add(text="foo")
    assert await service.delete(r.id) is True
    assert service.get(r.id) is None


async def test_delete_missing(service):
    assert await service.delete("nope") is False


async def test_update_title(service):
    r = await service.add(text="foo", tags=["old"])
    updated = await service.update(r.id, title="NewTitle")
    assert updated is not None
    assert updated.title == "NewTitle"


async def test_update_tags_replace(service):
    r = await service.add(text="foo", tags=["a", "b", "c"])
    updated = await service.update(r.id, tags=["x"])
    assert updated is not None
    assert updated.metadata.tags == ["x"]


async def test_update_clear_tags(service):
    r = await service.add(text="foo", tags=["a"])
    updated = await service.update(r.id, tags=[])
    assert updated is not None
    assert updated.metadata.tags == []


async def test_list_with_filter(service):
    r1 = await service.add(text="a", tags=["x"])
    r2 = await service.add(text="b", tags=["y"])
    ids = service.list(filter={"tags_any": ["x"]})
    assert r1.id in ids
    assert r2.id not in ids


async def test_count(service):
    for i in range(3):
        await service.add(text=f"r{i}", tags=["counted"])
    assert service.count(filter={"tags_any": ["counted"]}) == 3
