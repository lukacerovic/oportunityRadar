"""``seismo brief`` orchestrator (doc 08) — LLM checkpoint 2, the impact brief.

Mirrors the comprehension orchestrator (doc 05): for each entity the significance gate *passed* this
week (or one forced with ``--entity-id``), assemble the deterministic input pack, build a schema-
valid *fallback* draft from rule-derived facts, ask the provider for the real brief (forced tool
call), validate it, and store a new ``draft`` version for human review (DR-08.2 — nothing publishes
without a person).

Two validation layers guard the brief. The schema (``ImpactBrief``) makes malformed output an
API-level impossibility. Then a **post-validation** the type system can't express (doc 08 §2): every
ticker exposure's ``revenue_line`` must exist in the loaded map, and every named mechanism must be
legal for the relations of the map surface the entity's category touches. A failure retries once
with the error appended, then stores ``failed``. The budget ceiling (A-12) marks a brief ``pending``
rather than spending past ``SEISMO_LLM_BUDGET_USD``. The gate has already excluded entities whose
card is ``pending`` or whose reach is zero, so a passed entity always has a real card and a surface.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.orm import Session

from seismo.checkpoints.contracts import MECHANISMS, ImpactBrief, brief_tool_schema
from seismo.checkpoints.impact_pack import BriefPack, build_brief_pack
from seismo.checkpoints.llm import complete_brief
from seismo.config import settings

SYSTEM_PROMPT = (
    "You are the impact checkpoint of a technology-monitoring system.\n"
    "Input: a pack about one rising entity — its comprehension card, its momentum, and ONLY the "
    "exposure-map company slices its category touches. Output: the impact brief via the tool.\n"
    "Rules:\n"
    "- You explain exposure; you never predict prices. No price targets, no buy/sell language.\n"
    "- Reason ONLY over the pack. Resolve ticker exposures to the revenue lines shown; use a "
    "sector_class string for private/unlisted actors.\n"
    "- Name at least one mechanism from the taxonomy, and trace an explicit 2–5 step transmission "
    "path from the entity to each affected revenue line.\n"
    "- counter_mechanism is a REQUIRED one-to-three-sentence ARGUMENT for why the thesis might be "
    "wrong, stated as convincingly as its holder would (e.g. the Jevons paradox: cheaper inference "
    "grows total volume). It is prose, NOT a mechanism name — never answer with a bare word like "
    "'dependency_risk'.\n"
    "- If the honest direction is ambiguous, say ambiguous. That is a finding, not a failure.\n"
    "- Give at least one dated observable that would settle the thesis; prefer ones the system can "
    "measure (source='system').\n"
    "- evidence_refs must be raw_event ids that appear in the pack."
)


@dataclass
class BriefStats:
    candidates: int = 0
    drafted: int = 0
    failed: int = 0
    pending: int = 0
    skipped: int = 0  # already had a brief (queue mode)
    cost_usd: Decimal = field(default_factory=lambda: Decimal(0))

    def as_note(self) -> str:
        return (
            f"candidates={self.candidates} drafted={self.drafted} failed={self.failed} "
            f"pending={self.pending} skipped={self.skipped} cost=${self.cost_usd:.4f}"
        )


def run_brief(
    session: Session,
    as_of: datetime,
    *,
    entity_id: int | None = None,
    week_start: date | None = None,
    limit: int | None = None,
) -> BriefStats:
    """Draft impact briefs. ``entity_id`` forces one (bypassing the gate); otherwise every entity
    the gate passed for ``week_start`` that does not yet have a brief is drafted."""
    stats = BriefStats()
    if entity_id is not None:
        candidates = [entity_id]
    else:
        candidates = _passed_candidates(session, week_start, limit)
    stats.candidates = len(candidates)

    month_spent = _month_spend(session, as_of)
    budget = Decimal(str(settings.llm_budget_usd))

    for cid in candidates:
        # Queue mode is idempotent: don't re-brief an entity that already has a live draft/published
        # brief. A forced --entity-id always appends a new version (like comprehend --entity).
        if entity_id is None and _has_live_brief(session, cid):
            stats.skipped += 1
            continue

        pack = build_brief_pack(session, cid, as_of)
        fallback = _deterministic_brief(pack)

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

        brief, status, model, cost = _generate(pack, fallback)
        _store(session, cid, as_of, brief, model=model, status=status, cost=cost)
        month_spent += cost
        stats.cost_usd += cost
        if status == "draft":
            stats.drafted += 1
        else:
            stats.failed += 1
    return stats


def _generate(
    pack: BriefPack, fallback: dict[str, Any]
) -> tuple[dict[str, Any], str, str, Decimal]:
    """One generation + one validation retry (doc 08 §2). Returns (brief, status, model, cost).
    A successful brief is stored ``draft`` (human review pending, DR-08.2)."""
    schema = brief_tool_schema()
    result = complete_brief(SYSTEM_PROMPT, pack.markdown, schema, fallback=fallback)
    valid, err = _validate(result.content, pack)
    if valid is not None:
        return valid, "draft", result.model, result.cost_usd

    retry_user = (
        pack.markdown
        + "\n\n# Correction\nThe previous brief was rejected: "
        + (err or "schema mismatch")
        + "\nReturn a brief that matches the tool schema and only references revenue lines and "
        "mechanisms valid for the exposure-map surface above."
    )
    retry = complete_brief(SYSTEM_PROMPT, retry_user, schema, fallback=fallback)
    valid, _ = _validate(retry.content, pack)
    cost = result.cost_usd + retry.cost_usd
    if valid is not None:
        return valid, "draft", retry.model, cost
    return retry.content, "failed", retry.model, cost


def _validate(content: dict[str, Any], pack: BriefPack) -> tuple[dict[str, Any] | None, str | None]:
    """Schema validation, then the doc-08 §2 post-validation. Returns (brief_dump | None, error)."""
    try:
        brief = ImpactBrief.model_validate(content)
    except ValidationError as exc:
        return None, f"schema: {exc.errors()[0]['msg'] if exc.errors() else exc}"
    err = _post_validate(brief, pack)
    if err is not None:
        return None, err
    return brief.model_dump(), None


_COUNTER_MIN_WORDS = 4  # a bare mechanism keyword is 1 word; a real argument is a sentence


def _post_validate(brief: ImpactBrief, pack: BriefPack) -> str | None:
    """Every ticker exposure's revenue_line must exist for that ticker in the loaded map; every
    mechanism must be legal for a relation on the touched map surface; and counter_mechanism must be
    a real argument, not a keyword (doc 08 §2 / idea-spec §7 — a one-sided brief is marketing)."""
    reach = pack.reach
    cm = brief.counter_mechanism.strip()
    if cm.lower().rstrip(".") in MECHANISMS or len(cm.split()) < _COUNTER_MIN_WORDS:
        return (
            "counter_mechanism must be a fair one-to-three-sentence argument for why the thesis "
            "might be wrong, not a bare mechanism name"
        )
    for exp in brief.exposures:
        if exp.kind != "ticker":
            continue
        valid = reach.valid_lines.get(exp.ref.upper())
        if valid is None:
            return f"exposure ticker {exp.ref!r} is not in the exposure-map surface for this entity"
        if exp.revenue_line is None:
            return f"ticker exposure {exp.ref!r} must name a revenue_line"
        if exp.revenue_line not in valid:
            return (
                f"revenue_line {exp.revenue_line!r} does not exist for {exp.ref!r} "
                f"(valid: {sorted(valid)})"
            )
    # Mechanism legality only applies when there is a mapped surface to test against.
    if reach.allowed_mechanisms:
        illegal = [m for m in brief.mechanisms if m not in reach.allowed_mechanisms]
        if illegal:
            return (
                f"mechanism(s) {illegal} not legal for this category's map relations "
                f"(allowed: {sorted(reach.allowed_mechanisms)})"
            )
    return None


def _passed_candidates(session: Session, week_start: date | None, limit: int | None) -> list[int]:
    """Entity ids the gate passed. ``week_start=None`` → the most recent week with decisions."""
    if week_start is None:
        week_start = session.execute(text("SELECT MAX(week) FROM gate_decisions")).scalar()
        if week_start is None:
            return []
    sql = text(
        "SELECT entity_id FROM gate_decisions WHERE week = :w AND decision = 'pass' "
        "ORDER BY score DESC, entity_id" + (" LIMIT :lim" if limit is not None else "")
    )
    params: dict[str, Any] = {"w": week_start}
    if limit is not None:
        params["lim"] = limit
    return [int(r) for r in session.execute(sql, params).scalars()]


def _has_live_brief(session: Session, entity_id: int) -> bool:
    row = session.execute(
        text(
            "SELECT 1 FROM impact_briefs WHERE entity_id = :e "
            "AND status IN ('draft', 'published') LIMIT 1"
        ),
        {"e": entity_id},
    ).first()
    return row is not None


def _deterministic_brief(pack: BriefPack) -> dict[str, Any]:
    """A schema- and post-validation-valid brief built only from rule-derived facts — the ``mock``
    output and the safe fallback shape. Everything the evidence doesn't establish says so, so the
    mock never fabricates a thesis; it just produces a valid, reviewable, empty-of-claims draft."""
    reach = pack.reach
    exposures: list[dict[str, Any]]
    if reach.slices and reach.slices[0].lines:
        cs = reach.slices[0]
        exposures = [
            {
                "kind": "ticker",
                "ref": cs.ticker,
                "revenue_line": cs.lines[0].id,
                "direction": "ambiguous",
                "magnitude_class": "marginal",
            }
        ]
    else:
        exposures = [
            {
                "kind": "sector_class",
                "ref": "not established by evidence",
                "revenue_line": None,
                "direction": "ambiguous",
                "magnitude_class": "marginal",
            }
        ]
    mechanisms = (
        [next(iter(sorted(reach.allowed_mechanisms)))]
        if reach.allowed_mechanisms
        else ["enablement"]
    )
    return {
        "entity_ref": pack.entity_ref,
        "mechanisms": mechanisms,
        "transmission_path": [
            {
                "from_node": pack.entity_ref,
                "to_node": "affected capability",
                "effect": "not established by evidence",
            }
        ],
        "exposures": exposures,
        "counter_mechanism": "not established by evidence",
        "observables": [
            {
                "statement": "Direction unconfirmed; a human analyst must specify a falsifier.",
                "source": "manual",
                "system_metric": None,
                "horizon": "1-2y",
                "direction_if_thesis_holds": "flat",
            }
        ],
        "confidence": "low",
        "horizon": "1-2y",
        "summary": "Draft placeholder — the exposure thesis is not established by evidence yet.",
        "evidence_refs": pack.event_ids[:20],
    }


def _store(
    session: Session,
    entity_id: int,
    as_of: datetime,
    brief: dict[str, Any],
    *,
    model: str,
    status: str,
    cost: Decimal,
) -> None:
    """Append a new brief version (doc 08 §4). ``version`` = prior max + 1 for this entity."""
    next_version = session.execute(
        text("SELECT COALESCE(MAX(version), 0) + 1 FROM impact_briefs WHERE entity_id = :e"),
        {"e": entity_id},
    ).scalar_one()
    session.execute(
        text(
            """
            INSERT INTO impact_briefs (entity_id, version, as_of, brief, status, model, cost_usd)
            VALUES (:e, :v, :as_of, CAST(:brief AS JSONB), :status, :model, :cost)
            """
        ),
        {
            "e": entity_id,
            "v": next_version,
            "as_of": as_of,
            "brief": _json(brief),
            "status": status,
            "model": model,
            "cost": cost,
        },
    )


def _month_spend(session: Session, as_of: datetime) -> Decimal:
    """Sum of brief costs in ``as_of``'s calendar month — the total the budget ceiling checks."""
    month_start = as_of.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    total = session.execute(
        text("SELECT COALESCE(SUM(cost_usd), 0) FROM impact_briefs WHERE created_at >= :start"),
        {"start": month_start},
    ).scalar_one()
    return Decimal(str(total))


def week_as_of(week_start: date) -> datetime:
    """The as-of instant for a gate week — its last second, matching the gate's own scoring time."""
    return datetime.combine(week_start + timedelta(days=6), datetime.max.time()).replace(tzinfo=UTC)


def _json(value: dict[str, Any]) -> str:
    import json

    return json.dumps(value)
