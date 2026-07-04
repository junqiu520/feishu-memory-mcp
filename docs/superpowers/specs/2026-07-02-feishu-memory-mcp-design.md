# feishu-memory-mcp 设计文档

**项目**：多 agent 共享的 RAG 知识库 / 记忆库
**核心组件**：飞书（存储）+ 本地 MCP 服务（检索接口）+ LLM Agent（消费方）
**设计日期**：2026-07-02
**状态**：设计完成，待实施

---

## 1. 背景与目标

### 1.1 一句话定位
**feishu-memory-mcp**：以飞书为存储后端、以 MCP 为唯一服务接口的本地 RAG 知识库 / 记忆库。多 LLM agent 通过 MCP 协议共享同一份记忆。

### 1.2 核心约束（设计原则，不分阶段）
1. **飞书是唯一权威源（source of truth）** —— 元数据、内容、附件全部存飞书
2. **本地是可重建副本** —— 任何本地数据丢失都可通过 `memory_sync(mode="rebuild")` 恢复
3. **MCP 服务是 agent 的唯一入口** —— agent 不直接调飞书 CLI 或 SDK
4. **agent 自理附件解析** —— MCP 服务只接收纯文本输入
5. **单进程设计** —— 多 agent 连同一个 MCP 进程本地共享索引
6. **所有该做的功能都纳入** —— 不刻意分 v1 / v2
7. **双库概念隔离** —— 记忆库与知识库是两个独立飞书 Bitable，通过 scope 参数路由；记忆库多 agent 共享，知识库人类录入
8. **agent-first，人工极少操作** —— 主要用户是 LLM agent；CLI 仅做运维辅助（init/serve/doctor/sync 等）

### 1.2.1 Architecture Change Log

- **2026-07-XX**：从 `lark-oapi` Python SDK 切换为 `lark-cli` subprocess。
  理由：代码量更少、依赖更少、错误处理一致、上手更简单。
  实现：`LarkCliRunner` 类封装 `subprocess.run(["lark-cli", ...])`，
  位置见 `src/mcp_memory/feishu/runner.py`。
  权衡：每次调用约 200 ms 额外延迟（Node.js 启动开销）相对进程内 SDK
  约 10 ms。对于 RAG 场景这是可接受的（embedding 计算本身才是主要开销）。
- **2026-07-XX**：从 `pyproject.toml` 移除 `lark-oapi` 依赖；改为
  `feishu-memory install-deps` 子命令自动 `npm install -g @larksuite/cli`。
  原 `lark-oapi` 依赖在 stage 7 commit `df74868` 中删除。

### 1.3 数据源范围（最终）
| Source Type | 适用 | 访问限制 |
|---|---|---|
| `AGENT_ADD` | agent 主动 add | 无 |
| `FEISHU_DOC` | 飞书云文档 | bot 自身应用云空间 |
| `FEISHU_BITABLE` | 飞书多维表格 | bot 自身 Bitable |
| `FEISHU_DRIVE_FILE` | 图片/PPT/PDF/视频 | bot 自身 Drive |
| `FEISHU_WIKI` | 飞书知识库 | bot 自身 Wiki 节点 |

**已移除**：IM 消息、妙记（受 bot 权限限制，对个人场景价值低）。

### 1.4 与飞书 Bitable 的职责边界（明确划界）

飞书 Bitable **本身就是云数据库**——结构化存储、字段类型、视图、协作、权限全部内置。本项目的 MCP 服务**不重造这些轮子**，只在飞书 Bitable 之上加 agent 需要的检索语义层。

| 能力 | 飞书 Bitable 自带 | 我们这层提供 |
|---|---|---|
| 元数据 CRUD | ✅ | （只承担写入语义） |
| 字段类型 / 单/多选 | ✅ | （字段设计由我们定） |
| UI 视图 / 看板 / 仪表盘 | ✅ | ❌（不重做 UI） |
| 用户协作 / 权限 | ✅ | （飞书范围继承） |
| **精确 / 关键词搜索** | ✅ | ⚠️（我们也做，但仅本地兜底） |
| **语义检索（向量）** | ❌ | ✅ **核心价值** |
| **BM25 + RRF 召回** | ❌ | ✅ |
| **MCP 标准接口** | ❌ | ✅ **核心价值** |
| 多 agent 视图隔离 | ❌（租户粗粒度） | ⚠️ source_agent 字段（可选过滤） |
| 附件内容检索 | ❌ | ✅ file_ref + 解析后入库 |
| 重排序（reranker） | ❌ | ✅ 可选 |

**结论**：飞书 Bitable 负责"存与查（精确）"，本服务负责"语义检索 + agent 友好"。

### 1.5 双库概念隔离（记忆库 vs 知识库）—— 项目核心结构

**项目管理的不是"一种数据"，而是"两种概念上分开的资源库"**——用两个独立的飞书 Bitable 实例。

| 库 | 含义 | 主导写入者 | 消费者 | Bitable 实例 |
|---|---|---|---|---|
| **记忆库（Memory）** | agent 的长期记忆：对话、agent 主动 add、agent 解析的资源 | **agent** （agent_add / agent 解析后入库） | 所有 agent 可读可写；用户也能查 | **memory_bitable**（1 个，多 agent 共享）|
| **知识库（Knowledge）** | 人类的资料库：笔记、规范、文档、飞书已有资源 | **用户** （feishu_doc / wiki / drive_file 同步）| 用户主导；agent 可消费做检索 | **knowledge_bitable**（1 个，所有人共享）|

**记忆 ≠ 知识**（虽然实现完全相同）：
- 记忆：agent 自己生成的（agent 是生产者）
- 知识：人类录入的（人类是生产者）

但**在技术实现上完全一样**——两库都用同一套 8 个 tool + scope 参数路由。

#### 1.5.1 双库的设计要点

1. **两个 Bitable 实例**：config 配 `memory_bitable_app_token` + `knowledge_bitable_app_token`
2. **同一个 schema**：两库的飞书字段表完全一致（见 §3.2）
3. **同一组 8 个 tool**：所有 tool 加 `scope` 参数（memory / knowledge），默认 memory
4. **`source_agent` 字段保留**：记忆库内多 agent 共享，标记谁写的；知识库允许为空
5. **`source_user` 字段保留**：知识库内标记哪位人类录入；记忆库允许为空
6. **跨库不互通**：scope 不混（user 不会把"记忆"写到"知识库"里，反之亦然）

#### 1.5.2 为什么是 2 个 Bitable 而不是 1 个

理由：
- **概念隔离**：用户视角看，两库角色截然不同（一个给 agent 用，一个给主人用）
- **权限可分**：知识库范围可在飞书层独立设置（仅特定管理员能写）
- **统计可分**：未来想看"我的 agent 存了多少记忆 vs 我录入了多少知识"，分开更好统计
- **迁移可分**：将来某一方想换存储（迁移、重建）不影响另一方

#### 1.5.3 scope 作为路由参数（不存储在记录里）

