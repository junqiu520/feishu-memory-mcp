from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
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
    feishu_app_secret: SecretStr

    # 双 Bitable 实例
    # - memory 库必填（agent 主用）
    # - knowledge 库可选（owner 可不设置，sync 时跳过）
    memory_bitable_app_token: str
    memory_bitable_table_id: str
    knowledge_bitable_app_token: str | None = None
    knowledge_bitable_table_id: str | None = None

    # Agent 标识
    agent_id: str = "default"

    # lark-cli binary (optional override; default: PATH lookup via shutil.which)
    lark_cli_path: str | None = None

    # 本地存储
    data_dir: Path = Path("./.feishu_memory")

    # 模型
    embedding_model: str = "BAAI/bge-m3"
    reranker_model: str = "BAAI/bge-reranker-base"
    device: Literal["cpu", "cuda", "mps"] = "cpu"

    # 启动行为
    auto_sync_on_startup: bool = True
    auto_sync_scope: Literal["memory", "knowledge"] = "memory"

    # MCP
    mcp_transport: Literal["stdio", "sse"] = "stdio"

    # 检索默认
    default_top_k: int = Field(default=5, ge=1)
    default_rerank: bool = True
    default_scope: Literal["memory", "knowledge"] = "memory"
