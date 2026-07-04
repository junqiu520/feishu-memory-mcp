import json
import pytest
from unittest.mock import patch, MagicMock
from mcp_memory.feishu.runner import (
    LarkCliRunner,
    LarkCliError,
    LarkCliConfirmationRequired,
)


def _mock_result(returncode=0, stdout="", stderr=""):
    r = MagicMock()
    r.returncode = returncode
    r.stdout = stdout
    r.stderr = stderr
    return r


def test_run_success_returns_parsed_json():
    runner = LarkCliRunner(lark_cli_path="/bin/lark-cli")
    payload = {"ok": True, "data": "x"}
    with patch("subprocess.run", return_value=_mock_result(0, json.dumps(payload))):
        result = runner.run(["base", "+record-list", "--base-token", "X"])
    assert result == payload


def test_run_with_as_user():
    runner = LarkCliRunner(lark_cli_path="/bin/lark-cli")
    with patch("subprocess.run", return_value=_mock_result(0, "{}")) as mock_run:
        runner.run(["x"], as_user=True)
    cmd = mock_run.call_args[0][0]
    assert "--as" in cmd
    assert "user" in cmd


def test_run_with_yes_auto_confirms():
    runner = LarkCliRunner(lark_cli_path="/bin/lark-cli")
    with patch("subprocess.run", return_value=_mock_result(0, "{}")) as mock_run:
        runner.run(["base", "+record-delete"], yes=True)
    cmd = mock_run.call_args[0][0]
    assert "--yes" in cmd


def test_run_adds_format_json_by_default():
    runner = LarkCliRunner(lark_cli_path="/bin/lark-cli")
    with patch("subprocess.run", return_value=_mock_result(0, "{}")) as mock_run:
        runner.run(["x"])
    cmd = mock_run.call_args[0][0]
    assert "--format" in cmd
    assert "json" in cmd


def test_run_handles_confirmation_required():
    runner = LarkCliRunner(lark_cli_path="/bin/lark-cli")
    err_envelope = json.dumps({
        "ok": False,
        "error": {"type": "confirmation_required", "message": "needs --yes"}
    })
    with patch("subprocess.run", return_value=_mock_result(10, "", err_envelope)):
        with pytest.raises(LarkCliConfirmationRequired):
            runner.run(["base", "+record-delete"])


def test_run_handles_generic_error():
    runner = LarkCliRunner(lark_cli_path="/bin/lark-cli")
    err_envelope = json.dumps({
        "ok": False,
        "error": {"type": "permission_violations", "message": "scope missing"}
    })
    with patch("subprocess.run", return_value=_mock_result(1, "", err_envelope)):
        with pytest.raises(LarkCliError) as exc_info:
            runner.run(["base", "+record-list"])
    assert "scope missing" in str(exc_info.value)


def test_run_handles_not_found():
    runner = LarkCliRunner(lark_cli_path="/missing/binary")
    with patch("subprocess.run", side_effect=FileNotFoundError()):
        with pytest.raises(LarkCliError) as exc_info:
            runner.run(["x"])
    assert "not found" in str(exc_info.value).lower() or "lark-cli" in str(exc_info.value).lower()


def test_run_parses_json_in_markdown_fence():
    runner = LarkCliRunner(lark_cli_path="/bin/lark-cli")
    md = 'Some header\n```json\n{"ok":true}\n```\nMore text'
    with patch("subprocess.run", return_value=_mock_result(0, md)):
        result = runner.run(["x"])
    assert result == {"ok": True}


def test_run_returns_raw_text_on_unparseable():
    runner = LarkCliRunner(lark_cli_path="/bin/lark-cli")
    with patch("subprocess.run", return_value=_mock_result(0, "just some plain text")):
        result = runner.run(["x"])
    assert result == "just some plain text"


def test_default_path_uses_shutil_which_when_lark_cli_on_path():
    """When no explicit path and no env var, fallback to shutil.which.
    
    This locks in the Windows .CMD resolution fix — Python subprocess on Windows
    can't find .CMD files via PATH alone; we need shutil.which to return the
    resolved full path.
    """
    with patch.dict("os.environ", {}, clear=True):
        with patch("shutil.which", return_value=r"C:\Users\test\AppData\Roaming\npm\lark-cli.CMD"):
            runner = LarkCliRunner()
    assert runner.lark_cli == r"C:\Users\test\AppData\Roaming\npm\lark-cli.CMD"


def test_env_var_path_takes_precedence_over_which():
    """LARK_CLI_PATH env var should win over shutil.which."""
    with patch.dict("os.environ", {"LARK_CLI_PATH": "/custom/path/lark-cli"}):
        with patch("shutil.which", return_value="/different/path/lark-cli"):
            runner = LarkCliRunner()
    assert runner.lark_cli == "/custom/path/lark-cli"