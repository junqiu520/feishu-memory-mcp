---
name: feishu-memory
description: "用于跨会话持久化知识、搜索历史上下文、与飞书存储同步时使用。调用 feishu-memory-mcp 工具来访问共享的 agent 记忆。"
---

# feishu-memory MCP 技能

你可以通过 `feishu-memory-mcp` 访问一个共享的 RAG 记忆库。用于跨会话持久化——当用户要求你"记住这个"，或者你识别出可复用的知识，或者你需要查找过去的上下文时使用。

## 何时使用

| 用户说 | 工具 |
|--------|------|
| "记住这个偏好 / 存这条经验 / 记录这个教训" | `memory_add(scope="memory")` |
| "帮我存这份规范 / 把这份文档存到知识库" | `memory_add(scope="knowledge")` |
| "我之前讲过 X 吗 / 找那条关于 Y 的记忆" | `memory_query` |
| "展开看那条 / 给我完整内容" | `memory_get`（需要先有 `record_id`）|
| "改一下标签 / 改标题" | `memory_update` |
| "忘掉这条 / 删除" | `memory_delete`（需要 `confirm: true`）|
| "列出我有哪些 X" | `memory_list` 或 `memory_count` |
| "同步一下 / 拉取最新" | `memory_sync` |
| "把这个 PDF 上传到飞书 / 把这个文件存档" | `file_upload` |

## Scope 选择

- `memory`（默认）：存储可复用的经验、用户的偏好/教训、事件里程碑等。
  不要用于：临时上下文（对话中直接保留）、系统指令（不是记忆）。
- `knowledge`：存储用户的材料/文件（规范、文档、笔记等），但需要你先解析附件内容为文本。
  file_ref 需要先调用 file_upload 工具获取 file token + URL。
- 不确定？先用 `memory`。

## 查询模式选择

| 查询意图 | `mode` |
|----------|--------|
| 默认；混合意图；需要最佳结果 | `"hybrid_rerank"` |
| 精确匹配名称/日期/ID/缩写 | `"bm25_only"` |
| 抽象概念/相似表述 | `"vector_only"` |
| 想跳过重排以加速 | `"hybrid"` |

重排会花费额外时间和少量 CPU，但能显著提升长查询的质量。除非优化延迟，否则默认使用 `"hybrid_rerank"`。

## 文件上传

文件（PDF/PPT/图片）不能直接嵌入。添加文件内容的步骤：

1. 通过 MCP 工具上传到飞书云盘：
   `file_upload(file_paths=["/path/to/file.pdf"])`。传入一个列表可以一次上传多个文件。
   每条路径返回自己的状态条目；单个失败不会中止其他文件。
2. 从响应中获取每个成功上传的 `file_token` 和 `url`。
3. 使用你的原生文件读取能力（Claude/GPT-4o vision 等）将每个文件转换为文本。
4. 对每个文件调用 `memory_add(text=<转换后的文本>, file_ref={type: "drive_file", token, url})`。

`file_ref` 是元数据，让用户可以点击跳转到飞书中的原文档；可搜索的内容是你传入的 `text`。

## 同步

如果搜索结果看起来过时——比如用户说"我昨天加过那个"但你找不到——调用：

```
memory_sync(mode="incremental")
```

不要调用 `memory_sync(mode="rebuild")`，除非用户报告缓存损坏；`rebuild` 会重新嵌入所有内容，很慢。

## 不要使用的情况

- 会话内临时上下文——直接在对话中保留就好
- 系统提示/指令——这些不是记忆
- 用户明确说"不要记住"的数据

## 跨 scope 搜索

搜索一个 scope 不会自动搜索另一个。要搜索两个库：

1. 调用 `memory_query(scope="memory", ...)`
2. 调用 `memory_query(scope="knowledge", ...)`
3. 合并结果

MCP 工具故意没有 `scope="both"` 参数——CLI 的 `feishu-memory sync --scope both` 用于运维，但每次查询时 agent 决定查询哪个库。