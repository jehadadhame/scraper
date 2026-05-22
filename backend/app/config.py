from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Palestine Issue Signal Dashboard"
    database_url: str = (
        "postgresql+psycopg://signal:signal@127.0.0.1:5432/palestine_signals"
    )
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    frontend_origin: str = "http://127.0.0.1:5173"
    schedule_seconds: int = 60 * 60
    retention_days: int = 90
    evidence_limit_per_issue: int = 8

    telegram_api_id: int | None = None
    telegram_api_hash: str | None = None
    telegram_session_path: Path = Path("sessions/telegram.session")
    telegram_discovery_queries: str = "فلسطين,غزة,الضفة,Palestine,Gaza"

    discord_bot_token: str | None = None

    news_discovery_feed_urls: str = ""
    news_discovery_keywords: str = "فلسطين,غزة,الضفة,Palestine,Gaza,West Bank"

    hosted_ai_api_key: str | None = None
    hosted_ai_base_url: str = "https://api.openai.com/v1"
    hosted_ai_model: str = "gpt-5-mini"

    @field_validator("telegram_api_id", mode="before")
    @classmethod
    def blank_optional_int(cls, value: object) -> object:
        return None if value == "" else value

    @property
    def telegram_queries(self) -> list[str]:
        return split_csv(self.telegram_discovery_queries)

    @property
    def news_discovery_feeds(self) -> list[str]:
        return split_csv(self.news_discovery_feed_urls)

    @property
    def news_keywords(self) -> list[str]:
        return split_csv(self.news_discovery_keywords)


def split_csv(value: str) -> list[str]:
    return [entry.strip() for entry in value.split(",") if entry.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
