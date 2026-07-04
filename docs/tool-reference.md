# 工具参考

MCP 服务器暴露 **9 个工具** —— 8 个通过 `AppContext` 路由（每个都有
`scope` 参数，`"memory"` 或 `"knowledge"`，默认 `"memory"`），
1 个不带 scope 的工具（`file_upload`）。所有工具都在
[`src/mcp_memory/server.py`](../src/mcp_memory/server.py) 中实现。
本文档是权威参考；`server.py` 中的函数签名是规范来源。

## 约定

- 所有工具都是 **async** 的，返回 `dict`（MCP 兼容）。
- `scope="memory"`（默认）路由到 agent 共享的记忆 Bitable。
  `scope="knowledge"` 路由到 owner 维护的知识 Bitable。
  路由通过 **工具调用** 完成，而不是通过记录 —— 一条记录只存在于一个 Bitable 中。
- 错误以 `{"error": "<code>", ...}` 形式返回，其中 `error` 已设置；
  成功始终带有 `"status"`（或领域字段）以便于分支。
- 时间字段是 unix 纪元毫秒。

## Scope 参考

| Scope | 路由到 | 典型写入者 | 典型读取者 |
|-------|--------|------------|------------|
| `memory` | `memory_bitable` | `memory_add`（agents）| 所有 agents + owner |
| `knowledge` | `knowledge_bitable` | 直接编辑 Bitable / 文件同步 | Agents 通过 `memory_query` |

如果不确定，**从 `memory` 开始**。知识库用于 owner 整理参考资料时。

---

## memory_add

添加一条新的记忆记录。先写入飞书（权威源），然后尽力写入本地缓存。

**签名**（规范）：

```text
async def memory_add(
    text: str,
    file_ref: dict | None = None,
    title: str | None = None,
    tags: list[str] | None = None,
    extra: dict | None = None,
    scope: str = "memory",
) -> dict
```

### 何时调用：

scope="memory"（默认）：
存储可复用的经验、用户的偏好/教训、事件里程碑等。
不要用于：临时上下文（对话中直接保留）、系统指令（不是记忆）。

scope="knowledge"：
存储用户的材料/文件（规范、文档、笔记等），但需要你先解析附件内容为文本。
file_ref 需要先调用 file_upload 工具获取 file token + URL。

### 参数

| 名称 | 类型 | 必需 | 默认值 | 描述 |
|------|------|------|--------|------|
| `text` | `str` | 是 | — | 要存储的纯文本（1–100 000 字符）。文件附件必须由调用者先解析。 |
| `file_ref` | `dict \| None` | 否 | `None` | 飞书云盘文件的引用。格式：`{type, token, url, file_name?, mime_type?}`。 |
| `title` | `str \| None` | 否 | `text` 的前 30 个字符 | 在 Bitable 中显示的人类可读标题。 |
| `tags` | `list[str] \| None` | 否 | `[]` | 可搜索的标签。规范化为小写 + 去重。 |
| `extra` | `dict \| None` | 否 | `{}` | 额外的键值对元数据；序列化到 Bitable 的 `extra_json`。 |
| `scope` | `str` | 否 | `"memory"` | `"memory"` 或 `"knowledge"`。其他值会引发 `ValueError`。 |

### 返回格式

```json
{
  "record_id": "rec_a1b2c3d4",
  "status": "ok",
  "chunk_count": 0,
  "feishu_url": null,
  "scope": "memory",
  "warning": null
}
```

`status` 在成功时为 `"ok"`。`warning`（可选）是非致命的提示，
例如 `"local embedding skipped; will retry on next sync"`。

### 示例

```python
await memory_add(
    text="FastAPI + uvicorn 部署；根据 CPU 数量设置 --workers。",
    tags=["python", "deployment"],
    extra={"source_doc": "runbook-2026Q3"},
    scope="memory",
)

# 使用 file_ref
await memory_add(
    text="PDF 内容由 agent 转换为文本 ...",
    file_ref={
        "type": "drive_file",
        "token": "boxcnxxx",
        "url": "https://feishu.cn/drive/file/boxcnxxx",
        "file_name": "whitepaper.pdf",
        "mime_type": "application/pdf",
    },
    tags=["whitepaper", "rag"],
)
```

---

## memory_query

搜索本地索引。**默认和推荐的模式是 `"hybrid_rerank"`**，
它结合了 BM25、向量、RRF 和重排。

### 签名

```text
async def memory_query(
    query: str,
    top_k: int = 5,
    filter: dict | None = None,
    mode: str = "hybrid_rerank",
    scope: str = "memory",
) -> dict
```

