# 更新日志

本项目的所有重要更改都将记录在此文件中。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/spec/v2.0.0.html)。

## [0.1.0] - 2026-07-XX

### 新增

- 初始发布
- 9 个 MCP 工具：`memory_add` / `memory_query` / `memory_get` /
  `memory_update` / `memory_delete` / `memory_list` / `memory_count` /
  `memory_sync` / `file_upload`
- 飞书支持的 RAG（Bitable + Docx + Drive + Wiki 数据源）
- 本地 SQLite + LanceDB + FTS5 缓存（可从飞书重建）
- bge-m3 嵌入 + 可选的 bge-reranker-base 交叉编码器
- 9 个 CLI 子命令：`init` / `install-deps` / `serve` / `doctor` /
  `sync` / `status` / `schema` / `migrate` / `version`
- 双 Bitable 概念：`memory` + `knowledge`（基于 scope 的路由）
- 通过记录上的 `source_agent` 字段支持多 agent
- Agent 技能位于 `skill/feishu-memory/SKILL.md`（由支持 MCP 的客户端自动加载）
- `file_upload` MCP 工具：批量将本地文件上传到飞书云盘，
  并返回每个文件的 `file_token` + `url`，供 `memory_add.file_ref` 使用
- 测试：22 个文件中 174 个用例

### 架构决策

- 飞书是唯一的真相来源；本地缓存可重建
- lark-cli 子进程替代 lark-oapi Python SDK（少一个依赖，跨运行时统一 OAuth）
- `feishu_app_secret` 在端到端以 `pydantic.SecretStr` 保存，从不跨越子进程边界
- 三种同步模式（`incremental` / `full` / `rebuild`）；incremental 是默认且安全的定时任务
- 混合检索：BM25 + 向量 + RRF（+ 可选的重排）
- 写入路径以飞书为先；本地缓存尽力而为，使用 `pending` 回退，下次同步时协调

[0.1.0]: https://github.com/your-org/feishu-memory-mcp/releases/tag/v0.1.0