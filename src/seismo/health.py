"""``seismo doctor`` checks — a single green/red table over the box's health.

Stage 0 covers the foundation checks (DB reachable, extension present, schema at head,
core tables exist, config sane). Later stages extend :func:`run_checks` with collector
silence, queue depth, LLM spend, map staleness, and backup age (docs 03/12).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import inspect, text

from seismo.config import settings
from seismo.db import engine

CORE_TABLES = {
    "raw_events",
    "entities",
    "entity_links",
    "entity_merge_queue",
    "themes",
    "entity_themes",
    "comprehension_cards",
    "entity_metrics_daily",
    "maturity_promotions",
    "momentum_states",
    "gate_decisions",
    "impact_briefs",
    "brief_scores",
    "exposure_companies",
    "reach_links",
    "collector_runs",
    "pipeline_runs",
}


@dataclass
class Check:
    name: str
    ok: bool
    detail: str


def _db_reachable() -> Check:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return Check(
            "database", True, f"reachable at {engine.url.render_as_string(hide_password=True)}"
        )
    except Exception as exc:
        return Check("database", False, f"unreachable: {type(exc).__name__}: {exc}")


def _pg_trgm() -> Check:
    try:
        with engine.connect() as conn:
            present = conn.execute(
                text("SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'")
            ).first()
        return (
            Check("pg_trgm", True, "extension installed")
            if present
            else Check("pg_trgm", False, "missing — run CREATE EXTENSION pg_trgm")
        )
    except Exception as exc:
        return Check("pg_trgm", False, f"check failed: {exc}")


def _schema() -> Check:
    try:
        insp = inspect(engine)
        existing = set(insp.get_table_names())
        missing = CORE_TABLES - existing
        if "alembic_version" not in existing:
            return Check("schema", False, "no alembic_version — run: uv run alembic upgrade head")
        if missing:
            return Check("schema", False, f"missing tables: {', '.join(sorted(missing))}")
        return Check("schema", True, f"{len(CORE_TABLES)} core tables present, migrations applied")
    except Exception as exc:
        return Check("schema", False, f"check failed: {exc}")


def _llm_config() -> Check:
    provider = settings.llm_provider
    if provider not in {"mock", "ollama", "anthropic"}:
        return Check("llm", False, f"unknown provider {provider!r}")
    if provider == "anthropic" and not settings.anthropic_api_key:
        return Check("llm", False, "provider=anthropic but SEISMO_ANTHROPIC_API_KEY is empty")
    return Check("llm", True, f"provider={provider} (dev/CI cost $0 unless anthropic)")


def run_checks() -> list[Check]:
    checks = [_db_reachable()]
    if checks[0].ok:  # only probe the DB further if it is reachable
        checks += [_pg_trgm(), _schema()]
    checks.append(_llm_config())
    return checks
