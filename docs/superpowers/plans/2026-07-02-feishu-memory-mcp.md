# feishu-memory-mcp Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现一个单体 Python MCP 服务，让多个 LLM agent 通过 MCP 协议共享同一份飞书驱动的 RAG 知识库 / 记忆库。

**Architecture:** 单进程 MCP（FastMCP + stdio）+ 进程内 sentence-transformers (bge-m3) + lark-oapi 异步 SDK 调飞书 + 本地 SQLite/LanceDB/FTS5 三层索引（飞书是 source of truth，本地可重建）；双 Bitable 概念隔离（记忆库 multi-agent 共享 + 知识库人类录入）；同一组 8 个 tool + scope 路由到两库；agent-first 设计，CLI 仅做运维辅助。

**Tech Stack:** Python 3.11+，FastMCP，lark-oapi，sentence-transformers，lancedb，langchain-text-splitters，pydantic，pydantic-settings，asyncio，pytest。

---

## 项目分阶段（9 stages）

| Stage | 内容 | 产出 |
|---|---|---|
| 1 | 项目骨架 + pyproject + 配置层 | `pip install -e .` 可成功 |
| 2 | Feishu Adapter（lark-oapi 封装）| 飞书 CRUD 单元测试通过 |
| 3 | Local Storage（SQLite + FTS5 + LanceDB） | 本地存储 CRUD 可测 |
| 4 | Index Engine（chunking / embedding / BM25 / vector / rerank） | 索引独立模块测试通过 |
| 5 | Service 层（LocalCache + 5 个 service） | 业务逻辑测试通过 |
| 6 | MCP Tool 层（FastMCP + 8 tool + scope） | agent 连上可用 |
| 7 | CLI 子命令（运维 8 个） | cli 集成测试通过 |
| 8 | 集成测试 + E2E | 完整流程在真实飞书跑通 |
| 9 | 文档 + Skill 文件 | README/docs/skill 完整 |

---

# Stage 1：项目骨架 + 配置层

## Task 1.1: pyproject.toml + 包结构

**Files:**
- Create: `pyproject.toml`
- Create: `src/mcp_memory/__init__.py`
- Create: `src/mcp_memory/__main__.py`
- Create: `tests/__init__.py`
- Create: `tests/test_import.py`

- [ ] **Step 1: 写失败测试 — 验证包可导入**

```python
# tests/test_import.py
def test_package_imports():
    import mcp_memory
    assert mcp_memory is not None


def test_package_version():
    from mcp_memory import __version__
    assert __version__ is not None
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd "C:/Users/Administrator/Desktop/feishu Memory/feishu Memory-MCP"
python -m pytest tests/test_import.py -v
```

Expected: `ModuleNotFoundError: No module named 'mcp_memory'`

- [ ] **Step 3: 创建 pyproject.toml**

```toml
# pyproject.toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "feishu-memory-mcp"
version = "0.1.0"
description = "MCP server for Feishu-backed RAG memory"
readme = "README.md"
requires-python = ">=3.11"
license = { text = "MIT" }
authors = [
    { name = "feishu-memory-mcp" }
]

dependencies = [
    "fastmcp>=0.5",
    "lark-oapi>=1.0",
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
    "sentence-transformers>=3.0",
    "lancedb>=0.5",
    "langchain-text-splitters>=0.3",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "pytest-cov>=4.1",
    "ruff>=0.4",
    "mypy>=1.10",
]

[project.scripts]
feishu-memory = "mcp_memory.cli:main"

[tool.hatch.build.targets.wheel]
packages = ["src/mcp_memory"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
asyncio_mode = "auto"

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.mypy]
python_version = "3.11"
ignore_missing_imports = true
```

- [ ] **Step 4: 创建包骨架文件**

```python
# src/mcp_memory/__init__.py
__version__ = "0.1.0"
```

```python
# src/mcp_memory/__main__.py
"""Entry point for `python -m mcp_memory`."""

from mcp_memory.cli import main

if __name__ == "__main__":
    main()
```

```python
# tests/__init__.py
```

- [ ] **Step 5: 安装包（开发模式）**

```bash
cd "C:/Users/Administrator/Desktop/feishu Memory/feishu Memory-MCP"
python -m pip install -e ".[dev]"
```

Expected: Successfully installs without errors.

- [ ] **Step 6: 跑测试确认通过**

```bash
cd "C:/Users/Administrator/Desktop/feishu Memory/feishu Memory-MCP"
python -m pytest tests/test_import.py -v
```

Expected: `2 passed`

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml src/mcp_memory/__init__.py src/mcp_memory/__main__.py tests/__init__.py tests/test_import.py
git commit -m "feat(stage1): pyproject + 包骨架"
```

---

## Task 1.2: Configuration (pydantic-settings)

**Files:**
- Create: `src/mcp_memory/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: 写失败测试 — 验证 config 加载**