### 参数

| 名称 | 类型 | 必需 | 默认值 | 描述 |
|------|------|------|--------|------|
| `query` | `str` | 是 | — | 自然语言查询字符串。 |
| `top_k` | `int` | 否 | `5` | 要返回的结果数（1+）。 |
| `filter` | `dict \| None` | 否 | `None` | 在检索前按元数据进行预过滤。 |
| `mode` | `str` | 否 | `"hybrid_rerank"` | 检索模式。见下表。 |
| `scope` | `str` | 否 | `"memory"` | `"memory"` 或 `"knowledge"`。 |

#### 过滤器格式

```python
{
    "tags_any": ["python", "deployment"],          # 这些标签中的任何一个
    "tags_all": ["python"],                         # 所有这些标签
    "source_agent": "claude-1",                     # 按 agent 限制（memory scope）
    "source_type": "agent_add",                     # agent_add / feishu_doc / 等
    "created_after": 1719000000000,                 # unix 毫秒；包含
    "updated_after": 1719000000000,                 # unix 毫秒；包含
    "include_empty_text": False                     # 默认 False：跳过 text_empty
}
```

所有键都是可选的。空/`None` 过滤器表示没有预过滤。

#### 模式比较

| 模式 | 路径 | 何时使用 | 成本 |
|------|------|----------|------|
| `bm25_only` | 仅 FTS5 关键词 | 精确名称 / 日期 / id / 缩写 | 最快 |
| `vector_only` | bge-m3 → LanceDB 余弦 | 抽象概念 / 改写意图 | 快 |
| `hybrid` | BM25 + 向量，用 RRF 融合，**不重排** | 想要 RRF 收益但跳过重排器 | 中 |
| `hybrid_rerank`（默认） | BM25 + 向量 + RRF + bge-reranker-base | 混合意图；想要最佳结果 | 最慢（最佳质量） |

### 返回格式

```json
{
  "results": [
    {
      "record_id": "rec_a1b2c3d4",
      "score": 0.93,
      "title": "FastAPI + uvicorn 部署",
      "preview": "FastAPI + uvicorn 部署；设置 --workers ...",
      "matched_chunk_text": "...匹配的片段...",
      "content_ref_url": "https://feishu.cn/docs/...",
      "tags": ["python", "deployment"],
      "source": "agent_add",
      "source_agent": "claude-1",
      "created_at": 1719000000
    }
  ],
  "query_embedding_ms": 47,
  "total_candidates": 23,
  "cache_age_seconds": 12,
  "scope": "memory"
}
```

`cache_age_seconds` 报告自上次同步以来本地索引的陈旧程度（以秒为单位）。
较高的值表明你可能需要 `memory_sync`。

### 示例

```python
# 默认 —— 适合"我想要正确答案，快速"
results = await memory_query(query="如何部署 FastAPI 应用")

# 强制仅关键词查找项目代号
results = await memory_query(
    query="ATLAS-2042",
    mode="bm25_only",
)

# 限制标签 + 日期窗口
results = await memory_query(
    query="事件复盘模板",
    top_k=10,
    filter={"tags_any": ["postmortem"], "updated_after": 1717200000000},
)
```

---

## memory_get

按 id 获取一条记录，包括其完整文本和内容引用。

### 签名

```text
async def memory_get(record_id: str, scope: str = "memory") -> dict
```

### 参数

| 名称 | 类型 | 必需 | 默认值 | 描述 |
|------|------|------|--------|------|
| `record_id` | `str` | 是 | — | 由 `memory_add` / `memory_list` / `memory_query` 返回的 id。 |
| `scope` | `str` | 否 | `"memory"` | 要查找的 Bitable。 |

### 返回格式

```json
{
  "record_id": "rec_a1b2c3d4",
  "title": "FastAPI + uvicorn 部署",
  "preview": "FastAPI + uvicorn 部署；根据 CPU 数量设置 --workers。",
  "content_ref": {
    "type": "docx",
    "token": "doccnxxx",
    "url": "https://feishu.cn/docs/doccnxxx"
  },
  "file_ref": null,
  "tags": ["python", "deployment"],
  "source": "agent_add",
  "source_agent": "claude-1",
  "created_at": 1719000000,
  "updated_at": 1719000123,
  "full_text": "FastAPI + uvicorn 部署；根据 CPU 数量设置 --workers。\n\n...",
  "chunks": [],
  "scope": "memory"
}
```

如果未找到：

```json
{ "error": "not_found", "record_id": "rec_xxx", "scope": "memory" }
```

