"""Feishu Drive client via lark-cli v2 protocol."""
from __future__ import annotations

from mcp_memory.feishu.runner import LarkCliRunner, LarkCliError


class DriveClient:
    def __init__(self, runner: LarkCliRunner):
        self.runner = runner

    async def get_file_info(self, file_token: str) -> dict:
        try:
            result = self.runner.run([
                "drive", "+file-get",
                "--file-token", file_token,
                "--format", "json",
            ])
        except LarkCliError:
            return {}

        if isinstance(result, dict):
            data = result.get("data")
            file_obj = result.get("file")
            if not isinstance(file_obj, dict) and isinstance(data, dict):
                file_obj = data.get("file")
            # Fallback: flat response shape (e.g. top-level keys directly).
            if not isinstance(file_obj, dict):
                file_obj = result if "file_token" in result or "name" in result else {}
            return {
                "file_token": file_obj.get("file_token", file_token),
                "name": file_obj.get("name"),
                "type": file_obj.get("type"),
                "url": file_obj.get("url"),
                "size": file_obj.get("size"),
            }
        return {}

    async def upload_file(self, local_path: str) -> dict:
        try:
            result = self.runner.run([
                "drive", "+upload", local_path, "--yes", "--format", "json",
            ])
        except LarkCliError:
            return {}
        if isinstance(result, dict):
            data = result.get("data") if isinstance(result.get("data"), dict) else {}
            return {
                "file_token": (
                    result.get("file_token")
                    or result.get("token")
                    or data.get("file_token")
                ),
                "url": result.get("url") or data.get("url"),
                "name": result.get("name") or data.get("name"),
            }
        return {}