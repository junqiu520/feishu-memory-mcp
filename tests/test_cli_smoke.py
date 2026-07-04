"""CLI smoke tests for Stage 7 (sync / schema / migrate subcommands).

Spec referenced `tests/test_cli_smoke.py` separately from `tests/test_cli.py`
to keep the heavier smoke surface focused on the most-touched commands.
"""
import os
import subprocess
import sys


# Minimal env for tests that need Config credentials.
# knowledge_bitable_* is optional — the user's knowledge library may not be set up.
_TEST_ENV = {
    "FEISHU_APP_ID": "cli_test_xxxxxxxxxxxxxxxx",
    "FEISHU_APP_SECRET": "test_secret_xxx",  # pragma: allowlist secret
    "MEMORY_BITABLE_APP_TOKEN": "bascnTestToken",
    "MEMORY_BITABLE_TABLE_ID": "tblTest",
}


def _run(args, timeout=30, env=None):
    """Run CLI as subprocess. Caller may pass env to inject test credentials.

    With fake credentials, sync/schema/migrate will fail when they try to call
    the real Bitable — we just assert the CLI responds gracefully (clean exit
    code or friendly error).
    """
    final_env = env if env is not None else None
    return subprocess.run(
        [sys.executable, "-m", "mcp_memory.cli", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=final_env,
    )


def test_cli_sync_incremental_memory_scope():
    r = _run(
        ["sync", "--mode", "incremental", "--scope", "memory"],
        env={**os.environ, **_TEST_ENV},
    )
    out = r.stdout
    # Friendly: "memory:" section appears (with skipped or counts)
    assert "memory:" in out or "skipped" in out
    assert r.returncode in (0, 1)


def test_cli_sync_full_knowledge_scope():
    r = _run(
        ["sync", "--mode", "full", "--scope", "knowledge"],
        env={**os.environ, **_TEST_ENV},
    )
    out = r.stdout
    assert "knowledge" in out
    assert r.returncode in (0, 1)


def test_cli_sync_rebuild_both_scope():
    r = _run(
        ["sync", "--mode", "rebuild", "--scope", "both"],
        env={**os.environ, **_TEST_ENV},
    )
    out = r.stdout
    assert "memory:" in out and "knowledge" in out
    assert r.returncode in (0, 1)


def test_cli_migrate_runs_cleanly():
    r = _run(["migrate"], env={**os.environ, **_TEST_ENV})
    out = r.stdout
    assert "migrate" in out.lower() or "rebuild" in out.lower()
    assert r.returncode in (0, 1)


def test_cli_schema_default_runs_cleanly():
    r = _run(["schema"], env={**os.environ, **_TEST_ENV})
    out = r.stdout
    assert any(s in out for s in ("Bitable", "field-list", "error", "config"))
    assert r.returncode in (0, 1)


def test_cli_schema_verify_runs_cleanly():
    r = _run(["schema", "--verify"], env={**os.environ, **_TEST_ENV})
    out = r.stdout
    assert any(s in out for s in ("Bitable", "field-list", "error", "config"))
    assert r.returncode in (0, 1)
