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
    llm_provider: str = "mock"  # mock | ollama | anthropic | claude_cli
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b-instruct"
    model_live: str = ""  # Anthropic snapshot id, used only when llm_provider="anthropic"
    model_hindcast: str = ""  # pinned snapshot id for the H2 assertion (doc 13 A-8)
    anthropic_api_key: str = ""

    # --- claude_cli provider (shells out to the installed `claude` CLI in print mode) ---
    claude_cli_model: str = "opus"  # --model alias (e.g. "opus", "fable"); free-form string
    claude_cli_bin: str = "claude"  # binary/path invoked for the CLI
    claude_cli_timeout_s: int = 120  # per-call subprocess timeout in seconds

    # --- API + dashboard (doc 10 DR-10.2) ---
    api_token: str = ""  # static bearer for curation (non-GET) endpoints; empty = open (dev only)
    dashboard_origin: str = "http://localhost:3000"  # CORS allow-origin for the Next.js dev server

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
    sanity_llm_budget_usd: float = 5.0  # separate ceiling — sanity runs over every scraped row, not
    # a handful of triggered entities, so it must not be able to starve comprehend/brief's budget
    cohort_min_size: int = 8
    cohort_warmup_state_cap: str = "simmering"
    tracking_archive_days: int = 90
    pending_alert_hours: int = 48
    coldstart_sweep_days: int = 180

    # --- significance gate (doc 07 §2; weights tunable, defaults faithful to the doc) ---
    gate_m_breakout: float = 1.0  # peak-state base for Momentum when the week peaked at breakout
    gate_m_accelerating: float = 0.7  # peak-state base when the week peaked at accelerating
    gate_m_percentile_floor: float = 0.5  # M = base × (floor + (1-floor)·P_peak); keeps breakout≈1
    gate_score_reach_floor: float = 0.4  # the 0.4 in Score's (0.4 + 0.6·R) term
    gate_score_novelty_floor: float = 0.4  # the 0.4 in Score's (0.4 + 0.6·N) term
    gate_rebrief_days: int = 60  # a published brief younger than this suppresses re-briefing
    gate_novelty_cohort_days: int = 180  # the (category, age<Nd) window for the Novelty cohort

    # --- momentum state machine (doc 06 §4; tuned against hindcasts, not vibes) ---
    momentum_p_simmering: float = 0.60  # velocity pctl for simmering (>=1 metric)
    momentum_p_accelerating: float = 0.80  # velocity pctl for accelerating (>=2 metrics)
    momentum_p_breakout: float = 0.95  # velocity pctl for breakout (with breadth gate)
    momentum_p_fade: float = 0.40  # below this for the fade hold window -> fading
    momentum_promote_hold_days: int = 2  # entry condition must hold N days to promote (DR-06.2)
    momentum_demote_hold_days: int = 7  # exit condition must hold N days to demote
    momentum_fade_hold_days: int = 14  # P<fade this many consecutive days -> fading
    momentum_active_days: int = 14  # any event within this window => active
    momentum_fade_inactive_days: int = 30  # inactive this long => fading

    # --- discovery triage (Feature 6): deterministic fallback bar when the LLM is unavailable ---
    triage_github_star_threshold: int = 500  # min latest gh_stars to threshold-track a github repo
    triage_hf_downloads_threshold: int = 50000  # min latest hf_downloads_30d to threshold-track
    triage_pypi_downloads_threshold: int = 50000  # min latest pypi_downloads_7d to threshold-track

    # --- hype-gap signal (idea-spec principle 3): loud attention, thin adoption, narrow breadth ---
    hype_attention_p: float = 0.95  # attention-group pctl must be at least this high
    hype_gap_min: float = 0.5  # attention_p - adoption_p must be at least this
    hype_max_breadth: int = 2  # only flag hype when corroboration breadth is this narrow or less


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
