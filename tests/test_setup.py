"""Tests for mcp_memory.setup — cross-platform dep detection + install.

We mock `shutil.which` and `subprocess.run` so tests don't actually shell
out to npm. Pattern mirrors tests/test_cli.py in style (plain pytest,
no fixtures beyond standard library + mock).
"""
from __future__ import annotations

import asyncio
import subprocess
from unittest.mock import MagicMock, patch

from mcp_memory.setup import (
    DepStatus,
    EXPECTED_BITABLE_FIELDS,
    LARK_CLI_NPM_PACKAGE,
    LARK_CLI_REPO_URL,
    NODEJS_DOWNLOAD_URL,
    check_status,
    ensure_bitable_schema,
    install_lark_cli,
)


def _mock_which_factory(node=False, npm=False, lark_cli=False,
                          lark_cli_path=None):
    """Return a fake `shutil.which` that maps names to fake paths."""
    def fake_which(name):
        if name == "node" and node:
            return "/usr/bin/node"
        if name == "npm" and npm:
            return "/usr/bin/npm"
        if name == "lark-cli" and lark_cli:
            return lark_cli_path or "/usr/local/bin/lark-cli"
        return None
    return fake_which


def _fake_capture_factory(node_ver=None, npm_ver=None, lark_cli_ver=None,
                            node_rc=0, npm_rc=0, lark_cli_rc=0):
    """Return a fake `subprocess.run` that mimics the relevant --version calls.

    Matches commands by basename (e.g. "node") so it works whether the
    implementation passes the bare command or the full resolved path
    (which is what production does on Windows for .CMD / .PS1 wrappers).
    """
    import os

    def fake_run(cmd, *args, **kwargs):
        r = MagicMock()
        exe_basename = os.path.basename(cmd[0]) if cmd else ""
        if exe_basename == "node":
            r.returncode = node_rc
            r.stdout = node_ver or ""
            r.stderr = ""
        elif exe_basename == "npm":
            r.returncode = npm_rc
            r.stdout = npm_ver or ""
            r.stderr = ""
        elif exe_basename == "lark-cli":
            r.returncode = lark_cli_rc
            r.stdout = lark_cli_ver or ""
            r.stderr = ""
        else:
            r.returncode = 0
            r.stdout = ""
            r.stderr = ""
        return r
    return fake_run


# ---------------------------------------------------------------------------
# check_status()
# ---------------------------------------------------------------------------


def test_check_status_all_present():
    """When node, npm, lark-cli are all on PATH, status reflects them."""
    which = _mock_which_factory(node=True, npm=True, lark_cli=True)
    run = _fake_capture_factory(
        node_ver="v20.11.0",
        npm_ver="10.4.0",
        lark_cli_ver="lark-cli version 1.0.51",
    )
    with patch("shutil.which", side_effect=which):
        with patch("subprocess.run", side_effect=run):
            s = check_status()

    assert s.node_installed is True
    assert s.node_version == "v20.11.0"
    assert s.npm_installed is True
    assert s.npm_version == "10.4.0"
    assert s.lark_cli_installed is True
    assert s.lark_cli_path == "/usr/local/bin/lark-cli"
    assert s.lark_cli_version == "1.0.51"
    # When all three are installed, the probes should have used the
    # resolved full paths (not the bare "node" / "npm" / "lark-cli"
    # names), because shutil.which returns the .CMD / .PS1 path on
    # Windows and that's the only way subprocess.run can execute them.
    assert s.node_version is not None
    assert s.npm_version is not None
    assert s.lark_cli_version is not None


def test_check_status_node_missing():
    """When nothing is installed, status reports none of them."""
    with patch("shutil.which", return_value=None):
        s = check_status()

    assert s.node_installed is False
    assert s.node_version is None
    assert s.npm_installed is False
    assert s.lark_cli_installed is False
    assert s.lark_cli_version is None


def test_check_status_node_present_no_npm():
    """Rare: node on PATH but no npm — flag as a note."""
    which = _mock_which_factory(node=True, npm=False, lark_cli=False)
    run = _fake_capture_factory(node_ver="v18.0.0", node_rc=0)
    with patch("shutil.which", side_effect=which):
        with patch("subprocess.run", side_effect=run):
            s = check_status()

    assert s.node_installed is True
    assert s.node_version == "v18.0.0"
    assert s.npm_installed is False
    assert any("npm" in n for n in s.notes)


