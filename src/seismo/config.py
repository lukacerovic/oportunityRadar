"""Configuration — pydantic-settings, env prefix ``SEISMO_``.

Local dev reads ``.env``; the server loads ``/etc/seismograph/env`` via systemd
``EnvironmentFile`` (doc 12). Secrets never live in git. Defaults here are safe for
a local empty database so ``seismo doctor`` works out of the box.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SEISMO_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- core ---
    database_url: str = "postgresql+psycopg://seismo:seismo@localhost:5432/seismograph"
    product_name: str = "Seismograph"

    # --- LLM provider (doc 13 A-13) ---
    llm_provider: str = "mock"  # mock | ollama | anthropic
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b-instruct"
    model_live: str = ""  # Anthropic snapshot id, used only when llm_provider="anthropic"
    model_hindcast: str = ""  # pinned snapshot id for the H2 assertion (doc 13 A-8)
    anthropic_api_key: str = ""

    # --- source credentials (optional until their collector lands) ---
    github_token: str = ""
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    hf_token: str = ""

    # --- budgets & thresholds (doc 13 Part C) ---
    briefs_per_week: int = 5
    breakout_callouts_per_day: int = 1
    breakout_min_breadth: int = 2  # → 3 once the 4th evidence type (pricing) ships
    llm_budget_usd: float = 30.0
    cohort_min_size: int = 8
    cohort_warmup_state_cap: str = "simmering"
    tracking_archive_days: int = 90
    pending_alert_hours: int = 48
    coldstart_sweep_days: int = 180


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
