"""FastMCP server with 9 tool wrappers (spec §5).

Tools:
  memory_add(text, file_ref?, title?, tags?, extra?, scope='memory')
  memory_query(query, top_k?, filter?, mode='hybrid_rerank', scope='memory')
  memory_get(record_id, scope='memory')
  memory_update(record_id, scope='memory', title?, tags?, extra?)
  memory_delete(record_id, confirm=False, scope='memory')
  memory_list(filter?, page?, page_size?, sort_by?, desc?, scope='memory')
  memory_count(filter?, scope='memory')
  memory_sync(mode='incremental', scope='memory')
  file_upload(file_paths)

Scope routing: 'memory' / 'knowledge' — handled by AppContext for the
8 memory_* tools. ``file_upload`` is global (not scope-keyed) because
Feishu Drive uploads aren't bound to either library.

The wiring targets the Service interfaces from Stage 5
(MemoryService, SearchService, SyncService). No Feishu SDK calls run here;
Network-touching branches stay as stubs until Stage 8.
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP


_VALID_SCOPES = ("memory", "knowledge")


def _validate_scope(scope: str) -> str:
    if scope not in _VALID_SCOPES:
        raise ValueError(f"scope must be 'memory' or 'knowledge', got {scope!r}")
    return scope


class AppContext:
    """Bundle of services keyed by scope ('memory' / 'knowledge').

    Constructed with two service instances per kind, one per scope. Provides
    `.mem(scope)`, `.search(scope)`, `.sync(scope)` accessors that raise
    ValueError for invalid scope names — keeping the surface small and the
    routing rule explicit.
    """

    def __init__(
        self,
        memory_service_memory: Any,
        memory_service_knowledge: Any,
        search_service_memory: Any,
        search_service_knowledge: Any,
        sync_service_memory: Any,
        sync_service_knowledge: Any,
    ) -> None:
        self._mem = {
            "memory": memory_service_memory,
            "knowledge": memory_service_knowledge,
        }
        self._search = {
            "memory": search_service_memory,
            "knowledge": search_service_knowledge,
        }
        self._sync = {
            "memory": sync_service_memory,
            "knowledge": sync_service_knowledge,
        }

    def mem(self, scope: str) -> Any:
        _validate_scope(scope)
        return self._mem[scope]

    def search(self, scope: str) -> Any:
        _validate_scope(scope)
        return self._search[scope]

    def sync(self, scope: str) -> Any:
        _validate_scope(scope)
        return self._sync[scope]


def _record_to_summary(rec: Any) -> dict:
    """Build a summary dict from a MemoryRecord for memory_list items.

    Pulled out so it can be unit-tested independently and reused if other
    tools (memory_query) want a similar shape.
    """
    content_ref = rec.content_ref
    return {
        "record_id": rec.id,
        "title": rec.title,
        "preview": rec.preview,
        "tags": list(rec.metadata.tags),
        "source": rec.source.value,
        "source_agent": rec.metadata.source_agent,
        "content_ref_url": content_ref.url if content_ref else None,
        "created_at": rec.created_at,
        "updated_at": rec.updated_at,
    }


_SUMMARY_SORTABLE_FIELDS = ("record_id", "title", "preview", "source",
                            "source_agent", "created_at", "updated_at")


def _sort_summaries(items: list[dict], sort_by: str, desc: bool) -> list[dict]:
    """Sort a list of summary dicts by ``sort_by`` and ``desc``.

    Falls back to updated_at desc if sort_by is unrecognized. Items lacking
    the field sort to the end on desc=True (None treated as -infinity).
    """
    if sort_by not in _SUMMARY_SORTABLE_FIELDS:
        sort_by = "updated_at"

    def key(it: dict):
        value = it.get(sort_by)
        # Push None to the end (treated as smaller than any real value).
        return (value is None, value)

    return sorted(items, key=key, reverse=desc)


_upload_service_singleton: Any = None


def _get_upload_service():
    """Module-level singleton UploadService for file_upload tool.

    file_upload doesn't take a scope (uploads are global to Feishu Drive),
    so it doesn't fit into AppContext's per-scope routing. A lazy singleton
    keeps the construction cost off the import path and avoids threading
    a new dependency through ``make_server``'s signature.
    """
    from mcp_memory.feishu.drive import DriveClient
    from mcp_memory.feishu.runner import LarkCliRunner
    from mcp_memory.services.upload_service import UploadService

    global _upload_service_singleton
    if _upload_service_singleton is None:
        _upload_service_singleton = UploadService(DriveClient(LarkCliRunner()))
    return _upload_service_singleton


def make_server(ctx: AppContext) -> FastMCP:
    """Build FastMCP server with all 9 tools wired to ``ctx`` services."""
    mcp = FastMCP("feishu-memory-mcp")

    @mcp.tool
    async def memory_add(
        text: str,
        file_ref: dict | None = None,
        title: str | None = None,
        tags: list[str] | None = None,
        extra: dict | None = None,
        scope: str = "memory",
    ) -> dict:
        """添加一条记忆到 long-term RAG。

        何时调用：
        scope="memory"（默认）：
        存储可复用的经验、用户的偏好/教训、事件里程碑等。
        不要用于：临时上下文（对话中直接保留）、系统指令（不是记忆）。

        scope="knowledge"：
        存储用户的材料/文件（规范、文档、笔记等），但需要你先解析附件内容为文本。
        file_ref 需要先调用 file_upload 工具获取 file token + URL。
        """
        from mcp_memory.models.record import FeishuFileRef

        file_ref_obj: FeishuFileRef | None = None
        if file_ref:
            file_ref_obj = FeishuFileRef(
                type="drive_file",
                token=file_ref.get("token", ""),
                url=file_ref.get("url", ""),
                file_name=file_ref.get("file_name"),
                mime_type=file_ref.get("mime_type"),
            )

        svc = ctx.mem(scope)
        record = await svc.add(
            text=text,
            title=title,
            tags=tags,
            extra=extra,
            file_ref=file_ref_obj,
        )
        return {
            "record_id": record.id,
            "status": "ok",
            "chunk_count": 0,
            "feishu_url": None,
            "scope": scope,
            "warning": None,
        }

    @mcp.tool
    async def memory_query(
        query: str,
        top_k: int = 5,
        filter: dict | None = None,
        mode: str = "hybrid_rerank",
        scope: str = "memory",
    ) -> dict:
        """从知识库检索最相关的记忆（4 种 mode）。"""
        svc = ctx.search(scope)
        results = await svc.query(query=query, top_k=top_k, filter=filter, mode=mode)
        return {
            "results": results,
            "query_embedding_ms": 0,
            "total_candidates": len(results),
            "cache_age_seconds": 0,
            "scope": scope,
        }

    @mcp.tool
    async def memory_get(record_id: str, scope: str = "memory") -> dict:
        """取一条记录的完整内容。"""
        rec = ctx.mem(scope).get(record_id)
        if rec is None:
            return {"error": "not_found", "record_id": record_id, "scope": scope}
        content_ref = rec.content_ref
        return {
            "record_id": rec.id,
            "title": rec.title,
            "preview": rec.preview,
            "content_ref": (
                {
                    "type": content_ref.type,
                    "token": content_ref.token,
                    "url": content_ref.url,
                }
                if content_ref
                else None
            ),
            "file_ref": (rec.file_ref.__dict__ if rec.file_ref else None),
            "tags": rec.metadata.tags,
            "source": rec.source.value,
            "source_agent": rec.metadata.source_agent,
            "created_at": rec.created_at,
            "updated_at": rec.updated_at,
            "full_text": rec.text,
            "chunks": [],
            "scope": scope,
        }

    @mcp.tool
    async def memory_update(
        record_id: str,
        scope: str = "memory",
        title: str | None = None,
        tags: list[str] | None = None,
        extra: dict | None = None,
    ) -> dict:
        """修改一条记忆的元数据（不改 text）。"""
        rec = ctx.mem(scope).update(record_id=record_id, title=title, tags=tags, extra=extra)
        if rec is None:
            return {"error": "not_found", "record_id": record_id, "scope": scope}
        changed_fields = [
            k for k, v in {"title": title, "tags": tags, "extra": extra}.items() if v is not None
        ]
        return {
            "record_id": record_id,
            "status": "ok",
            "scope": scope,
            "updated_at": rec.updated_at,
            "changed_fields": changed_fields,
        }

    @mcp.tool
    async def memory_delete(record_id: str, confirm: bool = False, scope: str = "memory") -> dict:
        """删除一条记忆（飞书 + 本地同时删）。confirm 必须 True 才执行。"""
        if not confirm:
            return {"error": "confirm_required", "record_id": record_id}
        deleted = ctx.mem(scope).delete(record_id)
        return {
            "status": "deleted" if deleted else "not_found",
            "record_id": record_id,
            "scope": scope,
        }

    @mcp.tool
    async def memory_list(
        filter: dict | None = None,
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "updated_at",
        desc: bool = True,
        scope: str = "memory",
    ) -> dict:
        """列表分页（不带语义检索）。

        Returns:
            items:  每条记录的摘要字典（按 sort_by/desc 排序，默认 updated_at desc）
            _ids:   仅返回 id 列表（已废弃，请改用 items；Stage 10 移除）
        """
        ids = ctx.mem(scope).list(filter=filter, page=page, page_size=page_size)
        total = ctx.mem(scope).count(filter=filter)

        # Hydrate ids → full summary dicts; skip records that can't be fetched.
        items: list[dict] = []
        for rid in ids:
            rec = ctx.mem(scope).get(rid)
            if rec is None:
                continue
            items.append(_record_to_summary(rec))

        # Apply sort. sort_by must be one of the fields we materialize above.
        items = _sort_summaries(items, sort_by=sort_by, desc=desc)

        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_more": len(ids) >= page_size,
            "scope": scope,
            "_ids": ids,  # @deprecated: migrate to items in Stage 10
        }

    @mcp.tool
    async def memory_count(filter: dict | None = None, scope: str = "memory") -> dict:
        """按 filter 计数。"""
        count = ctx.mem(scope).count(filter=filter)
        return {"count": count, "filter_applied": filter, "scope": scope}

    @mcp.tool
    async def memory_sync(mode: str = "incremental", scope: str = "memory") -> dict:
        """校准本地索引与飞书。可指定 mode 和 scope（memory/knowledge/both）。"""
        svc = ctx.sync(scope)
        if mode == "incremental":
            result = await svc.incremental()
        elif mode == "full":
            result = await svc.full()
        elif mode == "rebuild":
            result = await svc.rebuild()
        else:
            return {"error": "invalid_mode", "mode": mode}
        return result.to_dict() | {"scope": scope}

    @mcp.tool
    async def file_upload(file_paths: list[str]) -> dict:
        """上传文件到飞书云盘，返回 file token + URL。

        何时调用：
        - 用户要保存本地文件到飞书
        - 需要先把文件上传到飞书，再调用 memory_add 存储为 memory 或 knowledge
        - 用户提供了多个本地文件需要入库

        参数：
        - file_paths: 本地文件路径列表（支持一次上传多个文件）

        返回：
        每条路径对应一条结果，结构：
        {
          "uploads": [
            {"file_path": "...", "status": "ok", "file_token": "...", "url": "...", "name": "..."},
            {"file_path": "...", "status": "error", "error": "file_not_found"}
          ]
        }

        失败处理：单个文件失败不会中止其他文件的上传。
        """
        if not file_paths:
            return {"error": "empty_file_paths", "uploads": []}
        upload_svc = _get_upload_service()
        uploads = await upload_svc.upload(file_paths)
        return {"uploads": uploads}

    return mcp