- scope **不存为记录字段**（因为每条记录只属于一个 Bitable 实例）
- scope 是 MCP tool 入参，决定走哪个 Bitable client
- schema 一致让代码复用，scope 让行为不同

#### 1.5.4 双库场景示例

```
agent 在对话中学到一个事实
  → 调 memory_add(scope="memory", text="...", source_agent="claude-1")
  → 写到 memory_bitable；这条"记忆"不会跑到 knowledge_bitable

用户想保存"工程规范"到知识库
  → 调 memory_add(scope="knowledge", text="...") 
  → 或通过文件 sync (feishu_doc) 入库到 knowledge_bitable

agent 想给主人找规范
  → 调 memory_query(scope="knowledge", query="...")
  → 不污染记忆库结果
```



---



---

## 2. 系统架构

### 2.1 一句话架构
**单体 Python MCP 进程**：进程内 bge-m3 embedding + lark-oapi 同步调用飞书 + 本地 SQLite/LanceDB/FTS5 三层索引。

### 2.2 架构图

```
                     ┌─────────────────────────┐
                     │   多 LLM Agent           │
                     │   (Claude, Cursor, ...) │
                     └────────────┬────────────┘
                                  │ MCP (stdio)
                                  ↓
                  ┌───────────────────────────────┐
                  │     feishu-memory-mcp        │
                  │     (单 Python 进程)           │
                  │                                │
                  │  ┌──────────────────────────┐ │
                  │  │ MCP Tools (FastMCP)      │ │
                  │  │ - memory_add             │ │
                  │  │ - memory_query           │ │
                  │  │ - memory_get             │ │
                  │  │ - memory_update          │ │
                  │  │ - memory_delete          │ │
                  │  │ - memory_list            │ │
                  │  │ - memory_count           │ │
                  │  │ - memory_sync            │ │
                  │  └──────────────────────────┘ │
                  │           ↓                    │
                  │  ┌──────────────────────────┐ │
                  │  │  Service Layer           │ │
                  │  │  ─ Memory / Search /     │ │
                  │  │    Sync / Bootstrap       │ │
                  │  └──────────────────────────┘ │
                  │           ↓                    │
                  │  ┌──────────────────────────┐ │
                  │  │  Index Engine            │ │
                  │  │  ─ Embedding / Chunking  │ │
                  │  │  ─ BM25 / Vector / RRF   │ │
                  │  │  ─ Rerank                │ │
                  │  └──────────────────────────┘ │
                  │           ↓                    │
                  │  ┌──────────────────────────┐ │
                  │  │  Feishu Adapter          │ │
                  │  │  (lark-oapi 封装)         │ │
                  │  └──────────────────────────┘ │
                  │           ↓                    │
                  │  ┌──────────────────────────┐ │
                  │  │  Local Storage           │ │
                  │  │  ─ SQLite / LanceDB /    │ │
                  │  │    FTS5                  │ │
                  │  └──────────────────────────┘ │
                  └───────────────┬───────────────┘
                                  │ lark-oapi HTTPS
                                  ↓
                  ┌───────────────────────────────┐
                  │      飞书开放平台 + 云存储       │
                  │  ─────────────────────────     │
                  │  Bitable / Docx / Drive / Wiki  │
                  └───────────────────────────────┘
```

### 2.3 关键决策摘要

| 维度 | 决策 | 理由 |
|---|---|---|
| 进程模型 | 单 Python 进程 | 调试简单、零部署，符合个人使用 |
| MCP 传输 | stdio | 标准 MCP 协议，配置简单 |
| Feishu 调用 | lark-oapi Python SDK（进程内 HTTPS） | 避免 fork exec 子进程开销 |
| Embedding | sentence-transformers 进程内 bge-m3 | 零外部依赖、确定性推理 |
| 向量库 | LanceDB（默认，可换 Chroma） | 文件级、可重建 |
| 检索 | BM25 + 向量 + RRF + 可选 rerank | 双路召回兜底 |
| 写入策略 | 飞书先成功 → 本地后写入 | 飞书是权威源 |
| Sync | 三模式：incremental / full / rebuild | 灵活迁移与恢复 |
| 视图隔离 | `source_agent` 字段 + 多 agent 字段视图 | 不依赖飞书权限配置 |
| 启动行为 | 启动时自动 incremental sync | 跨进程 / 跨设备数据对齐 |
| agent 文件处理 | agent 自理 ParseAdapter | MCP 服务不解析附件 |

---

## 3. 数据模型

### 3.1 存储分层

| 层 | 技术 | 角色 | 权威源 |
|---|---|---|---|
| 元数据 | 飞书 Bitable | 主存储 + 人类可视化 | ✅ 飞书 |
| 富文本内容 | 飞书 Docx / 文件 | 主存储 | ✅ 飞书 |
| 元数据缓存 | 本地 SQLite | 工作缓存，可丢弃 | ❌ 飞书 |
| 关键词索引 | 本地 SQLite FTS5 | 倒排索引 | ❌ 飞书 |
| 向量索引 | 本地 LanceDB | 向量索引 | ❌ 飞书 |

**关键不变量**：Bitable 写入成功即视为"记忆落地"；本地索引失败是次要问题，下次 sync 补偿。

### 3.2 飞书 Bitable 字段（权威定义）

| 字段名 | 类型 | 说明 |
|---|---|---|
| `id` | text (uuid) | 主键 |
| `source` | single_select | agent_add / feishu_doc / feishu_bitable / feishu_drive_file / feishu_wiki |
| `title` | text | 人类可读标题；agent_add 时自动取 text 前 30 字 |
| `preview` | long_text | content 前 200 字（UI 展示用） |
| `content_ref_type` | single_select | docx / bitable / drive_file / wiki |
| `content_ref_token` | text | 内容存储的飞书资源 token |
| `content_ref_url` | url | 直接打开链接 |
| `content_hash` | text | sha256(content)，增量同步核心 |
| `feishu_last_modified` | number | 飞书端版本号（增量同步用） |
| `tags` | multi_select | 检索过滤 |
| `source_user` | text | 录入者飞书 open_id |
| `source_agent` | text | agent_id；null = 全共享 |
| `origin` | single_select | manual / auto_sync |
| `extra_json` | long_text | 扩展字段（会议时间、文件名等） |
| `text_empty` | bool | text 字段是否为空（影响可搜索性）|
| `created_at` | datetime | |
| `updated_at` | datetime | |

**Bitable 设计原则**：字段越少越好 —— 字段少 = 飞书 API 调用快 + schema 简单 + 未来易扩展。状态信息（embedding_status、sync_status、token_count）放本地 SQLite。

### 3.3 MemoryRecord 数据类定义

