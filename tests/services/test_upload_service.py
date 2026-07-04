"""Tests for UploadService.

Covers per-file result shape, error handling, and batch semantics
(single-file failure doesn't abort the batch). Feishu Drive calls are
mocked; only the orchestration is validated here.
"""
from unittest.mock import AsyncMock

import pytest

from mcp_memory.services.upload_service import UploadService


def _drive_mock(upload_side_effect):
    """Build a DriveClient-shaped mock with the given upload side effect."""
    m = AsyncMock()
    m.upload_file = AsyncMock(side_effect=upload_side_effect)
    return m


@pytest.mark.asyncio
async def test_upload_empty_path_returns_error(tmp_path):
    drive = _drive_mock(AsyncMock(return_value={"file_token": "x"}))
    svc = UploadService(drive)

    results = await svc.upload([""])

    assert len(results) == 1
    assert results[0]["status"] == "error"
    assert results[0]["error"] == "empty_path"
    assert results[0]["file_path"] == ""


@pytest.mark.asyncio
async def test_upload_missing_file_returns_error(tmp_path):
    drive = _drive_mock(AsyncMock(return_value={"file_token": "x"}))
    svc = UploadService(drive)

    missing = tmp_path / "does_not_exist.pdf"
    results = await svc.upload([str(missing)])

    assert len(results) == 1
    assert results[0]["status"] == "error"
    assert results[0]["error"] == "file_not_found"
    assert results[0]["file_path"] == str(missing)
    # Drive client should NOT have been invoked for a missing file
    drive.upload_file.assert_not_called()


@pytest.mark.asyncio
async def test_upload_single_file_success(tmp_path):
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"%PDF-1.4\nfake")

    drive = _drive_mock(
        AsyncMock(
            return_value={
                "file_token": "boxcnxxx",
                "url": "https://feishu.cn/drive/file/boxcnxxx",
                "name": "doc.pdf",
            }
        )
    )
    svc = UploadService(drive)

    results = await svc.upload([str(f)])

    assert len(results) == 1
    entry = results[0]
    assert entry["status"] == "ok"
    assert entry["file_token"] == "boxcnxxx"
    assert entry["url"] == "https://feishu.cn/drive/file/boxcnxxx"
    assert entry["name"] == "doc.pdf"
    assert entry["file_path"] == str(f)


@pytest.mark.asyncio
async def test_upload_no_file_token_returns_error(tmp_path):
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"x")

    # Drive returned an empty payload
    drive = _drive_mock(AsyncMock(return_value={}))
    svc = UploadService(drive)

    results = await svc.upload([str(f)])

    assert results[0]["status"] == "error"
    assert results[0]["error"] == "no_file_token_returned"


@pytest.mark.asyncio
async def test_upload_drive_raises_is_caught(tmp_path):
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"x")

    async def boom(_path):
        raise RuntimeError("lark-cli died")

    drive = _drive_mock(boom)
    svc = UploadService(drive)

    results = await svc.upload([str(f)])

    assert results[0]["status"] == "error"
    assert "lark-cli died" in results[0]["error"]


@pytest.mark.asyncio
async def test_upload_batch_partial_failure(tmp_path):
    """One file failing must not abort the rest of the batch."""
    good1 = tmp_path / "a.pdf"
    good1.write_bytes(b"a")
    bad = tmp_path / "does_not_exist.pdf"
    good2 = tmp_path / "b.pdf"
    good2.write_bytes(b"b")

    async def upload(path):
        if "a.pdf" in path:
            return {
                "file_token": "tok-a",
                "url": "https://feishu/a",
                "name": "a.pdf",
            }
        if "b.pdf" in path:
            return {
                "file_token": "tok-b",
                "url": "https://feishu/b",
                "name": "b.pdf",
            }
        raise AssertionError(f"unexpected path: {path}")

    drive = _drive_mock(upload)
    svc = UploadService(drive)

    results = await svc.upload([str(good1), str(bad), str(good2)])

    assert len(results) == 3

    # First: ok
    assert results[0]["status"] == "ok"
    assert results[0]["file_token"] == "tok-a"

    # Middle: missing → error, drive never called for it
    assert results[1]["status"] == "error"
    assert results[1]["error"] == "file_not_found"

    # Last: ok — proves the batch didn't abort
    assert results[2]["status"] == "ok"
    assert results[2]["file_token"] == "tok-b"


@pytest.mark.asyncio
async def test_upload_falls_back_to_basename_when_name_missing(tmp_path):
    f = tmp_path / "original-name.pdf"
    f.write_bytes(b"x")

    drive = _drive_mock(
        AsyncMock(return_value={"file_token": "tok", "url": "u"})
    )
    svc = UploadService(drive)

    results = await svc.upload([str(f)])

    assert results[0]["status"] == "ok"
    # No `name` from drive → use basename of input path
    assert results[0]["name"] == "original-name.pdf"