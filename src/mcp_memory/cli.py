"""CLI entry — Stage 7 implements all 9 subcommands (agent-first, ops-only).

Usage:
  feishu-memory init          # interactive configuration
  feishu-memory install-deps  # detect + install Node.js/lark-cli dependency
  feishu-memory serve         # start MCP server (stdio)
  feishu-memory doctor        # diagnostics
  feishu-memory sync          # trigger sync manually
  feishu-memory status        # show local cache status
  feishu-memory schema        # dump/verify Bitable schema
  feishu-memory migrate       # rebuild Bitable schema (upgrade)
  feishu-memory version       # version
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from mcp_memory import __version__


def _load_env_file() -> None:
    """Best-effort .env load so 'feishu-memory' works from any cwd.

    Tries in order: cwd/.env → ~/.feishu-memory/.env → /etc/feishu-memory/.env.
    Silently does nothing if python-dotenv is not installed or no .env is found.
    """
    try:
        from dotenv import load_dotenv
    except ImportError:
        return

    candidates = [
        Path.cwd() / ".env",
        Path.home() / ".feishu-memory" / ".env",
        Path("/etc/feishu-memory/.env"),
    ]
    for p in candidates:
        if p.is_file():
            load_dotenv(p, override=False)
            return


_load_env_file()

log = logging.getLogger(__name__)


def _build_services_for_scope(scope: str):
    """Build a wired-up SyncService for the given scope ('memory' or 'knowledge').

    Returns (SyncService, Config) or raises an error if config is missing
    the required Bitable credentials for that scope.
    """
    from mcp_memory.config import Config
    from mcp_memory.feishu.runner import LarkCliRunner
    from mcp_memory.feishu.bitable import BitableClient
    from mcp_memory.storage.local_cache import LocalCache
    from mcp_memory.storage.paths import local_cache_path
    from mcp_memory.index.embedding_engine import EmbeddingEngine
    from mcp_memory.index.vector_index import LanceVectorIndex
    from mcp_memory.services.sync_service import SyncService

    cfg = Config(_env_file=None)  # type: ignore[call-arg]

    if scope == "memory":
        app_token = cfg.memory_bitable_app_token
        table_id = cfg.memory_bitable_table_id
    elif scope == "knowledge":
        app_token = cfg.knowledge_bitable_app_token
        table_id = cfg.knowledge_bitable_table_id
    else:
        raise ValueError(f"scope must be 'memory' or 'knowledge', got {scope!r}")

    runner = LarkCliRunner()
    bitable = BitableClient(runner, app_token, table_id)
    cache = LocalCache(local_cache_path(cfg.data_dir, scope), scope=scope)
    embedding = EmbeddingEngine(model_name=cfg.embedding_model, device=cfg.device)
    vector = LanceVectorIndex(_lance_path(cfg.data_dir, scope), scope=scope)
    sync = SyncService(
        local_cache=cache,
        bitable_client=bitable,
        embedding_engine=embedding,
        vector_index=vector,
        scope=scope,
    )
    return sync, cfg


def _lance_path(data_dir, scope):
    from mcp_memory.storage.paths import lance_path
    return lance_path(data_dir, scope)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="feishu-memory",
        description="feishu-memory-mcp: Feishu-backed RAG for LLM agents",
    )
    sub = parser.add_subparsers(dest="command", required=False)

    sub.add_parser("init", help="interactive configuration (create config.toml)")
    sub.add_parser(
        "install-deps",
        help="detect Node.js / npm and install lark-cli globally",
    )
    sub.add_parser("serve", help="start MCP server (stdio)")
    sub.add_parser("doctor", help="diagnose connectivity and local cache")

    p_sync = sub.add_parser("sync", help="trigger sync manually")
    p_sync.add_argument(
        "--mode",
        choices=["incremental", "full", "rebuild"],
        default="incremental",
        help="sync mode",
    )
    p_sync.add_argument(
        "--scope",
        choices=["memory", "knowledge", "both"],
        default="memory",
        help="which scope to sync",
    )

    sub.add_parser("status", help="show local cache + sync state")

    p_schema = sub.add_parser("schema", help="dump/verify Bitable schema")
    p_schema.add_argument("--verify", action="store_true", help="verify schema only")

    sub.add_parser("migrate", help="rebuild Bitable schema (upgrade)")
    sub.add_parser("version", help="print version and exit")

    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command is None:
        print(__version__)
        return 0

    dispatch = {
        "version": lambda: (_print_version(), 0)[1],
        "init": _cmd_init,
        "install-deps": _cmd_install_deps,
        "serve": _cmd_serve,
        "doctor": _cmd_doctor,
        "sync": lambda: _cmd_sync(args),
        "status": _cmd_status,
        "schema": lambda: _cmd_schema(args),
        "migrate": _cmd_migrate,
    }

    handler = dispatch.get(args.command)
    if handler is None:
        parser.print_help()
        return 1
    return int(handler())


def _print_version() -> None:
    print(__version__)


def _cmd_init() -> int:
    """Interactive configuration with template + optional Bitable schema setup.

    Flow:
      1. Verify lark-cli is installed (else exit 1 with install-deps hint).
      2. Print the env-var template the user needs to set.
      3. If MEMORY_* / KNOWLEDGE_* env vars are set, best-effort call
         ``ensure_bitable_schema()`` for each so the user doesn't have to
         add every column manually in the Feishu UI.
      4. Recommend running ``feishu-memory doctor`` next.
    """
    import asyncio
    import os

    from mcp_memory.feishu.runner import LarkCliRunner
    from mcp_memory.setup import check_status, ensure_bitable_schema

    status = check_status()
    if not status.lark_cli_installed:
        print("feishu-memory init")
        print("=" * 50)
        print("lark-cli is not installed.")
        print()
        print("Step 1: Install the lark-cli system dependency:")
        print("  feishu-memory install-deps")
        print()
        print("Step 2: Authorize lark-cli with your Feishu app:")
        print("  lark-cli config init")
        print()
        print("Step 3: Re-run `feishu-memory init` for the config template.")
        return 1

    print("feishu-memory init")
    print("=" * 50)
    print()
    print("Step 1: Set environment variables (or write config.toml):")
    print("  FEISHU_APP_ID=cli_xxxxxxxxxxxxxxxx")
    print("  FEISHU_APP_SECRET=...")
    print("  MEMORY_BITABLE_APP_TOKEN=bascnxxxxxxxxxxxx")
    print("  MEMORY_BITABLE_TABLE_ID=tblxxxxxxxxxxxx")
    print("  KNOWLEDGE_BITABLE_APP_TOKEN=bascnyyyyyyyyyyyy")
    print("  KNOWLEDGE_BITABLE_TABLE_ID=tblyyyyyyyyyyyy")
    print()
    print("Step 2: Create the two Bitables in Feishu UI first.")
    print("  - Go to https://open.feishu.cn/base")
    print("  - Create two Bitables (one for memory, one for knowledge)")
    print("  - Copy each one's app_token + table_id into the env vars above")
    print()

    memory_token = os.environ.get("MEMORY_BITABLE_APP_TOKEN")
    memory_table = os.environ.get("MEMORY_BITABLE_TABLE_ID")
    knowledge_token = os.environ.get("KNOWLEDGE_BITABLE_APP_TOKEN")
    knowledge_table = os.environ.get("KNOWLEDGE_BITABLE_TABLE_ID")

    if memory_token and memory_table:
        print("Step 3: Ensuring Bitable schema for memory library...")
        try:
            runner = LarkCliRunner()
            result = asyncio.run(
                ensure_bitable_schema(runner, memory_token, memory_table, scope_label="memory")
            )
            print(
                f"  memory: created {len(result['created'])} fields, "
                f"already had {len(result['existing'])}, "
                f"errors {len(result['errors'])}"
            )
            for f in result["created"]:
                print(f"    + {f}")
            for err in result["errors"]:
                print(f"    ! {err}")
        except Exception as e:
            print(f"  memory: setup skipped — {e}")
    else:
        print(
            "Step 3: (skipped) set MEMORY_BITABLE_APP_TOKEN + MEMORY_BITABLE_TABLE_ID "
            "to auto-create the schema."
        )

    if knowledge_token and knowledge_table:
        print("Step 4: Ensuring Bitable schema for knowledge library...")
        try:
            runner = LarkCliRunner()
            result = asyncio.run(
                ensure_bitable_schema(runner, knowledge_token, knowledge_table, scope_label="knowledge")
            )
            print(
                f"  knowledge: created {len(result['created'])} fields, "
                f"already had {len(result['existing'])}, "
                f"errors {len(result['errors'])}"
            )
            for f in result["created"]:
                print(f"    + {f}")
            for err in result["errors"]:
                print(f"    ! {err}")
        except Exception as e:
            print(f"  knowledge: setup skipped — {e}")
    else:
        print(
            "Step 4: (skipped) set KNOWLEDGE_BITABLE_APP_TOKEN + KNOWLEDGE_BITABLE_TABLE_ID "
            "to auto-create the schema."
        )

    print()
    print("Step 5: Run `feishu-memory doctor` to verify.")
    print("Step 6: Run `feishu-memory serve` to start.")
    return 0


def _cmd_install_deps() -> int:
    """Detect Node.js/npm and install lark-cli globally via npm.

    Behavior:
      - If lark-cli is already installed -> exit 0 with a "nothing to do" line.
      - If Node.js is missing -> exit 1 with a pointer to https://nodejs.org.
      - Otherwise -> run `npm install -g @larksuite/cli` and report result.
    """
    from mcp_memory.setup import check_status, install_lark_cli

    print("feishu-memory install-deps")
    print("=" * 50)

    status = check_status()

    print(f"OS:                {sys.platform}")
    print(f"Node.js:           {status.node_version or 'NOT FOUND'}")
    print(f"npm:               {status.npm_version or 'NOT FOUND'}")
    print(f"lark-cli:          {status.lark_cli_version or 'NOT FOUND'}")
    if status.lark_cli_path:
        print(f"lark-cli path:     {status.lark_cli_path}")
    print()

    if status.lark_cli_installed:
        print("lark-cli already installed. Nothing to do.")
        print("Next step: `lark-cli config init` to authorize with Feishu.")
        return 0

    if not status.node_installed:
        print("Node.js not found.")
        print()
        print("Install Node.js (>= 18 LTS) first:")
        print("  -> Download from https://nodejs.org/en/download/")
        print()
        print("After installing Node.js, re-run `feishu-memory install-deps`.")
        return 1

    print(f"Node.js found ({status.node_version}). Installing lark-cli via npm...")
    print("  Command: npm install -g @larksuite/cli")
    print()

    success, message = install_lark_cli()
    print(message)
    return 0 if success else 1


def _cmd_serve() -> int:
    """Start MCP server with stdio transport.

    Stage 6/7: wiring real services to the server happens in Stage 8. This
    subcommand exits cleanly with an informative note so that
    `feishu-memory --help`, `version`, `doctor`, etc. work today.
    """
    print(
        "[feishu-memory serve] MCP server requires wiring to real services.\n"
        "This command will be active after Stage 8 integration.\n"
        "For now, it exits cleanly so `feishu-memory --help` and friends work.",
        file=sys.stderr,
    )
    return 0


def _cmd_doctor() -> int:
    """Diagnose connectivity + local cache.

    Returns 0 if every check is healthy or has only soft failures (e.g. missing
    env vars in a freshly initialized installation). Returns 1 only on hard
    failures (package import broken, data dir not writable, SDK not installed).
    """
    print("feishu-memory doctor")
    print("=" * 50)

    checks: list[tuple[str, bool, str, bool]] = []  # (name, ok, detail, fatal)
    hard_failed = 0

    try:
        from mcp_memory.config import Config

        cfg = Config(_env_file=None)  # type: ignore[call-arg]
        checks.append(("Config loads", True, f"agent_id={cfg.agent_id}", False))
    except Exception as e:
        # Missing env vars is a soft failure: doctor should still report on the
        # rest of the install even before `feishu-memory init` has been run.
        checks.append(
            (
                "Config loads",
                False,
                f"{e!r} (run 'feishu-memory init' or set FEISHU_* env vars)",
                False,
            )
        )

    try:
        import mcp_memory

        checks.append(("Package importable", True, f"version {mcp_memory.__version__}", False))
    except ImportError as e:
        checks.append(("Package importable", False, str(e), True))

    try:
        from mcp_memory.storage.paths import ensure_data_dir
        import tempfile

        tmp = Path(tempfile.gettempdir()) / "feishu_memory_doctor"
        ensure_data_dir(tmp)
        checks.append(("Local data dir writable", True, str(tmp), False))
    except Exception as e:
        checks.append(("Local data dir writable", False, str(e), True))

    try:
        from mcp_memory.setup import check_status

        dep = check_status()

        if dep.node_installed:
            checks.append((
                "Node.js runtime",
                True,
                dep.node_version or "unknown version",
                False,
            ))
        else:
            checks.append((
                "Node.js runtime",
                False,
                "not found; install from https://nodejs.org (>= 18 LTS)",
                True,
            ))

        if dep.npm_installed:
            checks.append((
                "npm",
                True,
                dep.npm_version or "unknown version",
                False,
            ))
        else:
            checks.append((
                "npm",
                False,
                "not found; bundled with Node.js — reinstall Node.js",
                True,
            ))

        if dep.lark_cli_installed:
            checks.append((
                "lark-cli",
                True,
                dep.lark_cli_version or "installed",
                False,
            ))
        else:
            checks.append((
                "lark-cli",
                False,
                "not installed; run `feishu-memory install-deps`",
                True,
            ))
    except Exception as e:
        checks.append(("lark-cli dependency check", False, str(e), True))

    for name, ok, detail, fatal in checks:
        status = "[OK]" if ok else ("[WARN]" if not fatal else "[FAIL]")
        print(f"  {status} {name}: {detail}")
        if not ok and fatal:
            hard_failed += 1

    print("=" * 50)
    if hard_failed:
        print(f"FAILED: {hard_failed} hard failure(s)")
        return 1
    print(f"All hard checks passed ({len(checks)} checks total, some warnings possible)")
    return 0


def _cmd_sync(args: argparse.Namespace) -> int:
    """Trigger sync manually (real Feishu calls)."""
    print(f"feishu-memory sync --mode {args.mode} --scope {args.scope}")
    print("=" * 50)

    scopes = ["memory", "knowledge"] if args.scope == "both" else [args.scope]
    failed = False
    for scope in scopes:
        try:
            sync, _ = _build_services_for_scope(scope)
        except Exception as e:
            print(f"  {scope}: skipped — {e}")
            print(f"    hint: ensure Bitable credentials for {scope} are set")
            failed = True
            continue
        try:
            if args.mode == "incremental":
                result = asyncio.run(sync.incremental())
            elif args.mode == "full":
                result = asyncio.run(sync.full())
            elif args.mode == "rebuild":
                result = asyncio.run(sync.rebuild())
            else:
                print(f"  {scope}: unknown mode {args.mode!r}")
                failed = True
                continue
            d = result.to_dict()
            print(
                f"  {scope}: mode={d['mode']} added={d['added']} "
                f"updated={d['updated']} deleted={d['deleted']} errors={len(d['errors'])}"
            )
            for err in d["errors"][:5]:
                print(f"    ! {err}")
        except Exception as e:
            print(f"  {scope}: sync failed — {e}")
            failed = True

    return 1 if failed else 0


def _cmd_status() -> int:
    """Show local cache + sync state."""
    print("feishu-memory status")
    print("=" * 50)

    cache_path: Path | None = None
    vector_path: Path | None = None
    cfg = None
    try:
        from mcp_memory.storage.paths import local_cache_path, lance_path
        from mcp_memory.config import Config
        cfg = Config(_env_file=None)  # type: ignore[call-arg]
        data_dir = cfg.data_dir
        cache_path = local_cache_path(data_dir, "memory")
        vector_path = lance_path(data_dir, "memory")
    except Exception as e:
        print(f"Config / paths: {e}")

    if cache_path is None:
        print("Local data directory: (config not loaded)")
        return 0

    print(f"Local data directory: {cache_path}")

    # Check actual state from disk
    from mcp_memory.storage.local_cache import LocalCache
    try:
        cache = LocalCache(cache_path, scope="memory")
        try:
            mem_count = cache.count_by_filter({})
            mem_initialized = mem_count > 0
            print(f"Memory cache:    {mem_count} records ({'initialized' if mem_initialized else 'empty'})")
            if mem_initialized:
                state = cache.get_sync_state()
                print(f"  Last sync:      {state.get('last_sync_at', 'never')}")
                print(f"  Last full sync: {state.get('last_full_sync_at', 'never')}")
        finally:
            cache.close()
    except Exception as e:
        print(f"Memory cache:     [error] {e}")

    # Check vector index dir
    if vector_path and vector_path.exists():
        try:
            size = sum(f.stat().st_size for f in vector_path.rglob("*") if f.is_file())
            print(f"Vector index:     {vector_path} ({size:,} bytes)")
        except Exception:
            print(f"Vector index:     {vector_path} (exists)")
    else:
        print("Vector index:     not yet created (run sync)")

    print()
    # Machine-readable hint for tooling
    print(json.dumps({
        "memory_cache": str(cache_path),
        "memory_cache_exists": cache_path.exists(),
        "vector_index": str(vector_path) if vector_path else None,
        "vector_index_exists": vector_path.exists() if vector_path else False,
    }))
    return 0


def _cmd_schema(args: argparse.Namespace) -> int:
    """Dump / verify Bitable schema against the spec's expected fields."""
    from mcp_memory.setup import (
        EXPECTED_BITABLE_FIELDS,
        check_status,
    )
    from mcp_memory.feishu.runner import LarkCliRunner
    from mcp_memory.config import Config

    status = check_status()
    if not status.lark_cli_installed:
        print("[error] lark-cli not installed; run `feishu-memory install-deps` first")
        return 1

    try:
        cfg = Config(_env_file=None)  # type: ignore[call-arg]
    except Exception as e:
        print(f"[error] Config: {e}")
        return 1

    runner = LarkCliRunner()
    app_token = cfg.memory_bitable_app_token
    table_id = cfg.memory_bitable_table_id

    if not app_token or not table_id:
        print("[error] MEMORY_BITABLE_APP_TOKEN / TABLE_ID not set; run `feishu-memory init`")
        return 1

    # List existing fields
    try:
        result = runner.run([
            "base", "+field-list",
            "--base-token", app_token,
            "--table-id", table_id,
        ])
    except Exception as e:
        print(f"[error] field-list failed: {e}")
        return 1

    existing = set()
    if isinstance(result, dict):
        # v2 response shape: data.fields is the array of fields
        data_block = result.get("data", {})
        if isinstance(data_block, dict):
            fields_array = data_block.get("fields") or data_block.get("items") or []
        elif isinstance(data_block, list):
            fields_array = data_block
        else:
            fields_array = []
        for f in fields_array:
            if isinstance(f, dict):
                n = f.get("field_name") or f.get("name")
                if n:
                    existing.add(n)

    expected = {f["name"] for f in EXPECTED_BITABLE_FIELDS}
    missing = expected - existing
    extra = existing - expected

    print(f"Bitable: {app_token} / table {table_id}")
    print(f"Existing fields ({len(existing)}): {sorted(existing)}")
    print(f"Expected fields ({len(expected)}): {sorted(expected)}")
    if missing:
        print(f"  Missing ({len(missing)}): {sorted(missing)}")
    if extra:
        print(f"  Extra (in Bitable, not in spec): {sorted(extra)}")

    if args.verify:
        if missing:
            print(f"\n[FAIL] {len(missing)} field(s) missing from Bitable")
            print("Run `feishu-memory init` to auto-create them, or use sync tool.")
            return 1
        print("\n[PASS] Bitable schema matches spec")
        return 0

    # --no-verify (default): offer to create missing
    if missing:
        print(f"\nWould create {len(missing)} missing fields. Run `feishu-memory init` to do so.")
    else:
        print("\n[OK] schema is complete")
    return 0


def _cmd_migrate() -> int:
    """Rebuild local cache: clear_all_records and re-run full sync from Bitable.

    This is a destructive local operation; Bitable data is preserved.
    Use this if your local SQLite has been corrupted or you want a fresh start.
    """
    print("feishu-memory migrate")
    print("=" * 50)
    print("This will:")
    print("  1. Clear all records from local cache (memory + knowledge)")
    print("  2. Run full sync to re-import from Bitable")
    print()

    failed = False
    for scope in ("memory", "knowledge"):
        try:
            sync, _ = _build_services_for_scope(scope)
        except Exception as e:
            print(f"  {scope}: skipped — {e}")
            failed = True
            continue
        try:
            result = asyncio.run(sync.rebuild())
            d = result.to_dict()
            print(
                f"  {scope}: rebuilt added={d['added']} "
                f"deleted={d['deleted']} errors={len(d['errors'])}"
            )
            for err in d["errors"][:5]:
                print(f"    ! {err}")
        except Exception as e:
            print(f"  {scope}: rebuild failed — {e}")
            failed = True

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
