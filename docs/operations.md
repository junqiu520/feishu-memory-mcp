# Operations

This document is for people running `feishu-memory-mcp` in a long-lived
setup — daily CLI work, cron jobs, self-hosted agents, debugging a broken
install.

For first-time install and configuration, see
[`docs/installation.md`](installation.md). For architecture and design
rationale, see [`docs/architecture.md`](architecture.md).

## Sync strategy

There are three sync modes. Each is exposed through both the CLI
(`feishu-memory sync --mode … --scope …`) and the `memory_sync` MCP tool.

### `incremental` (default for daily use)

Pulls records whose `updated_at` is greater than `sync_state.last_sync_at`,
embeds any changed text, deletes anything locally that disappeared
remotely. Cost is proportional to the **number of records changed since
the last sync**, not the total — so it stays cheap on large libraries.

Use this:

- As a daily cron (`feishu-memory sync --mode incremental`).
- After `memory_update` (which does not change `updated_at`, but if you've
  been editing the Bitable in the Feishu UI you want to pull those edits).
- On server startup if `FEISHU_MEMORY_AUTO_SYNC=true` (default).

### `full`

Pulls **every** record from Feishu and diffs against local. Cheap on a
small library, expensive on a large one. Use this:

- After a long absence on a busy library, instead of running N
  incrementals.
- After a Bitable-side bulk operation (e.g., a CSV import).
- When you suspect `sync_state` drift, but rebuilding is overkill.

`full` preserves local data; it only adds/updates/removes the diff.

### `rebuild`

Physically wipes `data_dir/local_cache_*.sqlite` and
`data_dir/vectors_*.lance`, then re-imports everything from Feishu.

Use this **only** when:

- Local cache is corrupted (you see `SQLite database disk image is
  malformed`, embeddings return nonsense, etc.).
- You changed the embedding model and want to re-embed everything (note:
  this is the only way to do so currently).
- You're debugging and want a deterministic baseline.

`rebuild` is safe to run — it does not touch Feishu data. It does,
however, re-downloads everything, so on a 10k-record library expect
several minutes.

### Mode comparison

| Mode          | Reads from Feishu | Writes locally | Re-embeds | Time cost          | Use case                          |
|---------------|-------------------|----------------|-----------|--------------------|-----------------------------------|
| `incremental` | Records changed since `last_sync_at` | Yes | Only changed text | Seconds–minutes | Daily use, cron                   |
| `full`        | All records       | Yes (diff)      | Only changed text | Minutes | Catch-up after long absence       |
| `rebuild`     | All records       | Yes (drop+fill) | All text  | Minutes (longest)  | Cache corruption, model changes   |

## Local cache and disaster recovery

The local cache **is disposable**. Feishu owns the truth.

```
data_dir/                          (default: ./.feishu_memory)
├── local_cache_memory.sqlite      # records + tags + sync_state + FTS5
├── local_cache_knowledge.sqlite   # same, knowledge scope
├── vectors_memory.lance/          # LanceDB bge-m3 vectors
└── vectors_knowledge.lance/       # same, knowledge scope
```

To recover from a corrupted cache or a fresh machine:

1. **Stop the MCP server** (Ctrl-C in your client).
2. **Optionally delete the data dir**:
   ```bash
   rm -rf .feishu_memory/
   ```
3. **Restart** with `feishu-memory serve`. With
   `FEISHU_MEMORY_AUTO_SYNC=true` (default), the server runs
   `incremental` on the first boot — which, given there's no
   `last_sync_at`, behaves exactly like `full`.

You won't lose data. The only loss is the embedding work — which is
recomputed automatically.

## Multi-instance constraint

**Do not run multiple MCP instances on the same machine pointing at the
same Feishu tenant.**

Why:

- Each instance writes to its own `data_dir` (default
  `./.feishu_memory/`).
- Local SQLite + LanceDB are not coordinated across instances.
- Two processes calling `memory_add` concurrently will end up with two
  local caches that each need re-syncing.

If you need parallel agents, run **one** MCP server with multiple
connected agent clients. The `AppContext` is built to handle concurrent
tool calls.

If you accidentally start two, you'll see the second one's `memory_query`
return stale results and will keep "discovering" records the first
instance just added. Stop one of them.

## Multi-device setups

`feishu-memory-mcp` is **not** real-time-synced across machines. Each
machine has its own data_dir; sync is pull-based on demand.

Pattern:

- Laptop writes a memory (`memory_add`).
- Desktop doesn't see it until it runs `memory_sync(mode="incremental")`.
- Trigger this manually (`memory_sync` MCP tool), via cron, or rely on
  server startup auto-sync (`FEISHU_MEMORY_AUTO_SYNC=true`).

If you want near-real-time cross-device sync, point both machines at the
same Feishu tenant and run `memory_sync` on a short cron interval (5–15
minutes). Anything stricter means a real-time event hook (out of scope
for this project; see spec §14.1).

## Cache maintenance

When does each layer need cleaning?

| Layer            | File                              | When to clear                              |
|------------------|-----------------------------------|--------------------------------------------|
| SQLite cache     | `local_cache_*.sqlite`            | Corruption; before/after schema migration. Auto-rebuilt by `memory_sync` on startup. |
| FTS5 index       | (inside the SQLite file)          | Same as SQLite — triggers keep it consistent. Manual `INSERT INTO records_fts(records_fts) VALUES('rebuild')` if FTS5 drift is suspected. |
| LanceDB vectors  | `vectors_*.lance/`                | After embedding-model change; cache corruption. `memory_sync(mode="rebuild")` re-embeds. |
| HuggingFace cache| `~/.cache/huggingface/`           | Disk space. Safe to delete; re-downloads on next server start. |

