"""LarkCliRunner — subprocess wrapper for `lark-cli` calls.

lark-cli is the official CLI from Feishu/Lark. It internally uses lark-oapi SDK
and exposes a stable JSON-protocol interface with consistent error shapes:
  - exit 0: stdout has JSON (or markdown with JSON in code-fence)
  - exit 10: stderr has confirmation_required envelope (we always auto-confirm
    since these are agent-driven)
  - other non-zero: stderr has error JSON

We treat lark-cli as the only "backend" — there is no Python SDK fallback.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
from typing import Any

log = logging.getLogger(__name__)


class LarkCliError(Exception):
    """Generic lark-cli error."""
    def __init__(self, message: str, code: str | None = None, payload: dict | None = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.payload = payload or {}


class LarkCliConfirmationRequired(LarkCliError):
    """Exit code 10 — high-risk write needs confirmation. We auto-confirm."""


class LarkCliRunner:
    """Subprocess wrapper around lark-cli."""

    def __init__(
        self,
        lark_cli_path: str | None = None,
        default_as: str = "bot",
        timeout: float = 30.0,
    ):
        # Allow override for testing; default to PATH lookup
        self.lark_cli = lark_cli_path or self._resolve_path()
        self.default_as = default_as
        self.timeout = timeout

    @staticmethod
    def _resolve_path() -> str:
        """Find lark-cli binary path. Env override > shutil.which > PATH lookup."""
        env_override = os.environ.get("LARK_CLI_PATH")
        if env_override:
            return env_override
        # On Windows, subprocess can't always find .CMD files via PATH.
        # shutil.which returns the resolved full path which works cross-platform.
        resolved = shutil.which("lark-cli")
        if resolved:
            return resolved
        return "lark-cli"  # last resort: hope subprocess can find it

    def run(
        self,
        args: list[str],
        as_user: bool = False,
        yes: bool = False,
    ) -> dict | list | str:
        """Run lark-cli with the given args and return parsed output."""
        cmd = [self.lark_cli, *args]
        if as_user:
            cmd += ["--as", "user"]
        else:
            cmd += ["--as", self.default_as]
        if yes:
            # Auto-confirm high-risk writes (delete, etc.)
            cmd += ["--yes"]
        cmd += ["--format", "json"]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired as e:
            raise LarkCliError(f"lark-cli timeout after {self.timeout}s") from e
        except FileNotFoundError as e:
            raise LarkCliError(
                f"lark-cli not found at {self.lark_cli!r}. "
                f"Install via `npm install -g @larksuite/cli` or set LARK_CLI_PATH."
            ) from e

        stdout = result.stdout or ""
        stderr = result.stderr or ""

        if result.returncode == 0:
            parsed = self._parse_stdout(stdout)
            # Normalize two output shapes:
            #   - lark-cli shortcut form: {"ok": true, "data": {...}, "error": {...}}
            #   - native Feishu API form: {"code": 0, "msg": "ok", "data": {...}}
            if isinstance(parsed, dict):
                if "ok" in parsed and parsed.get("ok") is False:
                    err = parsed.get("error", {})
                    if isinstance(err, dict):
                        raise LarkCliError(
                            err.get("message", "lark-cli error"),
                            code=err.get("type"),
                            payload=parsed,
                        )
                    raise LarkCliError(str(err) or "lark-cli error", payload=parsed)
                # Native Feishu API: code != 0 means error
                if "code" in parsed and parsed.get("code") not in (0, None):
                    raise LarkCliError(
                        parsed.get("msg", f"Feishu API error code={parsed.get('code')}"),
                        code=str(parsed.get("code")),
                        payload=parsed,
                    )
                # Promote native API form to lark-cli shortcut form so callers see uniform shape.
                # Some native endpoints (e.g. bot/v3/info) return payload at top level without a `data` key.
                if "code" in parsed and "ok" not in parsed:
                    data = parsed.get("data", {k: v for k, v in parsed.items() if k not in ("code", "msg")})
                    return {
                        "ok": True,
                        "identity": self.default_as,
                        "data": data,
                        "code": parsed.get("code"),
                        "msg": parsed.get("msg"),
                    }
            return parsed

        # Try to parse stderr as error JSON envelope
        err = self._parse_stderr_error(stderr)
        if err is not None:
            if result.returncode == 10:
                raise LarkCliConfirmationRequired(err["message"], code=err.get("type"), payload=err)
            raise LarkCliError(err["message"], code=err.get("type"), payload=err)

        # Fallback: return raw stderr
        raise LarkCliError(
            f"lark-cli failed (exit={result.returncode}): {stderr or stdout}".strip()
        )

    @staticmethod
    def _parse_stdout(text: str) -> Any:
        """lark-cli --format json output is JSON; or markdown with JSON in code-fence."""
        text = text.strip()
        if not text:
            return {}
        # Try direct JSON
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        # Try markdown code-fence
        m = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass
        # Return raw text
        return text

    @staticmethod
    def _parse_stderr_error(stderr: str) -> dict | None:
        """Parse lark-cli's stderr error envelope. Returns None if not parseable."""
        stderr = stderr.strip()
        if not stderr:
            return None
        try:
            payload = json.loads(stderr)
            if isinstance(payload, dict) and payload.get("ok") is False and "error" in payload:
                err = payload["error"]
                if isinstance(err, dict):
                    return err
        except json.JSONDecodeError:
            pass
        return None


def make_runner(config: Any | None = None) -> LarkCliRunner:
    """Factory: build a LarkCliRunner from Config (or with defaults).

    Args:
        config: optional Config object. If provided and has `lark_cli_path`,
            use it. Otherwise fall back to env LARK_CLI_PATH, then PATH.
    """
    lark_cli_path = None
    if config is not None:
        lark_cli_path = getattr(config, "lark_cli_path", None)
    return LarkCliRunner(lark_cli_path=lark_cli_path)