"""Feishu Wiki client via lark-cli v2 protocol."""
from __future__ import annotations

from mcp_memory.feishu.runner import LarkCliRunner, LarkCliError


class WikiClient:
    def __init__(self, runner: LarkCliRunner):
        self.runner = runner

    async def get_node_content(self, node_token: str) -> str:
        try:
            result = self.runner.run([
                "wiki", "+node-get",
                "--token", node_token,
                "--format", "json",
            ])
        except LarkCliError:
            return ""

        if isinstance(result, dict):
            node = result.get("node") or result
            return (
                node.get("description")
                or node.get("content")
                or node.get("title")
                or ""
            )
        return ""