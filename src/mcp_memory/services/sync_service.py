"""SyncService — incremental / full / rebuild sync from Feishu.

Stage 9: real wire-up via LarkCliRunner subprocess. Each mode:
  - incremental: pull records updated since last_sync_at; embed & upsert
  - full: pull all remote records; diff with local; add/update/delete
  - rebuild: drop local; then run full
"""
from __future__ import annotations

import logging
import time
from typing import Any

from mcp_memory.index.embedding_engine import EmbeddingEngine
from mcp_memory.models.record import MemoryRecord, MemoryMetadata, SourceType
from mcp_memory.storage.local_cache import LocalCache

log = logging.getLogger(__name__)


class SyncResult:
    """Sync result summary."""

    def __init__(
        self,
        mode: str,
        added: int = 0,
        updated: int = 0,
        deleted: int = 0,
        errors: list[str] | None = None,
    ):
        self.mode = mode
        self.added = added
        self.updated = updated
        self.deleted = deleted
        self.errors = errors or []
        self.started_at = int(time.time())
        self.finished_at: int | None = None

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "added": self.added,
            "updated": self.updated,
            "deleted": self.deleted,
            "errors": list(self.errors),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


def _record_from_bitable(rec) -> MemoryRecord:
    """Build a local MemoryRecord from a BitableRecord (Stage 9 mapping)."""
    fields = rec.fields or {}
    tags_raw = fields.get("tags") or []
    if isinstance(tags_raw, str):
        # lark-cli may return comma-joined string for select fields
        tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
    else:
        tags = list(tags_raw)

    text = fields.get("preview", "") or fields.get("title", "")

    # Bitable select / single_select fields return ['value'] (list of one).
    # Unwrap to plain string. Same for content_ref_type.
    def _unwrap_select(value):
        if isinstance(value, list):
            return value[0] if value else ""
        return value or ""

    content_ref_type = _unwrap_select(fields.get("content_ref_type"))
    content_ref_token = fields.get("content_ref_token")
    content_ref_url = fields.get("content_ref_url")

    from mcp_memory.models.record import FeishuRef

    content_ref = None
    if content_ref_type and content_ref_token:
        # Coerce content_ref_type to a known literal
        ctype = str(content_ref_type)
        if ctype in ("docx", "bitable", "drive_file", "wiki"):
            content_ref = FeishuRef(
                type=ctype,
                token=str(content_ref_token),
                url=content_ref_url or "",
            )

    # source: Bitable single-select returns ['agent_add']
    source_raw = _unwrap_select(fields.get("source"))
    try:
        source = SourceType(source_raw or "agent_add")
    except ValueError:
        source = SourceType.AGENT_ADD

    # origin: same single-select unwrap
    origin = _unwrap_select(fields.get("origin")) or "auto_sync"
    if origin not in ("manual", "auto_sync"):
        origin = "auto_sync"

    metadata = MemoryMetadata(
        tags=tags,
        source_agent=fields.get("source_agent"),
        origin=origin,
    )

    return MemoryRecord(
        id=rec.id,
        source=source,
        title=fields.get("title", ""),
        preview=fields.get("preview", ""),
        text=text,
        content_hash=fields.get("content_hash", ""),
        content_ref=content_ref,
        metadata=metadata,
        text_empty=bool(fields.get("text_empty", False)),
        created_at=_parse_bitable_datetime(fields.get("created_at")),
        updated_at=_parse_bitable_datetime(fields.get("updated_at")),
    )


def _parse_bitable_datetime(value: Any) -> int:
    """Parse a Bitable datetime value into a unix timestamp (seconds).

    Feishu Bitable returns datetime values as strings like ``"2026-07-03 06:46:00"``
    (v2 lark-cli) or occasionally as ints (unix ms in older v1 responses).
    Accept both. Return 0 for None / unparseable so the field stays valid.
    """
    if value is None or value == "":
        return 0
    if isinstance(value, (int, float)):
        # Assume unix ms; fall back to unix seconds if value is suspiciously small.
        v = int(value)
        if v > 1e12:  # > year 2001 in ms
            return v // 1000
        return v
    if isinstance(value, str):
        s = value.strip()
        # Try common Feishu datetime formats
        from datetime import datetime
        for fmt in (
            "%Y-%m-%d %H:%M:%S",
            "%Y/%m/%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d",
        ):
            try:
                dt = datetime.strptime(s, fmt)
                return int(dt.timestamp())
            except ValueError:
                continue
        # Try plain int string
        try:
            return _parse_bitable_datetime(int(s))
        except (ValueError, TypeError):
            return 0
    return 0