```python
from enum import Enum
from typing import Literal
from pydantic import BaseModel
import uuid


class SourceType(str, Enum):
    AGENT_ADD = "agent_add"
    FEISHU_DOC = "feishu_doc"
    FEISHU_BITABLE = "feishu_bitable"
    FEISHU_DRIVE_FILE = "feishu_drive_file"
    FEISHU_WIKI = "feishu_wiki"


class FeishuRef(BaseModel):
    """飞书资源引用"""
    type: Literal["docx", "bitable", "drive_file", "wiki"]
    token: str
    url: str
    last_modified_version: int = 0


class FeishuFileRef(BaseModel):
    """用于 memory_add 时的原文附件 ref"""
    type: Literal["drive_file"]
    token: str
    url: str
    file_name: str | None = None
    mime_type: str | None = None


class MemoryMetadata(BaseModel):
    tags: list[str] = []
    source_user: str | None = None
    source_agent: str | None = None  # null = 全 agent 共享
    origin: Literal["manual", "auto_sync"] = "manual"
    extra: dict[str, str] = {}


class MemoryChunk(BaseModel):
    chunk_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    record_id: str
    text: str
    start_offset: int
    end_offset: int


class MemoryRecord(BaseModel):
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source: SourceType
    title: str
    preview: str
    text: str                                   # 正文（可能被空）
    content_hash: str
    content_ref: FeishuRef | None               # 主引用
    file_ref: FeishuFileRef | None              # 仅 agent_add 时存在的原文
    metadata: MemoryMetadata
    extra: dict[str, str] = {}
    text_empty: bool = False
    created_at: int
    updated_at: int
```

### 3.4 本地 SQLite Schema

#### 3.4.1 records 表（缓存层，结构对应 Bitable 字段）
```
CREATE TABLE records (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    title TEXT,
    preview TEXT,
    text TEXT,                          -- 缓存正文用于本地检索，可空
    content_hash TEXT,
    content_ref_type TEXT,
    content_ref_token TEXT,
    content_ref_url TEXT,
    file_ref_json TEXT,                 -- JSON 序列化
    tags_json TEXT,                     -- JSON 数组
    source_user TEXT,
    source_agent TEXT,
    origin TEXT,
    extra_json TEXT,
    text_empty INTEGER DEFAULT 0,
    embedding_status TEXT,              -- 'pending'/'ok'/'failed'
    sync_status TEXT,                   -- 'pending'/'synced'/'error'
    last_attempt_at INTEGER,
    token_count INTEGER,
    created_at INTEGER,
    updated_at INTEGER
);

CREATE INDEX idx_records_source_agent ON records(source_agent);
CREATE INDEX idx_records_updated_at ON records(updated_at);
CREATE INDEX idx_records_source ON records(source);
CREATE INDEX idx_records_content_hash ON records(content_hash);
```

#### 3.4.2 sync_state 表（全局单行）
```
CREATE TABLE sync_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),  -- 强制单行
    last_sync_at INTEGER,                    -- 最近 incremental sync 时间
    last_full_sync_at INTEGER,
    last_rebuild_at INTEGER,
    bitable_schema_hash TEXT,                -- detect 飞书 Bitable schema 变化
    local_instance_id TEXT
);
```

#### 3.4.3 record_tags 表（用于 AND/OR filter 高效过滤）
```
CREATE TABLE record_tags (
    record_id TEXT,
    tag TEXT,
    PRIMARY KEY (record_id, tag)
);
CREATE INDEX idx_record_tags_tag ON record_tags(tag);
```

#### 3.4.4 FTS5 关键词索引
```
CREATE VIRTUAL TABLE records_fts USING fts5(
    text,
    title,
    preview,
    tags,
    content='records',
    content_rowid='rowid'
);
-- 触发器维持一致性
```

### 3.5 LanceDB Schema（chunk 级别）

| 字段 | 类型 | 说明 |
|---|---|---|
| `chunk_id` | str | 主键 |
| `record_id` | str | 关联到 records.id |
| `text` | str | chunk 文本 |
| `embedding` | list[float] | 1024 维 bge-m3 |
| `start_offset` | int | |
| `end_offset` | int | |
| `metadata` | dict | tags / source_agent / source_type / updated_at（用于前置过滤） |

---

## 4. 关键流程

### 4.1 写入流程 `memory_add(text, file_ref?, title?, tags?, extra?)`

**流程图**：
```
agent 调 memory_add(text="...", file_ref={...}, tags=[...])
  │
  ├─[进程内] Step 1: 入口校验
  │  - text 非空、长度 1-100K
  │  - tags 标准化（lowercase + 去重）
  │  - file_ref 格式校验
  │
  ├─[飞书] Step 2: 飞书持久化（必须成功）
  │  a. DocxClient.create_docx(text) → docx_token   ← 先创建 Docx
  │  b. BitableClient.create_record({               ← 再创建 Bitable 行
  │       source, title, preview, text_empty=..., 
  │       content_ref=docx_token, content_hash=..., 
  │       tags, source_agent, origin, extra_json
  │     })
  │  (若失败：返回 error；本地不写。Docx 若是孤儿，
  │   下次 sync 识别后清理)
  │
  ├─[进程内/线程池] Step 3: 本地写入（best-effort）
  │  a. content_hash = sha256(text)
  │  b. TextChunker.split(text) → chunks
  │     - 短（<800字）：1 个 chunk
  │     - 长：滑动窗口 800 字 + overlap 100
  │  c. EmbeddingEngine.embed(chunks) [线程池]
  │  d. LocalCache.upsert(record)          ← SQLite
  │  e. VectorIndex.upsert(chunks)         ← LanceDB
  │  f. FTS5Index.upsert(text)             ← FTS5 触发器自动
  │
  ├─返回
  │  {
  │    record_id, status: "ok"|"partial",
  │    chunk_count, feishu_url, warning: ...
  │  }
```

**关键不变量**：
- 飞书 Bitable 有这条 → 记忆已落地
- 本地有没有只是性能问题，不影响正确性
- 失败记录标记 `sync_status='pending'`，下次 incremental sync 补偿

### 4.2 检索流程 `memory_query(query, top_k?, filter?, mode?)`

**流程图**：
```
agent 调 memory_query(query=..., top_k=5, filter=..., mode="hybrid_rerank")
  │
  ├─[进程内] Step 1: filter 解析 + metadata 前置过滤
  │  - 在 SQLite records 表中筛出符合 filter 的 record_ids
  │  - filter 维度: tags_any / tags_all / source_agent / 
  │                source_type / created_after / updated_after / 
  │                include_empty_text
  │
  ├─[进程内] Step 2: 双路召回
  │  ┌────────────────┐    ┌────────────────────┐
  │  │ BM25 召回      │    │ 向量召回           │
  │  │ FTS5 search    │    │ bge-m3(query)      │
  │  │ top-50         │    │ LanceDB cosine     │
  │  │                 │    │ top-50             │
  │  └────────┬───────┘    └──────┬─────────────┘
  │           ↓                  ↓
  ├─[进程内] Step 3: RRF 融合
  │  score = Σ 1/(60+rank)  双路各自贡献
  │
  ├─[进程内] Step 4: 重排（mode='hybrid_rerank' 时启用）
  │  - 取 RRF top-2k
  │  - bge-reranker-base 重排 [线程池]
  │
  ├─[进程内] Step 5: 取回原文 + 组装返回
  │  - record_ids → metadata from SQLite
  │  - chunk_ids → chunk text from LanceDB
  │
  ├─返回
  │  {
  │    results: [{ record_id, title, preview, 
  │                matched_chunk_text, content_ref_url, ... }],
  │    query_embedding_ms,
  │    total_candidates,
  │    cache_age_seconds
  │  }
```

