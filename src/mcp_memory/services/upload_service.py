"""UploadService — orchestrates file uploads to Feishu Drive.

Wraps ``DriveClient.upload_file`` so the MCP ``file_upload`` tool can accept
a list of paths and return per-file results. Single-file failures don't
abort the batch — every entry in ``file_paths`` produces a result entry.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


class UploadService:
    """Batch file-upload orchestration.

    Stateless w.r.t. Feishu side: every call goes through the injected
    ``drive_client``. Local-side validation (existence) is done up-front so
    a missing path doesn't waste a lark-cli subprocess invocation.
    """

    def __init__(self, drive_client: Any):
        self.drive = drive_client

    async def upload(self, file_paths: list[str]) -> list[dict]:
        """Upload each path; return a per-file result list.

        Each result entry has shape::

            {
                "file_path": "<original input>",
                "status": "ok" | "error",
                "file_token": "...",   # only when status == "ok"
                "url": "...",          # only when status == "ok"
                "name": "...",         # only when status == "ok"
                "error": "...",        # only when status == "error"
            }

        A missing local file is reported as ``status="error"`` with
        ``error="file_not_found"`` without invoking lark-cli.
        """
        results: list[dict] = []
        for raw_path in file_paths:
            path_str = str(raw_path) if raw_path is not None else ""
            entry: dict[str, Any] = {"file_path": path_str}

            if not path_str:
                entry["status"] = "error"
                entry["error"] = "empty_path"
                results.append(entry)
                continue

            if not os.path.isfile(path_str):
                entry["status"] = "error"
                entry["error"] = "file_not_found"
                results.append(entry)
                continue

            try:
                feishu_result = await self.drive.upload_file(path_str)
            except Exception as e:
                log.warning("upload failed for %s: %s", path_str, e)
                entry["status"] = "error"
                entry["error"] = str(e) or "upload_failed"
                results.append(entry)
                continue

            file_token = feishu_result.get("file_token") or ""
            if not file_token:
                entry["status"] = "error"
                entry["error"] = "no_file_token_returned"
                results.append(entry)
                continue

            entry["status"] = "ok"
            entry["file_token"] = file_token
            entry["url"] = feishu_result.get("url") or ""
            entry["name"] = (
                feishu_result.get("name")
                or Path(path_str).name
            )
            results.append(entry)

        return results