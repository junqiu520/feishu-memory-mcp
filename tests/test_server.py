"""Tests for the FastMCP server wiring (Stage 6).

These tests validate that:
  * AppContext routes scope names to the correct service bundle.
  * make_server builds a FastMCP instance with all 9 tools registered.
  * The default scope is "memory".
  * The AppContext name-validation rejects bad scopes.
  * memory_list returns full record summaries sorted by updated_at desc.

Service interactions are mocked — FastMCP and Services have separate test coverage,
this module only asserts the wiring shim.
"""

import inspect
from unittest.mock import AsyncMock, MagicMock

import pytest

from mcp_memory.models.record import SourceType
from mcp_memory.server import AppContext, make_server


def _make_mem_service():
    """Build a MemoryService-shaped MagicMock with realistic return values."""
    m = MagicMock()
    m.add = AsyncMock(
        return_value=MagicMock(
            id="rec_123",
            text="hello",
            metadata=MagicMock(tags=[], source_agent="test-agent"),
            source=SourceType.AGENT_ADD,
            title="H",
            preview="h",
            content_ref=None,
            created_at=0,
            updated_at=0,
        )
    )
    # For memory_list: each id in list() maps to a fully-populated record via get().
    # Distinct updated_at values so the default desc sort is observable.
    _records_by_id = {
        "r1": MagicMock(
            id="r1",
            text="alpha text",
            title="Alpha",
            preview="alpha preview",
            content_ref=MagicMock(type="docx", token="d1", url="https://x/d1"),
            file_ref=None,
            metadata=MagicMock(tags=["t1", "t2"], source_agent="agent-A"),
            source=SourceType.AGENT_ADD,
            created_at=1000,
            updated_at=3000,
        ),
        "r2": MagicMock(
            id="r2",
            text="beta text",
            title="Beta",
            preview="beta preview",
            content_ref=None,
            file_ref=None,
            metadata=MagicMock(tags=["t3"], source_agent="agent-B"),
            source=SourceType.AGENT_ADD,
            created_at=2000,
            updated_at=2000,
        ),
    }
    m.get = MagicMock(side_effect=lambda rid: _records_by_id.get(rid))
    m.delete = MagicMock(return_value=True)
    m.update = MagicMock(return_value=MagicMock(id="r", updated_at=999, title="N"))
    m.list = MagicMock(return_value=["r1", "r2"])
    m.count = MagicMock(return_value=7)
    return m


def _make_search_service():
    s = MagicMock()
    s.query = AsyncMock(return_value=[{"record_id": "r1", "score": 0.9}])
    return s


def _make_sync_service():
    s = MagicMock()
    s.incremental = AsyncMock(
        return_value=MagicMock(
            to_dict=MagicMock(
                return_value={"mode": "incremental", "added": 0, "updated": 0, "deleted": 0}
            )
        )
    )
    s.full = AsyncMock(
        return_value=MagicMock(
            to_dict=MagicMock(return_value={"mode": "full", "added": 0, "updated": 0, "deleted": 0})
        )
    )
    s.rebuild = AsyncMock(
        return_value=MagicMock(
            to_dict=MagicMock(
                return_value={"mode": "rebuild", "added": 0, "updated": 0, "deleted": 0}
            )
        )
    )
    return s


@pytest.fixture
def ctx():
    """An AppContext with distinct service mocks per scope.

    Distinct mocks are needed so identity-based routing assertions
    (memory vs knowledge) hold.
    """
    return AppContext(
        memory_service_memory=_make_mem_service(),
        memory_service_knowledge=_make_mem_service(),
        search_service_memory=_make_search_service(),
        search_service_knowledge=_make_search_service(),
        sync_service_memory=_make_sync_service(),
        sync_service_knowledge=_make_sync_service(),
    )


@pytest.fixture
def mcp(ctx):
    return make_server(ctx)


EXPECTED_TOOLS = {
    "memory_add",
    "memory_query",
    "memory_get",
    "memory_update",
    "memory_delete",
    "memory_list",
    "memory_count",
    "memory_sync",
    "file_upload",
}


def test_app_context_mem_routes_by_scope(ctx):
    assert ctx.mem("memory") is ctx.mem("memory")
    assert ctx.mem("knowledge") is not None
    assert ctx.mem("memory") is not ctx.mem("knowledge")
    with pytest.raises(ValueError):
        ctx.mem("invalid_scope")


def test_app_context_search_routes_by_scope(ctx):
    assert ctx.search("memory") is ctx.search("memory")
    assert ctx.search("memory") is not ctx.search("knowledge")
    with pytest.raises(ValueError):
        ctx.search("invalid_scope")


