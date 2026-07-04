# Architecture

This document is for contributors and curious users who want to understand
how `feishu-memory-mcp` fits together. The spec lives in
[`docs/superpowers/specs/2026-07-02-feishu-memory-mcp-design.md`](superpowers/specs/2026-07-02-feishu-memory-mcp-design.md);
this file is the readable companion.

## What it's for

`feishu-memory-mcp` gives every LLM agent on the same machine a **shared
RAG memory** that survives across sessions. The agent uses MCP tools
(`memory_add`, `memory_query`, etc.) to write and read records; the records
are persisted to a Feishu Bitable (so the agent's owner can read them in
the Feishu UI, or sync them to another machine). A local SQLite + LanceDB
+ FTS5 cache holds the working copy — fast for queries, recoverable from
Feishu on demand. Feishu is the source of truth; the local cache is
rebuildable.

## High-level flow

```
agent ──MCP stdio──> feishu-memory-mcp ──subprocess──> lark-cli ──HTTPS──> Feishu
                                       └──in-process──> bge-m3 + LanceDB + SQLite
```

Reads are local (fast, offline). Writes go to Feishu first (authoritative),
then best-effort to the local cache. A periodic `memory_sync` reconciles
the cache back to the canonical Feishu state.

## Five-layer architecture

### L1 — MCP Protocol

