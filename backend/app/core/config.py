from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py -> repo root is three levels up
_REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    app_name: str = "razorpay-agent"
    app_env: str = "development"
    log_level: str = "INFO"
    default_user_id: str = "user_demo"
    # The one canonical dev frontend origin — used for CORS, OAuth origin
    # validation, and every post-login redirect target. Deliberately a
    # single value, not a list: `localhost` and `127.0.0.1` are different
    # origins for cookies and CORS even on the same machine/port, and on
    # some machines `localhost` resolves to ::1 while the dev server only
    # binds IPv4 (ERR_FAILED) — supporting both invited exactly that class
    # of bug. Pick one address and use it consistently everywhere.
    frontend_url: str = "http://127.0.0.1:3000"
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

    # --- Layer 4.5: agent-readable catalog ---
    merchant_display_name: str = "Razorpay AI Buildathon Demo Store"

    # --- Layer 4.5: bounded upsell ---
    policy_upsell_max_per_session: int = 1  # how many upsell offers this session will ever see, regardless of outcome
    policy_upsell_max_pct_of_cart: float = 0.50  # an offer priced above this fraction of the original cart value is blocked

    # --- Layer 4.6: campaign orchestrator ---
    # Segmentation thresholds (deterministic, no LLM — app/campaigns/segmentation.py)
    campaign_lapsed_days: int = 90
    campaign_repeat_min_orders: int = 3
    campaign_high_value_threshold_paise: int = 200_000  # ₹2,000 lifetime spend
    campaign_category_loyal_min_share: float = 0.6

    # Offer policy — merchant-wide constants, never overridable by a campaign proposal
    campaign_max_discount_pct: float = 0.30  # ₹ off must never exceed 30% of list price
    campaign_min_margin_pct: float = 0.15  # discounted price must clear cost by at least 15%

    # Per-campaign-run parameters, resolved once from config before any offer is evaluated
    campaign_default_budget_paise: int = 300_000  # ₹3,000 max total giveaway per campaign
    campaign_min_segment_size: int = 5  # refuse to run a campaign on a smaller segment
    campaign_max_offers_per_window: int = 1  # a customer may be targeted this many times per window
    campaign_offer_frequency_window_days: int = 30

    # Control group + simulated redemption (see docs/046-campaigns.md — this
    # whole block is a documented, explicit toy assumption, never observed data)
    campaign_control_group_fraction: float = 0.25
    campaign_base_organic_conversion_rate: float = 0.05  # baseline chance ANY customer buys the featured product anyway
    campaign_discount_lift_sensitivity: float = 0.6  # extra conversion-probability points per 1.0 (100%) of discount_pct

    # --- Layer 4.6b: browse abandonment segment ---
    campaign_browse_min_views: int = 3  # same SKU viewed at least this many times...
    campaign_browse_window_days: int = 7  # ...within this many days, with no purchase of it
    # Deliberately small: a nudge for someone already close to buying, not
    # persuasion for someone who needs convincing. Fixed by config, never
    # proposed by the LLM — there's no judgment call to make about "how much
    # to discount a product this customer already told us they're circling."
    campaign_browse_abandonment_discount_pct: float = 0.02

    # --- Layer 3: chaos injection + resilience ---
    # A global, sticky fault for a demo segment (e.g. CHAOS_FAULT=SLOW_LLM).
    # Empty = off. Overridable per-request via the X-Chaos-Fault header.
    # Both are gated by app_env == "development" in app/testing/chaos.py —
    # there is no way to enable chaos from a production config.
    chaos_fault: str = ""
    llm_circuit_breaker_failure_threshold: int = 3
    llm_circuit_breaker_cooldown_seconds: float = 30.0

    # --- Layer 4.7: principals (buyer/merchant Google OAuth, agent credentials) ---
    google_client_id: str = ""
    google_client_secret: str = ""
    # NOT read by app/auth/oauth_router.py — the actual redirect_uri sent to
    # Google is derived per-request from request.url_for(), specifically so
    # the OAuth flow works whether the backend is reached via localhost:8842
    # or 127.0.0.1:8842 (the SessionMiddleware cookie carrying the CSRF
    # state is host-scoped, so login and callback must share a host, but
    # that host doesn't have to be fixed in advance). Kept as a documentation
    # default: register THIS value, and any other host/port you'll actually
    # use, as separate "Authorized redirect URIs" on the Google OAuth
    # client — Google allows more than one. See docs/047-principals.md.
    google_redirect_uri: str = "http://localhost:8842/api/auth/google/callback"
    jwt_secret_key: str = ""
    jwt_algorithm: str = "HS256"
    jwt_expires_minutes: int = 60 * 24 * 7  # 7 days — a demo session, not a production-grade lifetime
    # Comma-separated emails that get MERCHANT on first login; anyone else
    # who signs in becomes a BUYER. A real deployment would have an actual
    # admin flow instead of a config allowlist — see docs/047-principals.md.
    merchant_emails: str = ""
    # The full list of tool names a newly-created agent may pick scopes
    # from — one source of truth shared by the frontend's scope checkboxes
    # and the credential-creation endpoint's validation.
    agent_available_scopes: str = (
        "search_products,get_product,add_to_cart,view_cart,remove_from_cart,"
        "initiate_payment,decline_upsell,report_content_gap"
    )

    model_config = SettingsConfigDict(
        env_file=_REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def merchant_email_set(self) -> set[str]:
        return {e.strip().lower() for e in self.merchant_emails.split(",") if e.strip()}

    @property
    def agent_available_scope_list(self) -> list[str]:
        return [s.strip() for s in self.agent_available_scopes.split(",") if s.strip()]


settings = Settings()
