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

    # --- Layer 1: agent + policy engine ---
    nvidia_api_key: str = ""
    llm_model: str = "nvidia/nemotron-3.5-lightning-30b-a3b"
    llm_fallback: str = "openai/gpt-oss-120b"
    llm_timeout_seconds: float = 30.0
    llm_max_retries: int = 2
    llm_retry_backoff_seconds: float = 1.0
    # paise per token. Default 0 — NVIDIA's current tier is free. cost_paise
    # on every audit event is computed from this, so it's real the day the
    # rate isn't zero, with no code changes.
    llm_cost_paise_per_token: float = 0.0

    agent_max_iterations: int = 8

    # --- Layer 2: payments (Razorpay test mode) ---
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_currency: str = "INR"
    razorpay_timeout_seconds: float = 10.0

    # Policy thresholds. All in paise; all overridable via env, all with a
    # sane default so the system is never unbounded even if unconfigured.
    policy_default_spend_cap_paise: int = 500_000  # ₹5,000 — used only when a session sets no budget_paise
    policy_per_item_max_paise: int = 300_000  # ₹3,000 — no single catalog item is denied by default
    policy_quantity_max: int = 10
    policy_confirmation_threshold_paise: int = 100_000  # ₹1,000

    # --- Layer 3: chaos injection + resilience ---
    # A global, sticky fault for a demo segment (e.g. CHAOS_FAULT=SLOW_LLM).
    # Empty = off. Overridable per-request via the X-Chaos-Fault header.
    # Both are gated by app_env == "development" in app/testing/chaos.py —
    # there is no way to enable chaos from a production config.
    chaos_fault: str = ""
    llm_circuit_breaker_failure_threshold: int = 3
    llm_circuit_breaker_cooldown_seconds: float = 30.0

    model_config = SettingsConfigDict(
        env_file=_REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