def test_check_status_node_npm_no_lark_cli():
    """Common case pre-install: node+npm present but lark-cli missing."""
    which = _mock_which_factory(node=True, npm=True, lark_cli=False)
    run = _fake_capture_factory(node_ver="v20.0.0", npm_ver="10.0.0")
    with patch("shutil.which", side_effect=which):
        with patch("subprocess.run", side_effect=run):
            s = check_status()

    assert s.node_installed is True
    assert s.npm_installed is True
    assert s.lark_cli_installed is False
    assert s.lark_cli_version is None


def test_check_status_lark_cli_version_extraction():
    """Version string parsing — strip surrounding text, keep semver."""
    which = _mock_which_factory(node=True, npm=True, lark_cli=True)
    run = _fake_capture_factory(
        node_ver="v20.0.0",
        npm_ver="10.0.0",
        lark_cli_ver="\x1b[32mlark-cli version 1.0.51\x1b[0m",
    )
    with patch("shutil.which", side_effect=which):
        with patch("subprocess.run", side_effect=run):
            s = check_status()
    assert s.lark_cli_version == "1.0.51"


def test_check_status_uses_resolved_paths_in_subprocess():
    """Windows safety: subprocess must get the full path from which(),
    not the bare command name, so .CMD / .PS1 wrappers execute correctly.
    """
    which = _mock_which_factory(node=True, npm=True, lark_cli=True)
    seen_cmds = []

    def fake_run(cmd, *args, **kwargs):
        seen_cmds.append(cmd)
        r = MagicMock()
        r.returncode = 0
        r.stdout = "v1.0.0" if "node" in cmd[0] else "ok"
        r.stderr = ""
        return r

    with patch("shutil.which", side_effect=which):
        with patch("subprocess.run", side_effect=fake_run):
            check_status()

    # Each probe should have been called with the full path returned by
    # shutil.which, not with the bare "node" / "npm" / "lark-cli".
    for cmd in seen_cmds:
        assert cmd[0].startswith("/usr/bin/") or cmd[0].startswith("/usr/local/"), (
            f"expected resolved path, got: {cmd[0]!r}"
        )


def test_check_status_no_exceptions_when_subprocess_fails():
    """If `node --version` fails, status still builds without raising."""
    which = _mock_which_factory(node=True, npm=False, lark_cli=False)
    run = _fake_capture_factory(node_rc=1, node_ver="")
    with patch("shutil.which", side_effect=which):
        with patch("subprocess.run", side_effect=run):
            s = check_status()
    # node is "installed" per shutil.which but version capture failed -> None
    assert s.node_installed is True
    assert s.node_version is None or s.node_version == "?"


# ---------------------------------------------------------------------------
# install_lark_cli()
# ---------------------------------------------------------------------------


def test_install_lark_cli_no_npm_returns_helpful_failure():
    """Without npm on PATH, return False + pointer to Node.js install."""
    with patch("shutil.which", return_value=None):
        success, msg = install_lark_cli()

    assert success is False
    assert "npm not found" in msg
    assert "nodejs.org" in msg.lower()
    assert NODEJS_DOWNLOAD_URL in msg


def test_install_lark_cli_success_calls_correct_npm_command():
    """Successful npm install: True + runs `npm install -g @larksuite/cli`."""
    with patch("shutil.which", return_value="/usr/bin/npm"):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="installed", stderr="",
            )
            success, msg = install_lark_cli()

    assert success is True
    assert "lark-cli installed" in msg.lower() or "successfully" in msg.lower()
    call_args = mock_run.call_args[0][0]
    # First arg is the resolved npm path (from shutil.which), rest is the
    # literal install command. This is the Windows-safe form.
    assert call_args[0] == "/usr/bin/npm"
    assert call_args[1:] == ["install", "-g", LARK_CLI_NPM_PACKAGE]


def test_install_lark_cli_failure_includes_hints():
    """npm failure: include sudo hint + repo URL + truncated stderr."""
    with patch("shutil.which", return_value="/usr/bin/npm"):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1, stdout="", stderr="EACCES permission denied",
            )
            success, msg = install_lark_cli()

    assert success is False
    assert "EACCES" in msg
    assert "sudo" in msg
    assert LARK_CLI_REPO_URL in msg


def test_install_lark_cli_timeout_returns_clear_message():
    """Subprocess timeout: clear 'timed out' message."""
    with patch("shutil.which", return_value="/usr/bin/npm"):
        with patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="npm", timeout=180),
        ):
            success, msg = install_lark_cli()
    assert success is False
    assert "timed out" in msg.lower()