### 示例

```python
rec = await memory_get(record_id="rec_a1b2c3d4")
if "error" not in rec:
    print(rec["full_text"])
```

---

## memory_update

编辑现有记录的元数据。**不会更改 `text` 或 `content_ref`。**
要更改文本，请调用 `memory_delete` 然后 `memory_add`。

### 签名

```text
async def memory_update(
    record_id: str,
    scope: str = "memory",
    title: str | None = None,
    tags: list[str] | None = None,
    extra: dict | None = None,
) -> dict
```

### 参数

| 名称 | 类型 | 必需 | 默认值 | 描述 |
|------|------|------|--------|------|
| `record_id` | `str` | 是 | — | 目标记录。 |
| `scope` | `str` | 否 | `"memory"` | 记录所在的 Bitable。 |
| `title` | `str \| None` | 否 | 不变 | 新标题（替换现有的）。 |
| `tags` | `list[str] \| None` | 否 | 不变 | 替换。传 `[]` 表示清空；传 `None` 表示保持不变。 |
| `extra` | `dict \| None` | 否 | 不变 | 替换。与 `tags` 相同的语义。 |

注意：`tags=[]` 表示 *清空*，`tags=None`（或省略参数）表示
*保持原样*。`extra` 也是如此。

### 返回格式

```json
{
  "record_id": "rec_a1b2c3d4",
  "status": "ok",
  "scope": "memory",
  "updated_at": 1719000999,
  "changed_fields": ["title", "tags"]
}
```

如果未找到：

```json
{ "error": "not_found", "record_id": "rec_xxx", "scope": "memory" }
```

### 示例

```python
await memory_update(
    record_id="rec_a1b2c3d4",
    tags=["python", "deployment", "fastapi"],
    title="FastAPI + uvicorn — 生产部署笔记",
)
```

---

## memory_delete

从飞书和本地缓存中永久删除一条记录。云盘源文件（如果有）**不会**被删除。

### 签名

```text
async def memory_delete(record_id: str, confirm: bool = False, scope: str = "memory") -> dict
```

### 参数

| 名称 | 类型 | 必需 | 默认值 | 描述 |
|------|------|------|--------|------|
| `record_id` | `str` | 是 | — | 目标记录。 |
| `confirm` | `bool` | 是（实际） | `False` | 安全检查。必须为 `True` 才能删除。 |
| `scope` | `str` | 否 | `"memory"` | 记录所在的 Bitable。 |

### 返回格式

成功：

```json
{ "status": "deleted", "record_id": "rec_a1b2c3d4", "scope": "memory" }
```

未找到：

```json
{ "status": "not_found", "record_id": "rec_xxx", "scope": "memory" }
```

拒绝（无确认）：

```json
{ "error": "confirm_required", "record_id": "rec_xxx" }
```

### 示例

```python
await memory_delete(record_id="rec_a1b2c3d4", confirm=True)
```

### 注意

- **此操作不可逆。** Bitable 记录被删除，缓存也被删除。
  要"编辑"正文，请使用 `memory_update` 编辑元数据，
  或使用 `memory_delete` + `memory_add` 来更改内容。
- 云盘源文件不受影响（飞书自身的云盘保留策略适用）。

---

## memory_list

分页列出记录，**不带语义搜索** —— 只是元数据过滤 + 排序。
当你需要相关性排序时，请使用 `memory_query`。

### 签名

```text
async def memory_list(
    filter: dict | None = None,
    page: int = 1,
    page_size: int = 20,
    sort_by: str = "updated_at",
    desc: bool = True,
    scope: str = "memory",
) -> dict
```

### 参数

| 名称 | 类型 | 必需 | 默认值 | 描述 |
|------|------|------|--------|------|
| `filter` | `dict \| None` | 否 | `None` | 与 `memory_query` 相同的过滤器格式。 |
| `page` | `int` | 否 | `1` | 从 1 开始的页码。 |
| `page_size` | `int` | 否 | `20` | 每页项数（1–200）。 |
| `sort_by` | `str` | 否 | `"updated_at"` | 排序字段。 |
| `desc` | `bool` | 否 | `True` | 如果为 `True`，按最新优先；如果为 `False`，按最旧优先。 |
| `scope` | `str` | 否 | `"memory"` | `"memory"` 或 `"knowledge"`。 |

### 返回格式

```json
{
  "items": [],
  "total": 142,
  "page": 1,
  "page_size": 20,
  "has_more": true,
  "scope": "memory",
  "_ids": ["rec_a1b2c3d4", "rec_e5f6g7h8", "rec_i9j0k1l2"]
}
```

