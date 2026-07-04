"""CLI smoke tests for Stage 7.

These run the CLI as a subprocess because:
  - argparse exits cleanly via `python -m mcp_memory.cli --help`
  - the `feishu-memory` console script shim isn't on PATH in CI/dev unless installed
  - subprocess gives us a real exit-code and stdout/stderr surface

We don't validate command output content beyond exit codes for most commands;
doctor/status print scaffolding that may evolve across stages.
"""

import os
import subprocess
import sys


def _run(args, timeout=30, env=None):
    """Run CLI as subprocess. By default inherits parent env so env vars flow through.

    For sync-style commands that need Bitable credentials, callers should pass env=
    explicitly to ensure the test doesn't depend on a .env file.
    """
    final_env = env if env is not None else None
    return subprocess.run(
        [sys.executable, "-m", "mcp_memory.cli", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=final_env,
    )


# Minimal env for sync tests that need Config credentials.
# Memory scope only — knowledge scope may not be set in CI.
_SYNC_TEST_ENV = {
    "FEISHU_APP_ID": "cli_test_xxxxxxxxxxxxxxxx",
    "FEISHU_APP_SECRET": "test_secret_xxx",  # pragma: allowlist secret
    "MEMORY_BITABLE_APP_TOKEN": "bascnTestToken",
    "MEMORY_BITABLE_TABLE_ID": "tblTest",
}


def test_cli_help_exits_zero():
    r = _run(["--help"])
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "feishu-memory" in r.stdout or "usage" in r.stdout.lower()


def test_cli_no_args_prints_version_and_exits_zero():
    """Per spec: no args == version command (exit 0)."""
    r = _run([])
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "0.1.0" in r.stdout


def test_cli_version_subcommand():
    r = _run(["version"])
    assert r.returncode == 0
    assert "0.1.0" in r.stdout


def test_cli_init_prints_env_var_help():
    r = _run(["init"])
    assert r.returncode == 0
    assert "FEISHU_APP_ID" in r.stdout


def test_cli_status_prints_status_lines():
    r = _run(["status"])
    assert r.returncode == 0
    assert "status" in r.stdout.lower() or "cache" in r.stdout.lower()


def test_cli_doctor_runs_check_suite():
    r = _run(["doctor"])
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "doctor" in r.stdout.lower()


def test_cli_doctor_checks_lark_cli():
    """doctor must check whether `lark-cli` is on PATH."""
    r = _run(["doctor"])
    assert r.returncode in (0, 1), (r.stdout, r.stderr)
    assert "lark-cli" in r.stdout.lower()


def test_cli_install_deps_mentions_lark_cli_and_node():
    """install-deps prints Node.js + npm + lark-cli status.

    On a developer machine lark-cli is usually already installed, so the
    command exits 0 with "already installed". On a fresh box it exits 1
    with install instructions. Either way, output must mention lark-cli.
    """
    r = _run(["install-deps"], timeout=60)
    assert r.returncode in (0, 1), (r.stdout, r.stderr)
    assert "lark-cli" in r.stdout.lower()
    assert "node" in r.stdout.lower() or "node.js" in r.stdout.lower()


def test_cli_help_lists_install_deps():
    r = _run(["--help"])
    assert r.returncode == 0
    assert "install-deps" in r.stdout


def test_cli_unknown_subcommand_exits_nonzero():
    r = _run(["not-a-real-command"])
    assert r.returncode != 0


def test_cli_sync_incremental_memory_scope():
    r = _run(
        ["sync", "--mode", "incremental", "--scope", "memory"],
        env={**os.environ, **_SYNC_TEST_ENV},
    )
    # With fake credentials, sync will fail to reach Bitable but the CLI should
    # surface a friendly error message, not crash.
    out = r.stdout
    assert ("memory:" in out) or ("skipped" in out) or ("invalid" in out)
    # exit code may be 0 (no error in CLI) or 1 (auth error from Bitable)
    assert r.returncode in (0, 1)


def test_cli_sync_full_both_scope():
    r = _run(
        ["sync", "--mode", "full", "--scope", "both"],
        env={**os.environ, **_SYNC_TEST_ENV},
    )
    out = r.stdout
    assert ("memory:" in out) and ("knowledge" in out)
    assert r.returncode in (0, 1)


def test_cli_schema_default():
    r = _run(["schema"], env={**os.environ, **_SYNC_TEST_ENV})
    # With fake credentials, schema tries field-list on Bitable which fails.
    # We expect either a successful schema output OR a graceful error
    # message containing "Bitable" or "field-list" or "error".
    out = r.stdout
    assert any(s in out for s in ("Bitable", "field-list", "error", "config")), \
        f"unexpected output: {out!r}"
    assert r.returncode in (0, 1)


def test_cli_schema_verify_flag():
    r = _run(["schema", "--verify"], env={**os.environ, **_SYNC_TEST_ENV})
    out = r.stdout
    assert any(s in out for s in ("Bitable", "field-list", "error", "config")), \
        f"unexpected output: {out!r}"
    assert r.returncode in (0, 1)


def test_cli_migrate_runs():
    r = _run(["migrate"], env={**os.environ, **_SYNC_TEST_ENV})
    out = r.stdout
    # With fake creds, migrate tries to rebuild, fails, but prints something
    assert "migrate" in out.lower() or "rebuild" in out.lower()
    assert r.returncode in (0, 1)


def test_cli_sync_invalid_mode_rejected():
    r = _run(["sync", "--mode", "bogus"])
    assert r.returncode != 0


def test_cli_serve_exits_zero_with_info_message():
    """At Stage 6/7, serve is a stub that exits 0 — real wiring is Stage 8."""
    r = _run(["serve"])
    assert r.returncode == 0, (r.stdout, r.stderr)