class SyncService:
    """Three-mode sync orchestration (spec §4.3).

    Stage 9: real wire-up — calls BitableClient.list_records through
    LarkCliRunner subprocess; embeds text and writes to VectorIndex.
    """

    def __init__(
        self,
        local_cache: LocalCache,
        bitable_client: Any,
        embedding_engine: EmbeddingEngine,
        vector_index: Any,
        scope: str = "memory",
    ):
        self.cache = local_cache
        self.bitable = bitable_client
        self.embed = embedding_engine
        self.vector = vector_index
        self.scope = scope

    async def incremental(self) -> SyncResult:
        """Incremental: pull records with updated_at > last_sync_at, embed."""
        result = SyncResult(mode="incremental")
        state = self.cache.get_sync_state()
        last_sync_at_s = state.get("last_sync_at")
        last_sync_at_ms = int(last_sync_at_s * 1000) if last_sync_at_s else None

        try:
            records = await self.bitable.list_records(updated_after_ms=last_sync_at_ms)
        except Exception as e:
            result.errors.append(f"list_records failed: {e}")
            result.finished_at = int(time.time())
            return result

        await self._upsert_and_embed(records, result)

        self.cache.update_sync_state({"last_sync_at": int(time.time())})
        result.finished_at = int(time.time())
        return result

    async def full(self) -> SyncResult:
        """Full diff: pull all Feishu records and diff against local."""
        result = SyncResult(mode="full")
        try:
            records = await self.bitable.list_records()
        except Exception as e:
            result.errors.append(f"list_records failed: {e}")
            result.finished_at = int(time.time())
            return result

        await self._upsert_and_embed(records, result)

        # Diff: detect deletions
        remote_ids = {r.id for r in records}
        local_ids = set(self.cache.list_by_filter({}))
        for local_id in local_ids - remote_ids:
            self.cache.delete(local_id)
            await self.vector.delete_by_record(local_id)
            result.deleted += 1

        self.cache.update_sync_state({"last_full_sync_at": int(time.time())})
        result.finished_at = int(time.time())
        return result

    async def rebuild(self) -> SyncResult:
        """Rebuild: drop local, re-import from zero."""
        result = SyncResult(mode="rebuild")
        try:
            self.cache.clear_all_records()
        except Exception as e:
            result.errors.append(f"local drop failed: {e}")
            result.finished_at = int(time.time())
            return result

        # Then run full — but force mode="rebuild" on result
        full_result = await self.full()
        full_result.mode = "rebuild"
        full_result.added = full_result.added  # already set
        full_result.deleted = full_result.deleted  # already set
        self.cache.update_sync_state({"last_rebuild_at": int(time.time())})
        return full_result

    async def _upsert_and_embed(self, records, result: SyncResult) -> None:
        """Upsert each record locally; batch embed text and push to vector index."""
        text_chunks: list[str] = []
        local_records: list[MemoryRecord] = []
        for rec in records:
            local = _record_from_bitable(rec)
            self.cache.upsert(local)
            local_records.append(local)
            result.added += 1
            if local.text and not local.text_empty:
                text_chunks.append(local.text)

        if not text_chunks:
            return

        try:
            embeddings = await self.embed.embed(text_chunks)
        except Exception as e:
            result.errors.append(f"embed failed: {e}")
            return

        from mcp_memory.index.vector_index import VectorChunk

        chunks_to_upsert: list[VectorChunk] = []
        for local, emb in zip(local_records, embeddings):
            if not (local.text and not local.text_empty):
                continue
            chunks_to_upsert.append(VectorChunk(
                chunk_id=f"{local.id}_chunk_0",
                record_id=local.id,
                text=local.text,
                embedding=emb,
                metadata={"source_agent": local.metadata.source_agent or ""},
            ))
        if chunks_to_upsert:
            try:
                await self.vector.upsert(chunks_to_upsert)
            except Exception as e:
                result.errors.append(f"vector upsert failed: {e}")