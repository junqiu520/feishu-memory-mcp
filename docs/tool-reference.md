# Tool reference

The MCP server exposes **8 tools**, all routed through `AppContext`. Each
accepts a `scope` parameter (`"memory"` or `"knowledge"`, default
`"memory"`) and is implemented in
[`src/mcp_memory/server.py`](../src/mcp_memory/server.py). This document
is the authoritative reference; the function signatures in `server.py`
are the canonical source.

## Conventions

- All tools are **async** and return `dict` (MCP-compatible).
- `scope="memory"` (default) routes to the agent-shared memory Bitable.
  `scope="knowledge"` routes to the owner-curated knowledge Bitable.
  Routing is by **the tool call**, not by the record — a record lives in
  exactly one Bitable.
- Errors come back as `{"error": "<code>", ...}` payloads with `error` set;
  successes always carry `"status"` (or a domain field) for easy
  branching.
- Time fields are unix epoch milliseconds.

## Scope reference

| Scope        | Routes to            | Typical writer                       | Typical reader               |
|--------------|----------------------|--------------------------------------|------------------------------|
| `memory`     | `memory_bitable`     | `memory_add` (agents)                | All agents + the owner       |
| `knowledge`  | `knowledge_bitable`  | Direct Bitable edits / file sync     | Agents via `memory_query`    |

If you're not sure, **start with `memory`**. Knowledge is for when the
owner is curating reference material.

---

## memory_add

Add a new memory record. Writes to Feishu first (authoritative), then
best-effort to the local cache.

**Signature** (canonical):

```text
async def memory_add(
    text: str,
    file_ref: dict | None = None,
    title: str | None = None,
    tags: list[str] | None = None,
    extra: dict | None = None,
    scope: str = "memory",
) -> dict
```

### Parameters

| Name       | Type           | Required | Default     | Description                                                |
|------------|----------------|----------|-------------|------------------------------------------------------------|
| `text`     | `str`          | yes      | —           | Plain text to store (1–100 000 chars). File attachments must be parsed by the caller first. |
| `file_ref` | `dict \| None` | no       | `None`      | Reference to a Feishu Drive file. Shape: `{type, token, url, file_name?, mime_type?}`. |
| `title`    | `str \| None`  | no       | first 30 chars of `text` | Human-readable title shown in Bitable. |
| `tags`     | `list[str] \| None` | no   | `[]`        | Searchable tags. Normalized lowercase + dedup.             |
| `extra`    | `dict \| None` | no       | `{}`        | Extra key/value metadata; serialized into Bitable `extra_json`. |
| `scope`    | `str`          | no       | `"memory"`  | `"memory"` or `"knowledge"`. Other values raise `ValueError`. |

### Return shape

```json
{
  "record_id": "rec_a1b2c3d4",
  "status": "ok",
  "chunk_count": 0,
  "feishu_url": null,
  "scope": "memory",
  "warning": null
}
```

`status` is `"ok"` on success. `warning` (optional) is a non-fatal note
such as `"local embedding skipped; will retry on next sync"`.

### Example

```python
await memory_add(
    text="FastAPI + uvicorn deploy; set --workers based on cpu count.",
    tags=["python", "deployment"],
    extra={"source_doc": "runbook-2026Q3"},
    scope="memory",
)

# With file_ref
await memory_add(
    text="PDF content converted to text by the agent ...",
    file_ref={
        "type": "drive_file",
        "token": "boxcnxxx",
        "url": "https://feishu.cn/drive/file/boxcnxxx",
        "file_name": "whitepaper.pdf",
        "mime_type": "application/pdf",
    },
    tags=["whitepaper", "rag"],
)
```

---

## memory_query

Search the local index. **Default and recommended mode is
`"hybrid_rerank"`**, which combines BM25, vector, RRF, and reranking.

### Signature

```text
async def memory_query(
    query: str,
    top_k: int = 5,
    filter: dict | None = None,
    mode: str = "hybrid_rerank",
    scope: str = "memory",
) -> dict
```

### Parameters

| Name    | Type     | Required | Default          | Description                              |
|---------|----------|----------|------------------|------------------------------------------|
| `query` | `str`    | yes      | —                | Natural-language query string.           |
| `top_k` | `int`    | no       | `5`              | Number of results to return (1+).        |
| `filter`| `dict \| None` | no  | `None`         | Pre-filter by metadata before recall.    |
| `mode`  | `str`    | no       | `"hybrid_rerank"`| Retrieval mode. See table below.         |
| `scope` | `str`    | no       | `"memory"`       | `"memory"` or `"knowledge"`.             |

#### Filter shape