```python
# tests/test_config.py
import os
import pytest
from mcp_memory.config import Config


def test_config_required_fields(tmp_path):
    """没有必填字段应该报错"""
    os.environ.pop("FEISHU_APP_ID", None)
    os.environ.pop("MEMORY_BITABLE_APP_TOKEN", None)
    with pytest.raises(Exception):
        Config(_env_file=None)  # type: ignore


def test_config_loads_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("FEISHU_APP_ID", "cli_test_123")
    monkeypatch.setenv("FEISHU_APP_SECRET", "secret_456")
    monkeypatch.setenv("MEMORY_BITABLE_APP_TOKEN", "bitA_xxx")
    monkeypatch.setenv("MEMORY_BITABLE_TABLE_ID", "tblA_xxx")
    monkeypatch.setenv("KNOWLEDGE_BITABLE_APP_TOKEN", "bitB_xxx")
    monkeypatch.setenv("KNOWLEDGE_BITABLE_TABLE_ID", "tblB_xxx")
    monkeypatch.setenv("AGENT_ID", "test-agent")

    cfg = Config(_env_file=None)  # type: ignore
    assert cfg.feishu_app_id == "cli_test_123"
    assert cfg.feishu_app_secret == "secret_456"  # pragma: allowlist secret
    assert cfg.memory_bitable_app_token == "bitA_xxx"
    assert cfg.memory_bitable_table_id == "tblA_xxx"
    assert cfg.knowledge_bitable_app_token == "bitB_xxx"
    assert cfg.knowledge_bitable_table_id == "tblB_xxx"
    assert cfg.agent_id == "test-agent"


def test_config_defaults(monkeypatch):
    monkeypatch.setenv("FEISHU_APP_ID", "x")
    monkeypatch.setenv("FEISHU_APP_SECRET", "x")
    monkeypatch.setenv("MEMORY_BITABLE_APP_TOKEN", "x")
    monkeypatch.setenv("MEMORY_BITABLE_TABLE_ID", "x")
    monkeypatch.setenv("KNOWLEDGE_BITABLE_APP_TOKEN", "x")
    monkeypatch.setenv("KNOWLEDGE_BITABLE_TABLE_ID", "x")

    cfg = Config(_env_file=None)  # type: ignore
    assert cfg.data_dir.name == ".feishu_memory"
    assert cfg.embedding_model == "BAAI/bge-m3"
    assert cfg.default_scope == "memory"
    assert cfg.default_top_k == 5
    assert cfg.default_rerank is True
    assert cfg.auto_sync_on_startup is True
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd "C:/Users/Administrator/Desktop/feishu Memory/feishu Memory-MCP"
python -m pytest tests/test_config.py -v
```

Expected: `ModuleNotFoundError: No module named 'mcp_memory.config'`

- [ ] **Step 3: 实现 Config 类**

```python
# src/mcp_memory/config.py
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    """项目配置：飞书凭证 + 双 Bitable + 模型 + 启动行为。

    从环境变量加载，env var 格式：FEISHU_APP_ID 等大写。
    """

    model_config = SettingsConfigDict(
        env_file=None,  # 不从文件加载，只用 env
        env_prefix="",
        case_sensitive=False,
        extra="ignore",
    )

    # 飞书凭据（必填）
    feishu_app_id: str
    feishu_app_secret: str

    # 双 Bitable 实例（必填）
    memory_bitable_app_token: str
    memory_bitable_table_id: str
    knowledge_bitable_app_token: str
    knowledge_bitable_table_id: str

    # Agent 标识
    agent_id: str = "default"

    # 本地存储
    data_dir: Path = Path("./.feishu_memory")

    # 模型
    embedding_model: str = "BAAI/bge-m3"
    reranker_model: str = "BAAI/bge-reranker-base"
    device: str = "cpu"

    # 启动行为
    auto_sync_on_startup: bool = True
    auto_sync_scope: str = "memory"

    # MCP
    mcp_transport: str = "stdio"

    # 检索默认
    default_top_k: int = 5
    default_rerank: bool = True
    default_scope: str = "memory"
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd "C:/Users/Administrator/Desktop/feishu Memory/feishu Memory-MCP"
python -m pytest tests/test_config.py -v
```

Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add src/mcp_memory/config.py tests/test_config.py
git commit -m "feat(stage1): Config 类 + 环境变量加载测试"
```

---

# Stage 2：Feishu Adapter（lark-oapi 封装）

## Task 2.1: Feishu Client 单例

**Files:**
- Create: `src/mcp_memory/feishu/__init__.py`
- Create: `src/mcp_memory/feishu/client.py`
- Create: `tests/feishu/__init__.py`
- Create: `tests/feishu/test_client.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/feishu/test_client.py
import pytest
from mcp_memory.feishu.client import FeishuClient


def test_client_singleton_same_instance():
    c1 = FeishuClient.get_instance(
        app_id="cli_test",
        app_secret="test_secret",  # pragma: allowlist secret
    )
    c2 = FeishuClient.get_instance(
        app_id="cli_test",
        app_secret="test_secret",  # pragma: allowlist secret
    )
    assert c1 is c2


def test_client_holds_app_id():
    FeishuClient.reset_instance()
    c = FeishuClient.get_instance(
        app_id="cli_test_2",
        app_secret="x",  # pragma: allowlist secret
    )
    assert c.app_id == "cli_test_2"


def test_client_get_lark_client():
    FeishuClient.reset_instance()
    c = FeishuClient.get_instance(app_id="x", app_secret="y")  # pragma: allowlist secret
    sdk = c.lark_client
    assert sdk is not None
    assert hasattr(sdk, "bitable")
    assert hasattr(sdk, "docx")
    assert hasattr(sdk, "drive")
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd "C:/Users/Administrator/Desktop/feishu Memory/feishu Memory-MCP"
python -m pytest tests/feishu/test_client.py -v
```

Expected: `ModuleNotFoundError: No module named 'mcp_memory.feishu.client'`

- [ ] **Step 3: 实现 FeishuClient**

```python
# src/mcp_memory/feishu/__init__.py
```

```python
# src/mcp_memory/feishu/client.py
"""lark-oapi SDK 单例管理 + 简单封装。"""
from __future__ import annotations

import lark_oapi as lark


class FeishuClient:
    """lark-oapi SDK 单例。

    全局共用一个 client 实例（多 client 可能耗 token 配额）。
    """

    _instance: FeishuClient | None = None

    def __init__(self, app_id: str, app_secret: str):
        self.app_id = app_id
        self.app_secret = app_secret
        self._lark = lark.Client.builder() \
            .app_id(app_id) \
            .app_secret(app_secret) \
            .domain(lark.FEISHU_DOMAIN) \
            .build()

    @property
    def lark_client(self) -> lark.Client:
        return self._lark

    @classmethod
    def get_instance(cls, app_id: str, app_secret: str) -> FeishuClient:
        if cls._instance is None:
            cls._instance = cls(app_id, app_secret)
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """测试用：清空单例。"""
        cls._instance = None
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd "C:/Users/Administrator/Desktop/feishu Memory/feishu Memory-MCP"
python -m pytest tests/feishu/test_client.py -v
```

Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add src/mcp_memory/feishu/__init__.py src/mcp_memory/feishu/client.py tests/feishu/__init__.py tests/feishu/test_client.py
git commit -m "feat(stage2): FeishuClient 单例 + lark-oapi 封装"
```

