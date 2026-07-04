"""Tests for BootstrapService (Stage 5.4).

BootstrapService runs the configured scope(s)' incremental sync at MCP startup.
It must never raise: a failed sync just gets logged.
"""
import logging
from unittest.mock import AsyncMock, MagicMock
from mcp_memory.services.bootstrap_service import BootstrapService
from mcp_memory.services.sync_service import SyncService, SyncResult


async def test_bootstrap_memory_scope_only():
    sync_memory = MagicMock(spec=SyncService)
    sync_memory.incremental = AsyncMock(return_value=SyncResult(mode="incremental", added=2))
    sync_knowledge = MagicMock(spec=SyncService)
    sync_knowledge.incremental = AsyncMock(return_value=SyncResult(mode="incremental"))

    bs = BootstrapService(
        sync_services={"memory": sync_memory, "knowledge": sync_knowledge},
        auto_sync_scope="memory",
    )
    await bs.on_startup()

    assert sync_memory.incremental.await_count == 1
    assert sync_knowledge.incremental.await_count == 0


async def test_bootstrap_both_scopes():
    sync_memory = MagicMock()
    sync_memory.incremental = AsyncMock(return_value=SyncResult(mode="incremental"))
    sync_knowledge = MagicMock()
    sync_knowledge.incremental = AsyncMock(return_value=SyncResult(mode="incremental"))

    bs = BootstrapService(
        sync_services={"memory": sync_memory, "knowledge": sync_knowledge},
        auto_sync_scope="both",
    )
    await bs.on_startup()

    assert sync_memory.incremental.await_count == 1
    assert sync_knowledge.incremental.await_count == 1


async def test_bootstrap_failure_does_not_raise(caplog):
    sync_memory = MagicMock()
    sync_memory.incremental = AsyncMock(side_effect=Exception("network down"))
    sync_knowledge = MagicMock()
    sync_knowledge.incremental = AsyncMock(return_value=SyncResult(mode="incremental"))

    bs = BootstrapService(
        sync_services={"memory": sync_memory, "knowledge": sync_knowledge},
        auto_sync_scope="both",
    )
    with caplog.at_level(logging.WARNING, logger="mcp_memory.services.bootstrap_service"):
        # Should not raise
        await bs.on_startup()
    # The failing scope is logged at WARNING; the healthy scope still runs
    assert sync_knowledge.incremental.await_count == 1
    assert any("network down" in rec.message for rec in caplog.records)


async def test_bootstrap_missing_scope_is_skipped():
    """If the configured scope has no service registered, skip it without raising."""
    bs = BootstrapService(
        sync_services={},  # nothing registered
        auto_sync_scope="memory",
    )
    # Should not raise
    await bs.on_startup()
