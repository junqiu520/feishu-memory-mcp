# feishu-memory-mcp

> MCP server for Feishu-backed RAG memory. Persistent agent memory and a
> personal knowledge library, both stored in Feishu Bitable, both
> searchable through a single Model Context Protocol surface.

## 5-minute quick start

```bash
# 1. Install the Python package
pip install feishu-memory-mcp

# 2. Install the lark-cli system dependency (Node.js >= 18, then lark-cli)
feishu-memory install-deps

# 3. Authorize lark-cli with your Feishu app
lark-cli config init

# 4. Set required env vars (see Configuration below)
export FEISHU_APP_ID=cli_xxxxxxxxxxxx
export FEISHU_APP_SECRET=...
export MEMORY_BITABLE_APP_TOKEN=bascnxxxxxxxxxxxx
export MEMORY_BITABLE_TABLE_ID=tblxxxxxxxxxxxxxxxx
export KNOWLEDGE_BITABLE_APP_TOKEN=bascnyyyyyyyyyyyy
export KNOWLEDGE_BITABLE_TABLE_ID=tblyyyyyyyyyyyyy

# 5. Verify the install
feishu-memory doctor

# 6. Run the MCP server
feishu-memory serve
```

Point your MCP client (Claude Desktop, Cursor, etc.) at
`feishu-memory serve`. See [docs/installation.md](docs/installation.md)
for platform-specific notes and troubleshooting.

## What this gives you

- **Two isolated Bitable-backed scopes**:
  - **memory** — write-once, append-only entries keyed to a specific
    agent (the agent's persistent scratchpad).
  - **knowledge** — your personal knowledge library, readable and
    writable by humans and agents alike.
- **Hybrid retrieval**: FTS5 keyword search over the local SQLite cache,
  vector similarity over a local LanceDB index, fused with reciprocal
  rank fusion (RRF) and reranked with BAAI/bge-reranker-base.
- **Local-first**: every operation goes through a SQLite + LanceDB
  cache so the server responds fast even on flaky networks. A sync
  command reconciles the cache with Feishu.

## CLI

`feishu-memory` ships a single-binary CLI for every operational task:

| Subcommand      | Purpose                                              |
|-----------------|------------------------------------------------------|
| `install-deps`  | Detect Node.js / npm and install lark-cli globally.  |
| `init`          | Print the env-var template for first-time setup.     |
| `serve`         | Start the MCP server (stdio transport).              |
| `doctor`        | Diagnose Node, npm, lark-cli, config, and cache.     |
| `sync`          | Reconcile the local cache with Feishu Bitables.      |
| `status`        | Show local cache + sync state.                       |
| `schema`        | Dump / verify the Bitable schema.                    |
| `migrate`       | Rebuild the Bitable schema (upgrade).                |
| `version`       | Print version and exit.                              |

Every subcommand supports `--help`. The CLI is documented as the
primary interface for ops — agents should prefer the MCP tools.

## MCP tools

The server exposes **9 MCP tools** for agent use:

| Tool          | Purpose                                              | Scope           |
|---------------|------------------------------------------------------|-----------------|
| `mem_add`     | Add a memory entry to the agent's memory scope.      | memory / knowledge |
| `mem_list`    | List recent memory entries for the agent.            | memory / knowledge |
| `mem_search`  | Hybrid-search over the agent's memory scope.         | memory / knowledge |
| `mem_delete`  | Delete a memory entry (memory scope only).           | memory / knowledge |
| `kno_search`  | Hybrid-search over the knowledge library.            | memory / knowledge |
| `kno_upsert`  | Insert or update a knowledge entry.                  | memory / knowledge |
| `sync_run`    | Trigger a sync against one or both Bitables.         | memory / knowledge |
| `sync_status` | Report the last sync timestamp + per-scope counts.   | memory / knowledge |
| `file_upload` | Upload local files to Feishu Drive; returns `file_token` + `url` for use as `mem_add.file_ref`. | — |

Full request / response schemas live in
[docs/tool-reference.md](docs/tool-reference.md) (placeholder — see
`src/mcp_memory/server.py` for the canonical tool decorators).

## Configuration

All configuration flows through environment variables (loaded by
Pydantic Settings). Required:

| Variable                       | Purpose                                                |
|--------------------------------|--------------------------------------------------------|
| `FEISHU_APP_ID`                | Feishu app id (`cli_xxx…`).                            |
| `FEISHU_APP_SECRET`            | Feishu app secret.                                     |
| `MEMORY_BITABLE_APP_TOKEN`     | App token of the agent-memory Bitable.                 |
| `MEMORY_BITABLE_TABLE_ID`      | Table id inside that Bitable.                          |
| `KNOWLEDGE_BITABLE_APP_TOKEN`  | App token of the personal-knowledge Bitable.           |
| `KNOWLEDGE_BITABLE_TABLE_ID`   | Table id inside that Bitable.                          |

Optional (with defaults):

| Variable                       | Default                | Purpose                                  |
|--------------------------------|------------------------|------------------------------------------|
| `FEISHU_MEMORY_AGENT_ID`       | `default`              | Identifies this agent's memory scope.    |
| `FEISHU_MEMORY_DATA_DIR`       | `./.feishu_memory`     | Local cache + index location.            |
| `FEISHU_MEMORY_DEVICE`         | `cpu`                  | `cpu` / `cuda` / `mps` for embeddings.   |
| `FEISHU_MEMORY_AUTO_SYNC`      | `true`                 | Sync on server startup.                  |
| `FEISHU_MEMORY_AUTO_SCOPE`     | `memory`               | Which scope to auto-sync.                |
| `LARK_CLI_PATH`                | (PATH lookup)          | Override lark-cli binary location.       |

## Architecture

Quick summary:

- **CLI** (`feishu_memory/cli.py`) — ops surface (install-deps, doctor,
  sync, …). Built on stdlib `argparse`, no extra deps.
- **MCP server** (`feishu_memory/server.py`) — FastMCP, 9 tools.
- **Services** (`src/mcp_memory/services/`) — domain logic (Memory,
  Search, Sync, Bootstrap). Wired to the feishu clients via
  dependency injection.
- **Feishu clients** (`src/mcp_memory/feishu/`) — thin subprocess
  wrappers around `lark-cli`. We dropped the Python `lark-oapi` SDK
  in favor of the CLI so we get OAuth + retries from a single
  cross-language surface.
- **Local cache** (`src/mcp_memory/storage/`) — SQLite (FTS5) +
  LanceDB. All retrieval reads from here; sync reconciles outward.

For a deeper dive, see [docs/architecture.md](docs/architecture.md)
(placeholder — see `src/mcp_memory/server.py` and the service layer).

## Development

```bash
git clone https://github.com/your-org/feishu-memory-mcp
cd feishu-memory-mcp
pip install -e ".[dev]"
pytest                 # full suite
pytest tests/test_setup.py  # just the install-deps tests
ruff check src tests
mypy src
```

## License

MIT. See `LICENSE` (TBD).