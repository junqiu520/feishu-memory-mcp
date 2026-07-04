"""BootstrapService — startup auto-sync.

Invoked when the MCP server starts. Failure is logged but does not block
startup, so a flaky network or Feishu auth issue never takes the server down.
"""
from __future__ import annotations

import logging

from mcp_memory.services.sync_service import SyncService

log = logging.getLogger(__name__)


class BootstrapService:
    """Called on MCP server startup. Failures do not propagate."""

    def __init__(
        self,
        sync_services: dict[str, SyncService],
        auto_sync_scope: str = "memory",
    ):
        """
        Args:
            sync_services: mapping of scope name ("memory" / "knowledge")
                to its SyncService instance.
            auto_sync_scope: which scope(s) to auto-sync. One of
                "memory" | "knowledge" | "both".
        """
        self.sync_services = sync_services
        self.auto_sync_scope = auto_sync_scope

    async def on_startup(self) -> None:
        """Run incremental sync for each configured scope. Never raises."""
        if self.auto_sync_scope == "both":
            scopes = ["memory", "knowledge"]
        else:
            scopes = [self.auto_sync_scope]

        for scope in scopes:
            svc = self.sync_services.get(scope)
            if svc is None:
                log.debug("startup sync: no service registered for scope=%s, skipping", scope)
                continue
            try:
                result = await svc.incremental()
                log.info("startup sync [%s]: %s", scope, result.to_dict())
            except Exception as e:
                log.warning("startup sync [%s] failed: %s", scope, e)


def make_bootstrap_from_config(
    sync_memory: SyncService,
    sync_knowledge: SyncService,
    auto_sync_scope: str = "memory",
) -> BootstrapService:
    """Factory: convenient assembly from main()."""
    return BootstrapService(
        sync_services={"memory": sync_memory, "knowledge": sync_knowledge},
        auto_sync_scope=auto_sync_scope,
    )
