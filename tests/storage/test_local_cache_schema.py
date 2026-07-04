import pytest
from mcp_memory.storage.local_cache import LocalCache


@pytest.fixture
def cache(tmp_path):
    db = LocalCache(tmp_path / "test.sqlite", scope="memory")
    yield db
    db.close()


def test_init_creates_records_table(cache):
    assert cache._table_exists("records")
    assert cache._table_exists("sync_state")
    assert cache._table_exists("record_tags")


def test_sync_state_starts_initialized(cache):
    state = cache.get_sync_state()
    assert state["local_instance_id"] is not None
    assert state["last_sync_at"] is None


def test_scope_separate_dbs(tmp_path):
    a = LocalCache(tmp_path / "memory.sqlite", scope="memory")
    b = LocalCache(tmp_path / "knowledge.sqlite", scope="knowledge")
    a.close()
    b.close()
    assert (tmp_path / "memory.sqlite").exists()
    assert (tmp_path / "knowledge.sqlite").exists()
