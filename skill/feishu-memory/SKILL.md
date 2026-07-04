---
name: feishu-memory
description: "Use when persisting knowledge across sessions, searching prior context, or syncing with Feishu storage. Calls the feishu-memory-mcp tools for shared agent memory."
---

# feishu-memory MCP skill

You have access to a shared RAG memory via `feishu-memory-mcp`. Use it for
cross-session persistence — when a user asks you to "remember this", or you
identify reusable knowledge, or you need to look up past context.

## When to use

| User says                                            | Tool                                                   |
|------------------------------------------------------|--------------------------------------------------------|
| "记住 / 帮我保存这条 / 收藏这段对话"                  | `memory_add`                                           |
| "我之前讲过 X 吗 / 找那条关于 Y 的记忆"              | `memory_query`                                         |
| "展开看那条 / 给我完整内容"                          | `memory_get` (must have `record_id` first)              |
| "改一下标签 / 改标题"                                | `memory_update`                                        |
| "忘掉这条 / 删除"                                    | `memory_delete` (with `confirm: true`)                 |
| "列出我有哪些 X"                                     | `memory_list` or `memory_count`                        |
| "同步一下 / 拉取最新"                                | `memory_sync`                                          |

## Scope choice

- `memory` (default): your own shared memory across agents. Use for notes,
  conversation, agent-generated content.
- `knowledge`: the owner's curated knowledge base. Use when the user is
  feeding you reference material they want indexed.
- Don't know? Start with `memory`.

## Query mode choice

| Query intent                                          | `mode`                |
|-------------------------------------------------------|-----------------------|
| Default; mixed intent; need best results              | `"hybrid_rerank"`     |
| Exact name / date / ID / acronym                      | `"bm25_only"`         |
| Abstract concept / similar phrasing                   | `"vector_only"`       |
| Want to skip reranker for speed                       | `"hybrid"`            |

Reranking takes extra time and a tiny amount of CPU but materially improves
quality on long, ambiguous queries. Default to `"hybrid_rerank"` unless
you're optimizing for latency.

## Filename / file uploads

Files (PDF / PPT / images) cannot be embedded directly. To add a file's content:

1. First upload to Feishu Drive: `lark-cli drive +upload /path/to/file.pdf`
2. Get back file token + URL from lark-cli output
3. Use your native file-reading capability (Claude/GPT-4o vision, etc.) to
   convert the file to text
4. Call `memory_add(text=<converted_text>, file_ref={type: "drive_file", token, url})`

The `file_ref` is metadata that lets the user click through to the original
in Feishu; the searchable body is the `text` you pass.

## Sync

If results look stale — for example, the user said "I added that yesterday"
but you can't find it — call:

```
memory_sync(mode="incremental")
```

Don't call `memory_sync(mode="rebuild")` unless the user reports cache
corruption; `rebuild` re-embeds everything and is slow.

## Don't use

- For session-only context — just keep it in conversation.
- For system prompts / instructions — these are not memories.
- For data the user explicitly says "don't remember".

## Cross-scope search

Searching one scope does NOT search the other. To search both:

1. Call `memory_query(scope="memory", ...)`
2. Call `memory_query(scope="knowledge", ...)`
3. Merge the results.

There is intentionally no `scope="both"` for the MCP tool — the CLI's
`feishu-memory sync --scope both` exists for ops, but per-query the agent
decides which library to query.
