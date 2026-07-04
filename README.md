# feishu-memory-mcp

> **飞书驱动的 RAG 记忆库 MCP server。** Agent 长期记忆 + 个人知识库，两者都存飞书多维表格，通过同一套 Model Context Protocol 接口可检索。

[![CI](https://github.com/junqiu520/feishu-memory-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/junqiu520/feishu-memory-mcp/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

## 这是什么

`feishu-memory-mcp` 把 **飞书（Lark / Feishu）** 当成持久化后端，
给 LLM agent 提供两套隔离但统一的记忆服务：

| Scope | 用途 | 谁来写 | 谁来读 |
|-------|------|--------|--------|
| **`memory`** | agent 的长期记忆（对话片段、agent 自动 add 的内容、解析后的资料）| **agent** | agent + 你 |
| **`knowledge`** | 你的个人知识库（笔记、规范、文档）| **你**（或 agent辅助录入）| agent + 你 |

两库都用飞书多维表格做持久化 + 本地 SQLite + LanceDB 做查询缓存，agent 通过 9 个 MCP 工具读写。

## 快速安装

```bash
# 1. 装 Python 包
pip install feishu-memory-mcp

# 2. 装系统依赖（自动检测 Node.js / npm 然后 npm install -g @larksuite/cli）
feishu-memory install-deps

# 3. lark-cli OAuth 授权（会打开浏览器）
lark-cli config init

# 4. 在飞书 UI 创建 2 个**空的**多维表格（memory / knowledge 各一个）
#    这一步必须手动：飞书不开放「创建空 Bitable」的 API，需要人去
#    https://open.feishu.cn/base 点几下创建。记下每个表的 app_token
#    和 table_id。

# 5. 配环境变量
export FEISHU_APP_ID=cli_xxxxxxxxxxxx
export FEISHU_APP_SECRET=...
export MEMORY_BITABLE_APP_TOKEN=bascnxxxxxxxxxxxx
export MEMORY_BITABLE_TABLE_ID=tblxxxxxxxxxxxxxxxx
export KNOWLEDGE_BITABLE_APP_TOKEN=bascnyyyyyyyyyyyy
export KNOWLEDGE_BITABLE_TABLE_ID=tblyyyyyyyyyyyyy

# 6. 自动建表（16 个字段一次性创建）+ 验证
feishu-memory init      # 自动建表（不需要手动加字段）
feishu-memory doctor    # 6/6 检查过
feishu-memory sync      # 第一次拉飞书 Bitable 数据
feishu-memory serve     # 启动 MCP server（agent 客户端连）
```

`init` 会自动调用 `ensure_bitable_schema()` 创建全部 16 个字段，所以**用户不需要在飞书 UI 手动加字段**。字段定义见 [docs/deployment.md](docs/deployment.md)。

## 给 agent 用：9 个 MCP 工具

把这段加到 agent 客户端的 mcp 配置（Claude Desktop / Cursor / Codex / etc）：

```json
{
  "mcpServers": {
    "feishu-memory": {
      "command": "feishu-memory",
      "args": ["serve"],
      "env": { "FEISHU_APP_ID": "...", "...": "..." }
    }
  }
}
```

启动后 agent 看到这 9 个 tool：

| Tool | 用途 | Scope |
|------|------|-------|
| `memory_add` | 写一条记忆（agent 自己加，或保存对话） | memory / knowledge |
| `memory_query` | 检索（4 种 mode：hybrid_rerank / hybrid / bm25 / vector） | memory / knowledge |
| `memory_get` | 取一条完整内容 | memory / knowledge |
| `memory_update` | 改一条的元数据（标题/标签） | memory / knowledge |
| `memory_delete` | 删除一条 | memory / knowledge |
| `memory_list` | 列表（带分页 + 排序） | memory / knowledge |
| `memory_count` | 计数 | memory / knowledge |
| `memory_sync` | 触发与飞书的同步（3 种 mode：incremental / full / rebuild） | memory / knowledge |
| `file_upload` | 上传本地文件到飞书云盘，返回 `file_token` + `url`（供 `memory_add.file_ref` 使用） | — |

每个 tool 接受 `scope` 参数（`memory` / `knowledge`）。`memory_query` 还有 4 种 mode 选：
- `hybrid_rerank`（默认）：BM25 + 向量 + RRF + 重排
- `hybrid`：BM25 + 向量 + RRF（不要重排，更快）
- `bm25_only`：纯关键词
- `vector_only`：纯语义

详细 tool 文档：[docs/tool-reference.md](docs/tool-reference.md)

## 命令行（CLI 运维）

`feishu-memory` 是个 single-binary CLI，每个子命令独立：

| 子命令 | 作用 |
|--------|------|
| `init` | 打印首次安装的环境变量模板 |
| `install-deps` | 检测 Node.js / npm 并装 lark-cli |
| `serve` | 启动 MCP server（stdio 传输）|
| `doctor` | 诊断 Node / npm / lark-cli / config / cache 状态 |
| `sync` | 手动触发与飞书的同步 |
| `status` | 看本地 cache 状态（记录数、最后 sync 时间、vector index 大小）|
| `schema` | 导出 / 验证 Bitable 字段定义 vs spec |
| `migrate` | 重建本地 cache（model 切换后 / cache 损坏）|
| `version` | 打印版本号 |

每个子命令都支持 `--help`。

## 架构一览

```
[agent client]  ←stdio/MCP→  [feishu-memory-mcp]  ←subprocess→  [lark-cli]  ←HTTPS→  [飞书]
    • 9 tools      │              │ Service Layer         │              │       • Bitable
    • stdin/stdout│              │ • MemoryService       │              │       • Docx
                  │              │ • SearchService       │              │       • Drive
                  │              │ • SyncService         │              │
                  │              │ • BootstrapService    │              │
                  │              │   (冷启动初始化)        │              │
                  │              │                       │              │
                  │              ├─ Index Engine         │              │
                  │              │ • EmbeddingEngine     │              │
                  │              │   (bge-m3 / MiniLM)   │              │
                  │              │ • TextChunker         │              │
                  │              │ • Reranker            │              │
                  │              │ • RRFMerger           │              │
                  │              │                       │              │
                  │              └─ Local Storage        │              │
                  │                 • SQLite (FTS5)       │              │
                  │                 • LanceDB (vectors)   │              │
                  │                                                  │
                  └─ Skill file: skill/feishu-memory/SKILL.md
```

详细架构：[docs/architecture.md](docs/architecture.md)

## Embedding 模型选择

`feishu-memory-mcp` 用 [sentence-transformers](https://www.sbert.net)
做 embedding。**默认**用 `BAAI/bge-m3`（中文/多语种最佳选择，2.3GB / 1024 维 / 首次下载约 30 分钟无 HF_TOKEN，约 5 分钟有 `HF_TOKEN`）。

如果想要更轻量的替代：

| Model | 大小 | 维度 | 何时用 |
|-------|------|------|--------|
| `BAAI/bge-m3` *(默认)* | 2.3GB | 1024 | 中文 / 多语种推荐 |
| `sentence-transformers/all-MiniLM-L6-v2` | 80MB | 384 | 快速启动（英文为主，不需要 HF_TOKEN） |
| `BAAI/bge-small-en-v1.5` | 33MB | 384 | 极简英文 |
| `BAAI/bge-large-en-v1.5` | 1.3GB | 1024 | 纯英文高质量 |
| `intfloat/multilingual-e5-base` | 1GB | 768 | 中英文平衡 |

切换：`.env` 里改 `EMBEDDING_MODEL` 然后重启 + 跑 `feishu-memory migrate`（不同 model 维度不同）。

加速下载：免费申请 HF_TOKEN <https://huggingface.co/settings/tokens>，5-10x 加速。

## 项目特点

- **飞书是唯一权威源** — 本地 cache 可任意删，`feishu-memory migrate` 一键从飞书恢复
- **多 agent 共享同一记忆库** — `source_agent` 字段标记来源，不同 agent 共享同一张 Bitable
- **可重建 vector index** — 切换 embedding model 后 `migrate` 重建 LanceDB
- **失败容忍** — 飞书写失败不阻塞本地写，下次 sync 自动重试
- **CLI 优先** — 9 个子命令覆盖所有运维场景，不需要查 SQL / 直接读 Bitable
- **零额外 Node 包** — `lark-cli` 是 npm 全局唯一依赖；Python 端纯 `lancedb` + `sentence-transformers` + SQLite
- **OS 跨平台** — Windows / macOS / Linux 全部 CI 测过

## 文档索引

- [docs/deployment.md](docs/deployment.md) — 11 步详细部署指南
- [docs/installation.md](docs/installation.md) — 安装 + 飞书后台 + 模型选择
- [docs/architecture.md](docs/architecture.md) — 架构详解
- [docs/operations.md](docs/operations.md) — sync 策略 + 运维 + 故障排查
- [docs/tool-reference.md](docs/tool-reference.md) — 9 个 tool 完整入参出参
- [CHANGELOG.md](CHANGELOG.md) — 0.1.0 release notes
- [CONTRIBUTING.md](CONTRIBUTING.md) — 贡献指南
- [skill/feishu-memory/SKILL.md](skill/feishu-memory/SKILL.md) — agent 自动加载的 skill

## 开发

```bash
git clone https://github.com/junqiu520/feishu-memory-mcp
cd feishu-memory-mcp
pip install -e ".[dev]"
pytest                 # 跑全部 unit tests
ruff check src tests
```

CI：push 即跑（Python 3.11/3.12/3.13，Ubuntu latest）。

## 许可

MIT.