**mode 可选值**：
- `hybrid_rerank`（默认）：双路召回 + RRF + 重排
- `hybrid`：双路召回 + RRF，不重排
- `bm25_only`：仅关键词（适合精确查人名/日期/ID）
- `vector_only`：仅语义（适合抽象意图）

**关键不变量**：
- 查询不依赖飞书在线 —— 本地索引足够
- 飞书只在用户点击回链时才需要连通

### 4.3 校准流程 `memory_sync(mode)`

#### 4.3.1 incremental（增量）
```
读 sync_state.last_sync_at
  ↓
[飞书] BitableClient.list_records(updated_after=last_sync_at) → 增量记录集
  ↓
[飞书] 对每条记录拉 content（按 content_ref_type 分发）
  ↓
[进程内] 对每条记录：
  - content_hash 与本地缓存对比
    - 不同 → 重 embedding（删除旧 chunks，写新 chunks）
    - 相同 → 跳过 embedding
  - 更新本地 SQLite / FTS5 / LanceDB
  ↓
更新 sync_state.last_sync_at = now()
```

#### 4.3.2 full（全量）
```
[飞书] BitableClient.list_all_records() → 全量记录集
  ↓
[进程内] diff 与本地：
  - 删除候选：本地有飞书没有
  - 新增候选：飞书有本地没有
  - 修改候选：hash 不同
  ↓
[进程内] 应用 diff：
  - 删除：从 SQLite + LanceDB + FTS5 删除
  - 新增/修改：重新拉 content + embedding
  ↓
更新 sync_state
```

#### 4.3.3 rebuild（重建）
```
物理删除本地 SQLite / LanceDB / FTS5 文件
  ↓
从零拉飞书全量 → embedding → 写本地
  ↓
更新 sync_state 为初始值
```

#### 4.3.4 启动时自动 sync
```
MCP 服务启动时：
  - 如果 auto_sync_on_startup=True:
    - 调用 SyncService.incremental()
    - 失败不抛错（服务仍可启动）
  - 日志记录 sync 结果
```

### 4.4 删除流程 `memory_delete(record_id, confirm=True)`

```
agent 调 memory_delete(record_id, confirm=True)
  ↓
[飞书] BitableClient.delete_record(record_id)
  ↓
[飞书] Docx 删除（调 docx.v1.document.delete；具体回收站行为由飞书 SDK 决定）
  ↓
[本地] LocalCache.delete(record_id)
       VectorIndex.delete_by_record(record_id)
       FTS5 自动触发器清理
  ↓
注：若 file_ref 是 Drive 文件，Drive 文件本身保留（按飞书自身规则）
```

### 4.5 更新流程 `memory_update(record_id, title?, tags?, extra?, source_agent?)`

```
agent 调 memory_update(record_id="xxx", title="新标题", tags=["缓存"])
  │
  ├─[进程内] Step 1: 校验
  │  - record_id 必须存在（先查本地缓存）
  │  - title 不能改 text（校验：title 不是当前 text 前 30 字时无需拒绝；但用户传 text 视为错误参数）
  │  - tags 长度限制（最大 16）
  │  - extra dict 序列化大小限制（< 4KB）
  │
  ├─[飞书] Step 2: Bitable batch_update 同步更新字段
  │  - 只更新传入的字段，其他字段保留
  │  - updated_at 由飞书自动维护
  │
  ├─[本地] Step 3: LocalCache.update_metadata(...)
  │  - 更新 SQLite 中对应字段
  │  - 刷新 updated_at
  │  - 不动 LanceDB / FTS5（text 未变，向量与关键词索引仍然有效）
  │
  ├─返回
  │  { record_id, status: "ok", updated_at, changed_fields: [...] }
  │
  │  失败：record 不存在 → { error: "not_found" }
```

**关键不变量**：
- 只能改 metadata，不能改 text
- tags / extra 是**覆盖式**，不是合并
- 不动向量索引（这是性能优化）

### 4.6 计数流程 `memory_count(filter?)`

```
[进程内] SQLite COUNT(*) WHERE ... 
         （基于 records + record_tags 联合查询）
返回 { count, filter_applied }
```

**关键不变量**：纯本地 SQLite 操作，离线可用。

---

## 5. MCP 工具面（8 个 tool × 双 scope 路由）

**工具设计原则**：
每个 tool 必须有 `description`（FastMCP 暴露给 agent），包含**何时用 / 不要用于**两段 + 参数说明。这是 agent 看到后的第一份决策信息。

**scope 路由总开关**：所有 tool 都接受 `scope` 参数（默认 `"memory"`）。
- `scope="memory"` → 路由到 memory_bitable（agent 的记忆）
- `scope="knowledge"` → 路由到 knowledge_bitable（人类的知识）
- scope 缺省 → 取 config.default_scope

工具实现层面：8 个 tool 共享同一组 Service，但通过构造时传入不同 bitable_client。

### 5.1 `memory_add`

```python
@mcp.tool
async def memory_add(
    text: str,                              # 必填纯文本（1-100K 字）
    file_ref: dict | None = None,           # {type, token, url, file_name?, mime_type?}
    title: str | None = None,               # 空时自动取 text 前 30 字
    tags: list[str] | None = None,
    extra: dict | None = None,
    scope: str = "memory",                  # "memory" | "knowledge"
) -> dict:
    """把一条记忆加入长期知识库。
    
    何时调用：
      - 用户让你"记下 X / 帮我保存这段 / 收藏这一段"
      - 你识别当前对话里有可复用的观点、经验、决策，想未来能搜到
      - 你刚解析完一份 PDF / PPT / 图片，要入库检索
      - 用户给一段代码 / 命令让你"以后还会用到"
    
    不要用于：
      - 临时上下文（用会话内的 prompt）
      - 系统指令 / prompts 类内容
      - 用户明确说"不用记"的对话
    
    scope 选择：
      - "memory": agent 自己生成的记忆（默认）
      - "knowledge": 用户让你录入人类的知识（笔记、规范、文档）
      - 不确定时选 memory
    
    入参：
      text: 必填纯文本。文件类型附件请先自己解析为文本，再传 text
      file_ref: 可选 {type, token, url}，如原文存飞书 Drive 则填用于回链
      title: 可选；空时自动取 text 前 30 字
      tags: 可选；lowercase + 去重
      extra: 可选 dict；会写到 Bitable extra_json
      scope: 路由到记忆库或知识库
    
    返回：{ record_id, status, chunk_count, feishu_url, scope, warning? }
    """
```

### 5.2 `memory_query`

