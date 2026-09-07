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
    deepseek_research_model: str = "deepseek-v4-flash"
    deepseek_commentary_model: str = "deepseek-v4-pro"

    deepseek_connect_timeout_seconds: float = 15.0
    deepseek_stream_idle_timeout_seconds: float = 180.0
    deepseek_commentary_idle_timeout_seconds: float = 420.0

    # Backwards-compatible parsing only; these are no longer total deadlines.
    deepseek_request_timeout_seconds: float = 120.0
    deepseek_research_timeout_seconds: float = 75.0
    deepseek_commentary_timeout_seconds: float = 120.0

    deepseek_research_attempts: int = 1
    deepseek_synthesis_attempts: int = 1
    deepseek_max_search_calls_for_synthesis: int = 6
    deepseek_preflight_ttl_seconds: float = 300.0
    commentary_validation_attempts: int = 2

    deepseek_research_reasoning_effort: str = "none"
    deepseek_synthesis_reasoning_effort: str = "low"
    deepseek_commentary_reasoning_effort: str = "high"

    database_url: str = "sqlite+aiosqlite:///runtime/judicial_comment_bot.db"
    auto_accept_score: int = 90
    candidate_display_count: int = 3
    search_candidate_limit: int = 5
    search_retry_rounds: int = 1

    # Official catalog is the primary discovery path. A refresh is built as an
    # isolated snapshot and becomes active only after all activation gates pass.
    catalog_enabled: bool = True
    catalog_fallback_to_web: bool = True
    catalog_min_candidates_before_fallback: int = 3
    catalog_manifest_path: str = "config/catalog_sources.yaml"
    catalog_min_cases_for_activation: int = 20
    catalog_min_candidates_per_subject: int = 1
    catalog_required_subject_coverage_percent: int = 100
    catalog_max_document_failure_ratio: float = 0.35
    catalog_keep_inactive_generations: int = 2

    temp_dir: str = "runtime/tmp"
    log_level: str = "INFO"
    delete_files_after_send: bool = True
    stale_temp_max_age_hours: int = 6
    progress_update_interval_seconds: float = 3.0

    pdf_max_bytes: int = 50 * 1024 * 1024
    pdf_max_pages: int = 1500
    pdf_download_timeout_seconds: float = 45.0
    pdf_connect_timeout_seconds: float = 10.0
    pdf_processing_timeout_seconds: float = 90.0
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

    @field_validator("catalog_required_subject_coverage_percent")
    @classmethod
    def validate_coverage_percent(cls, value: int) -> int:
        if not 1 <= value <= 100:
            raise ValueError("CATALOG_REQUIRED_SUBJECT_COVERAGE_PERCENT must be 1..100")
        return value

    @field_validator("catalog_max_document_failure_ratio")
    @classmethod
    def validate_failure_ratio(cls, value: float) -> float:
        if not 0 <= value < 1:
            raise ValueError("CATALOG_MAX_DOCUMENT_FAILURE_RATIO must be >= 0 and < 1")
        return value

    @field_validator(
        "deepseek_research_attempts",
        "deepseek_synthesis_attempts",
        "deepseek_max_search_calls_for_synthesis",
        "commentary_validation_attempts",
        "search_retry_rounds",
        "search_candidate_limit",
        "catalog_min_candidates_before_fallback",
        "catalog_min_cases_for_activation",
        "catalog_min_candidates_per_subject",
        "catalog_keep_inactive_generations",
    )
    @classmethod
    def validate_positive_counts(cls, value: int) -> int:
        if value < 1:
            raise ValueError("Retry/attempt/count values must be at least 1")
        return value

    @field_validator(
        "progress_update_interval_seconds",
        "deepseek_connect_timeout_seconds",
        "deepseek_stream_idle_timeout_seconds",
        "deepseek_commentary_idle_timeout_seconds",
        "deepseek_request_timeout_seconds",
        "deepseek_research_timeout_seconds",
        "deepseek_commentary_timeout_seconds",
        "deepseek_preflight_ttl_seconds",
        "pdf_download_timeout_seconds",
        "pdf_connect_timeout_seconds",
        "pdf_processing_timeout_seconds",
    )
    @classmethod
    def validate_positive_timeouts(cls, value: float) -> float:
        if value < 1:
            raise ValueError("Timeout/interval values must be at least 1 second")
        return value

    @field_validator(
        "deepseek_research_reasoning_effort",
        "deepseek_synthesis_reasoning_effort",
        "deepseek_commentary_reasoning_effort",
    )
    @classmethod
    def validate_reasoning_effort(cls, value: str) -> str:
        normalized = value.strip().lower()
        allowed = {"none", "minimal", "low", "medium", "high", "xhigh", "max"}
        if normalized not in allowed:
            raise ValueError(f"Unsupported DeepSeek reasoning effort: {value}")
        return normalized


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