```python
{
    "tags_any": ["python", "deployment"],          # any of these tags
    "tags_all": ["python"],                         # all of these tags
    "source_agent": "claude-1",                     # restrict by agent (memory scope)
    "source_type": "agent_add",                     # agent_add / feishu_doc / etc
    "created_after": 1719000000000,                 # unix ms; inclusive
    "updated_after": 1719000000000,                 # unix ms; inclusive
    "include_empty_text": False                     # default False: skip text_empty
}
```

All keys are optional. Empty/`None` filter means no pre-filter.

#### Mode comparison

| Mode              | Path                                              | Use when                                      | Cost      |
|-------------------|---------------------------------------------------|-----------------------------------------------|-----------|
| `bm25_only`       | FTS5 keyword only                                 | Exact name / date / id / acronym              | Fastest   |
| `vector_only`     | bge-m3 → LanceDB cosine                           | Abstract concept / paraphrased intent         | Fast      |
| `hybrid`          | BM25 + vector, fused with RRF, **no rerank**      | Want RRF benefit but skip reranker            | Medium    |
| `hybrid_rerank` (default) | BM25 + vector + RRF + bge-reranker-base    | Mixed intent; want best results              | Slowest (best quality) |

### Return shape

```json
{
  "results": [
    {
      "record_id": "rec_a1b2c3d4",
      "score": 0.93,
      "title": "FastAPI + uvicorn deploy",
      "preview": "FastAPI + uvicorn deploy; set --workers ...",
      "matched_chunk_text": "...matched snippet...",
      "content_ref_url": "https://feishu.cn/docs/...",
      "tags": ["python", "deployment"],
      "source": "agent_add",
      "source_agent": "claude-1",
      "created_at": 1719000000
    }
  ],
  "query_embedding_ms": 47,
  "total_candidates": 23,
  "cache_age_seconds": 12,
  "scope": "memory"
}
```

`cache_age_seconds` reports how stale the local index is since the last
sync (in seconds). High values suggest you may want a `memory_sync`.

### Example

```python
# Default — best for "I want the right answer, fast"
results = await memory_query(query="how to deploy FastAPI app")

# Force keyword-only lookup for a project codename
results = await memory_query(
    query="ATLAS-2042",
    mode="bm25_only",
)

# Restrict to tags + a date window
results = await memory_query(
    query="incident postmortem template",
    top_k=10,
    filter={"tags_any": ["postmortem"], "updated_after": 1717200000000},
)
```

---

## memory_get

Fetch one record by id, including its full text and content reference.

### Signature

```text
async def memory_get(record_id: str, scope: str = "memory") -> dict
```

### Parameters

| Name        | Type   | Required | Default     | Description                          |
|-------------|--------|----------|-------------|--------------------------------------|
| `record_id` | `str`  | yes      | —           | The id returned by `memory_add` / `memory_list` / `memory_query`. |
| `scope`     | `str`  | no       | `"memory"`  | Which Bitable to look in.            |

### Return shape

```json
{
  "record_id": "rec_a1b2c3d4",
  "title": "FastAPI + uvicorn deploy",
  "preview": "FastAPI + uvicorn deploy; set --workers based on cpu count.",
  "content_ref": {
    "type": "docx",
    "token": "doccnxxx",
    "url": "https://feishu.cn/docs/doccnxxx"
  },
  "file_ref": null,
  "tags": ["python", "deployment"],
  "source": "agent_add",
  "source_agent": "claude-1",
  "created_at": 1719000000,
  "updated_at": 1719000123,
  "full_text": "FastAPI + uvicorn deploy; set --workers based on cpu count.\n\n...",
  "chunks": [],
  "scope": "memory"
}
```

If not found:

```json
{ "error": "not_found", "record_id": "rec_xxx", "scope": "memory" }
```

### Example

```python
rec = await memory_get(record_id="rec_a1b2c3d4")
if "error" not in rec:
    print(rec["full_text"])
```

---

## memory_update

Edit metadata on an existing record. **Does not change `text` or
`content_ref`.** To change text, call `memory_delete` then `memory_add`.

### Signature

```text
async def memory_update(
    record_id: str,
    scope: str = "memory",
    title: str | None = None,
    tags: list[str] | None = None,
    extra: dict | None = None,
) -> dict
```

### Parameters

| Name        | Type                | Required | Default     | Description                                  |
|-------------|---------------------|----------|-------------|----------------------------------------------|
| `record_id` | `str`               | yes      | —           | Target record.                               |
| `scope`     | `str`               | no       | `"memory"`  | Which Bitable the record is in.              |
| `title`     | `str \| None`       | no       | unchanged   | New title (replaces existing).               |
| `tags`      | `list[str] \| None` | no       | unchanged   | Replace. Pass `[]` to clear; pass `None` to leave unchanged. |
| `extra`     | `dict \| None`      | no       | unchanged   | Replace. Same semantics as `tags`.           |

