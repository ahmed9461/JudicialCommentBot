"""Application settings loaded from environment variables."""

from functools import lru_cache

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    telegram_bot_token: SecretStr
    owner_telegram_id: int

    deepseek_api_key: SecretStr | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-pro"
    deepseek_request_timeout_seconds: float = 120.0
    deepseek_research_attempts: int = 2

    database_url: str = "sqlite+aiosqlite:///runtime/judicial_comment_bot.db"
    auto_accept_score: int = 90
    candidate_display_count: int = 3
    search_candidate_limit: int = 8
    search_retry_rounds: int = 2

    temp_dir: str = "runtime/tmp"
    log_level: str = "INFO"
    delete_files_after_send: bool = True
    stale_temp_max_age_hours: int = 6
    progress_update_interval_seconds: float = 3.0

    pdf_max_bytes: int = 50 * 1024 * 1024
    pdf_max_pages: int = 1500
    pdf_download_timeout_seconds: float = 90.0
    pdf_max_redirects: int = 5
    compilation_page_threshold: int = 60
    commentary_input_max_chars: int = 70000
    commentary_min_text_chars: int = 500

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore"
    )

    @field_validator("owner_telegram_id")
    @classmethod
    def validate_owner_id(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("OWNER_TELEGRAM_ID must be a positive Telegram user ID")
        return value

    @field_validator("auto_accept_score")
    @classmethod
    def validate_score(cls, value: int) -> int:
        if not 0 <= value <= 100:
            raise ValueError("AUTO_ACCEPT_SCORE must be between 0 and 100")
        return value

    @field_validator("deepseek_research_attempts", "search_retry_rounds")
    @classmethod
    def validate_positive_attempts(cls, value: int) -> int:
        if value < 1:
            raise ValueError("Retry/attempt counts must be at least 1")
        return value

    @field_validator("progress_update_interval_seconds")
    @classmethod
    def validate_progress_interval(cls, value: float) -> float:
        if value < 1:
            raise ValueError("PROGRESS_UPDATE_INTERVAL_SECONDS must be at least 1")
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
