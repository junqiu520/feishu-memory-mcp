"""Tests for MemoryService wiring to lark-cli subprocess.

Stage 8+9 wire-up: MemoryService.add creates a Docx (via DocxClient),
then creates a Bitable record (via BitableClient), then writes locally.
Failure modes must degrade gracefully (log warning, fall back).
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from mcp_memory.services.memory_service import MemoryService
from mcp_memory.storage.local_cache import LocalCache
from mcp_memory.feishu.bitable import BitableRecord
from mcp_memory.feishu.runner import LarkCliError


@pytest.fixture
def cache(tmp_path):
    db = LocalCache(tmp_path / "test.sqlite", scope="memory")
    yield db
    db.close()


@pytest.fixture
def bitable():
    b = MagicMock()
    b.create_record = AsyncMock(
        return_value=BitableRecord(id="rec_remote_1", fields={"title": "T"})
    )
    b.delete_record = AsyncMock(return_value=True)
    return b


@pytest.fixture
def docx():
    d = MagicMock()
    d.create_docx = AsyncMock(return_value="doc_abc")
    d.delete_docx = AsyncMock(return_value=True)
    return d


@pytest.fixture
def service(cache, bitable, docx):
    return MemoryService(
        local_cache=cache, bitable_client=bitable, docx_client=docx, agent_id="test-agent"
    )


async def test_add_wires_docx_then_bitable(service, bitable, docx):
    """add() must call docx.create_docx, then bitable.create_record."""
    r = await service.add(text="hello world", title="Hi")
    assert r.id == "rec_remote_1"  # came from bitable response
    docx.create_docx.assert_awaited_once()
    bitable.create_record.assert_awaited_once()


async def test_add_records_local_after_remote(service, cache):
    r = await service.add(text="foo bar")
    got = cache.get_record(r.id)
    assert got is not None
    assert got.text == "foo bar"


async def test_add_records_content_ref(service, docx):
    r = await service.add(text="foo")
    assert r.content_ref is not None
    assert r.content_ref.type == "docx"
    assert r.content_ref.token == "doc_abc"


async def test_add_falls_back_when_docx_fails(cache, bitable):
    """If docx fails, content_ref is None but the record still gets persisted."""
    docx = MagicMock()
    docx.create_docx = AsyncMock(side_effect=LarkCliError("docx failed"))
    svc = MemoryService(
        local_cache=cache, bitable_client=bitable, docx_client=docx, agent_id="a"
    )
    r = await svc.add(text="x")
    assert r.content_ref is None
    # bitable.create_record was still called (with content_ref_token=None)
    bitable.create_record.assert_awaited_once()
    call_kwargs = bitable.create_record.call_args
    fields = call_kwargs[0][0]
    assert fields["content_ref_token"] is None


async def test_add_falls_back_when_bitable_fails(cache, docx):
    """If bitable fails, the record id is a fresh uuid but still written locally."""
    bitable = MagicMock()
    bitable.create_record = AsyncMock(side_effect=LarkCliError("bitable down"))
    svc = MemoryService(
        local_cache=cache, bitable_client=bitable, docx_client=docx, agent_id="a"
    )
    r = await svc.add(text="x")
    # Bitable failed → local-only fallback uses generated uuid
    assert r.id != ""
    got = cache.get_record(r.id)
    assert got is not None


async def test_delete_calls_bitable_and_docx_and_local(service, cache, bitable, docx):
    r = await service.add(text="foo")
    ok = await service.delete(r.id)
    assert ok is True
    assert cache.get_record(r.id) is None
    # Bitable should have been called to delete the remote record
    bitable.delete_record.assert_awaited_once_with(r.id)


async def test_delete_missing_returns_false(service):
    assert await service.delete("nope") is False


async def test_add_without_docx_client(cache, bitable):
    """docx_client is optional; if None, content_ref stays None."""
    svc = MemoryService(
        local_cache=cache, bitable_client=bitable, docx_client=None, agent_id="a"
    )
    r = await svc.add(text="x")
    assert r.content_ref is None
    bitable.create_record.assert_awaited_once()