Note: `tags=[]` means *clear*, `tags=None` (or omitting the param) means
*keep as-is*. Same for `extra`.

### Return shape

```json
{
  "record_id": "rec_a1b2c3d4",
  "status": "ok",
  "scope": "memory",
  "updated_at": 1719000999,
  "changed_fields": ["title", "tags"]
}
```

If not found:

```json
{ "error": "not_found", "record_id": "rec_xxx", "scope": "memory" }
```

### Example

```python
await memory_update(
    record_id="rec_a1b2c3d4",
    tags=["python", "deployment", "fastapi"],
    title="FastAPI + uvicorn — production deploy notes",
)
```

---

## memory_delete

Permanently delete a record from both Feishu and the local cache. The
Drive source file (if any) is **not** deleted.

### Signature

```text
async def memory_delete(record_id: str, confirm: bool = False, scope: str = "memory") -> dict
```

### Parameters

| Name        | Type   | Required | Default     | Description                                  |
|-------------|--------|----------|-------------|----------------------------------------------|
| `record_id` | `str`  | yes      | —           | Target record.                               |
| `confirm`   | `bool` | yes (effectively) | `False` | Safety check. Must be `True` to delete.   |
| `scope`     | `str`  | no       | `"memory"`  | Which Bitable the record is in.              |

### Return shape

Success:

```json
{ "status": "deleted", "record_id": "rec_a1b2c3d4", "scope": "memory" }
```

Not found:

```json
{ "status": "not_found", "record_id": "rec_xxx", "scope": "memory" }
```

Refused (no confirmation):

```json
{ "error": "confirm_required", "record_id": "rec_xxx" }
```

### Example

```python
await memory_delete(record_id="rec_a1b2c3d4", confirm=True)
```

### Notes

- **This is irreversible.** The Bitable record is removed and the cache is
  deleted. To "edit" a body, use `memory_update` for metadata or
  `memory_delete` + `memory_add` for content.