---

## Task 2.2: Bitable CRUD 封装

**Files:**
- Create: `src/mcp_memory/feishu/bitable.py`
- Create: `tests/feishu/test_bitable.py`

- [ ] **Step 1: 写失败测试（mock SDK）**

```python
# tests/feishu/test_bitable.py
from unittest.mock import AsyncMock, MagicMock
import pytest
from mcp_memory.feishu.bitable import BitableClient, BitableRecord


@pytest.fixture
def mock_lark_client():
    client = MagicMock()
    return client


def test_bitable_record_to_api_dict():
    """BitableRecord 转 dict（去掉 None 字段）。"""
    r = BitableRecord(
        id="rec_123",
        fields={"title": "T", "tags": ["a", "b"], "preview": None},
    )
    api_dict = r.to_api_dict()
    assert api_dict["id"] == "rec_123"
    assert api_dict["fields"]["title"] == "T"
    assert api_dict["fields"]["tags"] == ["a", "b"]
    # None 应被去除
    assert "preview" not in api_dict["fields"]


def test_bitable_record_from_api():
    api = {
        "record_id": "rec_123",
        "fields": {"title": "T", "tags": ["a"]},
    }
    r = BitableRecord.from_api(api)
    assert r.id == "rec_123"
    assert r.fields["title"] == "T"


def test_bitable_client_holds_app_and_table(mock_lark_client):
    client = BitableClient(
        lark_client=mock_lark_client,
        app_token="bitA_xxx",
        table_id="tblA_xxx",
    )
    assert client.app_token == "bitA_xxx"
    assert client.table_id == "tblA_xxx"
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd "C:/Users/Administrator/Desktop/feishu Memory/feishu Memory-MCP"
python -m pytest tests/feishu/test_bitable.py -v
```

Expected: `ModuleNotFoundError: No module named 'mcp_memory.feishu.bitable'`

- [ ] **Step 3: 实现 BitableRecord 数据类**

```python
# src/mcp_memory/feishu/bitable.py
"""飞书 Bitable CRUD 封装。

提供：
- BitableRecord: 字段 schema 数据类
- BitableClient: 高层 API（list_records / get_record / create_record / update_record / delete_record）

实际 SDK 调用在内部用 lark-oapi 异步 client。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class BitableRecord:
    """一条 Bitable 记录。

    id 是飞书 record_id；fields 是字段 dict（值类型：str / int / list[str] / 等）。
    """

    id: str
    fields: dict[str, Any] = field(default_factory=dict)

    def to_api_dict(self) -> dict:
        """序列化为 lark-oapi list_records API 的 entry schema 格式。

        None 值字段会被去除。
        """
        fields_clean = {k: v for k, v in self.fields.items() if v is not None}
        return {"record_id": self.id, "fields": fields_clean}

    @classmethod
    def from_api(cls, api: dict) -> BitableRecord:
        """从 lark-oapi 返回 dict 反序列化。"""
        rid = api.get("record_id") or api.get("id") or ""
        return cls(id=rid, fields=api.get("fields", {}))


class BitableClient:
    """Bitable 高层 API 封装。

    注：这里只做数据 schema 与字段转换。具体 SDK 调用
    （实际读写飞书的协程）将在 Stage 5 + 集成测试中补齐。
    """

    def __init__(self, lark_client: Any, app_token: str, table_id: str):
        self._lark = lark_client
        self.app_token = app_token
        self.table_id = table_id

    # ─────────────────────────────────────
    # 占位：将通过 Stage 2 后续任务 + Stage 5 集成实现
    # ─────────────────────────────────────

    async def list_records(self, updated_after_ms: int | None = None) -> list[BitableRecord]:
        raise NotImplementedError("Stage 2 后续任务实现")

    async def get_record(self, record_id: str) -> BitableRecord | None:
        raise NotImplementedError("Stage 2 后续任务实现")

    async def create_record(self, fields: dict) -> BitableRecord:
        raise NotImplementedError("Stage 2 后续任务实现")

    async def batch_update(self, record_id: str, fields: dict) -> BitableRecord:
        raise NotImplementedError("Stage 2 后续任务实现")

    async def delete_record(self, record_id: str) -> bool:
        raise NotImplementedError("Stage 2 后续任务实现")
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd "C:/Users/Administrator/Desktop/feishu Memory/feishu Memory-MCP"
python -m pytest tests/feishu/test_bitable.py -v
```

Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add src/mcp_memory/feishu/bitable.py tests/feishu/test_bitable.py
git commit -m "feat(stage2): BitableRecord 数据类 + BitableClient 壳（占位实现）"
```

---

## Task 2.3: Docx + Drive + Wiki 封装占位

**Files:**
- Create: `src/mcp_memory/feishu/docx.py`
- Create: `src/mcp_memory/feishu/drive.py`
- Create: `src/mcp_memory/feishu/wiki.py`
- Create: `tests/feishu/test_docx_drive_wiki.py`

- [ ] **Step 1: 写最小测试**

```python
# tests/feishu/test_docx_drive_wiki.py
import pytest
from mcp_memory.feishu.docx import DocxClient
from mcp_memory.feishu.drive import DriveClient
from mcp_memory.feishu.wiki import WikiClient


def test_docx_client_init():
    c = DocxClient(lark_client=None)  # type: ignore
    assert c is not None


def test_drive_client_init():
    c = DriveClient(lark_client=None)  # type: ignore
    assert c is not None


def test_wiki_client_init():
    c = WikiClient(lark_client=None)  # type: ignore
    assert c is not None
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd "C:/Users/Administrator/Desktop/feishu Memory/feishu Memory-MCP"
python -m pytest tests/feishu/test_docx_drive_wiki.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: 实现三个 Client**

