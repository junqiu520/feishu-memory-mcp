# Installation

`feishu-memory-mcp` is a Python MCP server that uses **lark-cli** (npm
package `@larksuite/cli`) as its Feishu backend. Installing it is a
two-step process: install the Python package, then make sure the
`lark-cli` binary is on `PATH`.

## 1. Python package

```bash
pip install feishu-memory-mcp
```

(Or, for development: `pip install -e .` from a clone.)

## 2. System dependency: lark-cli

`feishu-memory-mcp` shells out to **lark-cli**, which requires
**Node.js >= 18** on `PATH`. The easiest path is to let
`feishu-memory` install it for you:

```bash
feishu-memory install-deps
```

This will:

1. Detect Node.js / npm availability
2. Skip if lark-cli is already installed
3. Otherwise run `npm install -g @larksuite/cli` to install lark-cli
   globally

If Node.js itself is missing, the command prints a clear pointer to
<https://nodejs.org/en/download/> instead of trying to install it.

### Manual install (alternative)

If you'd rather set things up yourself:

```bash
# 1. Install Node.js (>= 18 LTS) from https://nodejs.org
# 2. Install lark-cli globally:
npm install -g @larksuite/cli

# 3. Verify:
lark-cli --version
# Expected output: lark-cli version 1.0.x
```

### What `install-deps` actually does

| Step | Probe / Command                              | Why                                    |
|------|----------------------------------------------|----------------------------------------|
| 1    | `shutil.which("node")` + `node --version`    | Confirm Node.js >= 18 is installed     |
| 2    | `shutil.which("npm")` + `npm --version`      | Confirm npm is available               |
| 3    | `shutil.which("lark-cli")` + version parse   | Skip install if already present        |
| 4    | `npm install -g @larksuite/cli`              | Install lark-cli globally              |

All probes are best-effort: a missing binary or a failing `--version`
call never raises — the helper just reports `NOT FOUND` and moves on.
The git repo for lark-cli is
<https://github.com/larksuite/cli>.

## 3. Authorize lark-cli

After lark-cli is on `PATH`, authorize it with your Feishu app:

```bash
lark-cli config init
```

This will print a verification URL. Open it in a browser and complete
the OAuth flow there. Once authorized, lark-cli will cache its tokens
and `feishu-memory` can call into it transparently.

## 4. Configure feishu-memory-mcp

Set the required environment variables (or equivalent entries in a
`.env` file in your working directory):

```bash
FEISHU_APP_ID=cli_xxxxxxxxxxxx
FEISHU_APP_SECRET=...
MEMORY_BITABLE_APP_TOKEN=bascnxxxxxxxxxxxx
MEMORY_BITABLE_TABLE_ID=tblxxxxxxxxxxxxxxxx
KNOWLEDGE_BITABLE_APP_TOKEN=bascnyyyyyyyyyyyy
KNOWLEDGE_BITABLE_TABLE_ID=tblyyyyyyyyyyyyy
```

Get the app credentials from <https://open.feishu.cn/app>. The two
Bitable tokens come from the URLs of the Bitables you create for
memory and knowledge, respectively.

## 4.5 Embedding model selection

`feishu-memory-mcp` uses `sentence-transformers` for embedding. The
default is the **smallest, fastest** model that still works for our
retrieval use case, so the project is runnable out of the box on any
machine. For production / best quality, swap to a larger model.

| Model | Size | Dim | Quality | First download | Notes |
|-------|------|-----|---------|----------------|-------|
| `sentence-transformers/all-MiniLM-L6-v2` (default) | 80MB | 384 | OK | ~30s | English-focused; works without HF_TOKEN |
| `BAAI/bge-small-en-v1.5` | 33MB | 384 | Good | ~15s | English-only, faster than MiniLM |
| `BAAI/bge-m3` | 2.3GB | 1024 | **Best** (multilingual) | ~30+ min unauthenticated, ~5 min with `HF_TOKEN` | Recommended for Chinese / multilingual memory |
| `BAAI/bge-large-en-v1.5` | 1.3GB | 1024 | Excellent (English) | ~10 min unauth | Large English |
| `intfloat/multilingual-e5-base` | 1GB | 768 | Strong multilingual | ~5 min with `HF_TOKEN` | Good Chinese/English balance |

