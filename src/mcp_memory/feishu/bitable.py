"""Bitable CRUD via lark-cli subprocess (v2 protocol).

v2 protocol notes:
  * ``+record-upsert`` is the unified create+update command.
    - Without ``--record-id`` → creates a new record.
    - With ``--record-id`` → updates the existing record.
  * Field maps use the ``--json`` flag with the direct field map (no ``fields``
    wrapper).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from mcp_memory.feishu.runner import LarkCliRunner, LarkCliError


@dataclass
class BitableRecord:
    id: str
    fields: dict[str, Any] = field(default_factory=dict)

    def to_api_dict(self) -> dict:
        fields_clean = {k: v for k, v in self.fields.items() if v is not None}
        return {"record_id": self.id, "fields": fields_clean}

    @classmethod
    def from_api(cls, api: dict) -> "BitableRecord":
        rid = api.get("record_id") or api.get("id") or ""
        return cls(id=rid, fields=api.get("fields", {}))


class BitableClient:
    """Bitable high-level API, all calls go through lark-cli v2."""

    def __init__(self, runner: LarkCliRunner, app_token: str, table_id: str):
        self.runner = runner
        self.app_token = app_token
        self.table_id = table_id

    async def list_records(
        self,
        updated_after_ms: int | None = None,
        page_size: int = 200,
    ) -> list[BitableRecord]:
        """List records (paged). v2 uses offset/limit; no explicit time filter.

        ``updated_after_ms`` is accepted for API stability but filtering by
        timestamp is left to the caller (we just return all rows and the caller
        decides what to ingest).
        """
        out: list[BitableRecord] = []
        offset = 0
        while True:
            args = [
                "base", "+record-list",
                "--base-token", self.app_token,
                "--table-id", self.table_id,
                "--limit", str(page_size),
                "--offset", str(offset),
                "--format", "json",
            ]
            try:
                result = self.runner.run(args)
            except LarkCliError as e:
                if "not_found" in str(e).lower():
                    return out
                raise
            records = self._parse_v2_list(result)
            if not records:
                break

            out.extend(records)

            # Pagination: rely on `has_more` flag (v2), fall back to size check
            has_more = False
            if isinstance(result, dict):
                data_block = result.get("data")
                if isinstance(data_block, dict):
                    has_more = bool(data_block.get("has_more", False))
            if not has_more and len(records) < page_size:
                break
            offset += page_size
        return out

    async def get_record(self, record_id: str) -> BitableRecord | None:
        try:
            result = self.runner.run([
                "base", "+record-get",
                "--base-token", self.app_token,
                "--table-id", self.table_id,
                "--record-id", record_id,
                "--format", "json",
            ])
        except LarkCliError:
            return None
        records = self._parse_v2_list(result, single=True)
        if not records:
            return None
        return records[0]

    async def create_record(self, fields: dict) -> BitableRecord:
        """v2: ``+record-upsert`` without ``--record-id`` creates a new record."""
        result = self.runner.run([
            "base", "+record-upsert",
            "--base-token", self.app_token,
            "--table-id", self.table_id,
            "--json", json.dumps(fields),
            "--format", "json",
        ])
        rid = self._extract_record_id(result) or ""
        return BitableRecord(id=rid, fields=fields)

    async def batch_update(self, record_id: str, fields: dict) -> BitableRecord:
        """v2: ``+record-upsert`` WITH ``--record-id`` updates the existing record."""
        self.runner.run([
            "base", "+record-upsert",
            "--base-token", self.app_token,
            "--table-id", self.table_id,
            "--record-id", record_id,
            "--json", json.dumps(fields),
            "--format", "json",
        ])
        return BitableRecord(id=record_id, fields=fields)

    async def delete_record(self, record_id: str) -> bool:
        try:
            self.runner.run([
                "base", "+record-delete",
                "--base-token", self.app_token,
                "--table-id", self.table_id,
                "--record-id", record_id,
                "--yes",
            ])
            return True
        except LarkCliError:
            return False

    @staticmethod
    def _parse_v2_list(result: Any, single: bool = False) -> list[BitableRecord]:
        """Parse v2 lark-cli Bitable list/get response into BitableRecord list.

        v2 response shape (verified against real CLI):
            {
              "ok": true,
              "data": {
                "data": [            # parallel array of value rows
                  [v1, v2, v3, ...],  # row 1, in same order as fields
                  ...
                ],
                "fields": [...],     # parallel array of field names
                "field_id_list": [...], # parallel array of field IDs
                "record_id_list": [...],  # parallel array of record IDs
                "has_more": bool,
                ...
              }
            }
        """
        if isinstance(result, list):
            # Legacy: list at top level
            records = BitableClient._extract_items_list(result)
            if single and records:
                return records[:1]
            return records
        if not isinstance(result, dict):
            return []
        data = result.get("data")
        if not isinstance(data, dict):
            # Fallback: maybe list at top level
            if isinstance(data, list):
                records = BitableClient._extract_items_list(data)
                if single and records:
                    return records[:1]
                return records
            return []

        # v2 parallel-array shape
        rows = data.get("data")
        fields = data.get("fields") or data.get("field_id_list")
        record_ids = data.get("record_id_list") or []

        if not isinstance(rows, list) or not isinstance(fields, list):
            return []

        records = []
        for i, row in enumerate(rows):
            if not isinstance(row, list):
                continue
            # Build {field_name: value} dict
            fmap = {}
            for j, fname in enumerate(fields):
                if j < len(row):
                    fmap[fname] = row[j]
            rid = record_ids[i] if i < len(record_ids) else ""
            records.append(BitableRecord(id=rid, fields=fmap))

        if single and records:
            return records[:1]
        return records

    @staticmethod
    def _extract_items_list(items: list) -> list[BitableRecord]:
        """Legacy fallback for v1-style item lists."""
        out: list[BitableRecord] = []
        for r in items:
            if not isinstance(r, dict):
                continue
            rid = r.get("record_id") or r.get("id") or ""
            fmap = r.get("fields") or {}
            if isinstance(fmap, str):
                try:
                    fmap = json.loads(fmap)
                except json.JSONDecodeError:
                    fmap = {}
            out.append(BitableRecord(id=rid, fields=fmap))
        return out

    @staticmethod
    def _extract_record_id(result: Any) -> str | None:
        """Extract newly created record_id from ``+record-upsert`` response."""
        if not isinstance(result, dict):
            return None
        if result.get("record_id"):
            return result["record_id"]
        record = result.get("record")
        if isinstance(record, dict):
            if record.get("record_id"):
                return record["record_id"]
            # v2 +record-upsert actually returns record_id_list (list of one)
            rid_list = record.get("record_id_list")
            if isinstance(rid_list, list) and rid_list:
                return rid_list[0]
        data = result.get("data")
        if isinstance(data, dict):
            if data.get("record_id"):
                return data["record_id"]
            nested = data.get("record")
            if isinstance(nested, dict):
                if nested.get("record_id"):
                    return nested["record_id"]
                rid_list = nested.get("record_id_list")
                if isinstance(rid_list, list) and rid_list:
                    return rid_list[0]
        return None