A `rebuild` is the canonical reset: it wipes `records`, `record_tags`,
`records_fts` (by table recreation through the schema) and the LanceDB
tables, and re-imports. Nothing in Feishu is touched.

## Token / auth refresh

`lark-cli` manages its own tenant token cache after
`lark-cli config init`. Our `LarkCliRunner` (in
[`src/mcp_memory/feishu/runner.py`](../src/mcp_memory/feishu/runner.py))
does **not** see the Feishu app secret — the secret lives in lark-cli's
config and is used internally. We pass `--as bot` by default.

If you see `LarkCliError: token expired` or `401 Unauthorized`:

1. Re-run `lark-cli config init` (refreshes the cached token).
2. Verify with `lark-cli auth status` (or whatever lark-cli's check
   subcommand is in your version).
3. Restart the MCP server so the next call gets the refreshed token.

## Troubleshooting

### `feishu-memory doctor`

```
feishu-memory doctor
==================================================
  [OK] Config loads: agent_id=default
  [OK] Package importable: version 0.1.0
  [OK] Local data dir writable: …
  [WARN] Node.js runtime: 18.17.0 (>= 18 LTS)
  [OK] npm: 9.6.7
  [FAIL] lark-cli: not installed; run `feishu-memory install-deps`
==================================================
FAILED: 1 hard failure(s)
```

Status meanings:

| Status    | Meaning                                                        |
|-----------|----------------------------------------------------------------|
| `[OK]`    | Check passed.                                                  |
| `[WARN]`  | Soft failure (e.g., config env vars not yet set). Tool runs.   |
| `[FAIL]`  | Hard failure. The corresponding feature is unusable until fixed. |

Exit code:

- `0` if no hard failures (warnings are OK).
- `1` if any hard failure.

### Common error messages

| Symptom                                              | Likely cause                                  | Fix                                                                                             |
|------------------------------------------------------|-----------------------------------------------|-------------------------------------------------------------------------------------------------|
| `lark-cli not found at 'lark-cli'`                   | npm global bin not on `PATH`, or `lark-cli` not installed. | Run `feishu-memory install-deps`. On Linux/macOS, `echo $PATH` to confirm `npm config get prefix/bin` is present. |
| `Bitable schema mismatch`                            | Bitable was edited by hand and lost required fields. | Run `feishu-memory schema --verify`. Then `feishu-memory migrate` to add missing fields. Or recreate from the template. |
| `scope must be 'memory' or 'knowledge'`              | Tool called with `scope="something-else"` (or a typo). | Check the calling agent. Valid values: `"memory"` (default) and `"knowledge"`.                  |
| `record not found` from `memory_get` / `memory_update` / `memory_delete` | Either wrong `record_id` or the record exists in the other scope. | Try once per scope. Or search: `memory_query(query=<hint>)` to locate the right `record_id`. |
| `confirm_required` from `memory_delete`              | Caller forgot `confirm: true`.                | Re-call with `confirm: true`.                                                                   |
| `text length > 100K`                                  | Trying to add more than 100K chars at once.  | Split into multiple `memory_add` calls, or embed a `file_ref` and split text into chunks yourself. |
| Token errors (401, "invalid_access_token", "token expired") | lark-cli OAuth token expired or revoked.       | Re-run `lark-cli config init`. Restart the MCP server.                                          |

### Logs

Logs go to **stderr** by default (intentional: MCP uses stdout for
protocol). Levels:

| Env var                              | Default | Effect                                                |
|--------------------------------------|---------|-------------------------------------------------------|
| `FEISHU_MEMORY_LOG_LEVEL` (or unset)| `INFO`  | Standard logs of every Feishu call (with truncated bodies) and sync progress. |
| `FEISHU_MEMORY_DEBUG=1`              | unset   | Verbose: payload previews, retry attempts, lark-cli stdio traces. |

Set `FEISHU_MEMORY_DEBUG=1` before reproducing any sync / add error —
the resulting trace is usually enough to identify the failing bitable
field or scope mismatch.

### When all else fails

1. Re-run `feishu-memory doctor` to confirm the four hard checks pass.
2. Run `memory_sync(mode="full")` once. If that resolves it, it was a
   cache drift; subsequent `incremental` will stay healthy.
3. As a last resort, `memory_sync(mode="rebuild")`.
4. None of the above will touch Feishu data — Feishu is the source of
   truth, locally we can only ever lose cache, never records.

## CLI quick reference

```
feishu-memory init            # Print env-var template (run-once setup)
feishu-memory install-deps    # Detect Node.js + install lark-cli
feishu-memory serve           # Start the MCP server (stdio)
feishu-memory doctor          # Diagnostics
feishu-memory sync            # Manually trigger sync
feishu-memory status          # Local cache + sync state
feishu-memory schema          # Dump / verify Bitable schema
feishu-memory migrate         # Rebuild Bitable schema (upgrade)
feishu-memory version         # Print version
```

Every subcommand accepts `--help`. The CLI exposes only operations —
agent-driven `add`/`query`/`get`/etc. should go through MCP.
