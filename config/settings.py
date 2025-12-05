"""
AI Workforce Platform - Configuration Settings
Enhanced with environment-specific configs and validation
"""

from functools import lru_cache
from typing import Any, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    """Database configuration"""

    model_config = SettingsConfigDict(env_prefix="DATABASE_")

    url: SecretStr = Field(
        default="postgresql+asyncpg://user:password@localhost:5432/ai_workforce"
    )
    pool_size: int = Field(default=20, ge=5, le=100)
    max_overflow: int = Field(default=10, ge=0, le=50)
    echo: bool = Field(default=False)


class RedisSettings(BaseSettings):
    """Redis configuration"""

    model_config = SettingsConfigDict(env_prefix="REDIS_")

    url: str = Field(default="redis://localhost:6379/0")
    cache_url: str = Field(default="redis://localhost:6379/1")
    celery_url: str = Field(default="redis://localhost:6379/2")


class AnthropicSettings(BaseSettings):
    """Anthropic API configuration"""

    model_config = SettingsConfigDict(env_prefix="ANTHROPIC_")

    api_key: SecretStr = Field(default="")
    default_model: str = Field(default="claude-sonnet-4-20250514")
    fast_model: str = Field(default="claude-3-haiku-20240307")
    powerful_model: str = Field(default="claude-opus-4-20250514")
    max_tokens: int = Field(default=4096)
    temperature: float = Field(default=0.7, ge=0, le=1)


class OpenAISettings(BaseSettings):
    """OpenAI API configuration"""

    model_config = SettingsConfigDict(env_prefix="OPENAI_")

    api_key: SecretStr = Field(default="")
    default_model: str = Field(default="gpt-4o")
    fast_model: str = Field(default="gpt-4o-mini")
    embedding_model: str = Field(default="text-embedding-3-small")


class ProxySettings(BaseSettings):
    """Proxy configuration for anti-detection"""

    model_config = SettingsConfigDict(env_prefix="PROXY_")

    provider: Literal["brightdata", "oxylabs", "smartproxy", "none"] = Field(
        default="none"
    )
    brightdata_zone: str = Field(default="residential")
    brightdata_username: SecretStr = Field(default="")
    brightdata_password: SecretStr = Field(default="")
    oxylabs_username: SecretStr = Field(default="")
    oxylabs_password: SecretStr = Field(default="")
    rotation_interval_minutes: int = Field(default=30)


class CaptchaSettings(BaseSettings):
    """CAPTCHA solving configuration"""

    model_config = SettingsConfigDict(env_prefix="CAPTCHA_")

    provider: Literal["2captcha", "anticaptcha", "capsolver", "none"] = Field(
        default="none"
    )
    twocaptcha_api_key: SecretStr = Field(default="")
    anticaptcha_api_key: SecretStr = Field(default="")


class QualitySettings(BaseSettings):
    """Quality assurance configuration"""

    model_config = SettingsConfigDict(env_prefix="QA_")

    plagiarism_check_enabled: bool = Field(default=True)
    ai_detection_enabled: bool = Field(default=True)
    grammar_check_enabled: bool = Field(default=True)
    min_quality_score: float = Field(default=0.8, ge=0, le=1)
    max_ai_detection_score: float = Field(default=0.3, ge=0, le=1)


class RateLimitSettings(BaseSettings):
    """Rate limiting configuration"""

    model_config = SettingsConfigDict(env_prefix="RATE_")

    max_proposals_per_hour: int = Field(default=5, ge=1)
    max_messages_per_hour: int = Field(default=20, ge=1)
    max_job_applications_per_day: int = Field(default=30, ge=1)
    max_concurrent_agents: int = Field(default=100, ge=1)
    max_concurrent_jobs: int = Field(default=50, ge=1)


class FeatureFlagSettings(BaseSettings):
    """Feature flags for gradual rollout"""

    model_config = SettingsConfigDict(env_prefix="ENABLE_")

    auto_bidding: bool = Field(default=True)
    auto_messaging: bool = Field(default=True)
    learning_system: bool = Field(default=True)
    ab_testing: bool = Field(default=True)
    market_intelligence: bool = Field(default=True)
    multi_model_routing: bool = Field(default=True)
    federated_learning: bool = Field(default=False)


class JobScoringSettings(BaseSettings):
    """Job scoring algorithm configuration"""

    model_config = SettingsConfigDict(env_prefix="JOB_SCORING_")

    min_hourly_rate: float = Field(default=15.0, ge=0)
    max_completion_time_hours: int = Field(default=24, ge=1)
    min_client_rating: float = Field(default=4.0, ge=0, le=5)
    min_client_jobs_posted: int = Field(default=3, ge=0)
    max_applicants: int = Field(default=20, ge=1)
    min_score_threshold: float = Field(default=0.6, ge=0, le=1)

    # Scoring weights
    weight_profit_margin: float = Field(default=0.25, ge=0, le=1)
    weight_difficulty: float = Field(default=0.15, ge=0, le=1)
    weight_client_quality: float = Field(default=0.20, ge=0, le=1)
    weight_competition: float = Field(default=0.15, ge=0, le=1)
    weight_success_probability: float = Field(default=0.25, ge=0, le=1)

    @model_validator(mode="after")
    def validate_weights_sum(self) -> "JobScoringSettings":
        total = (
            self.weight_profit_margin
            + self.weight_difficulty
            + self.weight_client_quality
            + self.weight_competition
            + self.weight_success_probability
        )
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"Scoring weights must sum to 1.0, got {total}")
        return self


class Settings(BaseSettings):
    """Main application settings"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = Field(default="ai-workforce-platform")
    app_env: Literal["development", "staging", "production"] = Field(
        default="development"
    )
    debug: bool = Field(default=False)
    secret_key: SecretStr = Field(default="change-me-in-production")

    # API
    api_host: str = Field(default="0.0.0.0")
    api_port: int = Field(default=8000)
    api_workers: int = Field(default=4)

    # Nested settings
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    anthropic: AnthropicSettings = Field(default_factory=AnthropicSettings)
    openai: OpenAISettings = Field(default_factory=OpenAISettings)
    proxy: ProxySettings = Field(default_factory=ProxySettings)
    captcha: CaptchaSettings = Field(default_factory=CaptchaSettings)
    quality: QualitySettings = Field(default_factory=QualitySettings)
    rate_limits: RateLimitSettings = Field(default_factory=RateLimitSettings)
    features: FeatureFlagSettings = Field(default_factory=FeatureFlagSettings)
    job_scoring: JobScoringSettings = Field(default_factory=JobScoringSettings)

    # Monitoring
    sentry_dsn: str = Field(default="")
    prometheus_enabled: bool = Field(default=True)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO"
    )
    log_format: Literal["json", "text"] = Field(default="json")

    @field_validator("secret_key")
    @classmethod
    def validate_secret_key(cls, v: SecretStr) -> SecretStr:
        if v.get_secret_value() == "change-me-in-production":
            import warnings
            warnings.warn("Using default secret key - change in production!")
        return v

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()


# Export commonly used settings
settings = get_settings()