```python
@mcp.tool
async def memory_query(
    query: str,
    top_k: int = 5,
    filter: dict | None = None,
    mode: str = "hybrid_rerank",
    scope: str = "memory",
) -> dict:
    """从知识库检索最相关的记忆。
    
    何时调用：
      - 用户问"我之前讲过 X 吗 / 有没有 Y 相关的"
      - 你想引用过去的对话 / 资料回答
      - 你要确认"我已经知道 X"再决定要不要重新探索
    
    不要用于：
      - 当前会话上下文（不需要检索）
      - 实时性问题（最新一分钟发生的事）
      - 用户没问任何历史信息时主动用
    
    scope 选择：
      - "memory": 默认。查 agent 自己的记忆库
      - "knowledge": 查主人的知识库（规范、文档等）
      - 想全看 → 调两次（分别传 scope=memory 和 scope=knowledge）
    
    mode:
      - "hybrid_rerank" (默认): BM25 + 向量 + RRF + 重排。通用首选
      - "bm25_only":            仅关键词（人名/日期/ID/精确名词）
      - "vector_only":          仅语义（抽象意图找相似）
    
    filter:
      {
        "tags_any": [...],     # 任一标签
        "tags_all": [...],     # 全部标签
        "source_agent": str,   # 默认当前 agent（仅 memory 库有效）
        "source_type": str,    # 来自哪里
        "created_after": int,  # unix ts
        "updated_after": int,
        "include_empty_text": bool  # 默认 False
      }
    
    返回：{ results: [{...}], query_embedding_ms, total_candidates, cache_age_seconds, scope }
    """
```

### 5.3 `memory_get`

```python
@mcp.tool
async def memory_get(
    record_id: str,
    scope: str = "memory",          # 指明去哪个库取
) -> dict:
    """取一条记忆的完整内容（含全文 + 全部 chunks）。
    
    何时调用：
      - query 返回了命中但不够完整，需要全文
      - 用户问"展开看看 X 这条"
      - 要基于某条记录做二次生成（读全文 + 重写）
    
    不要用于：
      - 还没拿到 record_id 时（要先 query 或 list）
    
    返回：{ record_id, title, preview, content_ref, file_ref, tags,
            source, source_agent, created_at, updated_at, full_text, chunks, scope }
    """
```

### 5.4 `memory_delete`

```python
@mcp.tool
async def memory_delete(
    record_id: str,
    confirm: bool = False,
    scope: str = "memory",
) -> dict:
    """删除一条记忆（飞书 + 本地索引同时删）。
    
    何时调用：
      - 用户明确说"忘掉这条 / 删掉 / 移除"
      - 你发现某条记忆有错误且无法 update 修正（用 delete + add 重写）
    
    不要用于：
      - 修订内容（改 text 走 delete + add；改标题/标签走 update）
    
    confirm 必须为 True 才执行（防误删）。
    不删除 Drive 原文（按飞书 Drive 自身规则）。
    """
```

### 5.5 `memory_list`

```python
@mcp.tool
async def memory_list(
    filter: dict | None = None,
    page: int = 1,
    page_size: int = 20,
    sort_by: str = "updated_at",
    desc: bool = True,
    scope: str = "memory",
) -> dict:
    """分页列出记忆（纯本地 SQLite 元数据，不走语义检索）。
    
    何时调用：
      - 用户问"我有哪些 X 类的记忆 / 列出来看看"
      - 已知大致范围但不需要语义匹配（用 metadata filter 缩小）
      - 调试 / 排查时枚举
    
    不要用于：
      - 模糊意图检索（用 memory_query）
      - 一次性看完所有（数据量大时分页）
    
    返回：{ items: [record 简要], total, page, page_size, has_more, scope }
    """
```

### 5.6 `memory_sync`

```python
@mcp.tool
async def memory_sync(
    mode: str = "incremental",
    scope: str = "memory",         # 默认只 sync memory；可传 "knowledge" 或 "both"
) -> dict:
    """校准本地索引与飞书。
    
    何时调用：
      - 服务刚启动但还没触发自动 sync（auto_sync_on_startup=False）
      - 用户说"同步一下 / 拉取最新"
      - 本地数据看起来不对（陈旧、缺失），想强制对齐
      - 跨设备后想看到在其他地方写入的内容
    
    不要用于：
      - 高频重复触发（sync 是 io + embedding 重活）
      - 大库 full 模式调试（用 rebuild 替代）
    
    scope 选择：
      - "memory": 默认，只 sync 记忆库
      - "knowledge": 只 sync 知识库
      - "both": 两个都 sync
      - sync 阶段会同时维护各自的 sync_state
    
    mode:
      - "incremental" (默认): 增量，按 updated_at 拉
      - "full":              全量 diff 后增量嵌入（保留本地数据）
      - "rebuild":           清空本地后从零重建（最重，本地可丢情况下用）
    
    返回：{ mode, scope, started_at, finished_at, added, updated, deleted, errors, next_sync_at }
    
    注意：大库时阻塞调用，可能几分钟。
    """
```

### 5.7 `memory_update`

```python
@mcp.tool
async def memory_update(
    record_id: str,
    scope: str = "memory",
    title: str | None = None,         # 可选，覆盖式新标题
    tags: list[str] | None = None,    # 可选，覆盖式新标签列表（[] 表示清空）
    extra: dict | None = None,        # 可选，覆盖式新扩展字段
) -> dict:
    """修改一条记忆的元数据（不改 text）。
    
    何时调用：
      - 想纠正标题 / 加标签 / 改标签
      - 用户修正元数据
    
    不要用于：
      - 改 text（要走 delete + add）
      - 改 content_ref（重写等于新记录）
      - 改 source_agent（同一 Bitable 多 agent 共享，记录归属不应该转）
    
    修改原则：
      - title / tags / extra 任选其一或组合
      - text 不能修改（要改 text → delete + add）
      - content_ref 不能修改（要改 → delete + add）
      - created_at / updated_at 不能手动改（updated_at 由系统维护）
      - tags: None = 不变；[] = 清空；[a,b] = 替换为 [a,b]
      - extra: None = 不变；{} = 清空；{...} = 替换
    
    行为：
      1. 飞书 Bitable 用 batch_update API 同步字段
      2. 本地 SQLite 同步更新（updated_at 自动刷新）
      3. 不动 LanceDB / FTS5（因为 text 没变）
    
    返回：
      { record_id, status: "ok", scope, updated_at, changed_fields: [str] }
    
    失败：record 不存在 → { error: "not_found" }
    """
```

### 5.8 `memory_count`

```python
@mcp.tool
async def memory_count(
    filter: dict | None = None,
    scope: str = "memory",
) -> dict:
    """按 filter 计数（不返回详情）。
    
    何时调用：
      - 用户问"我有多少 XXX 类记忆"
      - 大批量 update / delete 前评估规模
      - 调试时确认库大小
    
    不要用于：
      - 要看具体记录时（用 list / query）
    
    返回：
      { count: int, scope, filter_applied: dict | None }
    
    离线可用（纯 SQLite 计数）。
    """
```

