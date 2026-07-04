"""MemoryService — add / get / delete / update / list / count orchestration.

Spec §4.1 (write), §4.4 (delete), §4.5 (update).

Stage 9 wire-up: add() now calls DocxClient → BitableClient (via lark-cli
subprocess), then writes locally. Failure modes degrade gracefully
(log warning, fall back to local-only).
"""
from __future__ import annotations

import hashlib
import logging
import time
import uuid
from typing import Any

from mcp_memory.models.record import (
    MemoryRecord,
    SourceType,
    FeishuRef,
    FeishuFileRef,
    MemoryMetadata,
)
from mcp_memory.storage.local_cache import LocalCache

log = logging.getLogger(__name__)


class MemoryService:
    """add / get / delete / update / list / count operations.

    add flow (spec §4.1):
      1. docx create → token (Feishu; via LarkCliRunner subprocess)
      2. bitable create_record (Feishu; via LarkCliRunner subprocess)
      3. write local cache + embed (embedding pending)

    Failure modes: any step that touches Feishu is best-effort. We never
    block local-write on Feishu availability.
    """

    def __init__(
        self,
        local_cache: LocalCache,
        bitable_client: Any,
        docx_client: Any = None,
        agent_id: str = "default",
    ):
        self.cache = local_cache
        self.bitable = bitable_client
        self.docx = docx_client
        self.agent_id = agent_id

    async def add(
        self,
        text: str,
        title: str | None = None,
        tags: list[str] | None = None,
        extra: dict | None = None,
        file_ref: FeishuFileRef | None = None,
        source: SourceType = SourceType.AGENT_ADD,
    ) -> MemoryRecord:
        if not text:
            raise ValueError("text 不能为空")
        if len(text) > 100_000:
            raise ValueError("text 长度超过 100K 字限制")

        text_empty = not text.strip()
        record_id_local = str(uuid.uuid4())
        auto_title = title if title else text[:30]
        preview = text[:200] if text else ""
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()

        # Step 1: docx create (best effort)
        content_ref_token: str | None = None
        content_ref_url: str | None = None
        if self.docx is not None:
            try:
                content_ref_token = await self.docx.create_docx(content=text, title=auto_title)
            except Exception as e:
                log.warning("docx create failed: %s", e)

        # Step 2: build fields dict for bitable
        now_ms = int(time.time() * 1000)
        fields: dict[str, Any] = {
            "source": source.value,
            "title": auto_title,
            "preview": preview,
            "content_ref_type": "docx" if content_ref_token else None,
            "content_ref_token": content_ref_token,
            "content_ref_url": content_ref_url,
            "content_hash": content_hash,
            "tags": tags or [],
            "source_agent": self.agent_id,
            "origin": "manual" if source == SourceType.AGENT_ADD else "auto_sync",
            "text_empty": text_empty,
            "created_at": now_ms,
            "updated_at": now_ms,
        }

        # Step 3: bitable create (best effort)
        record_id = record_id_local
        if self.bitable is not None:
            try:
                feishu_rec = await self.bitable.create_record(fields)
                if feishu_rec.id:
                    record_id = feishu_rec.id
            except Exception as e:
                log.error(
                    "Bitable create failed: %s, falling back to local-only id=%s",
                    e, record_id_local,
                )

        # Step 4: build local MemoryRecord
        content_ref = (
            FeishuRef(type="docx", token=content_ref_token, url=content_ref_url or "")
            if content_ref_token
            else None
        )
        record = MemoryRecord(
            id=record_id,
            source=source,
            title=auto_title,
            preview=preview,
            text=text,
            content_hash=content_hash,
            content_ref=content_ref,
            file_ref=file_ref,
            metadata=MemoryMetadata(
                tags=tags or [],
                source_agent=self.agent_id,
                origin="manual" if source == SourceType.AGENT_ADD else "auto_sync",
                extra=extra or {},
            ),
            text_empty=text_empty,
            created_at=now_ms // 1000,
            updated_at=now_ms // 1000,
        )

        self.cache.upsert(record)
        return record

    def get(self, record_id: str) -> MemoryRecord | None:
        return self.cache.get_record(record_id)

    async def delete(self, record_id: str) -> bool:
        if self.cache.get_record(record_id) is None:
            return False
        # Propagate to Bitable first; on failure, leave local cache intact.
        try:
            deleted = await self.bitable.delete_record(record_id)
        except Exception as e:
            log.warning("Bitable delete failed for %s: %s", record_id, e)
            return False
        if not deleted:
            return False
        self.cache.delete(record_id)
        return True

    async def update(
        self,
        record_id: str,
        title: str | None = None,
        tags: list[str] | None = None,
        extra: dict | None = None,
    ) -> MemoryRecord | None:
        # Update local cache first
        updated = self.cache.update_metadata(
            record_id=record_id,
            title=title,
            tags=tags,
            extra=extra,
        )
        if updated is None:
            return None

        # Propagate to Bitable (best-effort — local update wins on failure)
        try:
            fields: dict = {}
            if title is not None:
                fields["title"] = title
            if tags is not None:
                fields["tags"] = tags
            if extra is not None:
                import json
                fields["extra_json"] = json.dumps(extra, ensure_ascii=False)
            if fields:
                result = await self.bitable.batch_update(record_id, fields)
                log.info("Bitable update returned: %s", result)
        except Exception as e:
            log.warning(
                "local update OK but Bitable update failed for %s: %s",
                record_id, e,
            )
            import traceback
            log.debug(traceback.format_exc())

        return updated

    def list(
        self,
        filter: dict | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> list[str]:
        ids = self.cache.list_by_filter(filter or {})
        start = (page - 1) * page_size
        end = start + page_size
        return ids[start:end]

    def count(self, filter: dict | None = None) -> int:
        return self.cache.count_by_filter(filter or {})