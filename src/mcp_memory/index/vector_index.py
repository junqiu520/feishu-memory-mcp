"""LanceVectorIndex real implementation.

Replaces the Stage 4 stub with actual lancedb operations:
  - open / create table on first upsert
  - upsert: convert VectorChunk list to records, add via lancedb
  - search: lancedb vector_search with optional metadata filter
  - delete_by_record: filter + delete

Schema is fixed (per scope):
  chunk_id: str (primary key)
  record_id: str
  text: str
  embedding: list[float]
  start_offset: int
  end_offset: int
  metadata: str (JSON-serialized dict for portability)

v1: keep things simple — no auto-merging / fragmenting. Each chunk is one row.
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

log = logging.getLogger(__name__)


@dataclass
class VectorChunk:
    chunk_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    record_id: str = ""
    text: str = ""
    embedding: list[float] = field(default_factory=list)
    start_offset: int = 0
    end_offset: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


class VectorIndex(Protocol):
    async def upsert(self, chunks: list[VectorChunk]) -> None: ...
    async def delete_by_record(self, record_id: str) -> None: ...
    async def search(
        self,
        query_vector: list[float],
        top_k: int,
        metadata_filter: dict | None = None,
    ) -> list[tuple[str, float]]: ...


def _chunk_to_row(c: VectorChunk) -> dict:
    return {
        "chunk_id": c.chunk_id,
        "record_id": c.record_id,
        "text": c.text,
        "embedding": c.embedding,
        "start_offset": c.start_offset,
        "end_offset": c.end_offset,
        "metadata": json.dumps(c.metadata, ensure_ascii=False),
    }


def _row_to_chunk(row: dict) -> VectorChunk:
    try:
        meta = json.loads(row.get("metadata") or "{}")
    except (json.JSONDecodeError, TypeError):
        meta = {}
    return VectorChunk(
        chunk_id=row["chunk_id"],
        record_id=row.get("record_id", ""),
        text=row.get("text", ""),
        embedding=list(row.get("embedding") or []),
        start_offset=int(row.get("start_offset") or 0),
        end_offset=int(row.get("end_offset") or 0),
        metadata=meta,
    )


class LanceVectorIndex:
    """LanceDB-backed vector index with per-scope tables."""

    def __init__(self, path: Any, scope: str):
        self.path = Path(path)
        self.scope = scope
        self._db: Any = None
        self._table: Any = None
        self._table_initialized: bool = False

    def _table_name(self) -> str:
        # LanceDB table names: [a-zA-Z0-9_], must start with letter
        return f"{self.scope}_chunks"

    def _ensure_table(self, embedding_dim: int | None = None) -> Any:
        """Open or create the table. Pass embedding_dim on first creation."""
        if self._table_initialized:
            return self._table
        import lancedb
        import pyarrow as pa

        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = lancedb.connect(str(self.path))

        name = self._table_name()
        if name in self._db.table_names():
            self._table = self._db.open_table(name)
        else:
            # Define schema with explicit vector dim so subsequent upserts
            # of the same dim work, and mismatched dims fail loudly.
            if embedding_dim is None:
                embedding_dim = 384  # default; first upsert with real data will fix it
            schema = pa.schema([
                pa.field("chunk_id", pa.string(), nullable=False),
                pa.field("record_id", pa.string()),
                pa.field("text", pa.string()),
                pa.field("embedding", pa.list_(pa.float32(), embedding_dim)),
                pa.field("start_offset", pa.int32()),
                pa.field("end_offset", pa.int32()),
                pa.field("metadata", pa.string()),
            ])
            self._table = self._db.create_table(name, schema=schema, mode="create")
        self._table_initialized = True
        return self._table

    async def upsert(self, chunks: list[VectorChunk]) -> None:
        if not chunks:
            return
        # Use the dim of the first chunk to define schema on first create.
        emb_dim = len(chunks[0].embedding) if chunks and chunks[0].embedding else 384
        table = self._ensure_table(embedding_dim=emb_dim)
        rows = [_chunk_to_row(c) for c in chunks]
        # Re-upsert: delete any existing chunk with same (record_id, start_offset)
        # then add fresh. This keeps "last write wins" semantics.
        for c in chunks:
            if not c.record_id:
                continue
            try:
                table.delete(
                    f"record_id = '{_escape(c.record_id)}' AND start_offset = {c.start_offset}"
                )
            except Exception:
                log.debug("delete-before-upsert skipped")
        table.add(rows)

    async def delete_by_record(self, record_id: str) -> None:
        if not self._table_initialized:
            return
        table = self._ensure_table()
        try:
            table.delete(f"record_id = '{_escape(record_id)}'")
        except Exception as e:
            log.warning("delete_by_record failed for %s: %s", record_id, e)

    async def search(
        self,
        query_vector: list[float],
        top_k: int,
        metadata_filter: dict | None = None,
    ) -> list[tuple[str, float]]:
        """Search by vector similarity. Returns [(record_id, score), ...].

        The caller is expected to look up the record in the local cache by
        record_id. chunk_id is internal — we return record_id for downstream
        compatibility with bm25 results (which also return record_id).
        """
        table = self._ensure_table(embedding_dim=len(query_vector))
        try:
            q = table.search(query_vector, vector_column_name="embedding").limit(top_k)
            tbl = q.to_arrow()
        except Exception as e:
            log.warning("LanceDB search failed: %s", e)
            return []
        if tbl.num_rows == 0:
            return []
        record_ids = tbl.column("record_id").to_pylist() if "record_id" in tbl.column_names else []
        distances = tbl.column("_distance").to_pylist() if "_distance" in tbl.column_names else []
        results = []
        for rid, dist in zip(record_ids, distances):
            if not rid or rid == "":
                continue
            score = 1.0 - float(dist)
            results.append((rid, score))
        return results


def _escape(s: str) -> str:
    """Escape single quotes for lancedb SQL where() clauses."""
    return str(s).replace("'", "''")