> 注意：在当前实现中，已解析的 `record_id` 在 `_ids` 中返回。
> `items` 字段保留供将来使用详细负载。请使用 `memory_get` 获取任何 id 的完整内容。

### 示例

```python
# 分页浏览所有"design"条目，最新优先
listed = await memory_list(
    filter={"tags_any": ["design"]},
    page=1,
    page_size=50,
)
for rid in listed["_ids"]:
    rec = await memory_get(record_id=rid)
    print(rec["title"])
```

---

## memory_count

按过滤器计算匹配记录数，不返回负载。**仅本地** —— 离线工作。

### 签名

```text
async def memory_count(filter: dict | None = None, scope: str = "memory") -> dict
```

### 参数

| 名称 | 类型 | 必需 | 默认值 | 描述 |
|------|------|------|--------|------|
| `filter` | `dict \| None` | 否 | `None` | 与 `memory_query` 相同的过滤器格式。 |
| `scope` | `str` | 否 | `"memory"` | `"memory"` 或 `"knowledge"`。 |

### 返回格式

```json
{ "count": 142, "filter_applied": null, "scope": "memory" }
```

### 示例

```python
n = await memory_count(filter={"tags_any": ["design"]})
print(f"有 {n['count']} 条带 design 标签的记忆")
```

---

## memory_sync

协调本地缓存与飞书。**如果你发现本地索引看起来陈旧，或在直接编辑 Bitable 后，请调用此函数。**

### 签名

```text
async def memory_sync(mode: str = "incremental", scope: str = "memory") -> dict
```

### 参数

| 名称 | 类型 | 必需 | 默认值 | 描述 |
|------|------|------|--------|------|
| `mode` | `str` | 否 | `"incremental"` | 之一：`"incremental"`、`"full"`、`"rebuild"`。 |
| `scope` | `str` | 否 | `"memory"` | `"memory"`、`"knowledge"`。（CLI 还接受 `"both"`；MCP 工具每次调用针对一个 scope。） |

> CLI `feishu-memory sync --scope both` 一次同步两个 scope。
> MCP `memory_sync` 工具针对单个 scope；要同步两者，请调用两次。

#### 模式比较

| 模式 | 它做什么 | 时间 | 是否触及飞书数据 | 使用场景 |
|------|----------|------|------------------|----------|
| `incremental` | 拉取 `updated_at > last_sync_at` 的记录；仅为更改的文本生成嵌入 | 秒级 | 否 | 日常使用；定时任务；启动自动同步 |
| `full` | 拉取所有飞书记录；与本地缓存对比；仅为更改重新嵌入 | 分钟级 | 否 | 长时间离开后赶上 |
| `rebuild` | 擦除本地缓存，重新导入所有内容，重新嵌入所有内容 | 分钟级（最长） | 否 | 缓存损坏，嵌入模型更改 |

### 返回格式

一个 `SyncResult` 字典：

```json
{
  "mode": "incremental",
  "added": 3,
  "updated": 1,
  "deleted": 0,
  "errors": [],
  "started_at": 1719000123,
  "finished_at": 1719000189,
  "scope": "memory"
}
```

对于无效的 `mode`：

```json
{ "error": "invalid_mode", "mode": "weekly" }
```

### 示例

```python
# 在飞书 UI 中编辑 Bitable 后
await memory_sync(mode="incremental")

# 长时间离开后，在繁忙的库上
await memory_sync(mode="full")

# 在更改嵌入模型后，或缓存损坏
await memory_sync(mode="rebuild")
```

### 注意

- 同步是 **仅拉取** —— 它永远不会修改飞书记录（除了
  `memory_add` 和 `memory_delete` 创建/删除的记录）。
- 在庞大的库上同步可能很慢。`incremental` 是唯一适合
  不到一分钟间隔的定时任务的模式。
- 在启动时，当 `FEISHU_MEMORY_AUTO_SYNC=true`（默认）时，
  服务器会自动运行 `incremental`。

---

## 过滤器参考（由 `memory_query`、`memory_list`、`memory_count` 使用）

每个键都是可选的。缺失的键 = 对该维度没有约束。