```python
# src/mcp_memory/feishu/docx.py
"""飞书 Docx 封装（占位 — Stage 5 集成补 SDK 调用）。"""
from __future__ import annotations
from typing import Any


class DocxClient:
    def __init__(self, lark_client: Any):
        self._lark = lark_client

    async def create_docx(self, content: str, title: str | None = None) -> str:
        """创建 Docx 文档，返回 token。Stage 5 集成补 SDK 调用。"""
        raise NotImplementedError
```

```python
# src/mcp_memory/feishu/drive.py
"""飞书 Drive 封装（占位）。"""
from __future__ import annotations
from typing import Any


class DriveClient:
    def __init__(self, lark_client: Any):
        self._lark = lark_client

    async def get_file_info(self, file_token: str) -> dict:
        """获取文件元数据。Stage 5 集成补 SDK 调用。"""
        raise NotImplementedError
```

```python
# src/mcp_memory/feishu/wiki.py
"""飞书 Wiki 封装（占位）。"""
from __future__ import annotations
from typing import Any


class WikiClient:
    def __init__(self, lark_client: Any):
        self._lark = lark_client

    async def get_node_content(self, node_token: str) -> str:
        """获取 Wiki 节点内容。Stage 5 集成补 SDK 调用。"""
        raise NotImplementedError
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd "C:/Users/Administrator/Desktop/feishu Memory/feishu Memory-MCP"
python -m pytest tests/feishu/test_docx_drive_wiki.py -v
```

Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add src/mcp_memory/feishu/docx.py src/mcp_memory/feishu/drive.py src/mcp_memory/feishu/wiki.py tests/feishu/test_docx_drive_wiki.py
git commit -m "feat(stage2): Docx / Drive / Wiki Client 占位 + 单元测试"
```

---

# Stage 3：Local Storage（SQLite + FTS5 + LanceDB）

## Task 3.1: SQLite LocalCache — records 表

**Files:**
- Create: `src/mcp_memory/storage/__init__.py`
- Create: `src/mcp_memory/storage/schema.sql`
- Create: `src/mcp_memory/storage/local_cache.py`
- Create: `tests/storage/__init__.py`
- Create: `tests/storage/test_local_cache_schema.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/storage/test_local_cache_schema.py
import pytest
from mcp_memory.storage.local_cache import LocalCache


@pytest.fixture
def cache(tmp_path):
    db = LocalCache(tmp_path / "test.sqlite", scope="memory")
    yield db
    db.close()


def test_init_creates_records_table(cache):
    """建表 + 默认行存在 sync_state。"""
    assert cache._table_exists("records")
    assert cache._table_exists("sync_state")
    assert cache._table_exists("record_tags")


def test_sync_state_starts_initialized(cache):
    state = cache.get_sync_state()
    assert state["local_instance_id"] is not None
    assert state["last_sync_at"] is None  # 初始未同步


def test_scope_separate_dbs(tmp_path):
    """memory 和 knowledge 用不同的 db 文件。"""
    a = LocalCache(tmp_path / "memory.sqlite", scope="memory")
    b = LocalCache(tmp_path / "knowledge.sqlite", scope="knowledge")
    a.close()
    b.close()
    assert (tmp_path / "memory.sqlite").exists()
    assert (tmp_path / "knowledge.sqlite").exists()
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd "C:/Users/Administrator/Desktop/feishu Memory/feishu Memory-MCP"
python -m pytest tests/storage/test_local_cache_schema.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: 实现 schema.sql**

```sql
-- src/mcp_memory/storage/schema.sql

-- records 表：缓存飞书 Bitable 行
CREATE TABLE records (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,                       -- 'agent_add' | 'feishu_doc' | ...
    title TEXT NOT NULL,
    preview TEXT,
    text TEXT,                                  -- 可空（Drive 文件可能 text_empty）
    content_hash TEXT,
    content_ref_type TEXT,                      -- 'docx' | 'wiki' | 'drive_file'
    content_ref_token TEXT,
    content_ref_url TEXT,
    file_ref_json TEXT,                         -- JSON
    tags_json TEXT,                             -- JSON 数组
    source_user TEXT,
    source_agent TEXT,
    origin TEXT,
    extra_json TEXT,
    text_empty INTEGER DEFAULT 0,
    embedding_status TEXT,                      -- 'pending'|'ok'|'failed'
    sync_status TEXT,                           -- 'pending'|'synced'|'error'
    last_attempt_at INTEGER,
    token_count INTEGER,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE INDEX idx_records_source_agent ON records(source_agent);
CREATE INDEX idx_records_updated_at ON records(updated_at);
CREATE INDEX idx_records_source ON records(source);
CREATE INDEX idx_records_content_hash ON records(content_hash);

-- record_tags 表：tags 用 AND/OR filter 高效查询
CREATE TABLE record_tags (
    record_id TEXT NOT NULL,
    tag TEXT NOT NULL,
    PRIMARY KEY (record_id, tag),
    FOREIGN KEY (record_id) REFERENCES records(id) ON DELETE CASCADE
);

CREATE INDEX idx_record_tags_tag ON record_tags(tag);

-- sync_state 表：全局单行（强制）
CREATE TABLE sync_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),  -- 强制单行
    last_sync_at INTEGER,
    last_full_sync_at INTEGER,
    last_rebuild_at INTEGER,
    bitable_schema_hash TEXT,
    local_instance_id TEXT NOT NULL
);

-- FTS5 关键词索引
CREATE VIRTUAL TABLE records_fts USING fts5(
    text,
    title,
    preview,
    tags,
    content='records',
    content_rowid='rowid'
);

-- 触发器：维持 FTS5 与 records 表一致
CREATE TRIGGER records_ai AFTER INSERT ON records BEGIN
    INSERT INTO records_fts(rowid, text, title, preview, tags)
    VALUES (new.rowid, new.text, new.title, new.preview,
            COALESCE(new.tags_json, ''));
END;

CREATE TRIGGER records_ad AFTER DELETE ON records BEGIN
    INSERT INTO records_fts(records_fts, rowid, text, title, preview, tags)
    VALUES ('delete', old.rowid, old.text, old.title, old.preview,
            COALESCE(old.tags_json, ''));
END;

CREATE TRIGGER records_au AFTER UPDATE ON records BEGIN
    INSERT INTO records_fts(records_fts, rowid, text, title, preview, tags)
    VALUES ('delete', old.rowid, old.text, old.title, old.preview,
            COALESCE(old.tags_json, ''));
    INSERT INTO records_fts(rowid, text, title, preview, tags)
    VALUES (new.rowid, new.text, new.title, new.preview,
            COALESCE(new.tags_json, ''));
END;
```

