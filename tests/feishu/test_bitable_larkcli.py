import json
import pytest
from unittest.mock import MagicMock
from mcp_memory.feishu.bitable import BitableClient, BitableRecord
from mcp_memory.feishu.runner import LarkCliRunner


@pytest.fixture
def mock_runner():
    r = MagicMock(spec=LarkCliRunner)
    return r


def test_list_records_parses_v2_parallel_array(mock_runner):
    """v2 +record-list returns parallel arrays (data + record_id_list + fields)."""
    mock_runner.run.return_value = {
        "data": {
            "data": [
                ["T1"],
                ["T2"],
            ],
            "fields": ["title"],
            "field_id_list": ["fld1", "fld2"],
            "record_id_list": ["rec_1", "rec_2"],
            "has_more": False,
        }
    }
    client = BitableClient(mock_runner, "bitA", "tblA")
    import asyncio
    records = asyncio.run(client.list_records())

    assert len(records) == 2
    assert records[0].id == "rec_1"
    assert records[0].fields["title"] == "T1"
    assert records[1].id == "rec_2"
    assert records[1].fields["title"] == "T2"
    # Verify the call uses lark-cli's record-list command
    args = mock_runner.run.call_args[0][0]
    assert args[0] == "base"
    assert args[1] == "+record-list"
    assert "--base-token" in args
    assert "bitA" in args


def test_list_records_handles_list_response(mock_runner):
    """lark-cli sometimes returns a list directly (legacy / unrolled)."""
    mock_runner.run.return_value = [
        {"record_id": "rec_1", "fields": {"title": "T"}}
    ]
    client = BitableClient(mock_runner, "bit", "tbl")
    import asyncio
    records = asyncio.run(client.list_records())
    assert len(records) == 1


def test_list_records_handles_pagination(mock_runner):
    """v2 paginated: each call returns rows <= page_size."""
    page1 = {
        "data": {
            "data": [["v"] for _ in range(100)],
            "fields": ["title"],
            "record_id_list": [f"rec_{i}" for i in range(100)],
            "has_more": True,
        }
    }
    page2 = {
        "data": {
            "data": [["last"]],
            "fields": ["title"],
            "record_id_list": ["rec_last"],
            "has_more": False,
        }
    }
    mock_runner.run.side_effect = [page1, page2]
    client = BitableClient(mock_runner, "bit", "tbl")
    import asyncio
    records = asyncio.run(client.list_records())

    assert len(records) == 101
    assert mock_runner.run.call_count == 2


def test_get_record(mock_runner):
    """v2 +record-get returns parallel arrays (data + record_id_list)."""
    mock_runner.run.return_value = {
        "data": {
            "data": [["v"]],
            "fields": ["k"],
            "record_id_list": ["rec_x"],
        }
    }
    client = BitableClient(mock_runner, "bit", "tbl")
    import asyncio
    r = asyncio.run(client.get_record("rec_x"))

    assert r is not None
    assert r.id == "rec_x"
    assert r.fields["k"] == "v"


def test_get_record_returns_none_for_missing(mock_runner):
    from mcp_memory.feishu.runner import LarkCliError
    mock_runner.run.side_effect = LarkCliError("not found")
    client = BitableClient(mock_runner, "bit", "tbl")
    import asyncio
    r = asyncio.run(client.get_record("rec_x"))
    assert r is None


def test_create_record_uses_upsert_v2(mock_runner):
    """v2: create goes through ``+record-upsert`` without ``--record-id``."""
    # v2 upsert response shape: data.record.record_id_list[0]
    mock_runner.run.return_value = {
        "data": {
            "record": {
                "record_id_list": ["new_id"],
            }
        }
    }
    client = BitableClient(mock_runner, "bit", "tbl")
    import asyncio
    rec = asyncio.run(client.create_record({"title": "X"}))

    assert rec.id == "new_id"
    args = mock_runner.run.call_args[0][0]
    assert "+record-upsert" in args
    # v2: --json (direct field map), not --fields-json
    assert "--json" in args
    assert "--fields-json" not in args
    # No --record-id → upsert creates a new record
    assert "--record-id" not in args
    assert "+record-create" not in args


def test_create_record_uses_v2_direct_json_format(mock_runner):
    """v2: --json value is the direct field map (no ``fields`` wrapper)."""
    mock_runner.run.return_value = {"record_id": "x"}
    client = BitableClient(mock_runner, "bit", "tbl")
    import asyncio
    fields = {"title": "T", "tags": ["a"], "checkbox_field": True}
    asyncio.run(client.create_record(fields))

    args = mock_runner.run.call_args[0][0]
    idx = args.index("--json")
    payload = json.loads(args[idx + 1])
    assert payload == fields
    assert "fields" not in payload


def test_create_record_extracts_record_id_from_response(mock_runner):
    """v2: ``+record-upsert`` returns the new record_id at the top level."""
    mock_runner.run.return_value = {"record_id": "rec_new_42"}
    client = BitableClient(mock_runner, "bit", "tbl")
    import asyncio
    r = asyncio.run(client.create_record({"title": "T"}))

    assert r.id == "rec_new_42"


def test_create_record_extracts_record_id_from_nested_data(mock_runner):
    """Some responses nest the record under ``data.record_id``."""
    mock_runner.run.return_value = {"data": {"record_id": "rec_nested_1"}}
    client = BitableClient(mock_runner, "bit", "tbl")
    import asyncio
    r = asyncio.run(client.create_record({"title": "T"}))

    assert r.id == "rec_nested_1"


def test_delete_record_uses_yes_flag(mock_runner):
    """v2: ``+record-delete`` is high-risk; we embed ``--yes`` directly in args."""
    mock_runner.run.return_value = {}
    client = BitableClient(mock_runner, "bit", "tbl")
    import asyncio
    ok = asyncio.run(client.delete_record("rec_1"))

    assert ok is True
    args = mock_runner.run.call_args[0][0]
    assert "--yes" in args
    assert "+record-delete" in args


def test_delete_record_returns_false_on_error(mock_runner):
    from mcp_memory.feishu.runner import LarkCliError
    mock_runner.run.side_effect = LarkCliError("not found")
    client = BitableClient(mock_runner, "bit", "tbl")
    import asyncio
    ok = asyncio.run(client.delete_record("rec_1"))
    assert ok is False


def test_batch_update_uses_upsert_with_record_id_v2(mock_runner):
    """v2: update uses ``+record-upsert`` WITH ``--record-id``."""
    mock_runner.run.return_value = {}
    client = BitableClient(mock_runner, "bit", "tbl")
    import asyncio
    r = asyncio.run(client.batch_update("rec_1", {"k": "v"}))

    args = mock_runner.run.call_args[0][0]
    assert "+record-upsert" in args
    assert "--record-id" in args
    idx = args.index("--record-id")
    assert args[idx + 1] == "rec_1"
    # v2: --json instead of --fields-json
    assert "--json" in args
    assert "--fields-json" not in args
    # v1 command name no longer used
    assert "+record-batch-update" not in args
    assert r.id == "rec_1"
    assert r.fields == {"k": "v"}


def test_batch_update_serializes_fields_directly(mock_runner):
    """v2: --json value is the direct field map (no ``fields`` wrapper)."""
    mock_runner.run.return_value = {}
    client = BitableClient(mock_runner, "bit", "tbl")
    import asyncio
    fields = {"tags": ["a", "b"], "title": "T", "count": 5}
    asyncio.run(client.batch_update("rec_1", fields))

    args = mock_runner.run.call_args[0][0]
    idx = args.index("--json")
    payload = json.loads(args[idx + 1])
    assert payload == fields
    assert "fields" not in payload