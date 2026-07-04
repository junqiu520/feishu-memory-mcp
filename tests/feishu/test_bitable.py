from unittest.mock import MagicMock
import pytest
from mcp_memory.feishu.bitable import BitableClient, BitableRecord
from mcp_memory.feishu.runner import LarkCliRunner


@pytest.fixture
def mock_runner():
    client = MagicMock(spec=LarkCliRunner)
    return client


def test_bitable_record_to_api_dict():
    r = BitableRecord(
        id="rec_123",
        fields={"title": "T", "tags": ["a", "b"], "preview": None},
    )
    api_dict = r.to_api_dict()
    assert api_dict["record_id"] == "rec_123"
    assert api_dict["fields"]["title"] == "T"
    assert api_dict["fields"]["tags"] == ["a", "b"]
    assert "preview" not in api_dict["fields"]


def test_bitable_record_from_api():
    api = {
        "record_id": "rec_123",
        "fields": {"title": "T", "tags": ["a"]},
    }
    r = BitableRecord.from_api(api)
    assert r.id == "rec_123"
    assert r.fields["title"] == "T"


def test_bitable_client_holds_app_and_table(mock_runner):
    client = BitableClient(
        runner=mock_runner,
        app_token="bitA_xxx",
        table_id="tblA_xxx",
    )
    assert client.app_token == "bitA_xxx"
    assert client.table_id == "tblA_xxx"
    assert client.runner is mock_runner
