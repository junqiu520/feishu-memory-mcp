"""本地 SQLite 缓存层。

设计：每个 scope（memory / knowledge）一个独立 .sqlite 文件。
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from mcp_memory.models.record import MemoryRecord


class LocalCache:
    def __init__(self, db_path: Path, scope: str):
        if scope not in ("memory", "knowledge"):
            raise ValueError(f"scope must be 'memory' or 'knowledge', got {scope!r}")
        self.db_path = db_path
        self.scope = scope
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(str(db_path), isolation_level=None, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    def _init_schema(self) -> None:
        schema_path = Path(__file__).parent / "schema.sql"
        schema_sql = schema_path.read_text(encoding="utf-8")
        self._conn.executescript(schema_sql)
        cur = self._conn.execute("SELECT COUNT(*) FROM sync_state")
        if cur.fetchone()[0] == 0:
            self._conn.execute(
                "INSERT INTO sync_state (id, local_instance_id) VALUES (1, ?)",
                (str(uuid.uuid4()),),
            )
            self._conn.commit()

    def _table_exists(self, name: str) -> bool:
        cur = self._conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        )
        return cur.fetchone() is not None

    def get_sync_state(self) -> dict:
        row = self._conn.execute("SELECT * FROM sync_state WHERE id=1").fetchone()
        return dict(row) if row else {}

    def update_sync_state(self, updates: dict) -> None:
        if not updates:
            return
        sets = ",".join([f"{k} = ?" for k in updates.keys()])
        vals = list(updates.values())
        self._conn.execute(f"UPDATE sync_state SET {sets} WHERE id = 1", vals)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # ─────────────────────────────────────
    # records CRUD
    # ─────────────────────────────────────

    def upsert(self, record: MemoryRecord) -> None:
        row = record.to_row()
        now = int(time.time())
        row["created_at"] = now if not row["created_at"] else row["created_at"]
        row["updated_at"] = now
        text_empty_val = 1 if not record.text else 0
        row["text_empty"] = text_empty_val

        placeholders = ",".join([f":{k}" for k in row.keys()])
        cols = ",".join(row.keys())
        sql = f"INSERT OR REPLACE INTO records ({cols}) VALUES ({placeholders})"
        self._conn.execute(sql, row)

        self._conn.execute("DELETE FROM record_tags WHERE record_id = ?", (record.id,))
        for tag in record.metadata.tags:
            self._conn.execute(
                "INSERT OR IGNORE INTO record_tags (record_id, tag) VALUES (?, ?)",
                (record.id, tag),
            )
        self._conn.commit()

    def get_record(self, record_id: str) -> MemoryRecord | None:
        row = self._conn.execute(
            "SELECT * FROM records WHERE id = ?", (record_id,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_record(dict(row))

    def delete(self, record_id: str) -> None:
        self._conn.execute("DELETE FROM records WHERE id = ?", (record_id,))
        self._conn.execute("DELETE FROM record_tags WHERE record_id = ?", (record_id,))
        self._conn.commit()

    def clear_all_records(self) -> None:
        """Remove every record and tag from the local cache.

        Used by SyncService.rebuild before re-importing from Feishu. Does
        NOT touch sync_state — rebuild callers want to preserve
        last_sync_at / local_instance_id so subsequent incremental sync
        continues to work after the wipe.
        """
        self._conn.execute("DELETE FROM records")
        self._conn.execute("DELETE FROM record_tags")
        self._conn.commit()

    def list_by_filter(self, filt: dict) -> list[str]:
        where, params = self._build_filter_sql(filt)
        sql = f"SELECT id FROM records WHERE {where}"
        rows = self._conn.execute(sql, params).fetchall()
        return [r["id"] for r in rows]

    def count_by_filter(self, filt: dict) -> int:
        where, params = self._build_filter_sql(filt)
        sql = f"SELECT COUNT(*) AS c FROM records WHERE {where}"
        return self._conn.execute(sql, params).fetchone()["c"]

    def _build_filter_sql(self, filt: dict) -> tuple[str, list]:
        clauses = []
        params: list = []

        tags_any = filt.get("tags_any")
        if tags_any:
            placeholders = ",".join(["?"] * len(tags_any))
            clauses.append(
                f"id IN (SELECT record_id FROM record_tags WHERE tag IN ({placeholders}))"
            )
            params.extend(tags_any)

        tags_all = filt.get("tags_all")
        if tags_all:
            for tag in tags_all:
                clauses.append("id IN (SELECT record_id FROM record_tags WHERE tag = ?)")
                params.append(tag)

        if "source_agent" in filt and filt["source_agent"] is not None:
            clauses.append("(source_agent = ? OR source_agent IS NULL)")
            params.append(filt["source_agent"])

        if "source_type" in filt and filt["source_type"] is not None:
            clauses.append("source = ?")
            params.append(filt["source_type"])

        if "created_after" in filt and filt["created_after"] is not None:
            clauses.append("created_at >= ?")
            params.append(filt["created_after"])

        if "updated_after" in filt and filt["updated_after"] is not None:
            clauses.append("updated_at >= ?")
            params.append(filt["updated_after"])

        if not filt.get("include_empty_text", False):
            clauses.append("(text IS NOT NULL AND text != '')")

        where = " AND ".join(clauses) if clauses else "1=1"
        return where, params

    def _row_to_record(self, row: dict) -> MemoryRecord:
        from mcp_memory.models.record import (
            MemoryMetadata,
            SourceType,
            FeishuRef,
            FeishuFileRef,
        )

        content_ref = None
        if row.get("content_ref_type") and row.get("content_ref_token"):
            content_ref = FeishuRef(
                type=row["content_ref_type"],
                token=row["content_ref_token"],
                url=row.get("content_ref_url", ""),
            )

        file_ref = None
        if row.get("file_ref_json"):
            data = json.loads(row["file_ref_json"])
            file_ref = FeishuFileRef(**data)

        return MemoryRecord(
            id=row["id"],
            source=SourceType(row["source"]),
            title=row["title"],
            preview=row.get("preview", ""),
            text=row.get("text", "") or "",
            content_hash=row.get("content_hash", ""),
            content_ref=content_ref,
            file_ref=file_ref,
            metadata=MemoryMetadata(
                tags=json.loads(row["tags_json"]) if row.get("tags_json") else [],
                source_user=row.get("source_user"),
                source_agent=row.get("source_agent"),
                origin=row.get("origin", "manual"),
                extra=json.loads(row["extra_json"]) if row.get("extra_json") else {},
            ),
            text_empty=bool(row.get("text_empty", 0)),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def update_metadata(
        self,
        record_id: str,
        title: str | None = None,
        tags: list[str] | None = None,
        extra: dict | None = None,
    ) -> MemoryRecord | None:
        existing = self.get_record(record_id)
        if existing is None:
            return None

        if title is not None:
            existing.title = title
            existing.preview = existing.text[:200] if existing.text else ""

        if tags is not None:
            existing.metadata.tags = list(tags)
            self._conn.execute("DELETE FROM record_tags WHERE record_id = ?", (record_id,))
            for tag in existing.metadata.tags:
                self._conn.execute(
                    "INSERT OR IGNORE INTO record_tags (record_id, tag) VALUES (?, ?)",
                    (record_id, tag),
                )

        if extra is not None:
            existing.metadata.extra = dict(extra)

        existing.updated_at = int(time.time())
        self.upsert(existing)
        return self.get_record(record_id)

    def search_fts(
        self, query: str, candidate_ids: list[str] | None = None, limit: int = 50
    ) -> list[tuple[str, float]]:
        if not query.strip():
            return []
        q = query.replace('"', '""')
        where_extra = ""
        params: list = [f'"{q}"']
        if candidate_ids:
            placeholders = ",".join(["?"] * len(candidate_ids))
            where_extra = f" AND r.id IN ({placeholders})"
            params.extend(candidate_ids)
        sql = f"""
            SELECT r.id AS record_id, bm25(records_fts) AS score
            FROM records_fts
            JOIN records r ON r.rowid = records_fts.rowid
            WHERE records_fts MATCH ? {where_extra}
            ORDER BY bm25(records_fts)
            LIMIT ?
        """
        params.append(limit)
        rows = self._conn.execute(sql, params).fetchall()
        return [(r["record_id"], r["score"]) for r in rows]