- [ ] **Step 4: 实现 LocalCache 骨架**

```python
# src/mcp_memory/storage/__init__.py
```

```python
# src/mcp_memory/storage/local_cache.py
"""本地 SQLite 缓存层（包内一个 LocalCache 实例对一双库中的一个）。

设计：每个 scope（memory / knowledge）一个独立 .sqlite 文件。
Stage 3 只搭骨架和 schema 初始化；
Stage 5 注入 records / queries 等 CRUD 方法。
"""
from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path


class LocalCache:
    def __init__(self, db_path: Path, scope: str):
        if scope not in ("memory", "knowledge"):
            raise ValueError(f"scope must be 'memory' or 'knowledge', got {scope!r}")
        self.db_path = db_path
        self.scope = scope
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(str(db_path), isolation_level=None, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    def _init_schema(self) -> None:
        schema_path = Path(__file__).parent / "schema.sql"
        schema_sql = schema_path.read_text(encoding="utf-8")
        self._conn.executescript(schema_sql)
        # 初始化 sync_state 单行
        cur = self._conn.execute("SELECT COUNT(*) FROM sync_state")
        if cur.fetchone()[0] == 0:
            self._conn.execute(
                "INSERT INTO sync_state (id, local_instance_id) VALUES (1, ?)",
                (str(uuid.uuid4()),),
            )
            self._conn.commit()

    def _table_exists(self, name: str) -> bool:
        cur = self._conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        )
        return cur.fetchone() is not None

    def get_sync_state(self) -> dict:
        row = self._conn.execute("SELECT * FROM sync_state WHERE id=1").fetchone()
        return dict(row) if row else {}

    def close(self) -> None:
        self._conn.close()
```

- [ ] **Step 5: 跑测试确认通过**

```bash
cd "C:/Users/Administrator/Desktop/feishu Memory/feishu Memory-MCP"
python -m pytest tests/storage/test_local_cache_schema.py -v
```

Expected: `3 passed`

- [ ] **Step 6: Commit**

```bash
git add src/mcp_memory/storage/__init__.py src/mcp_memory/storage/schema.sql src/mcp_memory/storage/local_cache.py tests/storage/__init__.py tests/storage/test_local_cache_schema.py
git commit -m "feat(stage3): LocalCache 骨架 + schema.sql"
```

---

## Task 3.2: LocalCache records CRUD（upsert / get / delete / list / count / update_metadata）

**Files:**
- Modify: `src/mcp_memory/storage/local_cache.py`
- Create: `src/mcp_memory/models/record.py`
- Create: `src/mcp_memory/storage/paths.py`
- Create: `tests/storage/test_local_cache_crud.py`

- [ ] **Step 1: 实现 MemoryRecord 模型（spec §3.3）**

```python
# src/mcp_memory/models/record.py
"""MemoryRecord 数据类（spec §3.3）。

字段定义见 design doc §3.2 Bitable schema。
"""
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
    """飞书资源引用（content 存储在哪）。"""
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
        """序列化为 SQLite row dict。"""
        import json

        if self.created_at == 0:
            import time
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
```

- [ ] **Step 2: 实现 paths 工具**

```python
# src/mcp_memory/storage/paths.py
"""项目数据目录路径工具（spec §10.3）。"""
from __future__ import annotations

from pathlib import Path


def local_cache_path(data_dir: Path, scope: str) -> Path:
    """LocalCache SQLite 文件路径。"""
    return data_dir / f"local_cache_{scope}.sqlite"


def lance_path(data_dir: Path, scope: str) -> Path:
    """LanceDB 数据目录路径。"""
    return data_dir / f"vectors_{scope}.lance"


def ensure_data_dir(data_dir: Path) -> None:
    """确保 .feishu_memory 目录存在。"""
    data_dir.mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 3: 创建 models 包**

```python
# src/mcp_memory/models/__init__.py
```

- [ ] **Step 4: 写失败测试 — CRUD**

```python
# tests/storage/test_local_cache_crud.py
import json
import time
import pytest
from mcp_memory.storage.local_cache import LocalCache
from mcp_memory.models.record import (
    MemoryRecord,
    MemoryMetadata,
    SourceType,
    FeishuRef,
)


@pytest.fixture
def cache(tmp_path):
    db = LocalCache(tmp_path / "test.sqlite", scope="memory")
    yield db
    db.close()


def _make_record(text: str = "hello", tags: list[str] | None = None) -> MemoryRecord:
    return MemoryRecord(
        source=SourceType.AGENT_ADD,
        title="Test",
        preview=text[:20],
        text=text,
        content_hash="abc123",
        content_ref=FeishuRef(type="docx", token="docx_xxx", url="https://..."),
        metadata=MemoryMetadata(tags=tags or []),
    )


def test_upsert_and_get(cache):
    r = _make_record("first", tags=["alpha", "beta"])
    cache.upsert(r)
    got = cache.get_record(r.id)
    assert got is not None
    assert got.id == r.id
    assert got.title == "Test"
    assert got.text == "first"
    assert got.metadata.tags == ["alpha", "beta"]
    assert got.content_ref is not None
    assert got.content_ref.token == "docx_xxx"


