"""MemoryRecord 数据类（spec §3.3）。"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal
import uuid


class SourceType(str, Enum):
    AGENT_ADD = "agent_add"
    FEISHU_DOC = "feishu_doc"
    FEISHU_BITABLE = "feishu_bitable"
    FEISHU_DRIVE_FILE = "feishu_drive_file"
    FEISHU_WIKI = "feishu_wiki"


@dataclass
class FeishuRef:
    """飞书资源引用。"""
    type: Literal["docx", "bitable", "drive_file", "wiki"]
    token: str
    url: str
    last_modified_version: int = 0


@dataclass
class FeishuFileRef:
    """用于 memory_add 时 file_ref 入参。"""
    type: Literal["drive_file"] = "drive_file"
    token: str = ""
    url: str = ""
    file_name: str | None = None
    mime_type: str | None = None


@dataclass
class MemoryMetadata:
    tags: list[str] = field(default_factory=list)
    source_user: str | None = None
    source_agent: str | None = None
    origin: Literal["manual", "auto_sync"] = "manual"
    extra: dict[str, str] = field(default_factory=dict)


@dataclass
class MemoryRecord:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source: SourceType = SourceType.AGENT_ADD
    title: str = ""
    preview: str = ""
    text: str = ""
    content_hash: str = ""
    content_ref: FeishuRef | None = None
    file_ref: FeishuFileRef | None = None
    metadata: MemoryMetadata = field(default_factory=MemoryMetadata)
    text_empty: bool = False
    created_at: int = 0
    updated_at: int = 0

    def to_row(self) -> dict:
        import json
        import time
        if self.created_at == 0:
            self.created_at = int(time.time())
        self.updated_at = int(time.time())
        return {
            "id": self.id,
            "source": self.source.value,
            "title": self.title,
            "preview": self.preview,
            "text": self.text,
            "content_hash": self.content_hash,
            "content_ref_type": self.content_ref.type if self.content_ref else None,
            "content_ref_token": self.content_ref.token if self.content_ref else None,
            "content_ref_url": self.content_ref.url if self.content_ref else None,
            "file_ref_json": json.dumps(self.file_ref.__dict__) if self.file_ref else None,
            "tags_json": json.dumps(self.metadata.tags),
            "source_user": self.metadata.source_user,
            "source_agent": self.metadata.source_agent,
            "origin": self.metadata.origin,
            "extra_json": json.dumps(self.metadata.extra),
            "text_empty": 1 if self.text_empty else 0,
            "embedding_status": "pending",
            "sync_status": "synced",
            "last_attempt_at": None,
            "token_count": None,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
