"""Environment-backed settings.

This is an initial scaffold. Dependencies are added during implementation phase.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    telegram_bot_token: str
    owner_telegram_id: int

    deepseek_api_key: str
    deepseek_base_url: str = ""
    deepseek_model: str = ""

    database_url: str = "sqlite:///runtime/judicial_comment_bot.db"
    auto_accept_score: int = 90
    candidate_display_count: int = 3
    search_candidate_limit: int = 8

    temp_dir: str = "runtime/tmp"
    log_level: str = "INFO"
    delete_files_after_send: bool = True

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()
