"""``seismo comprehend`` orchestrator (doc 05) — LLM checkpoint 1.

For each triggered entity (doc 05 DR-05.3): assemble the evidence pack, build a deterministic
*fallback* card from rule-derived facts, ask the provider for the real card (forced tool call,
DR-05.2), validate it (one retry on failure, then ``failed``), and store a new version. The
provider is pluggable (A-13) — ``mock`` returns the fallback verbatim so dev/CI produce real card
rows at $0. Two safety rails: the model's ``category`` is compared to the rule-assigned one and the
disagreement is flagged, never silently applied (doc 05 §1); and once the month's spend hits
``SEISMO_LLM_BUDGET_USD`` the call is not attempted and the card is stored ``pending`` (A-12).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.orm import Session

from seismo.checkpoints.contracts import ComprehensionCard, card_tool_schema
from seismo.checkpoints.evidence import PACK_VERSION, EvidencePack, build_evidence_pack
from seismo.checkpoints.llm import complete_card
from seismo.config import settings
from seismo.identity.vocab import UNCATEGORIZED
from seismo.trajectory.ladder import MATURITY_STAGES

SURVIVAL_DAYS = 7
STALENESS_DAYS = 30
MIN_BREADTH = 2
WARM_STATES = ("simmering", "accelerating", "breakout")

SYSTEM_PROMPT = (
    "You are the comprehension checkpoint of a technology-monitoring system.\n"
    "Input: an evidence pack about one entity. Output: the card via the tool, nothing else.\n"
    "Rules:\n"
    "- Use ONLY the evidence pack. No outside knowledge about this entity.\n"
    "- Attribute claims: benchmarks and superiority statements are 'claims' unless corroborated "
    "in-pack.\n"
    "- Write 'not established by evidence' wherever the pack is silent.\n"
    "- If evidence is thin, say so in open_questions and set confidence accordingly.\n"
    "- what_it_is must be understandable by a non-specialist reader.\n"
    "- evidence_refs must be raw_event ids that appear in the pack timeline."
)


@dataclass
class ComprehendStats:
    candidates: int = 0
    ok: int = 0
    failed: int = 0
    pending: int = 0
    category_disputes: int = 0
    cost_usd: Decimal = field(default_factory=lambda: Decimal(0))

    def as_note(self) -> str:
        return (
            f"candidates={self.candidates} ok={self.ok} failed={self.failed} "
            f"pending={self.pending} disputes={self.category_disputes} cost=${self.cost_usd:.4f}"
        )


def run_comprehend(
    session: Session,
    as_of: datetime,
    *,
    entity_id: int | None = None,
    limit: int | None = None,
) -> ComprehendStats:
    stats = ComprehendStats()
    candidates = [entity_id] if entity_id is not None else select_candidates(session, as_of, limit)
    stats.candidates = len(candidates)
    month_spent = _month_spend(session, as_of)
    budget = Decimal(str(settings.llm_budget_usd))

    for cid in candidates:
        pack = build_evidence_pack(session, cid, as_of)
        fallback = _deterministic_card(session, pack)

        # A-12: budget ceiling — don't attempt the call, mark pending for next window.
        if settings.llm_provider != "mock" and month_spent >= budget:
            _store(
                session,
                cid,
                as_of,
                fallback,
                model=settings.llm_provider,
                status="pending",
                cost=Decimal(0),
            )
            stats.pending += 1
            continue

        card, status, model, cost = _generate(pack, fallback)
        disputed = pack.rule_category is not None and card.get("category") != pack.rule_category
        card["category_disputed"] = disputed
        _store(session, cid, as_of, card, model=model, status=status, cost=cost)
        month_spent += cost
        stats.cost_usd += cost
        if disputed:
            stats.category_disputes += 1
        if status == "ok":
            stats.ok += 1
        else:
            stats.failed += 1
    return stats


def _generate(
    pack: EvidencePack, fallback: dict[str, Any]
) -> tuple[dict[str, Any], str, str, Decimal]:
    """One generation + one validation retry (DR-05.2). Returns (card, status, model, cost)."""
    schema = card_tool_schema()
    result = complete_card(SYSTEM_PROMPT, pack.markdown, schema, fallback=fallback)
    valid = _validate(result.content)
    if valid is not None:
        return valid, "ok", result.model, result.cost_usd
    # Retry once with the validation error appended.
    retry_user = pack.markdown + "\n\n# Correction\nThe previous card failed validation. Return a "
    retry_user += (
        "card that matches the tool schema exactly, using only controlled-vocabulary values."
    )
    retry = complete_card(SYSTEM_PROMPT, retry_user, schema, fallback=fallback)
    valid = _validate(retry.content)
    if valid is not None:
        return valid, "ok", retry.model, result.cost_usd + retry.cost_usd
    return retry.content, "failed", retry.model, result.cost_usd + retry.cost_usd


def _validate(content: dict[str, Any]) -> dict[str, Any] | None:
    try:
        return ComprehensionCard.model_validate(content).model_dump()
    except ValidationError:
        return None


def select_candidates(session: Session, as_of: datetime, limit: int | None = None) -> list[int]:
    """Entities that earn a card this run (doc 05 DR-05.3): (a) survived 7d + ≥2 evidence types +
    no card yet; (b) a maturity promotion since the last card; (c) card older than 30d while the
    entity is simmering+. The 7-day survival gate alone kills most one-day-wonder spend."""
    sql = text(
        """
        WITH breadth AS (
            SELECT DISTINCT ON (entity_id) entity_id, value AS b
            FROM entity_metrics_daily
            WHERE metric = 'evidence_breadth' AND day <= :as_of_day
            ORDER BY entity_id, day DESC
        ),
        latest AS (
            SELECT entity_id, MAX(version) AS v FROM comprehension_cards GROUP BY entity_id
        ),
        last_card AS (
            SELECT c.entity_id, c.as_of
            FROM comprehension_cards c JOIN latest ON latest.entity_id = c.entity_id
                AND latest.v = c.version
        ),
        last_state AS (
            SELECT DISTINCT ON (entity_id) entity_id, state
            FROM momentum_states WHERE day <= :as_of_day
            ORDER BY entity_id, day DESC
        ),
        last_promo AS (
            SELECT entity_id, MAX(promoted_at) AS pat FROM maturity_promotions
            WHERE promoted_at <= :as_of GROUP BY entity_id
        )
        SELECT e.id
        FROM entities e
        LEFT JOIN breadth b ON b.entity_id = e.id
        LEFT JOIN last_card lc ON lc.entity_id = e.id
        LEFT JOIN last_state ls ON ls.entity_id = e.id
        LEFT JOIN last_promo lp ON lp.entity_id = e.id
        WHERE e.merged_into IS NULL
          AND e.created_at <= :survived
          AND (
              (lc.entity_id IS NULL AND COALESCE(b.b, 0) >= :min_breadth)
              OR (lc.as_of IS NOT NULL AND lp.pat IS NOT NULL AND lp.pat > lc.as_of)
              OR (lc.as_of IS NOT NULL AND lc.as_of < :stale AND ls.state = ANY(:warm))
          )
        ORDER BY e.id
        """
        + ("LIMIT :limit" if limit is not None else "")
    )
    params: dict[str, Any] = {
        "as_of": as_of,
        "as_of_day": as_of.date(),
        "survived": as_of - timedelta(days=SURVIVAL_DAYS),
        "stale": as_of - timedelta(days=STALENESS_DAYS),
        "min_breadth": MIN_BREADTH,
        "warm": list(WARM_STATES),
    }
    if limit is not None:
        params["limit"] = limit
    return [int(r) for r in session.execute(sql, params).scalars()]


def _deterministic_card(session: Session, pack: EvidencePack) -> dict[str, Any]:
    """A schema-valid card built only from rule-derived facts — the ``mock`` output and the safe
    fallback shape. Text fields say 'not established by evidence' so nothing is fabricated."""
    row = (
        session.execute(
            text("SELECT entity_type, canonical_name FROM entities WHERE id = :id"),
            {"id": pack.entity_id},
        )
        .mappings()
        .one()
    )
    stages = {
        s
        for (s,) in session.execute(
            text("SELECT stage FROM maturity_promotions WHERE entity_id = :id"),
            {"id": pack.entity_id},
        ).all()
    }
    maturity = _highest_stage(stages) or (
        "idea_paper" if row["entity_type"] == "paper" else "public_code"
    )
    return {
        "entity_ref": row["canonical_name"],
        "what_it_is": "not established by evidence",
        "category": pack.rule_category or UNCATEGORIZED,
        "function": "not established by evidence",
        "claimed_advantage": "not established by evidence",
        "replaces_or_enables": [],
        "maturity_stage": maturity,
        "who_is_behind": "not established by evidence",
        "open_questions": ["Only the evidence pack was available; details are unconfirmed."],
        "evidence_refs": pack.event_ids[:20],
        "confidence": "low",
    }


def _highest_stage(stages: set[str]) -> str | None:
    reached = [s for s in MATURITY_STAGES if s in stages]
    return reached[-1] if reached else None


def _store(
    session: Session,
    entity_id: int,
    as_of: datetime,
    card: dict[str, Any],
    *,
    model: str,
    status: str,
    cost: Decimal,
) -> None:
    """Append a new card version (doc 05 §5). ``version`` = prior max + 1 for this entity."""
    next_version = session.execute(
        text("SELECT COALESCE(MAX(version), 0) + 1 FROM comprehension_cards WHERE entity_id = :e"),
        {"e": entity_id},
    ).scalar_one()
    session.execute(
        text(
            """
            INSERT INTO comprehension_cards
                (entity_id, version, as_of, card, model, cost_usd, status, pack_version)
            VALUES (:e, :v, :as_of, CAST(:card AS JSONB), :model, :cost, :status, :pack_version)
            """
        ),
        {
            "e": entity_id,
            "v": next_version,
            "as_of": as_of,
            "card": _json(card),
            "model": model,
            "cost": cost,
            "status": status,
            "pack_version": PACK_VERSION,
        },
    )


def _month_spend(session: Session, as_of: datetime) -> Decimal:
    """Sum of card costs in ``as_of``'s calendar month — the total the budget ceiling checks."""
    month_start = as_of.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    total = session.execute(
        text(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM comprehension_cards WHERE created_at >= :start"
        ),
        {"start": month_start},
    ).scalar_one()
    return Decimal(str(total))


def _json(value: dict[str, Any]) -> str:
    import json

    return json.dumps(value)