---

## 6. 组件分解

### 6.1 五层架构

| 层 | 模块 | 职责 |
|---|---|---|
| **L1: MCP Protocol** | FastMCP server + 8 tool 装饰器 | 协议层、stdio |
| **L2: Service** | MemoryService / SearchService / SyncService / BootstrapService | 业务编排 |
| **L3: Index Engine** | EmbeddingEngine / TextChunker / BM25Index / VectorIndex / RRFMerger / Reranker / LocalCache | 索引与检索 |
| **L4: Feishu Adapter** | BitableClient / DocxClient / DriveClient / WikiClient / TokenManager / RateLimiter | 飞书 API 封装 |
| **L5: Local Storage** | SQLite / LanceDB / FTS5 | 本地持久化 |

### 6.2 关键模块接口

**EmbeddingEngine**：
```python
class EmbeddingEngine:
    def __init__(self, model: str = "BAAI/bge-m3", device: str = "cpu"):
        self._model = SentenceTransformer(model, device=device)
        self._pool = ThreadPoolExecutor(max_workers=2)
    
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """异步 embedding，线程池跑 bge-m3"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self._pool, self._model.encode, texts)
    
    async def embed_query(self, query: str) -> list[float]:
        return (await self.embed([query]))[0]
```

**VectorIndex（可插拔接口）**：
```python
class VectorIndex(Protocol):
    async def upsert(self, chunks: list[MemoryChunk], embeddings: list[list[float]]) -> None
    async def delete_by_record(self, record_id: str) -> None
    async def search(
        self, query_vector: list[float], top_k: int, metadata_filter: dict
    ) -> list[tuple[str, float]]  # (chunk_id, score)


class LanceVectorIndex:
    """默认实现（文件级 LanceDB）"""
```

**LocalCache（SQLite）**：
```python
class LocalCache:
    async def get_record(self, record_id: str) -> MemoryRecord | None
    async def list_by_filter(self, filter: dict) -> list[str]  # 返回 record_ids
    async def list_records_page(self, filter, page, page_size, sort_by, desc) -> tuple[list[MemoryRecord], int]
    async def upsert(self, record: MemoryRecord) -> None
    async def delete(self, record_id: str) -> None
    async def count_by_filter(self, filter: dict) -> int
    async def update_metadata(
        self,
        record_id: str,
        title: str | None = None,
        tags: list[str] | None = None,
        extra: dict | None = None,
        source_agent: str | None = None,
    ) -> MemoryRecord | None  # 返回更新后的完整 record
    async def get_sync_state(self) -> SyncState
    async def update_sync_state(self, updates: dict) -> None
```

**SyncService**：
```python
class SyncService:
    async def incremental(self) -> SyncResult
    async def full(self) -> SyncResult
    async def rebuild(self) -> SyncResult
    async def auto_sync_on_startup(self) -> None:
        """MCP 服务启动时自动调用一次 incremental"""
```

---

## 7. 配置

### 7.1 配置项

```python
class Config(BaseSettings):
    # 飞书（必填）
    feishu_app_id: str
    feishu_app_secret: str
    
    # 双 Bitable 实例（必填，互不干扰）
    memory_bitable_app_token: str     # 记忆库 Bitable（multi-agent 共享）
    memory_bitable_table_id: str
    knowledge_bitable_app_token: str  # 知识库 Bitable（共享，可只读）
    knowledge_bitable_table_id: str
    
    # Agent 标识（写入 source_agent 字段，记忆库使用）
    agent_id: str = "default"
    
    # 本地存储
    data_dir: Path = Path("./.feishu_memory")
    
    # 模型
    embedding_model: str = "BAAI/bge-m3"
    reranker_model: str = "BAAI/bge-reranker-base"
    device: str = "cpu"  # "cuda" if available
    
    # 启动行为
    auto_sync_on_startup: bool = True
    auto_sync_scope: str = "memory"  # 启动时只 sync memory 还是两个都
    
    # MCP
    mcp_transport: str = "stdio"
    
    # 检索默认
    default_top_k: int = 5
    default_rerank: bool = True
    default_scope: str = "memory"  # tool 入参 scope 缺省值
```

### 7.2 启动方式

```bash
# env vars
FEISHU_APP_ID=cli_xxx \
FEISHU_APP_SECRET=xxx \
MEMORY_BITABLE_APP_TOKEN=xxx \
MEMORY_BITABLE_TABLE_ID=xxx \
KNOWLEDGE_BITABLE_APP_TOKEN=xxx \
KNOWLEDGE_BITABLE_TABLE_ID=xxx \
python -m mcp_memory

# 或 config file
feishu-memory --config config.toml
```

### 7.3 双 Bitable 启动行为

MCP 服务启动时：
- auto_sync_scope="memory" 只 sync memory_bitable（默认，节约启动时间）
- auto_sync_scope="both" sync 两个
- auto_sync_scope="none" 都不自动 sync（手动调）

### 7.4 双库 MCP 路由

```
8 个 tool + scope 参数：
  scope="memory"     → memory_bitable
  scope="knowledge"  → knowledge_bitable
  scope 缺省         → config.default_scope（默认 memory）

工具实现：同一个 Service 类，构造时传 bitable_client 引用
  MemoryService(bitable_client=memory_bitable)      # 写记忆库
  KnowledgeService(bitable_client=knowledge_bitable) # 写知识库
```

代码层：8 个 tool 接收 scope → 路由到对应 Service / bitable_client。
数据层：两个 Bitable 的 schema 完全一致，零迁移成本。

---

## 8. 错误处理

| 错误类别 | 例子 | 处理 |
|---|---|---|
| 入参错误 | text 空 / 超长 | 立即返回 `validation_failed` |
| 飞书 API 业务错误 | rate limit / scope 不够 | 重试 1 次 + 缓冲；标记 `feishu_write_failed` |
| 飞书 SDK 网络错误 | timeout / DNS | 指数退避重试 3 次；最终 `feishu_unreachable` |
| Embedding 失败 | 模型未下载 / OOM | 标记 `embedding_failed`；record 进 sync_status=pending 等重试 |
| 本地存储错误 | SQLite lock / 磁盘满 | 抛错让 agent 知道 |
| 跨进程并发 | 同机器跑多个 MCP 实例 | 文档化禁止（本地缓存不共享） |

---

## 9. 测试策略

| 测试层级 | 内容 |
|---|---|
| Unit | models / filter / rrf_merger / text_chunker（纯逻辑） |
| Integration (mock feishu) | 各 service 的完整流程 |
| E2E (real feishu) | 完整 sync 流程（CI 中跑） |
| 性能 | 万级记录的 sync 时间 / query 延迟 |

---

## 10. 部署

### 10.1 安装

```bash
pip install feishu-memory-mcp
```

### 10.2 Agent 接入示例

