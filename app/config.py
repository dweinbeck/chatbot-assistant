"""Application configuration loaded from environment variables."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings with environment variable loading and sensible defaults."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/chatbot"
    app_name: str = "chatbot-assistant"
    debug: bool = False
    log_level: str = "INFO"
    host: str = "0.0.0.0"
    port: int = 8080

    # Phase 2: Ingestion pipeline settings
    github_webhook_secret: str = "dev-secret"
    github_token: str = ""
    gcp_project: str = ""
    gcp_location: str = "us-central1"
    cloud_tasks_queue: str = "indexing"
    task_handler_base_url: str = "http://localhost:8080"


settings = Settings()