def test_app_context_sync_routes_by_scope(ctx):
    assert ctx.sync("memory") is ctx.sync("memory")
    assert ctx.sync("memory") is not ctx.sync("knowledge")
    with pytest.raises(ValueError):
        ctx.sync("invalid_scope")


async def test_make_server_returns_fastmcp(ctx):
    """make_server must produce a FastMCP instance."""
    from fastmcp import FastMCP

    server = make_server(ctx)
    assert isinstance(server, FastMCP)


async def test_make_server_registers_all_nine_tools(mcp):
    """FastMCP must have all 9 tool wrappers registered."""
    tools = await mcp.list_tools()
    tool_names = {t.name for t in tools}
    assert EXPECTED_TOOLS.issubset(tool_names), f"missing tools: {EXPECTED_TOOLS - tool_names}"


def test_make_server_constructs_synchronously(ctx):
    """make_server itself is sync — it should build without awaiting."""
    server = make_server(ctx)
    assert server is not None


def test_make_server_is_callable_with_default_args():
    """make_server accepts an AppContext; parameters beyond that have defaults."""
    sig = inspect.signature(make_server)
    assert "ctx" in sig.parameters


def test_app_context_extra_kwargs_satisfy_constructor():
    """The AppContext constructor must accept the six service kwargs."""
    sig = inspect.signature(AppContext)
    # inspect.signature excludes `self`, so 6 explicit kwargs = 6 services.
    assert len(sig.parameters) == 6
    expected = {
        "memory_service_memory",
        "memory_service_knowledge",
        "search_service_memory",
        "search_service_knowledge",
        "sync_service_memory",
        "sync_service_knowledge",
    }
    assert set(sig.parameters) == expected


# ---------------------------------------------------------------------------
# memory_list tool — items populated, sorted, _ids kept for backward compat
# ---------------------------------------------------------------------------


def _call_tool(mcp, name: str, **kwargs):
    """Helper: call a registered async tool function by name with kwargs."""
    import asyncio

    tools = {t.name: t for t in asyncio.run(mcp.list_tools())}
    return asyncio.run(tools[name].fn(**kwargs))


def test_memory_list_returns_full_items(ctx, mcp):
    """memory_list returns populated items (not just _ids), sorted desc by updated_at."""
    result = _call_tool(mcp, "memory_list")

    assert "items" in result
    assert len(result["items"]) == 2
    # Sorted desc by updated_at: r1 (3000) before r2 (2000)
    assert [it["record_id"] for it in result["items"]] == ["r1", "r2"]

    # Each item must contain the full summary fields
    r1 = result["items"][0]
    assert r1["record_id"] == "r1"
    assert r1["title"] == "Alpha"
    assert r1["preview"] == "alpha preview"
    assert r1["tags"] == ["t1", "t2"]
    assert r1["source"] == "agent_add"
    assert r1["source_agent"] == "agent-A"
    assert r1["content_ref_url"] == "https://x/d1"
    assert r1["created_at"] == 1000
    assert r1["updated_at"] == 3000

    # _ids is still present (backward compat) and matches the unfiltered list
    assert result["_ids"] == ["r1", "r2"]
    assert result["total"] == 7
    assert result["page"] == 1
    assert result["page_size"] == 20
    assert result["scope"] == "memory"


def test_memory_list_sorts_ascending_when_desc_false(ctx, mcp):
    """desc=False reverses the default sort order."""
    result = _call_tool(mcp, "memory_list", desc=False)
    assert [it["record_id"] for it in result["items"]] == ["r2", "r1"]


def test_memory_list_supports_alternate_sort_field(ctx, mcp):
    """sort_by=created_at sorts by creation time (not updated_at)."""
    result = _call_tool(mcp, "memory_list", sort_by="created_at", desc=True)
    # r2 (created_at=2000) before r1 (created_at=1000) when desc=True
    assert [it["record_id"] for it in result["items"]] == ["r2", "r1"]


def test_memory_list_skips_records_that_cannot_be_fetched(ctx, mcp):
    """If cache.get_record returns None for an id, skip it but don't crash."""
    # Override list to include an id that get() can't resolve.
    ctx.mem("memory").list = MagicMock(return_value=["r1", "missing", "r2"])
    result = _call_tool(mcp, "memory_list")
    assert [it["record_id"] for it in result["items"]] == ["r1", "r2"]
    # _ids still has all three ids (preserves the legacy contract)
    assert result["_ids"] == ["r1", "missing", "r2"]
