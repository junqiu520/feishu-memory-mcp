"""Tests for the Docx / Drive / Wiki client wrappers (Stage 2 + Stage 9 wire-up).

After the lark-cli migration, these clients take a LarkCliRunner instead of a
lark.Client. The tests verify basic init and that the lark-cli command shape is
correct under the v2 protocol.
"""
import pytest
from unittest.mock import MagicMock
from mcp_memory.feishu.docx import DocxClient
from mcp_memory.feishu.drive import DriveClient
from mcp_memory.feishu.wiki import WikiClient
from mcp_memory.feishu.runner import LarkCliRunner, LarkCliError


@pytest.fixture
def mock_runner():
    return MagicMock(spec=LarkCliRunner)


def test_docx_client_init(mock_runner):
    c = DocxClient(mock_runner)
    assert c is not None
    assert c.runner is mock_runner


def test_drive_client_init(mock_runner):
    c = DriveClient(mock_runner)
    assert c is not None
    assert c.runner is mock_runner


def test_wiki_client_init(mock_runner):
    c = WikiClient(mock_runner)
    assert c is not None
    assert c.runner is mock_runner


def test_docx_create_invokes_lark_cli_v2(mock_runner):
    """v2: ``docs +create`` uses ``--content`` with an XML body, no ``--title``."""
    mock_runner.run.return_value = {"document_id": "doc_abc"}
    c = DocxClient(mock_runner)
    import asyncio
    token = asyncio.run(c.create_docx("hello content", title="Hello"))
    assert token == "doc_abc"
    args = mock_runner.run.call_args[0][0]
    assert args[0] == "docs"
    assert args[1] == "+create"
    # v1 command name no longer used
    assert "+document-create" not in args
    assert "--content" in args
    # v2: --title flag is gone
    assert "--title" not in args
    # Body contains the title wrapped in <title> and the body text in <p>
    idx = args.index("--content")
    body = args[idx + 1]
    assert "<title>Hello</title>" in body
    assert "<p>" in body
    assert "hello content" in body


def test_docx_create_returns_token_when_nested_under_data(mock_runner):
    """Some responses nest the new doc id under ``data.document_id``."""
    mock_runner.run.return_value = {"data": {"document_id": "doc_nested"}}
    c = DocxClient(mock_runner)
    import asyncio
    token = asyncio.run(c.create_docx("x", title="X"))
    assert token == "doc_nested"


def test_docx_create_escapes_xml_in_body(mock_runner):
    """XML special chars in content must be escaped to avoid malformed XML."""
    mock_runner.run.return_value = {"document_id": "d1"}
    c = DocxClient(mock_runner)
    import asyncio
    asyncio.run(c.create_docx("<script>alert(1)</script> & 'quotes'", title="T"))
    args = mock_runner.run.call_args[0][0]
    body = args[args.index("--content") + 1]
    assert "<script>" not in body  # < got escaped to &lt;
    assert "&lt;script&gt;" in body
    assert "&amp;" in body


def test_docx_create_truncates_huge_content(mock_runner):
    """Safety net: cap body at 90K chars to stay under the 100K CLI arg ceiling."""
    mock_runner.run.return_value = {"document_id": "d2"}
    c = DocxClient(mock_runner)
    huge = "x" * 200_000
    import asyncio
    asyncio.run(c.create_docx(huge, title="Big"))
    args = mock_runner.run.call_args[0][0]
    body = args[args.index("--content") + 1]
    # 90K chars of 'x' + ~30 chars of XML scaffolding
    assert len(body) < 95_000


def test_docx_create_default_title_when_missing(mock_runner):
    mock_runner.run.return_value = {"document_id": "d3"}
    c = DocxClient(mock_runner)
    import asyncio
    asyncio.run(c.create_docx("body"))
    args = mock_runner.run.call_args[0][0]
    body = args[args.index("--content") + 1]
    assert "<title>Untitled</title>" in body


def test_docx_delete_returns_false_no_lark_cli_command(mock_runner, caplog):
    """lark-cli v2 has no ``docs +delete`` shortcut. delete_docx is a no-op.

    It returns False and logs a warning pointing to native Feishu API.
    The runner should NOT be called.
    """
    c = DocxClient(mock_runner)
    import asyncio
    with caplog.at_level("WARNING"):
        ok = asyncio.run(c.delete_docx("doc_abc"))
    assert ok is False
    mock_runner.run.assert_not_called()


def test_docx_create_returns_empty_on_error(mock_runner):
    mock_runner.run.side_effect = LarkCliError("boom")
    c = DocxClient(mock_runner)
    import asyncio
    token = asyncio.run(c.create_docx("x", title="X"))
    assert token == ""


def test_docx_delete_returns_false_on_error(mock_runner):
    mock_runner.run.side_effect = LarkCliError("boom")
    c = DocxClient(mock_runner)
    import asyncio
    assert asyncio.run(c.delete_docx("d1")) is False


def test_drive_get_file_info(mock_runner):
    mock_runner.run.return_value = {
        "file": {
            "file_token": "ftok_1",
            "name": "report.pdf",
            "type": "file",
            "url": "https://example.com/file",
            "size": 1234,
        }
    }
    c = DriveClient(mock_runner)
    import asyncio
    info = asyncio.run(c.get_file_info("ftok_1"))
    assert info["file_token"] == "ftok_1"
    assert info["name"] == "report.pdf"
    assert info["url"] == "https://example.com/file"


def test_drive_get_file_info_handles_flat_response(mock_runner):
    """Fallback: when the response is flat (no ``file`` wrapper)."""
    mock_runner.run.return_value = {
        "file_token": "ftok_flat",
        "name": "flat.pdf",
        "type": "file",
        "url": "https://example.com/flat",
        "size": 99,
    }
    c = DriveClient(mock_runner)
    import asyncio
    info = asyncio.run(c.get_file_info("ftok_flat"))
    assert info["file_token"] == "ftok_flat"
    assert info["name"] == "flat.pdf"


def test_drive_get_file_info_returns_empty_on_error(mock_runner):
    mock_runner.run.side_effect = LarkCliError("boom")
    c = DriveClient(mock_runner)
    import asyncio
    assert asyncio.run(c.get_file_info("ftok_x")) == {}


def test_drive_upload_file(mock_runner):
    mock_runner.run.return_value = {
        "file_token": "upl_1",
        "url": "https://example.com/upl",
        "name": "uploaded.txt",
    }
    c = DriveClient(mock_runner)
    import asyncio
    out = asyncio.run(c.upload_file("/tmp/local.txt"))
    assert out["file_token"] == "upl_1"
    assert out["url"] == "https://example.com/upl"


def test_drive_upload_file_returns_empty_on_error(mock_runner):
    mock_runner.run.side_effect = LarkCliError("boom")
    c = DriveClient(mock_runner)
    import asyncio
    assert asyncio.run(c.upload_file("/tmp/x")) == {}


def test_wiki_get_node_content(mock_runner):
    mock_runner.run.return_value = {
        "description": "Wiki content here",
    }
    c = WikiClient(mock_runner)
    import asyncio
    content = asyncio.run(c.get_node_content("node_1"))
    assert content == "Wiki content here"


def test_wiki_get_node_content_returns_empty_on_error(mock_runner):
    mock_runner.run.side_effect = LarkCliError("boom")
    c = WikiClient(mock_runner)
    import asyncio
    assert asyncio.run(c.get_node_content("n1")) == ""