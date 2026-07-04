"""Live E2E test — runs against real Feishu.

Marked with @pytest.mark.live so it does NOT run in regular CI.
To run manually:
    FEISHU_APP_ID=... FEISHU_APP_SECRET=... \
    MEMORY_BITABLE_APP_TOKEN=... MEMORY_BITABLE_TABLE_ID=... \
    pytest -m live tests/feishu/test_bitable_live.py -v

This validates the full BitableClient + lark-cli v2 protocol against a real
Feishu tenant. It was used during the v1->v2 migration and subsequent bug fixes.
"""
import asyncio
import os
import uuid

import pytest
from dotenv import load_dotenv

load_dotenv('.env')

from mcp_memory.feishu.runner import LarkCliRunner
from mcp_memory.feishu.bitable import BitableClient

pytestmark = pytest.mark.live


@pytest.fixture
def client():
    app_token = os.environ.get('MEMORY_BITABLE_APP_TOKEN')
    table_id = os.environ.get('MEMORY_BITABLE_TABLE_ID')
    if not app_token or not table_id:
        pytest.skip("MEMORY_BITABLE_APP_TOKEN / MEMORY_BITABLE_TABLE_ID not set")
    runner = LarkCliRunner()
    return BitableClient(runner, app_token, table_id)


@pytest.mark.asyncio
async def test_live_list_records(client):
    records = await client.list_records()
    assert isinstance(records, list)


@pytest.mark.asyncio
async def test_live_create_and_delete(client):
    # Use a unique title to avoid duplicates
    unique = f"live-test-{uuid.uuid4().hex[:8]}"
    fields = {
        'title': unique,
        'preview': 'live e2e test',
        'source': 'agent_add',
        'origin': 'manual',
        'tags': ['untagged'],
        'source_agent': 'live-test',
        'text_empty': False,
        'created_at': '2026-07-03 08:00',
        'updated_at': '2026-07-03 08:00',
    }
    rec = await client.create_record(fields)
    assert rec.id

    # Read it back
    got = await client.get_record(rec.id)
    assert got is not None
    assert got.fields.get('title') == unique

    # Update
    upd = await client.batch_update(rec.id, {'title': f'{unique}-updated'})
    assert upd.id == rec.id

    # Verify update
    got2 = await client.get_record(rec.id)
    assert got2.fields.get('title') == f'{unique}-updated'

    # Cleanup
    deleted = await client.delete_record(rec.id)
    assert deleted
