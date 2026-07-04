# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-07-02

Initial release. 27 commits across spec / plan / 9 implementation stages
plus 13 follow-up bug fixes. Verified end-to-end against a real Feishu
app (cli_a94c2822fbf9dcee) with a 19-record test Bitable.

### Added

- 8 MCP tools: `memory_add` / `memory_query` / `memory_get` /
  `memory_update` / `memory_delete` / `memory_list` / `memory_count` /
  `memory_sync`; each accepts a `scope` parameter (`memory` / `knowledge`)
- 4 `memory_query` modes: `hybrid_rerank` / `hybrid` / `bm25_only` /
  `vector_only` (user-selectable per call)
- 3 `memory_sync` modes: `incremental` / `full` / `rebuild`; `incremental`
  is default and safe to cron
- 9 CLI subcommands: `init` / `install-deps` / `serve` / `doctor` /
  `sync` / `status` / `schema` / `migrate` / `version`
- Two-Bitable design: `memory` (agent-shared) + `knowledge` (user-curated),
  scope-routed through a single 8-tool surface
- Multi-agent support via the `source_agent` field on records; each
  record carries provenance
- Local cache: SQLite (records + record_tags + sync_state) with FTS5
  for BM25; LanceDB for vector embeddings; rebuildable from Feishu
- BootstrapService: cold-start sync; failures don't block server startup
- Agent Skill at `skill/feishu-memory/SKILL.md` (auto-loaded by
  MCP-aware clients like Claude Code / Cursor / Codex)
- End-to-end real-Feishu verification harness (`tests/feishu/test_bitable_live.py`,
  marked `@pytest.mark.live`)

### Backend: lark-cli subprocess

- We dropped the `lark-oapi` Python SDK in favor of the official
  `@larksuite/cli` (Node.js) invoked via subprocess — one fewer Python
  dependency, OAuth handled by the CLI, and consistent error shapes
  across runtimes.
- `feishu-memory install-deps` automates the Node.js / npm / lark-cli
  check + install (with `npm install -g @larksuite/cli`).
- All four Feishu clients (`Bitable` / `Docx` / `Drive` / `Wiki`)
  implement the v2 protocol correctly:
  - `+record-upsert` (replaces v1's `+record-create` + `+record-update`)
  - `--json` direct field map (no `fields` wrapper)
  - Bitable select fields return `['value']` list (handled via `_unwrap_select`)
  - Datetime fields are strings like `2026-07-03 06:46:00` (not unix ms)
  - `docs +create` requires `--content` with XML body (v2 protocol)

### Configuration

- `feishu_app_secret` is `pydantic.SecretStr` end-to-end; never crosses
  the subprocess boundary in plaintext; `_extract_document_id` and
  `_extract_record_id` walk the v2 response shape correctly
- `Config.embedding_model` default: `sentence-transformers/all-MiniLM-L6-v2`
  (80MB, ~30s first download, works without HF_TOKEN). For multilingual /
  production quality, set `EMBEDDING_MODEL=BAAI/bge-m3` (1024-dim, ~2.3GB)
  and run `feishu-memory migrate` to clear the old LanceDB index
- Schema fields use v2 names: `select` (with `multiple: true/false`),
  `text`, `datetime` (with `style.format`), `checkbox`. The auto-init
  helper installs missing fields idempotently.

### Architecture decisions

- Feishu is the single source of truth; local cache is rebuildable
  via `feishu-memory migrate` or `memory_sync(mode="rebuild")`
- lark-cli subprocess replaces lark-oapi Python SDK (one fewer dep, OAuth
  unified across runtimes)
- `feishu_app_secret` is held as `pydantic.SecretStr` end-to-end and
  never crosses the subprocess boundary
- Three sync modes (`incremental` / `full` / `rebuild`); incremental is
  default and safe to cron
- Hybrid retrieval: BM25 + vector + RRF (+ optional rerank)
- Write path is Feishu-first; local cache is best-effort with `pending`
  fallback reconciled on next sync
- One process per scope: a single `feishu-memory serve` invocation
  serves both `memory` and `knowledge` scopes; the rule of thumb is
  "run multiple instances only if you need cross-process isolation"

### Tests

- 205 unit tests (mocked) across 23 test files
- 2 live tests (`@pytest.mark.live`) that exercise real Feishu +
  real embedding model + real LanceDB against a 19-record Bitable
- 14-section end-to-end harness (run as a one-shot script) that covers
  Runner → 4 feishu clients → 5 services → AppContext → 8 MCP tools
- Real-environment bug-fix pass surfaced 13 BUGs, all fixed and
  re-verified end-to-end

### Known limitations

- `docs +delete` does not exist in lark-cli v2. `DocxClient.delete_docx`
  is a no-op that logs a warning pointing to the Feishu native API
  (call `DELETE /open-apis/docx/v1/documents/:document_id` directly if
  you need real deletion)
- Default embedding model is English-leaning; for Chinese-heavy corpora
  set `EMBEDDING_MODEL=BAAI/bge-m3` (see `docs/installation.md §4.5`)
- Knowledge Bitable credentials are optional; sync gracefully skips
  the missing scope

[0.1.0]: https://github.com/junqiu/feishu-memory-mcp/releases/tag/v0.1.0
