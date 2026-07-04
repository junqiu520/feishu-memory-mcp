"""Cross-platform system dependency checks + installer.

feishu-memory-mcp relies on lark-cli (npm package @larksuite/cli) as its
Feishu backend. This module detects and (when called from CLI) installs it.

For most users, the entry point is `feishu-memory install-deps`.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any, Optional


LARK_CLI_NPM_PACKAGE = "@larksuite/cli"
LARK_CLI_REPO_URL = "https://github.com/larksuite/cli"
NODEJS_DOWNLOAD_URL = "https://nodejs.org/en/download/"

_VERSION_RE = re.compile(r"\d+\.\d+\.\d+")


# ---------------------------------------------------------------------------
# Bitable schema bootstrap (spec §3.2)
# ---------------------------------------------------------------------------
#
# This is the source of truth for the columns memory/knowledge records need.
# `ensure_bitable_schema()` reads this list, queries the live Bitable for
# existing fields, and creates any missing ones via
# `lark-cli base +field-create --json ...` (v2 protocol).
#
# Each entry is a dict matching the lark-base field JSON spec. v2 type names:
#   text, number, select, datetime, checkbox, attachment,
#   auto_number, created_at, updated_at, formula, lookup, link_text
#
# Select fields require an explicit ``options`` array (at least one entry).
# ``datetime`` fields accept ``style.format`` of ``"date"`` or ``"date_time"``.
# URL fields use ``text`` with ``style.type: "url"``.

EXPECTED_BITABLE_FIELDS: list[dict] = [
    {
        "name": "source", "type": "select", "multiple": False,
        "options": [
            {"name": "agent_add"}, {"name": "feishu_doc"},
            {"name": "feishu_bitable"}, {"name": "feishu_drive_file"},
            {"name": "feishu_wiki"},
        ],
        "description": "来源类型",
    },
    {"name": "title", "type": "text", "description": "人类可读标题"},
    {"name": "preview", "type": "text", "description": "前 200 字（UI 展示用）"},
    {
        "name": "content_ref_type", "type": "select", "multiple": False,
        "options": [
            {"name": "docx"}, {"name": "bitable"},
            {"name": "drive_file"}, {"name": "wiki"},
        ],
        "description": "内容存储类型",
    },
    {"name": "content_ref_token", "type": "text", "description": "飞书资源 token"},
    {
        "name": "content_ref_url", "type": "text",
        "style": {"type": "url"},
        "description": "直接打开链接",
    },
    {"name": "content_hash", "type": "text", "description": "sha256 of content"},
    {"name": "feishu_last_modified", "type": "number", "description": "飞书端版本号"},
    {
        "name": "tags", "type": "select", "multiple": True,
        "options": [{"name": "untagged"}],
        "description": "过滤标签（多选）",
    },
    {"name": "source_user", "type": "text", "description": "录入者 open_id"},
    {"name": "source_agent", "type": "text", "description": "agent_id"},
    {
        "name": "origin", "type": "select", "multiple": False,
        "options": [{"name": "manual"}, {"name": "auto_sync"}],
        "description": "录入方式",
    },
    {"name": "extra_json", "type": "text", "description": "扩展字段 JSON"},
    {"name": "text_empty", "type": "checkbox", "description": "text 字段是否为空"},
    {
        "name": "created_at", "type": "datetime",
        "style": {"format": "date_time"},
        "description": "创建时间",
    },
    {
        "name": "updated_at", "type": "datetime",
        "style": {"format": "date_time"},
        "description": "更新时间",
    },
]


async def ensure_bitable_schema(
    runner: Any,
    app_token: str,
    table_id: str,
    scope_label: str,
) -> dict:
    """Ensure the Bitable has every field in ``EXPECTED_BITABLE_FIELDS`` (v2).

    Best-effort: queries the live Bitable for existing fields, then issues
    one ``lark-cli base +field-create --json '<field-property>'`` per missing
    field. Errors on individual fields are collected, not raised, so a single
    permission issue doesn't block the rest of the schema.

    Returns a dict with keys: ``scope``, ``created``, ``existing``, ``errors``.
    """
    from mcp_memory.feishu.runner import LarkCliError  # local import to avoid cycle

    created: list[str] = []
    existing: list[str] = []
    errors: list[str] = []

    # 1. List existing fields.
    try:
        result = runner.run([
            "base", "+field-list",
            "--base-token", app_token,
            "--table-id", table_id,
            "--format", "json",
        ])
    except LarkCliError as e:
        return {
            "scope": scope_label,
            "created": created,
            "existing": existing,
            "errors": [f"list fields failed: {e}"],
        }

    if isinstance(result, dict):
        for f in result.get("items", []):
            if not isinstance(f, dict):
                continue
            name = f.get("field_name") or f.get("name")
            if name:
                existing.append(str(name))

    existing_set = set(existing)

    # 2. Create missing fields one by one. Continue past per-field failures.
    for field_def in EXPECTED_BITABLE_FIELDS:
        name = field_def.get("name")
        if not name:
            errors.append(f"skip field def without name: {field_def!r}")
            continue
        if name in existing_set:
            continue
        try:
            runner.run([
                "base", "+field-create",
                "--base-token", app_token,
                "--table-id", table_id,
                "--json", json.dumps(field_def),
            ])
        except LarkCliError as e:
            errors.append(f"create field {name}: {e}")
            continue
        created.append(name)

    return {
        "scope": scope_label,
        "created": created,
        "existing": existing,
        "errors": errors,
    }


@dataclass
class DepStatus:
    """Detected dependency status for the runtime environment.

    All `*_installed` fields are booleans; the corresponding `*_version`
    fields are strings only when detection succeeded (None otherwise).
    `notes` carries human-readable warnings (e.g. "node without npm").
    """

    node_installed: bool = False
    node_version: Optional[str] = None
    npm_installed: bool = False
    npm_version: Optional[str] = None
    lark_cli_installed: bool = False
    lark_cli_path: Optional[str] = None
    lark_cli_version: Optional[str] = None
    is_windows: bool = (sys.platform == "win32")
    notes: list[str] = field(default_factory=list)


def check_status() -> DepStatus:
    """Detect Node.js / npm / lark-cli availability on the host.

    Never raises — if a probe fails, the corresponding field stays False
    or None. Callers can render the result directly.
    """
    s = DepStatus()

    node = shutil.which("node")
    if node:
        s.node_installed = True
        ver = _safe_capture([node, "--version"])
        s.node_version = ver if ver else None

    npm = shutil.which("npm")
    if npm:
        s.npm_installed = True
        ver = _safe_capture([npm, "--version"])
        s.npm_version = ver if ver else None
    else:
        s.notes.append("npm not on PATH")

    lark_cli = shutil.which("lark-cli")
    if lark_cli:
        s.lark_cli_installed = True
        s.lark_cli_path = lark_cli
        raw = _safe_capture([lark_cli, "--version"]) or ""
        m = _VERSION_RE.search(raw)
        s.lark_cli_version = m.group(0) if m else (raw.strip() or None)

    if s.node_installed and not s.npm_installed:
        s.notes.append(
            "Node.js found but npm missing — unusual; reinstall Node.js"
        )

    return s


def install_lark_cli(timeout: float = 180.0) -> tuple[bool, str]:
    """Run `npm install -g @larksuite/cli`.

    Returns (success, message). The message is human-readable and meant
    to be printed directly. Caller handles exit code.

    Never raises — all errors (npm missing, network failure, timeout,
    permission denied) are folded into a (False, helpful_message) tuple.
    """
    npm = shutil.which("npm")
    if not npm:
        return False, (
            "npm not found. Install Node.js first:\n"
            f"  -> {NODEJS_DOWNLOAD_URL}\n"
            "After installing Node.js, run `feishu-memory install-deps` again."
        )

    cmd = [npm, "install", "-g", LARK_CLI_NPM_PACKAGE]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, (
            f"npm install timed out after {timeout}s. "
            "Check your network connection and retry."
        )
    except Exception as e:
        return False, (
            f"npm install raised {type(e).__name__}: {e}\n"
            "If npm is on PATH but still fails, try running manually:\n"
            f"  npm install -g {LARK_CLI_NPM_PACKAGE}"
        )

    if result.returncode == 0:
        return True, (
            f"lark-cli installed successfully via `npm install -g {LARK_CLI_NPM_PACKAGE}`.\n"
            "Next step: authorize lark-cli with your Feishu app:\n"
            "  lark-cli config init"
        )

    return False, (
        f"npm install failed (exit {result.returncode}).\n"
        f"  stdout: {result.stdout[:500]!r}\n"
        f"  stderr: {result.stderr[:500]!r}\n"
        "\n"
        "Common causes:\n"
        f"  1. On Linux/macOS, may need sudo: `sudo npm install -g {LARK_CLI_NPM_PACKAGE}`\n"
        "  2. npm prefix may be read-only; check `npm config get prefix`\n"
        "  3. Network issue; retry when online or set a corporate registry mirror\n"
        f"  See {LARK_CLI_REPO_URL} for details."
    )


def _safe_capture(cmd: list[str]) -> Optional[str]:
    """Run a command and capture stdout. Returns None on any failure.

    Used for `node --version`, `npm --version`, `lark-cli --version` —
    all are best-effort probes, so failures must not propagate.

    On Windows, `shutil.which` returns paths with extensions like `.CMD`
    or `.PS1` that subprocess can't always execute via list-form args;
    passing the resolved path explicitly fixes that.
    """
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            return r.stdout.strip()
        return None
    except Exception:
        return None