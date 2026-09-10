from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ── Datastores ────────────────────────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://sovereign:sovereign_pass@postgres:5432/sovereign"
    sync_database_url: str = "postgresql+psycopg://sovereign:sovereign_pass@postgres:5432/sovereign"
    redis_url: str = "redis://redis:6379"
    qdrant_url: str = "http://qdrant:6333"
    ollama_url: str = "http://ollama:11434"

    # ── Shared volumes (identical mount points in `api` and `worker`) ─────────
    uploads_dir: str = "/data/uploads"
    knowledge_dir: str = "/data/knowledge"
    artifacts_dir: str = "/data/artifacts"
    workspaces_dir: str = "/data/workspaces"
    sandbox_queue_dir: str = "/sandbox_queue"

    models_yaml_path: str = "/app/infra/models.yaml"
    secret_key: str = "change-me-for-production"

    # ── Agent guards (plan.md: max 8 tool cycles, 10 min wall clock) ──────────
    max_tool_cycles: int = 8
    run_timeout_seconds: int = 600
    approval_timeout_seconds: int = 1800
    sandbox_timeout_seconds: int = 60


settings = Settings()