| 键 | 类型 | 含义 |
|----|------|------|
| `tags_any` | `list[str]` | 记录必须具有**至少一个**这些标签。 |
| `tags_all` | `list[str]` | 记录必须具有**所有**这些标签。 |
| `source_agent` | `str` | 限制为特定 agent（仅 memory scope）。 |
| `source_type` | `str` | 之一：`agent_add`、`feishu_doc`、`feishu_bitable`、`feishu_drive_file`、`feishu_wiki`。 |
| `created_after` | `int`（毫秒） | `created_at >= this`。 |
| `updated_after` | `int`（毫秒） | `updated_at >= this`。 |
| `include_empty_text` | `bool` | 默认 `False`：跳过 `text_empty=True` 的记录。设置为 `True` 以包含它们。 |

`tags_any` 和 `tags_all` 可以组合使用；记录必须满足两者。

## 快速 scope 决策表

| 用户希望 | 使用 |
|----------|------|
| 保存事实、笔记或对话片段 | `memory_add(scope="memory")` |
| 添加 owner 给你的参考文档 | `memory_add(scope="knowledge")` |
| 搜索之前的 agent 上下文 | `memory_query(scope="memory")` |
| 搜索 owner 维护的库 | `memory_query(scope="knowledge")` |
| 列出所有以某种方式标记的内容 | `memory_list` / `memory_count` |
| 修复以前记忆标题中的拼写错误 | `memory_update` |
| 忘记一条记忆 | `memory_delete(confirm=True)` |
| 在飞书 UI 中编辑 Bitable 后刷新 | `memory_sync` |

## 快速查询模式决策表

| 查询意图 | 使用模式 |
|----------|----------|
| 默认；混合意图；需要最佳结果 | `"hybrid_rerank"` |
| 精确名称 / 日期 / ID / 缩写 | `"bm25_only"` |
| 抽象概念；改写的含义 | `"vector_only"` |
| 想要融合但跳过重排器以加速 | `"hybrid"` |

---

## file_upload

将一个或多个本地文件上传到飞书云盘，并为每个文件返回 `file_token` +
`url`。使用此工具获取 `memory_add` 所需的 `file_ref` 负载。
**不按 scope 限定** —— 飞书云盘上传是全局的，因此此工具不接受 `scope` 参数。

**签名**（规范）：

```text
async def file_upload(
    file_paths: list[str],
) -> dict
```

### 参数

| 名称 | 类型 | 必需 | 默认值 | 描述 |
|------|------|------|--------|------|
| `file_paths` | `list[str]` | 是 | — | 要上传的本地文件路径。传入多个以进行批量上传。 |

### 返回格式

```json
{
  "uploads": [
    {
      "file_path": "/path/to/whitepaper.pdf",
      "status": "ok",
      "file_token": "boxcnxxx",
      "url": "https://feishu.cn/drive/file/boxcnxxx",
      "name": "whitepaper.pdf"
    },
    {
      "file_path": "/path/to/missing.pdf",
      "status": "error",
      "error": "file_not_found"
    }
  ]
}
```

对于空输入：

```json
{ "error": "empty_file_paths", "uploads": [] }
```

### 每个条目的状态

| `status` | 何时 | 其他字段 |
|----------|------|----------|
| `"ok"` | 上传成功 | `file_token`、`url`、`name` |
| `"error"` | 本地文件缺失 | `error: "file_not_found"` |
| `"error"` | 空 / null 路径 | `error: "empty_path"` |
| `"error"` | 云盘未返回 token | `error: "no_file_token_returned"` |
| `"error"` | lark-cli 子进程失败 | `error: <message>` |

一个条目失败绝不会中止批处理 —— 每个路径产生自己的结果，
因此你可以从部分成功中恢复。

### 示例

```python
# 上传一个文件，然后存储其内容
result = await file_upload(file_paths=["/path/to/whitepaper.pdf"])
ok = next(u for u in result["uploads"] if u["status"] == "ok")
await memory_add(
    text=<从文件转换的文本>,
    file_ref={
        "type": "drive_file",
        "token": ok["file_token"],
        "url": ok["url"],
        "file_name": ok["name"],
    },
)

# 一次上传多个文件
result = await file_upload(
    file_paths=["/path/to/a.pdf", "/path/to/b.png", "/path/to/c.pptx"],
)
for entry in result["uploads"]:
    if entry["status"] == "ok":
        # ... 转换每个文件并调用 memory_add ...
        pass
    else:
        # 向用户报告每个文件的错误
        print(f"失败：{entry['file_path']} ({entry['error']})")
```

### 注意

- 该工具返回 `file_token` + `url`。你希望被索引的 `text` 必须来自
  你自己的文件读取步骤（视觉模型、OCR、解析器等）——
  `file_upload` 不会提取内容。
- 返回条目中的 `file_name` 在可用时来自飞书上传响应，
  否则回退到 `file_paths` 的基本名称。