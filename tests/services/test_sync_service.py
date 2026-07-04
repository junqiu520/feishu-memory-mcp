"""Tests for SyncService (Stage 5.3).

The three sync modes (incremental / full / rebuild) are stubbed at Stage 5:
they return zero-count results, with started_at/finished_at populated, and
the actual Feishu list/diff/import wiring is deferred to Stage 8.
"""
import pytest
from unittest.mock import MagicMock
from mcp_memory.services.sync_service import SyncService, SyncResult


@pytest.fixture
def service():
    return SyncService(
        local_cache=MagicMock(),
        bitable_client=MagicMock(),
        embedding_engine=MagicMock(),
        vector_index=MagicMock(),
        scope="memory",
    )


async def test_incremental_returns_result(service):
    r = await service.incremental()
    assert r.mode == "incremental"
    assert r.started_at > 0
    assert r.finished_at is not None
    assert r.added == 0
    assert r.updated == 0
    assert r.deleted == 0


async def test_full_returns_result(service):
    r = await service.full()
    assert r.mode == "full"
    assert r.added == 0
    assert r.finished_at is not None


async def test_rebuild_returns_result(service):
    r = await service.rebuild()
    assert r.mode == "rebuild"
    assert r.finished_at is not None


def test_sync_result_to_dict():
    r = SyncResult(mode="test", added=3, deleted=2)
    d = r.to_dict()
    assert d["mode"] == "test"
    assert d["added"] == 3
    assert d["deleted"] == 2
    assert d["errors"] == []
    assert d["finished_at"] is None