def test_install_lark_cli_handles_unexpected_exception():
    """Unexpected subprocess errors don't kill the caller."""
    with patch("shutil.which", return_value="/usr/bin/npm"):
        with patch("subprocess.run", side_effect=OSError("spawn failed")):
            success, msg = install_lark_cli()
    assert success is False
    assert "OSError" in msg or "spawn failed" in msg


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------


def test_module_exports_expected_constants():
    """Constants are stable — tests + downstream docs reference them."""
    assert LARK_CLI_NPM_PACKAGE == "@larksuite/cli"
    assert "github.com/larksuite/cli" in LARK_CLI_REPO_URL
    assert "nodejs.org" in NODEJS_DOWNLOAD_URL


def test_dep_status_dataclass_defaults():
    """DepStatus() builds with safe defaults (no None errors)."""
    s = DepStatus()
    assert s.node_installed is False
    assert s.node_version is None
    assert s.npm_installed is False
    assert s.lark_cli_installed is False
    assert s.notes == []


# ---------------------------------------------------------------------------
# ensure_bitable_schema() — Bitable field bootstrap
# ---------------------------------------------------------------------------


class _StubRunner:
    """Minimal LarkCliRunner double — records every .run() call, returns queued results.

    Pops a queued result per call. Queue entries that are Exceptions get
    raised (matching LarkCliRunner's contract). Once the queue is empty,
    returns a benign default ``{"ok": True}`` for any extra calls (so tests
    that queue only the interesting results don't have to spell out every
    create success). Tests that want to fail-fast should set ``fail_on_extra=True``.
    """

    def __init__(self, results: list | None = None, fail_on_extra: bool = False):
        self._results = list(results or [])
        self.calls: list[list[str]] = []
        self._fail_on_extra = fail_on_extra

    def run(self, args, as_user: bool = False, yes: bool = False):
        self.calls.append(list(args))
        if self._results:
            item = self._results.pop(0)
            if isinstance(item, BaseException):
                raise item
            return item
        if self._fail_on_extra:
            raise RuntimeError(f"unexpected run() call: {args}")
        return {"ok": True}


def test_ensure_bitable_schema_creates_missing():
    """When the Bitable has no fields, every expected field gets created."""
    from mcp_memory.feishu.runner import LarkCliRunner  # noqa: F401  (used by ensure_bitable_schema signature)

    list_payload = {"items": []}
    runner = _StubRunner([list_payload])

    result = asyncio.run(
        ensure_bitable_schema(runner, "bascnX", "tblY", scope_label="memory")
    )

    assert result["scope"] == "memory"
    expected_names = [f["name"] for f in EXPECTED_BITABLE_FIELDS]
    assert result["created"] == expected_names
    assert result["existing"] == []
    assert result["errors"] == []

    # First call: list fields. Following calls: create one field each.
    assert runner.calls[0] == [
        "base", "+field-list",
        "--base-token", "bascnX",
        "--table-id", "tblY",
        "--format", "json",
    ]
    create_calls = runner.calls[1:]
    assert len(create_calls) == len(expected_names)
    for call, expected_name in zip(create_calls, expected_names):
        assert call[0:4] == ["base", "+field-create", "--base-token", "bascnX"]
        assert call[4] == "--table-id" and call[5] == "tblY"
        # The schema is passed as a single --json flag with a JSON object
        # containing the v2 field property shape (name, type, ...).
        json_idx = call.index("--json")
        payload = __import__("json").loads(call[json_idx + 1])
        assert payload["name"] == expected_name
        assert "type" in payload


def test_ensure_bitable_schema_uses_v2_json_flag():
    """v2: ``+field-create`` must use ``--json`` and no v1 ``--field-name`` etc."""
    list_payload = {"items": []}
    runner = _StubRunner([list_payload])
    asyncio.run(ensure_bitable_schema(runner, "bascnX", "tblY", scope_label="memory"))

    create_calls = [c for c in runner.calls if "+field-create" in c]
    assert len(create_calls) > 0
    for call in create_calls:
        assert "--json" in call
        # v1 flags removed in v2
        assert "--field-name" not in call
        assert "--field-type" not in call


def test_ensure_bitable_schema_skips_existing():
    """When every expected field is already present, no +field-create calls fire."""
    existing_names = [f["name"] for f in EXPECTED_BITABLE_FIELDS]
    list_payload = {"items": [{"field_name": n} for n in existing_names]}
    runner = _StubRunner([list_payload])

    result = asyncio.run(
        ensure_bitable_schema(runner, "bascnX", "tblY", scope_label="memory")
    )

    assert result["created"] == []
    assert sorted(result["existing"]) == sorted(existing_names)
    assert result["errors"] == []
    # Only the list call should have fired — no create calls.
    assert len(runner.calls) == 1


