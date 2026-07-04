# Deployment Guide

This walks through installing and running `feishu-memory-mcp` from
scratch on a fresh machine. The order matters: each step depends on
the previous.

## 0. Prerequisites

| What | Why | How to verify |
|------|-----|---------------|
| Python 3.11+ | runtime | `python --version` |
| pip | install | `pip --version` |
| Node.js 18+ | runs `lark-cli` (npm package) | `node --version` |
| npm | installs `lark-cli` | `npm --version` |
| A Feishu app | backend | https://open.feishu.cn/app |
| Two Feishu Bitables | one for memory, one for knowledge | https://open.feishu.cn/base |

> **Don't have Node.js?** The `feishu-memory install-deps` helper will
> tell you where to get it (<https://nodejs.org>).

## 1. Install the Python package

```bash
# from a clone (development)
git clone https://github.com/junqiu/feishu-memory-mcp.git
cd feishu-memory-mcp
pip install -e ".[dev]"

# or install the published wheel
pip install feishu-memory-mcp
```

Verify:
```bash
feishu-memory --help
# Should print usage with 9 subcommands:
#   init, install-deps, serve, doctor, sync, status, schema, migrate, version
```

## 2. Install lark-cli (the Feishu backend)

```bash
feishu-memory install-deps
```

This:
1. Detects whether Node.js / npm are present.
2. Skips if `lark-cli` is already on `PATH`.
3. Otherwise runs `npm install -g @larksuite/cli`.

Verify:
```bash
lark-cli --version
# Expected: lark-cli version 1.0.x
```

## 3. Authorize lark-cli with your Feishu app

```bash
lark-cli config init
```

This is **interactive** — it prints a verification URL. Open it in a
browser, complete the OAuth flow, then return to your terminal.
The CLI caches the resulting tokens.

## 4. Create two Feishu Bitables

In the Feishu UI (<https://open.feishu.cn/base>), create two Bitables:

- `agent-memory` — for agent-generated records (your agents write here)
- `personal-knowledge` — for human-curated knowledge

Each Bitable needs the same **16 fields** (v2 types). The
`feishu-memory init` helper will auto-create them. Or use this exact
field list:

| Field name | Type | Notes |
|------------|------|-------|
| `source` | `select` | options: `agent_add`, `feishu_doc`, `feishu_bitable`, `feishu_drive_file`, `feishu_wiki` |
| `title` | `text` | |
| `preview` | `text` (long) | first ~200 chars for UI |
| `content_ref_type` | `select` | options: `docx`, `bitable`, `drive_file`, `wiki` |
| `content_ref_token` | `text` | |
| `content_ref_url` | `text` (url style) | |
| `content_hash` | `text` | sha256 of the record content |
| `feishu_last_modified` | `number` | version number |
| `tags` | `select` (`multiple: true`) | option: `untagged` (extend as needed) |
| `source_user` | `text` | open_id of human user |
| `source_agent` | `text` | agent_id |
| `origin` | `select` | options: `manual`, `auto_sync` |
| `extra_json` | `text` (long) | JSON dump of extra metadata |
| `text_empty` | `checkbox` | whether `text` field is empty |
| `created_at` | `datetime` | format: `yyyy-MM-dd HH:mm` |
| `updated_at` | `datetime` | format: `yyyy-MM-dd HH:mm` |

After creating the two Bitables, capture for each:
- **App token** (from the Bitable URL — looks like `bascnXXXX...`)
- **Table ID** (looks like `tblXXXX...`)

## 5. Configure `.env`

The CLI auto-loads `.env` from any of:
- `$PWD/.env`
- `~/.feishu-memory/.env`
- `/etc/feishu-memory/.env`

Create one of these with your credentials:

```bash
FEISHU_APP_ID=cli_xxxxxxxxxxxx
FEISHU_APP_SECRET=...
MEMORY_BITABLE_APP_TOKEN=bascn...
MEMORY_BITABLE_TABLE_ID=tbl...
KNOWLEDGE_BITABLE_APP_TOKEN=bascn...
KNOWLEDGE_BITABLE_TABLE_ID=tbl...
AGENT_ID=default
DATA_DIR=./.feishu_memory

# Embedding model — see docs/installation.md §4.5 for the full comparison.
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
# Set HF_TOKEN to ~5x faster model downloads (free at huggingface.co/settings/tokens):
# HF_TOKEN=hf_xxxxxxxx
```

Tip: keep the file permissions tight: `chmod 600 .env`.

## 6. Verify

```bash
feishu-memory doctor
```

Expected output (all 6 checks pass):

```
feishu-memory doctor
==================================================
  [OK] Config loads: agent_id=cli_xxxxxx
  [OK] Package importable: version 0.1.0
  [OK] Local data dir writable: ...
  [OK] Node.js runtime: v20.x.x
  [OK] npm: 10.x.x
  [OK] lark-cli: 1.0.x
==================================================
All hard checks passed (6 checks total)
```

If any check fails, the hint next to it points at the fix (e.g. install
Node.js, set the missing env var).

## 7. First sync (pulls from Bitable → local cache + LanceDB)

```bash
feishu-memory sync --mode incremental --scope memory
```

First run takes longer because the embedding model downloads
(~30s for the default `all-MiniLM-L6-v2`, ~30+ min unauthenticated
for `BAAI/bge-m3`; ~5 min with `HF_TOKEN`).

Expected output:

```
feishu-memory sync --mode incremental --scope memory
==================================================
  memory: mode=incremental added=19 updated=0 deleted=0 errors=0
```

## 8. Confirm cache state

```bash
feishu-memory status
```

Should show:
- `Memory cache: 19 records (initialized)`
- `Last sync: 1783...`
- `Vector index: .feishu_memory/vectors_memory.lance (xxx,xxx bytes)`

## 9. Start the MCP server (for your agent to connect)

```bash
feishu-memory serve
```

The server uses **stdio** transport (the MCP standard). Your agent
launches it as a subprocess. Configure your MCP client like:

```json
{
  "mcpServers": {
    "feishu-memory": {
      "command": "feishu-memory",
      "args": ["serve"],
      "env": {
        "FEISHU_APP_ID": "...",
        "FEISHU_APP_SECRET": "...",
        "MEMORY_BITABLE_APP_TOKEN": "...",
        "MEMORY_BITABLE_TABLE_ID": "...",
        "KNOWLEDGE_BITABLE_APP_TOKEN": "...",
        "KNOWLEDGE_BITABLE_TABLE_ID": "..."
      }
    }
  }
}
```

You can omit the `env` block if your client launches from a working
directory that has a `.env` file (the CLI loads it automatically).

The server registers 8 tools (see
[docs/tool-reference.md](tool-reference.md)): `memory_add`,
`memory_query` (4 modes), `memory_get`, `memory_update`,
`memory_delete`, `memory_list`, `memory_count`, `memory_sync` (3
modes). Each tool accepts a `scope` parameter (`memory` / `knowledge`).

## 10. Cron sync (optional)

Add to your crontab for periodic re-sync:

```cron
# Every 30 minutes
*/30 * * * * cd /path/to/feishu-memory-mcp && feishu-memory sync --mode incremental --scope memory
```

## 11. Upgrade to a better embedding model (optional)

The default `all-MiniLM-L6-v2` works without `HF_TOKEN` but is
English-leaning. For Chinese-heavy corpora:

```bash
# 1. Get an HF token (free): https://huggingface.co/settings/tokens
export HF_TOKEN=hf_xxxxx

# 2. Switch model
echo 'EMBEDDING_MODEL=BAAI/bge-m3' >> .env

# 3. Wipe + re-sync (different model = different dimension)
feishu-memory migrate
feishu-memory sync --mode incremental --scope memory
```

The first `feishu-memory sync` after switching may take 5+ minutes
(downloading 2.3 GB).

See [docs/installation.md §4.5](installation.md#45-embedding-model-selection)
for the full model comparison table.

## Day-to-day

```bash
# Check health
feishu-memory doctor

# Check cache + sync state
feishu-memory status

# Manual sync (or wait for cron)
feishu-memory sync --mode incremental --scope memory

# Verify Bitable schema matches the spec
feishu-memory schema --verify

# Wipe local cache and re-import from Bitable
# (e.g. after model change, or cache corruption)
feishu-memory migrate
feishu-memory sync --mode rebuild --scope both
```

## Where the data lives

| Path | Contents |
|------|----------|
| `.feishu_memory/local_cache_memory.sqlite` | metadata cache, FTS5 index, sync state |
| `.feishu_memory/local_cache_knowledge.sqlite` | (if knowledge scope is used) |
| `.feishu_memory/vectors_memory.lance/` | vector embeddings (LanceDB) |
| `~/.cache/huggingface/hub/` | downloaded embedding models (HF cache) |
| `~/.lark-cli/config.json` | lark-cli's OAuth tokens (after `lark-cli config init`) |

**Feishu Bitable** is the source of truth. To migrate the project
to a new machine, copy the `.feishu_memory/` cache OR re-sync from
Bitable. The Feishu app credentials must be present; the embedding
model re-downloads on first run.

## Multi-machine / multi-agent

The recommended pattern: **one `feishu-memory serve` process per
agent** (or per worktree). They all share the same Feishu Bitable
(write-path is Feishu-first, so writes coordinate) and may share the
same `.feishu_memory/` cache dir **only** if you have a single-writer
model. The safe pattern is to give each agent its own `DATA_DIR`:

```bash
# agent 1
DATA_DIR=./.feishu_memory_agent1 feishu-memory serve

# agent 2
DATA_DIR=./.feishu_memory_agent2 feishu-memory serve
```

Both agents will read and write the same Feishu Bitables (they're
coordinated there), but their local caches are independent.

**Don't run multiple instances pointing to the same `DATA_DIR`** —
SQLite locking will cause data races. The CLI `doctor` doesn't
catch this; it's a documented constraint.

## Updating

```bash
# 1. Pull latest
git pull

# 2. Reinstall Python package
pip install -e ".[dev]"

# 3. Update lark-cli
npm install -g @larksuite/cli@latest

# 4. Re-sync (in case schema changed)
feishu-memory migrate   # wipes local; re-imports from Bitable
feishu-memory sync --mode rebuild --scope both

# 5. Verify
feishu-memory doctor
feishu-memory test
```

## Uninstalling

```bash
pip uninstall feishu-memory-mcp
npm uninstall -g @larksuite/cli
rm -rf .feishu_memory/        # local cache + LanceDB
rm -rf ~/.lark-cli/             # lark-cli OAuth tokens + config
```