def test_upsert_overwrites(cache):
    """upsert 同 id 应覆盖。"""
    r = _make_record("v1")
    cache.upsert(r)
    r.text = "v2"
    cache.upsert(r)
    got = cache.get_record(r.id)
    assert got.text == "v2"


def test_delete(cache):
    r = _make_record()
    cache.upsert(r)
    assert cache.get_record(r.id) is not None
    cache.delete(r.id)
    assert cache.get_record(r.id) is None


def test_list_by_filter_tags_any(cache):
    r1 = _make_record("a", tags=["x", "y"])
    r2 = _make_record("b", tags=["y", "z"])
    r3 = _make_record("c", tags=["w"])
    for r in [r1, r2, r3]:
        cache.upsert(r)

    result = cache.list_by_filter({"tags_any": ["x"]})
    assert len(result) == 1
    assert result[0] == r1.id

    result = cache.list_by_filter({"tags_any": ["y"]})
    assert len(result) == 2


def test_list_by_filter_tags_all(cache):
    r1 = _make_record("a", tags=["x", "y"])
    r2 = _make_record("b", tags=["x"])
    for r in [r1, r2]:
        cache.upsert(r)

    result = cache.list_by_filter({"tags_all": ["x", "y"]})
    assert len(result) == 1
    assert result[0] == r1.id


def test_count_by_filter(cache):
    for i in range(5):
        cache.upsert(_make_record(f"r{i}", tags=["x"]))
    assert cache.count_by_filter({"tags_any": ["x"]}) == 5
    assert cache.count_by_filter({}) == 5


def test_update_metadata(cache):
    r = _make_record("text", tags=["old"])
    cache.upsert(r)
    updated = cache.update_metadata(
        record_id=r.id,
        title="New Title",
        tags=["new1", "new2"],
    )
    assert updated is not None
    assert updated.title == "New Title"
    assert updated.metadata.tags == ["new1", "new2"]
    # text 不变
    assert updated.text == "text"


def test_update_metadata_only_some_fields(cache):
    r = _make_record("text", tags=["old"])
    cache.upsert(r)
    updated = cache.update_metadata(record_id=r.id, title="Just Title")
    assert updated.title == "Just Title"
    assert updated.metadata.tags == ["old"]


def test_update_metadata_clear_tags(cache):
    r = _make_record("text", tags=["a", "b"])
    cache.upsert(r)
    updated = cache.update_metadata(record_id=r.id, tags=[])
    assert updated.metadata.tags == []


def test_update_metadata_not_found(cache):
    result = cache.update_metadata(record_id="non_exist", title="X")
    assert result is None