`~/.config/your-agent/mcp.json`:
```json
{
  "mcpServers": {
    "feishu-memory": {
      "command": "feishu-memory",
      "args": ["serve"],
      "env": {
        "FEISHU_APP_ID": "...",
        "FEISHU_APP_SECRET": "...",
        "BITABLE_APP_TOKEN": "...",
        "BITABLE_TABLE_ID": "..."
      }
    }
  }
}
```

### 10.3 数据目录

```
.feishu_memory/
├── local_cache.sqlite            # 元数据缓存 + sync_state
├── vectors.lance/                # LanceDB 数据
└── (FTS5 在 SQLite 内)
~/.cache/huggingface/             # bge-m3 模型缓存
```

### 10.4 CLI 子命令（agent-first 定位：仅做运维辅助）

**核心原则**：
- 主要用户是 agent（通过 8 个 MCP tool）
- 人类 CLI 仅做**运维辅助**：初始化 / 诊断 / 同步 / 状态 / 升级
- **不再提供 add / query / get / list / update / count / delete 子命令**（这些都交给 agent）
- 调试时偶尔需要，agent 已经替代

```
feishu-memory <command> [options]

commands:
  init           # 交互式配置（首次接入）：创建 config.toml + 引导飞书开发者后台 + Bitable 自检
  serve          # 启动 MCP stdio 服务（agent 主入口）
  doctor         # 诊断：飞书连通性、本地索引健康、双 Bitable scope 完整性
  sync           # 命令行触发 sync（手动 / CI / cron 用）
                 # --mode incremental|full|rebuild
                 # --scope memory|knowledge|both
  status         # 显示本地索引状态（缓存大小、最后 sync 时间、孤儿 chunks）
  schema         # dump / verify 当前 Bitable schema（含双库）
  migrate        # 重建 Bitable schema（升级用）
  version        # 打印版本
```

**每个子命令的设计要求**：
- `init`：交互式提问 + 飞书开发者后台跳转链接 + scope 自检 + **双 Bitable 引导**（同时配 memory 和 knowledge）
- `doctor`：≥4 项检查 —— 飞书 API ping / 双 Bitable 连通性 / 本地索引健康 / scope 配置一致性
- `serve`：错误发生时 stderr 输出 + JSON 化（不污染 stdout，因为 stdout 是 MCP 协议）
- `sync`：`--watch` 模式可后台常驻增量同步（可选，针对单 scope 或双 scope）
- `status`：分别显示 memory / knowledge 库的统计

**为何不暴露 add/query/get 等 CLI 子命令**：
- 几乎不需要人手执行（agent 自动处理）
- 如有调试需求，agent 可以直接通过 MCP 调（或者直接到飞书 UI 看 Bitable）
- 减少 cli.py 的实现复杂度和测试范围

### 10.5 README.md 结构（面向开源接入者）

```markdown
# feishu-memory-mcp

> 让任意 LLM agent 共享同一份飞书记忆库

## 5 分钟接入
## 工作原理
## 安装
## 配置（飞书开发者后台）
## 启动
## MCP 工具一览
## 常用场景（使用示例）
## 常见问题
## 进阶：架构 / 自定义 / 扩展
```

每个章节详细约定：

- **5 分钟接入**：引导复制粘贴 — 创建飞书 app → 拿 app_id/secret → `pip install` → `feishu-memory init` → 启动 agent
- **工作原理**：一段图（复述架构图）+ 飞书是权威源这一句
- **配置（飞书开发者后台）**：截图 / 文本"创建应用 → 添加 5 个机器人权限"
- **MCP 工具一览**：8 个 tool 一图一表
- **常见问题**：第一次跑为什么没结果 / 怎么改个标签 / sync 怎么跑

### 10.6 通用版**显式不做的**（避免实施时 scope 蔓延）

明确告诉读者**不要期待**这些功能：

- ❌ 多机器人身份隔离（已选场景 X：单机器人）
- ❌ 企业级多租户权限管理
- ❌ Web UI（飞书 Bitable 自带可视化）
- ❌ IM 消息 / 妙记主动抓取
- ❌ 自动附件 OCR / 解析（agent 自理）

这些限制写进 README 的"非目标 / Out of Scope"小节。

---

## 11. 目录结构

```
feishu-memory-mcp/
├── pyproject.toml
├── config.example.toml
├── README.md
├── src/
│   └── mcp_memory/
│       ├── __init__.py
│       ├── __main__.py               # 入口（python -m mcp_memory）
│       ├── cli.py                    # CLI 子命令（init / serve / doctor / sync ...）
│       ├── server.py                 # FastMCP server + 8 tools
│       ├── config.py
│       ├── models/
│       │   ├── record.py
│       │   ├── sync_state.py
│       │   └── filter.py
│       ├── services/
│       │   ├── memory_service.py
│       │   ├── search_service.py
│       │   ├── sync_service.py
│       │   └── bootstrap_service.py
│       ├── index/
│       │   ├── embedding_engine.py
│       │   ├── reranker.py
│       │   ├── text_chunker.py
│       │   ├── vector_index.py
│       │   ├── bm25_index.py
│       │   └── rrf_merger.py
│       ├── storage/
│       │   ├── local_cache.py
│       │   ├── schema.sql
│       │   └── paths.py
│       ├── feishu/
│       │   ├── client.py             # lark-oapi 单例
│       │   ├── bitable.py
│       │   ├── docx.py
│       │   ├── drive.py
│       │   ├── wiki.py
│       │   ├── token_manager.py
│       │   └── rate_limiter.py
│       └── utils/
│           ├── logging.py
│           └── retry.py
├── docs/
│   ├── architecture.md
│   ├── operations.md
│   ├── feishu-setup.md
│   └── tool-reference.md
├── skill/
│   └── feishu-memory/
│       └── SKILL.md
├── CHANGELOG.md
├── CONTRIBUTING.md
└── tests/
    ├── test_memory_service.py
    ├── test_search_service.py
    ├── test_sync_service.py
    ├── fixtures/
    └── conftest.py
```

---

## 12. 文档交付（通用版形态）

| 文档 | 受众 | 内容要点 |
|---|---|---|
| **README.md** | 接入者（首次） | 5 分钟接入、工作原理、安装、配置、MCP 工具一览、FAQ、非目标声明 |
| **docs/feishu-setup.md** | 接入者（首次） | 飞书开发者后台：创建 app、配置 5 个机器人 scope、获取 app_id/app_secret、首次配 Bitable |
| **docs/architecture.md** | 进阶用户 / 二次开发 | 架构图与设计原则（本 spec 的可读版） |
| **docs/operations.md** | 运维 / 自部署 | sync 策略、多实例约束、本地重建、缓存清理 |
| **docs/tool-reference.md** | agent / 集成者 | 8 个 MCP tool 的入参/出参/示例完整版 |
| **skill/feishu-memory/SKILL.md** | agent 加载 | 工作流提示：什么场景用什么 tool、附件上传流程、mode 选择 |
| **CHANGELOG.md** | 升级用户 | 语义化版本 |
| **CONTRIBUTING.md** | 贡献者 | PR 流程、测试要求、scope 说明 |