### Switching the embedding model

Set the model name in `.env` (or `Config` directly):

```bash
# .env
EMBEDDING_MODEL=BAAI/bge-m3
```

Then restart `feishu-memory serve` so the model loads fresh. The
local cache (`local_cache_*.sqlite`) and the LanceDB vector index
(`vectors_*.lance`) **must be re-synced** after switching model because
the embedding dimension changes — running `feishu-memory migrate`
will wipe local and re-sync from Bitable.

### Speeding up downloads with HF_TOKEN

Anonymous requests to `huggingface.co` are rate-limited (~50 KB/s
on the public hub, often hangs on large model weights). To go 5–10×
faster, get a free read-only token from
<https://huggingface.co/settings/tokens> and set:

```bash
# Linux / macOS
export HF_TOKEN=hf_xxxxxxxxxxxx

# Windows PowerShell
$env:HF_TOKEN = "hf_xxxxxxxxxxxx"
```

The token is read by `huggingface_hub` at first model load. No code
changes needed.

### Embedding dimension and local cache compatibility

Different models produce different dimensions. The local LanceDB index
stores embeddings as `list[float32(N)`, so when you switch to a model
with a different `N` you must run `feishu-memory migrate` to clear the
old index. The Bitable records themselves are model-agnostic — only
the local vector store is dimension-sensitive.

## 5. Verify

```bash
feishu-memory doctor
```

`doctor` runs a battery of checks. All should pass:

- `Config loads` (warns until env vars are set)
- `Package importable`
- `Local data dir writable`
- `Node.js runtime`
- `npm`
- `lark-cli`

If any of the last three are missing, follow the hint printed next to
the failure (install Node.js, or run `feishu-memory install-deps`).

## Platforms

| OS      | Notes                                                                                            |
|---------|--------------------------------------------------------------------------------------------------|
| macOS   | Standard `npm install -g` works. On Apple Silicon, no special config needed for lark-cli 1.0.x.  |
| Linux   | Standard. `sudo` may be needed if the npm prefix is system-wide (see Troubleshooting below).     |
| Windows | Tested on Windows 10 / 11 with Node.js 20 LTS. No admin needed if Node was installed per-user.   |

## Troubleshooting

### "lark-cli not found" after `install-deps` succeeded

Check `npm config get prefix` and ensure the resulting `bin/` (or
`bin/` equivalent) is on `PATH`:

```bash
npm config get prefix
# macOS / Linux:
export PATH="$(npm config get prefix)/bin:$PATH"
# Windows (PowerShell):
$env:Path = "$(npm config get prefix);$env:Path"
```

Add the export line to your shell rc (`~/.zshrc`, `~/.bashrc`) to make
it persistent. Alternatively, set `LARK_CLI_PATH` env var to the full
path of the `lark-cli` binary.

### `npm install` fails with `EACCES` (Linux / macOS)

The npm prefix is owned by another user. Either:

```bash
sudo npm install -g @larksuite/cli
```

…or fix the prefix to be user-writable:

```bash
mkdir -p ~/.npm-global
npm config set prefix '~/.npm-global'
export PATH="$HOME/.npm-global/bin:$PATH"
npm install -g @larksuite/cli
```

### Corporate firewall / proxy blocking npm

Configure npm to use your corporate registry mirror:

```bash
npm config set registry https://your-internal-mirror/
```

### `lark-cli --version` prints ANSI color codes

The version parser in `mcp_memory.setup` strips non-digits using a
regex (`\d+\.\d+\.\d+`), so color codes don't affect version
detection. If you see the raw colored output, that means lark-cli is
working correctly; the helpers only fail to extract a version when
the output genuinely has no semver pattern.

## Source code

- `feishu-memory-mcp` Python: <https://github.com/your-org/feishu-memory-mcp>
- `lark-cli` (npm package): <https://github.com/larksuite/cli>