from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py -> repo root is three levels up
_REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    app_name: str = "razorpay-agent"
    app_env: str = "development"
    log_level: str = "INFO"
    default_user_id: str = "user_demo"
    cors_origins: str = "http://localhost:3000"
    database_url: str = "sqlite:///./razorpay_agent.db"

    model_config = SettingsConfigDict(
        env_file=_REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