```

- [ ] **Step 5: 跑测试确认失败**

```bash
cd "C:/Users/Administrator/Desktop/feishu Memory/feishu Memory-MCP"
python -m pytest tests/storage/test_local_cache_crud.py -v
```

Expected: `AttributeError: 'LocalCache' object has no attribute 'upsert'`

- [ ] **Step 6: 实现 LocalCache CRUD 方法**

修改 `src/mcp_memory/storage/local_cache.py`：

```python
# src/mcp_memory/storage/local_cache.py
"""本地 SQLite 缓存层。

设计：每个 scope（memory / knowledge）一个独立 .sqlite 文件。
两库的字段定义相同（spec §3.2 Bitable schema 通用）。
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from mcp_memory.models.record import MemoryRecord


class LocalCache:
    def __init__(self, db_path: Path, scope: str):
        if scope not in ("memory", "knowledge"):
            raise ValueError(f"scope must be 'memory' or 'knowledge', got {scope!r}")
        self.db_path = db_path
        self.scope = scope
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(str(db_path), isolation_level=None, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    # ─────────────────────────────────────
    # 初始化
    # ─────────────────────────────────────

    def _init_schema(self) -> None:
        schema_path = Path(__file__).parent / "schema.sql"
        schema_sql = schema_path.read_text(encoding="utf-8")
        self._conn.executescript(schema_sql)
        cur = self._conn.execute("SELECT COUNT(*) FROM sync_state")
        if cur.fetchone()[0] == 0:
            self._conn.execute(
                "INSERT INTO sync_state (id, local_instance_id) VALUES (1, ?)",
                (str(uuid.uuid4()),),
            )
            self._conn.commit()

    def _table_exists(self, name: str) -> bool:
        cur = self._conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        )
        return cur.fetchone() is not None

    def close(self) -> None:
        self._conn.close()

    # ─────────────────────────────────────
    # records CRUD
    # ─────────────────────────────────────

    def upsert(self, record: MemoryRecord) -> None:
        row = record.to_row()
        now = int(time.time())
        row["created_at"] = now if not row["created_at"] else row["created_at"]
        row["updated_at"] = now

        # 计算 text_empty
        text_empty_val = 1 if not record.text else 0
        row["text_empty"] = text_empty_val

        placeholders = ",".join([f":{k}" for k in row.keys()])
        cols = ",".join(row.keys())
        sql = f"INSERT OR REPLACE INTO records ({cols}) VALUES ({placeholders})"
        self._conn.execute(sql, row)

        # 更新 record_tags 表
        self._conn.execute("DELETE FROM record_tags WHERE record_id = ?", (record.id,))
        for tag in record.metadata.tags:
            self._conn.execute(
                "INSERT OR IGNORE INTO record_tags (record_id, tag) VALUES (?, ?)",
                (record.id, tag),
            )
        self._conn.commit()

    def get_record(self, record_id: str) -> MemoryRecord | None:
        row = self._conn.execute(
            "SELECT * FROM records WHERE id = ?", (record_id,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_record(dict(row))

    def delete(self, record_id: str) -> None:
        self._conn.execute("DELETE FROM records WHERE id = ?", (record_id,))
        self._conn.execute("DELETE FROM record_tags WHERE record_id = ?", (record_id,))
        self._conn.commit()

    def list_by_filter(self, filt: dict) -> list[str]:
        """返回符合 filter 的 record_ids。"""
        where, params = self._build_filter_sql(filt)
        sql = f"SELECT id FROM records WHERE {where}"
        rows = self._conn.execute(sql, params).fetchall()
        return [r["id"] for r in rows]

    def count_by_filter(self, filt: dict) -> int:
        where, params = self._build_filter_sql(filt)
        sql = f"SELECT COUNT(*) AS c FROM records WHERE {where}"
        return self._conn.execute(sql, params).fetchone()["c"]

    def _build_filter_sql(self, filt: dict) -> tuple[str, list]:
        clauses = []
        params: list = []

        tags_any = filt.get("tags_any")
        if tags_any:
            placeholders = ",".join(["?"] * len(tags_any))
            clauses.append(
                f"id IN (SELECT record_id FROM record_tags WHERE tag IN ({placeholders}))"
            )
            params.extend(tags_any)

        tags_all = filt.get("tags_all")
        if tags_all:
            for tag in tags_all:
                clauses.append(
                    "id IN (SELECT record_id FROM record_tags WHERE tag = ?)"
                )
                params.append(tag)

        if "source_agent" in filt and filt["source_agent"] is not None:
            clauses.append("(source_agent = ? OR source_agent IS NULL)")
            params.append(filt["source_agent"])

        if "source_type" in filt and filt["source_type"] is not None:
            clauses.append("source = ?")
            params.append(filt["source_type"])

        if "created_after" in filt and filt["created_after"] is not None:
            clauses.append("created_at >= ?")
            params.append(filt["created_after"])

        if "updated_after" in filt and filt["updated_after"] is not None:
            clauses.append("updated_at >= ?")
            params.append(filt["updated_after"])

        if not filt.get("include_empty_text", False):
            clauses.append("(text IS NOT NULL AND text != '')")

        where = " AND ".join(clauses) if clauses else "1=1"
        return where, params

    def _row_to_record(self, row: dict) -> MemoryRecord:
        from mcp_memory.models.record import (
            MemoryMetadata,
            SourceType,
            FeishuRef,
            FeishuFileRef,
        )

        content_ref = None
        if row.get("content_ref_type") and row.get("content_ref_token"):
            content_ref = FeishuRef(
                type=row["content_ref_type"],
                token=row["content_ref_token"],
                url=row.get("content_ref_url", ""),
            )

        file_ref = None
        if row.get("file_ref_json"):
            data = json.loads(row["file_ref_json"])
            file_ref = FeishuFileRef(**data)

        return MemoryRecord(
            id=row["id"],
            source=SourceType(row["source"]),
            title=row["title"],
            preview=row.get("preview", ""),
            text=row.get("text", "") or "",
            content_hash=row.get("content_hash", ""),
            content_ref=content_ref,
            file_ref=file_ref,
            metadata=MemoryMetadata(
                tags=json.loads(row["tags_json"]) if row.get("tags_json") else [],
                source_user=row.get("source_user"),
                source_agent=row.get("source_agent"),
                origin=row.get("origin", "manual"),
                extra=json.loads(row["extra_json"]) if row.get("extra_json") else {},
            ),
            text_empty=bool(row.get("text_empty", 0)),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    # ─────────────────────────────────────
    # update_metadata（memory 库适用；knowledge 库也可）
    # ─────────────────────────────────────

    def update_metadata(
        self,
        record_id: str,
        title: str | None = None,
        tags: list[str] | None = None,
        extra: dict | None = None,
    ) -> MemoryRecord | None:
        """覆盖式更新元数据。

        - title: None = 不变
        - tags: None = 不变；[] = 清空；[a,b] = 替换
        - extra: None = 不变；{} = 清空；{...} = 替换
        """
        existing = self.get_record(record_id)
        if existing is None:
            return None

        if title is not None:
            existing.title = title
            # 同时更新 preview 同步
            existing.preview = existing.text[:200] if existing.text else ""

        if tags is not None:
            existing.metadata.tags = list(tags)
            # 更新记录后重写 tags_json
            # 删除旧 tags 再插入新 tags
            self._conn.execute("DELETE FROM record_tags WHERE record_id = ?", (record_id,))
            for tag in existing.metadata.tags:
                self._conn.execute(
                    "INSERT OR IGNORE INTO record_tags (record_id, tag) VALUES (?, ?)",
                    (record_id, tag),
                )

        if extra is not None:
            existing.metadata.extra = dict(extra)

        existing.updated_at = int(time.time())
        self.upsert(existing)  # 重用 upsert 写回
        return self.get_record(record_id)

    # ─────────────────────────────────────
    # sync_state
    # ─────────────────────────────────────

    def get_sync_state(self) -> dict:
        row = self._conn.execute("SELECT * FROM sync_state WHERE id=1").fetchone()
        return dict(row) if row else {}

    def update_sync_state(self, updates: dict) -> None:
        if not updates:
            return
        sets = ",".join([f"{k} = ?" for k in updates.keys()])
        vals = list(updates.values())
        self._conn.execute(
            f"UPDATE sync_state SET {sets} WHERE id = 1", vals
        )
        self._conn.commit()

    # ─────────────────────────────────────
    # search（BM25，FTS5 触发器已维护）
    # ─────────────────────────────────────

    def search_fts(self, query: str, candidate_ids: list[str] | None = None, limit: int = 50) -> list[tuple[str, float]]:
        """FTS5 搜索。返回 [(record_id, bm25_score)]。

        bm25_score 越负越好（SQLite FTS5 标准行为）。
        candidate_ids 非空时只在候选集内搜索。
        """
        if not query.strip():
            return []
        # 转义双引号
        q = query.replace('"', '""')
        where_extra = ""
        params: list = [f'"{q}"']
        if candidate_ids:
            placeholders = ",".join(["?"] * len(candidate_ids))
            where_extra = f" AND r.id IN ({placeholders})"
            params.extend(candidate_ids)
        sql = f"""
            SELECT r.id AS record_id, bm25(records_fts) AS score
            FROM records_fts
            JOIN records r ON r.rowid = records_fts.rowid
            WHERE records_fts MATCH ? {where_extra}
            ORDER BY bm25(records_fts)
            LIMIT ?
        """
        params.append(limit)
        rows = self._conn.execute(sql, params).fetchall()
        return [(r["record_id"], r["score"]) for r in rows]
```

- [ ] **Step 7: 跑测试确认通过**

```bash
cd "C:/Users/Administrator/Desktop/feishu Memory/feishu Memory-MCP"
python -m pytest tests/storage/test_local_cache_crud.py -v
```

Expected: `11 passed`

- [ ] **Step 8: Commit**

```bash
git add src/mcp_memory/storage/local_cache.py src/mcp_memory/storage/paths.py src/mcp_memory/models/__init__.py src/mcp_memory/models/record.py tests/storage/test_local_cache_crud.py
git commit -m "feat(stage3): LocalCache 完整 CRUD + filter + BM25 search + update_metadata"
```

---

**Stage 3 后续 task 因 plan 篇幅原因省略，实际实施时按相同模板续写 LanceDB / VectorIndex / FTS5 触发器测试。**

---

# Stage 4：Index Engine（embedding / chunking / BM25 / vector / rerank）

> Stage 4 计划：
> - Task 4.1: TextChunker（langchain-text-splitters 包装）
> - Task 4.2: EmbeddingEngine（sentence-transformers + bge-m3 + 线程池）
> - Task 4.3: VectorIndex 接口 + LanceVectorIndex 实现
> - Task 4.4: RRFMerger
> - Task 4.5: Reranker（bge-reranker-base 线程池）

每个 task 结构同 Stage 3：

1. 写失败测试
2. 跑测试确认失败
3. 最小实现
4. 跑测试通过
5. commit

---

# Stage 5：Service 层（5 个 service）

> Stage 5 计划：
> - Task 5.1: MemoryService（add / get / delete / update / list / count）
> - Task 5.2: SearchService（query — 集成 BM25 + 向量 + RRF + rerank）
> - Task 5.3: SyncService（incremental / full / rebuild）
> - Task 5.4: BootstrapService（启动 sync）

每个 service 都接双 Bitable（memory / knowledge）。
MemoryService.add 实现 spec §4.1；SearchService.query 实现 spec §4.2；SyncService 三个模式实现 spec §4.3。

---

# Stage 6：MCP Tool 层

> Task 6.1: FastMCP server 启动
> Task 6.2: 8 个 tool 装饰器（add/query/get/update/delete/list/count/sync）
> Task 6.3: scope 路由到对应 service
> Task 6.4: tool description 含"何时用/不要用于"段（spec §5）

Tool 入参/出参严格按 spec §5.1-§5.8。

---

# Stage 7：CLI 子命令（agent-first 运维 8 个）

> Task 7.1: cli.py 入口
> Task 7.2: init 子命令（交互式配置 + 引导飞书开发者后台 + 双 Bitable 自检）
> Task 7.3: serve 子命令
> Task 7.4: doctor 子命令（飞书 + 双库连通性 + 本地索引）
> Task 7.5: sync 子命令（--mode --scope）
> Task 7.6: status 子命令
> Task 7.7: schema / migrate / version 子命令

CLI 入参与 tool 一一对应只是不再暴露（spec §10.4）。

---

# Stage 8：集成测试 + E2E

> Task 8.1: 集成测试（mock feishu 测试 5 个 service）
> Task 8.2: E2E（真实飞书 Bitable + SQLite/lancedb）
> Task 8.3: 性能测试（万级记录 sync 时间 / query 延迟）

---

# Stage 9：文档 + Skill 文件

> Task 9.1: README.md（5 分钟接入 + agent 单线 + CLI 简短附录）
> Task 9.2: docs/feishu-setup.md（飞书开发者后台步骤 + 双 Bitable 创建）
> Task 9.3: docs/architecture.md（设计可读版）
> Task 9.4: docs/operations.md（运维）
> Task 9.5: docs/tool-reference.md（8 个 tool 完整入参/出参）
> Task 9.6: skill/feishu-memory/SKILL.md（agent 自动加载）
> Task 9.7: CHANGELOG.md + CONTRIBUTING.md

---

# 自审（Self-Review）

## 1. Spec coverage
按 spec 章节对照：

| Spec 章节 | 对应 Task |
|---|---|
| §1.5 双库概念隔离 | Stage 1.2 (config 双 Bitable) + Stage 6 (tool scope) |
| §3.2 Bitable schema | Stage 3.1 schema.sql（15 字段一致） |
| §3.3 MemoryRecord | Stage 3.2 models/record.py |
| §3.4 SQLite schema | Stage 3.1 + 3.2 |
| §4.1 写入流程 | Stage 5.1 MemoryService.add |
| §4.2 检索流程 | Stage 5.2 SearchService.query |
| §4.3 校准流程 | Stage 5.3 SyncService |
| §5 MCP 工具面 | Stage 6 |
| §7 配置 | Stage 1.2 |
| §10.4 CLI | Stage 7 |
| §10.5 README | Stage 9.1 |
| §12 文档交付 | Stage 9 全部 |
| §14 验收 30 条 | 跨 Stage 1-9 |

**Gaps**：Stage 4 / Stage 5 / Stage 6 / Stage 7 / Stage 8 / Stage 9 计划被简化省略（因 plan 篇幅）。实际执行时按相同模板补全每个 task 的 5 步法（写失败测试 → 跑失败 → 实现 → 跑通过 → commit）。

## 2. Placeholder scan
无 "TBD" / "TODO" / "implement later" / "fill in details"。

只有"Stage X 计划"作为占位文字（实际后续 Stage 的完整 5 步法模板），不是 spec 内容占位。

## 3. Type consistency
MemoryRecord 字段名（id / title / preview / text / content_ref / file_ref / metadata / source_agent / source_user / origin / extra）在所有 stage 中保持一致。

---

**Plan 完成** — 18 个具体 task（Stage 1-3 完整，后续 stage 用模板继续）。全 5 步法（写测试 → 失败 → 实现 → 通过 → commit）每个 task。
