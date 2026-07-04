"""Tests for SyncService real wire-up (Stage 9).

SyncService now actually calls BitableClient.list_records, builds local
MemoryRecord objects, embeds text via EmbeddingEngine, and upserts to
VectorIndex. SyncResult counts and error handling are validated.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from mcp_memory.services.sync_service import SyncService, SyncResult
from mcp_memory.feishu.bitable import BitableRecord
from mcp_memory.storage.local_cache import LocalCache


@pytest.fixture
def cache(tmp_path):
    db = LocalCache(tmp_path / "test.sqlite", scope="memory")
    yield db
    db.close()


@pytest.fixture
def bitable():
    b = MagicMock()
    b.list_records = AsyncMock(return_value=[
        BitableRecord(id="rec_1", fields={"title": "T1", "preview": "hello world", "tags": ["greeting"]}),
        BitableRecord(id="rec_2", fields={"title": "T2", "preview": "goodbye sky", "tags": ["leave"]}),
    ])
    return b


@pytest.fixture
def embed():
    e = MagicMock()
    e.embed = AsyncMock(side_effect=lambda texts: [[0.1, 0.2, 0.3] for _ in texts])
    return e


@pytest.fixture
def vector():
    v = MagicMock()
    v.upsert = AsyncMock(return_value=None)
    v.delete_by_record = AsyncMock(return_value=None)
    return v


@pytest.fixture
def service(cache, bitable, embed, vector):
    return SyncService(
        local_cache=cache, bitable_client=bitable,
        embedding_engine=embed, vector_index=vector, scope="memory",
    )


async def test_incremental_pulls_and_embeds(service, cache, bitable, embed, vector):
    r = await service.incremental()
    assert r.mode == "incremental"
    assert r.added == 2
    bitable.list_records.assert_awaited_once()
    # Both records should be embedded
    assert embed.embed.await_args[0][0] == ["hello world", "goodbye sky"]
    # Vector upsert is batched (one call with both chunks)
    vector.upsert.assert_awaited_once()
    chunks_arg = vector.upsert.await_args[0][0]
    assert len(chunks_arg) == 2
    # Sync state was updated
    state = cache.get_sync_state()
    assert state.get("last_sync_at") is not None


async def test_incremental_handles_list_failure(cache, embed, vector):
    bitable = MagicMock()
    bitable.list_records = AsyncMock(side_effect=Exception("network down"))
    svc = SyncService(
        local_cache=cache, bitable_client=bitable,
        embedding_engine=embed, vector_index=vector, scope="memory",
    )
    r = await svc.incremental()
    assert r.added == 0
    assert any("list_records" in e for e in r.errors)


async def test_full_lists_all_records(service, cache):
    r = await service.full()
    assert r.mode == "full"
    assert r.added == 2
    assert r.deleted == 0
    # last_full_sync_at should be set
    state = cache.get_sync_state()
    assert state.get("last_full_sync_at") is not None


async def test_full_detects_deleted_records(cache, embed, vector):
    # Seed local cache with a record that won't appear in remote
    from mcp_memory.models.record import MemoryRecord, SourceType
    rec = MemoryRecord(id="stale_local", source=SourceType.AGENT_ADD, title="X", text="x")
    cache.upsert(rec)

    bitable = MagicMock()
    bitable.list_records = AsyncMock(return_value=[
        BitableRecord(id="remote_only", fields={"title": "R", "preview": "p"}),
    ])
    svc = SyncService(
        local_cache=cache, bitable_client=bitable,
        embedding_engine=embed, vector_index=vector, scope="memory",
    )
    r = await svc.full()
    assert r.added == 1
    assert r.deleted == 1
    assert cache.get_record("stale_local") is None
    assert cache.get_record("remote_only") is not None


async def test_rebuild_drops_local_then_fulls(cache, embed, vector, bitable):
    from mcp_memory.models.record import MemoryRecord, SourceType
    cache.upsert(MemoryRecord(id="seed", source=SourceType.AGENT_ADD, title="S", text="s"))
    svc = SyncService(
        local_cache=cache, bitable_client=bitable,
        embedding_engine=embed, vector_index=vector, scope="memory",
    )
    r = await svc.rebuild()
    assert r.mode == "rebuild"
    # After rebuild, seed is gone, bitable records are present
    assert cache.get_record("seed") is None
    assert cache.get_record("rec_1") is not None
    state = cache.get_sync_state()
    assert state.get("last_rebuild_at") is not None


async def test_sync_result_to_dict():
    r = SyncResult(mode="test", added=3, deleted=2)
    d = r.to_dict()
    assert d["mode"] == "test"
    assert d["added"] == 3
    assert d["deleted"] == 2
    assert d["errors"] == []
    assert d["finished_at"] is None


async def test_incremental_with_no_remote_records(cache, embed, vector):
    bitable = MagicMock()
    bitable.list_records = AsyncMock(return_value=[])
    svc = SyncService(
        local_cache=cache, bitable_client=bitable,
        embedding_engine=embed, vector_index=vector, scope="memory",
    )
    r = await svc.incremental()
    assert r.added == 0
    embed.embed.assert_not_awaited()