def test_ensure_bitable_schema_continues_on_error():
    """A failure creating one field doesn't stop the rest of the schema."""
    from mcp_memory.feishu.runner import LarkCliError

    list_payload = {"items": []}
    # Queue: field-list returns empty; the SECOND queued item is consumed by
    # the first field-create call (so we make that one fail).
    runner = _StubRunner([
        list_payload,
        LarkCliError("boom", code="permission_denied"),
    ])

    result = asyncio.run(
        ensure_bitable_schema(runner, "bascnX", "tblY", scope_label="knowledge")
    )

    # First field fails; the remaining N-1 fields succeed against the default
    # fallback ({"ok": True}).
    expected_created = len(EXPECTED_BITABLE_FIELDS) - 1
    assert len(result["created"]) == expected_created
    assert len(result["errors"]) == 1
    assert "boom" in result["errors"][0]
    assert result["scope"] == "knowledge"


def test_ensure_bitable_schema_returns_error_when_list_fails():
    """When field-list itself fails, the function short-circuits gracefully."""
    from mcp_memory.feishu.runner import LarkCliError

    runner = _StubRunner()
    runner.run = MagicMock(side_effect=LarkCliError("network down"))

    result = asyncio.run(
        ensure_bitable_schema(runner, "bascnX", "tblY", scope_label="memory")
    )

    assert result["created"] == []
    assert result["existing"] == []
    assert len(result["errors"]) == 1
    assert "list fields failed" in result["errors"][0]


def test_expected_bitable_fields_includes_required_columns():
    """Sanity check on the spec — keep this in sync with spec §3.2."""
    names = [f["name"] for f in EXPECTED_BITABLE_FIELDS]
    for required in ("source", "title", "preview", "tags", "created_at", "updated_at"):
        assert required in names, f"missing required field: {required}"


def test_expected_bitable_fields_uses_v2_type_names():
    """v2 protocol — type names migrated from v1.

    Mapping reference:
      single_select → select (with multiple=False)
      multi_select  → select (with multiple=True)
      long_text     → text
      bool          → checkbox
      url           → text (with style.type="url")
    """
    type_names = [f["type"] for f in EXPECTED_BITABLE_FIELDS]

    # v1 names must NOT appear
    for v1_type in ("single_select", "multi_select", "long_text", "bool"):
        assert v1_type not in type_names, (
            f"v1 type {v1_type!r} leaked into v2 EXPECTED_BITABLE_FIELDS"
        )

    # v2 names that must be present
    for v2_type in ("select", "text", "checkbox", "datetime", "number"):
        assert v2_type in type_names, (
            f"expected v2 type {v2_type!r} missing from EXPECTED_BITABLE_FIELDS"
        )


def test_expected_bitable_select_fields_have_options():
    """v2: every ``select`` field needs an explicit ``options`` array."""
    for f in EXPECTED_BITABLE_FIELDS:
        if f["type"] != "select":
            continue
        assert "options" in f, f"select field {f['name']!r} missing options"
        assert isinstance(f["options"], list)
        assert len(f["options"]) > 0, (
            f"select field {f['name']!r} has empty options"
        )
        for opt in f["options"]:
            assert isinstance(opt, dict) and "name" in opt, (
                f"select field {f['name']!r} option missing name: {opt!r}"
            )


def test_expected_bitable_datetime_fields_have_format_style():
    """v2: ``datetime`` fields must declare ``style.format`` ("date"|"date_time")."""
    for f in EXPECTED_BITABLE_FIELDS:
        if f["type"] != "datetime":
            continue
        style = f.get("style")
        assert isinstance(style, dict), (
            f"datetime field {f['name']!r} missing style"
        )
        assert style.get("format") in ("date", "date_time"), (
            f"datetime field {f['name']!r} style.format invalid: {style!r}"
        )


def test_expected_bitable_field_dicts_have_required_keys():
    """Every entry must be a dict with at least ``name`` and ``type``."""
    for f in EXPECTED_BITABLE_FIELDS:
        assert isinstance(f, dict)
        assert "name" in f and isinstance(f["name"], str) and f["name"]
        assert "type" in f and isinstance(f["type"], str) and f["type"]