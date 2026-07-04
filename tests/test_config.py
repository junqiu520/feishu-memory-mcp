import pytest
from pydantic import SecretStr, ValidationError
from mcp_memory.config import Config


REQUIRED_ENV_NAMES = [
    "FEISHU_APP_ID",
    "FEISHU_APP_SECRET",
    "MEMORY_BITABLE_APP_TOKEN",
    "MEMORY_BITABLE_TABLE_ID",
    "KNOWLEDGE_BITABLE_APP_TOKEN",
    "KNOWLEDGE_BITABLE_TABLE_ID",
]


def _set_required_env(monkeypatch) -> None:
    """Set the four required env vars (memory) to harmless placeholders.

    knowledge_bitable_* is now optional — the user's own knowledge library
    may not be set up. Sync gracefully skips the missing scope.
    """
    monkeypatch.setenv("FEISHU_APP_ID", "x")
    monkeypatch.setenv("FEISHU_APP_SECRET", "x")
    monkeypatch.setenv("MEMORY_BITABLE_APP_TOKEN", "x")
    monkeypatch.setenv("MEMORY_BITABLE_TABLE_ID", "x")


def test_config_required_fields(monkeypatch):
    """All four required (memory) fields must be reported when missing.

    knowledge_bitable_* is optional — its absence is allowed; sync gracefully
    skips the missing scope. We assert they are NOT in missing_locs.
    """
    for name in REQUIRED_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(ValidationError) as exc_info:
        Config(_env_file=None)  # type: ignore[call-arg]

    missing_locs = {
        tuple(err["loc"])
        for err in exc_info.value.errors()
        if err["type"] == "missing"
    }
    expected_required = {
        ("feishu_app_id",),
        ("feishu_app_secret",),
        ("memory_bitable_app_token",),
        ("memory_bitable_table_id",),
    }
    # knowledge fields must NOT be in missing (they're optional)
    expected_optional_absent = {
        ("knowledge_bitable_app_token",),
        ("knowledge_bitable_table_id",),
    }
    assert expected_required.issubset(missing_locs), (
        f"Expected all four required memory fields to be reported missing; "
        f"got {sorted(missing_locs)}"
    )
    assert not (expected_optional_absent & missing_locs), (
        f"knowledge_bitable_* must be optional, but they were reported missing: "
        f"{sorted(missing_locs & expected_optional_absent)}"
    )


def test_config_loads_from_env(monkeypatch):
    monkeypatch.setenv("FEISHU_APP_ID", "cli_test_123")
    monkeypatch.setenv("FEISHU_APP_SECRET", "secret_456")  # pragma: allowlist secret
    monkeypatch.setenv("MEMORY_BITABLE_APP_TOKEN", "bitA_xxx")
    monkeypatch.setenv("MEMORY_BITABLE_TABLE_ID", "tblA_xxx")
    monkeypatch.setenv("KNOWLEDGE_BITABLE_APP_TOKEN", "bitB_xxx")
    monkeypatch.setenv("KNOWLEDGE_BITABLE_TABLE_ID", "tblB_xxx")
    monkeypatch.setenv("AGENT_ID", "test-agent")

    cfg = Config(_env_file=None)  # type: ignore[call-arg]
    assert cfg.feishu_app_id == "cli_test_123"
    assert isinstance(cfg.feishu_app_secret, SecretStr)
    assert cfg.feishu_app_secret.get_secret_value() == "secret_456"  # pragma: allowlist secret
    assert cfg.memory_bitable_app_token == "bitA_xxx"
    assert cfg.memory_bitable_table_id == "tblA_xxx"
    assert cfg.knowledge_bitable_app_token == "bitB_xxx"
    assert cfg.knowledge_bitable_table_id == "tblB_xxx"
    assert cfg.agent_id == "test-agent"


def test_config_defaults(monkeypatch):
    _set_required_env(monkeypatch)

    cfg = Config(_env_file=None)  # type: ignore[call-arg]
    assert cfg.data_dir.name == ".feishu_memory"
    assert cfg.embedding_model == "sentence-transformers/all-MiniLM-L6-v2"
    assert cfg.reranker_model == "BAAI/bge-reranker-base"
    assert cfg.device == "cpu"
    assert cfg.default_scope == "memory"
    assert cfg.default_top_k == 5
    assert cfg.default_rerank is True
    assert cfg.auto_sync_on_startup is True
    assert cfg.auto_sync_scope == "memory"
    assert cfg.mcp_transport == "stdio"


def test_env_string_to_int_coercion(monkeypatch):
    """Env vars are strings; default_top_k must coerce to int."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("DEFAULT_TOP_K", "10")

    cfg = Config(_env_file=None)  # type: ignore[call-arg]
    assert cfg.default_top_k == 10
    assert isinstance(cfg.default_top_k, int)


def test_case_insensitive_env(monkeypatch):
    """Lowercase env var names must still resolve (case_sensitive=False)."""
    _set_required_env(monkeypatch)
    monkeypatch.delenv("FEISHU_APP_ID", raising=False)
    monkeypatch.setenv("feishu_app_id", "cli_lowercase")

    cfg = Config(_env_file=None)  # type: ignore[call-arg]
    assert cfg.feishu_app_id == "cli_lowercase"


def test_default_top_k_must_be_positive(monkeypatch):
    """default_top_k must be >= 1; zero must be rejected."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("DEFAULT_TOP_K", "0")

    with pytest.raises(ValidationError) as exc_info:
        Config(_env_file=None)  # type: ignore[call-arg]
    locs = {tuple(err["loc"]) for err in exc_info.value.errors()}
    assert ("default_top_k",) in locs


def test_invalid_literal_rejected(monkeypatch):
    """auto_sync_scope is Literal['memory','knowledge']; typo must be rejected."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("AUTO_SYNC_SCOPE", "memry_typo")

    with pytest.raises(ValidationError) as exc_info:
        Config(_env_file=None)  # type: ignore[call-arg]
    locs = {tuple(err["loc"]) for err in exc_info.value.errors()}
    assert ("auto_sync_scope",) in locs