[`src/mcp_memory/server.py`](../src/mcp_memory/server.py) wraps everything
in a [FastMCP](https://github.com/jlowin/fastmcp) server exposing **8
tools** over the stdio MCP transport. The 8 tools are the only surface
agents ever see:

```
memory_add · memory_query · memory_get · memory_update
memory_delete · memory_list · memory_count · memory_sync
```

Each tool accepts a `scope` parameter (`"memory"` or `"knowledge"`)
defaulting to `"memory"`. Routing is performed by the `AppContext` class:
the server is constructed with **two instances of every service** (one
per scope), and `ctx.mem(scope)` / `ctx.search(scope)` / `ctx.sync(scope)`
resolve to the right one.

### L2 — Service layer

[`src/mcp_memory/services/`](../src/mcp_memory/services/) holds the four
service classes that orchestrate everything:

| Service            | Responsibility                                                   |
|--------------------|------------------------------------------------------------------|
| `MemoryService`    | `add` / `get` / `update` / `delete` / `list` / `count`           |
| `SearchService`    | Hybrid recall + RRF + optional rerank                            |
| `SyncService`      | `incremental` / `full` / `rebuild` against Feishu               |
| `BootstrapService` | Cold-start: ensure data dirs, run startup sync, warm embedding   |

The services are intentionally thin. They compose L3 (index engine) and L4
(Feishu adapter) and contain almost no business logic — that's deliberate.
Tests inject fake `LocalCache` / `BitableClient` / `EmbeddingEngine`
implementations, so the service layer is easy to exercise without the
real Feishu backend.

### L3 — Index Engine

[`src/mcp_memory/index/`](../src/mcp_memory/index/) is where the retrieval
mechanics live. Five components:

| Component         | Role                                                                |
|-------------------|---------------------------------------------------------------------|
| `TextChunker`     | Sliding-window chunker (800 chars + 100 overlap). Short text → 1 chunk. |
| `EmbeddingEngine` | `BAAI/bge-m3` (1024-dim) loaded via `sentence-transformers`. Runs on a 2-worker `ThreadPoolExecutor` so the asyncio loop stays responsive. |
| `VectorIndex`     | Pluggable interface; default `LanceVectorIndex` writes to a LanceDB table per scope. |
| `BM25Index`       | SQLite FTS5 virtual table (`records_fts`) with INSERT/UPDATE/DELETE triggers to keep it in sync. |
| `RRFMerger`       | Reciprocal rank fusion: `score = Σ 1 / (60 + rank)`.                |
| `Reranker`        | Optional `BAAI/bge-reranker-base` cross-encoder for top-2k.        |

`SearchService.query` runs the four `mode` values:

- `bm25_only` — FTS5 only. Fast, exact.
- `vector_only` — bge-m3 + LanceDB cosine. Semantic.
- `hybrid` — BM25 + vector + RRF, no rerank.
- `hybrid_rerank` (default) — hybrid + rerank.

### L4 — Feishu Adapter

[`src/mcp_memory/feishu/`](../src/mcp_memory/feishu/) wraps the lark-cli
binary. The key class is `LarkCliRunner`
([`src/mcp_memory/feishu/runner.py`](../src/mcp_memory/feishu/runner.py)):
a thin `subprocess.run(["lark-cli", …, "--format", "json"])` wrapper that:

1. Always passes `--format json` and `--as bot` (or `--as user` if the
   call should use the user's identity).
2. Parses stdout as JSON (or extracts JSON from a markdown code fence if
   lark-cli returns its human-readable mode by accident).
3. Parses stderr's error envelope on non-zero exit, mapping `exit=10` to
   a `LarkCliConfirmationRequired` exception (we auto-`--yes` because
   these calls are agent-driven).
4. Surfaces timeouts / missing-binary errors as `LarkCliError`.

Above the runner sit four domain clients:

- `BitableClient` — list / create / update / delete records
- `DocxClient` — create / read / delete docx for content storage
- `DriveClient` — upload / list Drive files (PDF, image, PPT)
- `WikiClient` — list / read Wiki nodes

### L5 — Local Storage

[`src/mcp_memory/storage/`](../src/mcp_memory/storage/) is the working
copy. Three physical files per scope:

| File                                  | Holds                                     |
|---------------------------------------|-------------------------------------------|
| `data_dir/local_cache_<scope>.sqlite` | `records`, `record_tags`, `sync_state`, `records_fts` |
| `data_dir/vectors_<scope>.lance`      | LanceDB chunks (bge-m3 1024-dim vectors)  |
| `~/.cache/huggingface/...`            | bge-m3 / bge-reranker model weights       |

The SQLite schema is in [`schema.sql`](../src/mcp_memory/storage/schema.sql).
Note the FTS5 virtual table is maintained by triggers — there is no
explicit reindex path needed.

## The two-Bitable concept (`memory` vs `knowledge`)

The agent's primary surface is one MCP tool set with a `scope` parameter.
Under the hood, `scope` selects which Bitable to talk to:

| Scope        | Who writes           | Who reads                 | Bitable instance              |
|--------------|----------------------|---------------------------|-------------------------------|
| `memory`     | Agents (`memory_add`) | All agents + the owner    | `memory_bitable` (multi-agent shared) |
| `knowledge`  | The owner (via sync / direct edit) | Agents via `memory_query` | `knowledge_bitable` (personal library) |

The schema is identical for both; only the app/token differs. Routing is
implemented by **construction**: two `MemoryService` / `SearchService` /
`SyncService` instances are built at startup, one per Bitable client, and
the `AppContext` selects between them.

The conceptual split is documented in spec §1.5. Short version: agents
produce memories, humans curate knowledge — same machinery, different
writable edge.

## Core invariants

These are the design contracts that hold even when individual
implementations drift:

1. **Feishu is the source of truth.** Bitable write success is the
   definition of "the memory was saved". Local-only writes that didn't
   make it to Feishu are tagged `sync_status='pending'` and reconciled
   on the next sync.
2. **The local cache is rebuildable.** Deleting
   `data_dir/local_cache_*.sqlite` and `data_dir/vectors_*.lance` loses
   no data. The next `memory_sync(mode="rebuild")` (or any
   `memory_sync(mode="incremental")` from a cold state) restores both.
3. **`SecretStr` is end-to-end.** `feishu_app_secret` is typed as
   `pydantic.SecretStr` in `Config` and never logged or serialized in
   plaintext. The subprocess boundary (lark-cli) does not see it — lark-cli
   carries its own OAuth token from `lark-cli config init`.
4. **Agent-first surface.** The CLI is for ops (`init`, `doctor`, `sync`,
   `status`, `schema`, `migrate`, `version`); the MCP tools are for agents.
   There is no `cli memory add` — agents write through MCP.
5. **Write to Feishu first, cache second.** `memory_add` blocks on the
   Feishu write; embedding and indexing are best-effort with `pending`
   fallback.

## Design decisions (and why)

### lark-cli subprocess, not `lark-oapi` Python SDK

Originally the spec called for the `lark-oapi` Python SDK called in-process.
We moved to `lark-cli` (the npm package `@larksuite/cli`) for three
reasons:

- **Single source of OAuth / token / retry behavior.** The Python SDK and
  the JS CLI have historically diverged on token refresh and rate-limit
  retry. One binary, one set of behaviors, easier to debug.
- **No Python SDK dependency** = ~30MB lighter install and one fewer
  thing for users to build against when `pip install`-ing.
- **Cross-language onboarding.** Anyone working in TS/JS can read the
  same backend code as a Python user.

The cost is **~200ms of Node.js startup overhead per call**. For RAG
workloads that's fine — a single `memory_query` already spends 30–80ms on
embedding, and the lark-cli overhead is dominated by network anyway.

### Agent-first, CLI-only-for-ops

The 8 MCP tools are intentionally minimal (add/query/get/update/delete/
list/count/sync). The CLI re-implements none of them. The CLI exists
strictly for `init`, `doctor`, `sync`, `status`, `schema`, `migrate`,
`install-deps`, `version` — all operator-facing tasks. The reasoning is in
spec §10.4.

### Schema in Bitable, not in our code

We let Bitable own the schema definition (we just declare fields and
types). The MCP server treats Bitable as an external database and only
adds agent-facing semantics on top. This is what keeps the local
reconstruction cheap.

### Two scopes, two Bitables (not one Bitable with a `scope` column)

A single Bitable would have meant agents writing to the owner's knowledge
rows by mistake, and mixed recall. Separate Bitables enforce the role
separation at the data layer.

## Where to read next

- [`docs/tool-reference.md`](tool-reference.md) — every MCP tool, signature, example.
- [`docs/operations.md`](operations.md) — sync modes, cache cleanup, troubleshooting.
- [`docs/installation.md`](installation.md) — install + lark-cli dependency.
- Spec at [`docs/superpowers/specs/2026-07-02-feishu-memory-mcp-design.md`](superpowers/specs/2026-07-02-feishu-memory-mcp-design.md).