**关键的 3 个文档约定**：
1. README 必须引导读者 5 分钟内完成接入（命令复制粘贴可达）
2. docs/feishu-setup.md 必须配截图或详细步骤，因为飞书开发者后台流程多变
3. skill/feishu-memory/SKILL.md 必须教 agent 正确的"模式选择"（query mode / sync mode / filter）

### 12.1 Skill 文件关键内容约定

```yaml
# skill/feishu-memory/SKILL.md
---
name: feishu-memory
description: "Use when persisting knowledge, searching memories, or syncing with Feishu storage. Connects LLM agents to a Feishu-backed RAG via MCP."
---
```

内容应该教 agent：
- 何时用 `memory_add`（用户表达"我要记住 X"）
- 何时用 `memory_query` + mode 选择技巧
- 何时用 `memory_update` vs `delete + add`
- 何时用 `memory_sync`（本地陈旧、跨设备场景）
- 附件上传流程：先用 lark-drive 上传拿 token，再调 add
- 跨工具工作流：先 lark-cli 上传 → 再调 MCP add

---

## 13. 关键约束与已知限制

### 13.1 多实例约束
**禁止**同一机器跑多个 MCP 实例连同一飞书租户 —— 本地 SQLite 缓存不共享，会出现持久不一致。跨设备时飞书是权威源，各自 local cache 不会丢数据但不实时同步，需要 sync 触发对齐。

### 13.2 Drive 文件可搜索性约束
仅在飞书 UI 上传到 Drive 但未通过 MCP `memory_add` 录入的附件：
- `text_empty=True` 不被 `memory_query` 检索到（除非 `include_empty_text=True`）
- 元数据（文件名、标签）仍可 filter 到
- 解决方案：agent 主动调 `memory_add(text=解析内容, file_ref=...)` 补充

### 13.3 IM 消息 / 妙记不在范围
受 bot 身份权限限制，对个人场景价值低，已从范围中移除。

### 13.4 离线行为
- `memory_query` 完全离线可用
- `memory_get` / `memory_list` 完全离线可用
- `memory_count` 完全离线可用（纯 SQLite 计数）
- `memory_add` 必须联网（飞书写入）
- `memory_update` 必须联网（飞书 Bitable batch_update）
- `memory_sync` 必须联网
- `memory_delete` 必须联网（飞书 Bitable 删除）

### 13.5 启动时 sync 失败
启动时自动 sync 失败不会阻止 MCP 服务启动；下次启动或手动调用会重试。

---

## 14. 验收标准

待实施阶段通过 writing-plans skill 创建详细实施计划时细化。当前设计满足：

**功能性验收**
1. ✅ 飞书是唯一权威源，本地可重建
2. ✅ 多 agent 通过 `source_agent` 字段视图隔离
3. ✅ MCP 服务只暴露 8 个 tool，含 4 种 query mode + 3 种 sync mode
4. ✅ 三模式 sync（incremental / full / rebuild）
5. ✅ 启动自动 sync，失败不阻塞
6. ✅ 附件解析由 agent 自理
7. ✅ metadata 前置过滤 + 双路召回 + RRF + rerank
8. ✅ 写路径飞书先成功

**通用版（开源）验收**
9. ✅ `pip install` 后 `feishu-memory init` 能引导完成接入
10. ✅ `feishu-memory doctor` 输出可读诊断报告
11. ✅ `feishu-memory serve` 启动后 agent 通过 mcp.json 可连
12. ✅ README 5 分钟接入路径完整
13. ✅ docs/feishu-setup.md 含飞书后台步骤
14. ✅ skill/feishu-memory/SKILL.md 教 agent 正确工作流
15. ✅ 错误信息含 `console_url`（来自 lark-shared 规范的透传）

**CLI 运维辅助验收（agent-first 定位）**
16. ✅ CLI 仅暴露 `init / serve / doctor / sync / status / schema / migrate / version` 8 个运维子命令
17. ✅ `init` 同时引导配置 memory + knowledge 两个 Bitable（双库）
18. ✅ `doctor` 双 Bitable 连通性都能检查
19. ✅ `sync` 支持 `--scope memory|knowledge|both` 参数
20. ✅ README 主线是"5 分钟让 agent 接入"，CLI 简介附录

**Tool description 场景引导验收**
21. ✅ 8 个 tool 的 description 都含"何时用 / 不要用于"两段
22. ✅ query tool 的 4 个 mode 在 description 中各自带适用场景说明
23. ✅ sync tool 的 3 个 mode 在 description 中各自带适用场景说明
24. ✅ 8 个 tool 都接受 `scope` 参数（memory/knowledge），默认 memory
25. ✅ tool description 含"scope 选择"引导段

**双库隔离验收**
26. ✅ 配置文件含 memory_bitable_token + knowledge_bitable_token（各 2 个字段）
27. ✅ 同一组 8 个 tool 加 scope 路由到两个 Bitable
28. ✅ 两库 schema 完全一致，迁移成本零
29. ✅ scope="memory" 路由到 multi-agent 共享的 memory_bitable
30. ✅ scope="knowledge" 路由到知识库 Bitable

### 14.1 项目边界（明确不做的部分）

**减法审视后的非目标**，明确不实现：

| 非目标 | 理由 |
|---|---|
| 自动附件 OCR / 图片识别 | 现代 LLM agent 原生具备，agent 自理 |
| 多机器人身份隔离 | 已选"场景 X：单机器人共享身份" |
| 企业多租户权限 | 单用户 / 个人团队定位 |
| Web UI | 飞书 Bitable UI 已足够 |
| 实时事件订阅（lark-event）| 已选"主动 sync"，按需触发 |
| 跨设备实时同步 | 飞书是云但本地缓存不共享，sync 触发对齐 |
| IM 消息 / 妙记主动抓取 | 移除范围 |

实现时遇到非目标要扩范围，必须先回到设计讨论。

---

## 附录 A：依赖列表

```toml
[project]
dependencies = [
    "fastmcp>=0.5",                # MCP 协议
    "lark-oapi>=1.0",              # 飞书 SDK
    "pydantic>=2.0",               # 数据模型
    "pydantic-settings>=2.0",      # 配置
    "sentence-transformers>=3.0",  # bge-m3
    "lancedb>=0.5",                # 向量库
    "langchain-text-splitters>=0.3",  # 文本切分
    "sqlite-fts5",                 # 内建在 Python
]

[project.optional-dependencies]
dev = [
    "pytest",
    "pytest-asyncio",
    "pytest-cov",
    "ruff",
    "mypy",
]
```

## 附录 B：飞书 API 用到清单

- Bitable: `bitable.v1.app_table_record.list/create/update/delete`
- Docx: `docx.v1.document.create/raw_content` 等
- Drive: `drive.v1.file.upload/get_info`
- Wiki: `wiki.v2.space.list_node/...`
- 通用 `auth.v3.tenant_access_token.internal`

---

**设计文档结束。**