- Drive source files are untouched (Feishu's own Drive retention applies).

---

## memory_list

Paginated list of records, **no semantic search** — just metadata
filtering + sort. Use `memory_query` when you need relevance ranking.

### Signature

```text
async def memory_list(
    filter: dict | None = None,
    page: int = 1,
    page_size: int = 20,
    sort_by: str = "updated_at",
    desc: bool = True,
    scope: str = "memory",
) -> dict
```

### Parameters

| Name        | Type                | Required | Default       | Description                                                  |
|-------------|---------------------|----------|---------------|--------------------------------------------------------------|
| `filter`    | `dict \| None`      | no       | `None`        | Same filter shape as `memory_query`.                         |
| `page`      | `int`               | no       | `1`           | 1-indexed page number.                                       |
| `page_size` | `int`               | no       | `20`          | Items per page (1–200).                                       |
| `sort_by`   | `str`               | no       | `"updated_at"`| Field to sort by.                                            |
| `desc`      | `bool`              | no       | `True`        | If `True`, newest-first; if `False`, oldest-first.           |
| `scope`     | `str`               | no       | `"memory"`    | `"memory"` or `"knowledge"`.                                 |

### Return shape

```json
{
  "items": [],
  "total": 142,
  "page": 1,
  "page_size": 20,
  "has_more": true,
  "scope": "memory",
  "_ids": ["rec_a1b2c3d4", "rec_e5f6g7h8", "rec_i9j0k1l2"]
}
```

> Note: in the current implementation, the resolved `record_id`s are
> returned in `_ids`. The `items` field is reserved for future detailed
> payloads. Use `memory_get` to fetch the full body of any id.

### Example

```python
# Pages through all "design" entries, newest first
listed = await memory_list(
    filter={"tags_any": ["design"]},
    page=1,
    page_size=50,
)
for rid in listed["_ids"]:
    rec = await memory_get(record_id=rid)
    print(rec["title"])
```

---

## memory_count

Count records matching a filter, no payload returned. **Local-only** —
works offline.

### Signature

```text
async def memory_count(filter: dict | None = None, scope: str = "memory") -> dict
```

### Parameters

| Name     | Type             | Required | Default     | Description                            |
|----------|------------------|----------|-------------|----------------------------------------|
| `filter` | `dict \| None`   | no       | `None`      | Same filter shape as `memory_query`.   |
| `scope`  | `str`            | no       | `"memory"`  | `"memory"` or `"knowledge"`.           |

### Return shape

```json
{ "count": 142, "filter_applied": null, "scope": "memory" }
```

### Example

```python
n = await memory_count(filter={"tags_any": ["design"]})
print(f"There are {n['count']} design-tagged memories")
```

---

## memory_sync

Reconcile the local cache with Feishu. **Always call this if the local
index looks stale or after editing the Bitable directly.**

### Signature

```text
async def memory_sync(mode: str = "incremental", scope: str = "memory") -> dict
```

### Parameters

| Name    | Type   | Required | Default         | Description                                              |
|---------|--------|----------|-----------------|----------------------------------------------------------|
| `mode`  | `str`  | no       | `"incremental"` | One of: `"incremental"`, `"full"`, `"rebuild"`.          |
| `scope` | `str`  | no       | `"memory"`      | `"memory"`, `"knowledge"`. (CLI also accepts `"both"`; the MCP tool takes one per call.) |

> The CLI `feishu-memory sync --scope both` syncs both scopes in one
> invocation. The MCP `memory_sync` tool targets a single scope; to sync
> both, call it twice.

#### Mode comparison

| Mode           | What it does                                                              | Time         | Touches Feishu data | Use case                                |
|----------------|---------------------------------------------------------------------------|--------------|---------------------|-----------------------------------------|
| `incremental`  | Pull records with `updated_at > last_sync_at`; embed only changed text    | Seconds      | No                  | Daily use; cron; startup auto-sync      |
| `full`         | Pull all Feishu records; diff with local cache; re-embed only changed     | Minutes      | No                  | Catch up after long absence             |
| `rebuild`      | Wipe local cache, re-import everything, re-embed everything               | Minutes (longest) | No              | Cache corruption, embedding-model change |

### Return shape

A `SyncResult` dictionary:

```json
{
  "mode": "incremental",
  "added": 3,
  "updated": 1,
  "deleted": 0,
  "errors": [],
  "started_at": 1719000123,
  "finished_at": 1719000189,
  "scope": "memory"
}
```

For invalid `mode`:

```json
{ "error": "invalid_mode", "mode": "weekly" }
```

### Example

```python
# After editing the Bitable in the Feishu UI
await memory_sync(mode="incremental")

# After a long absence, on a busy library
await memory_sync(mode="full")

# After changing the embedding model, or cache corruption
await memory_sync(mode="rebuild")
```

### Notes

- Sync is **pull only** — it never modifies Feishu records (other than
  the records `memory_add` and `memory_delete` create / remove).
- Sync can be slow on huge libraries. `incremental` is the only mode
  suitable for cron intervals under a minute.
- On startup, the server runs `incremental` automatically when
  `FEISHU_MEMORY_AUTO_SYNC=true` (the default).

---

## Filter reference (used by `memory_query`, `memory_list`, `memory_count`)

Every key is optional. Missing keys = no constraint on that dimension.

| Key                 | Type          | Meaning                                              |
|---------------------|---------------|------------------------------------------------------|
| `tags_any`          | `list[str]`   | Record must have **at least one** of these tags.     |
| `tags_all`          | `list[str]`   | Record must have **all** of these tags.              |
| `source_agent`      | `str`         | Restrict to a specific agent (memory scope only).    |
| `source_type`       | `str`         | One of: `agent_add`, `feishu_doc`, `feishu_bitable`, `feishu_drive_file`, `feishu_wiki`. |
| `created_after`     | `int` (ms)    | `created_at >= this`.                                |
| `updated_after`     | `int` (ms)    | `updated_at >= this`.                                |
| `include_empty_text`| `bool`        | Default `False`: records with `text_empty=True` are skipped. Set `True` to include them. |

`tags_any` and `tags_all` can be combined; the record must satisfy
both.

## Quick scope decision table

| User wants                                           | Use                              |
|------------------------------------------------------|----------------------------------|
| Save a fact, note, or snippet from this conversation | `memory_add(scope="memory")`     |
| Add a reference doc the owner just gave you          | `memory_add(scope="knowledge")`  |
| Search prior agent context                           | `memory_query(scope="memory")`   |
| Search the owner's curated library                   | `memory_query(scope="knowledge")`|
| List everything tagged a certain way                 | `memory_list` / `memory_count`   |
| Fix a typo in a previous memory's title              | `memory_update`                  |
| Forget a memory                                      | `memory_delete(confirm=True)`    |
| Refresh after editing the Bitable in Feishu UI       | `memory_sync`                    |

## Quick query-mode decision table

| Query intent                                  | Use mode             |
|-----------------------------------------------|----------------------|
| Default; mixed intent; need best results       | `"hybrid_rerank"`    |
| Exact name / date / ID / acronym               | `"bm25_only"`        |
| Abstract concept; paraphrased meaning          | `"vector_only"`      |
| Want fusion but skip reranker for speed        | `"hybrid"`           |
