"""``seismo council`` orchestrator (doc 08 §5) — the council-review layer.

Checkpoint 2 (``impact.py``) produces one ImpactBrief from one LLM call; its schema forces a
``counter_mechanism`` field so the model argues against its own thesis, but it is still the same
model checking its own work. Council review adds three genuinely independent perspectives —
separate calls, separate system prompts, real disagreement possible — deliberating on an
already-drafted brief:

* ``skeptic`` — tries to refute the exposure thesis outright, the adversarial-verify pattern.
* ``evidence_auditor`` — checks every claim traces to ``evidence_refs``; the failure mode a cheap
  model reproduced on the one real qwen-vs-Fable comparison this system has (see HANDOFF §31):
  confident overclaiming past what the evidence pack actually supports.
* ``mechanism_reviewer`` — judges whether ``counter_mechanism`` and ``observables`` are genuinely
  falsifiable, not boilerplate.

Aggregation across the three is a deterministic majority vote (:func:`aggregate_stance`) — never
another LLM call, so cost never compounds and no dissenting verdict is silently smoothed away.

Three LLM calls per brief makes this the most expensive checkpoint in the pipeline, so it is
deliberately scoped to a small top-N population (ranked by momentum/velocity percentile,
independent of the weekly significance gate's own ≤5/week budget — see HANDOFF §32) and is never
invoked from ``daily.sh``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.orm import Session

from seismo.checkpoints.contracts import (
    CouncilRole,
    CouncilVerdict,
    council_tool_schema,
)
from seismo.checkpoints.council_vote import aggregate_stance  # noqa: F401 (re-exported)
from seismo.checkpoints.impact import run_brief
from seismo.checkpoints.impact_pack import build_brief_pack
from seismo.checkpoints.llm import complete_council

ROLES: tuple[CouncilRole, ...] = ("skeptic", "evidence_auditor", "mechanism_reviewer")

_SHARED_PREAMBLE = (
    "You are one independent reviewer on a three-person council deliberating on an already-drafted "
    "impact brief. You did not write the brief; your job is to judge it, not improve it. Reason "
    "ONLY over the evidence pack and the brief text below — do not use outside knowledge of the "
    "entity. Return your verdict via the tool."
)

_ROLE_PROMPT: dict[CouncilRole, str] = {
    "skeptic": (
        f"{_SHARED_PREAMBLE}\n"
        "Your role: SKEPTIC. Actively try to refute the exposure thesis. Look for the strongest "
        "reason the transmission path would NOT hold — a missing step, an alternative explanation, "
        "a mechanism that doesn't actually apply to this category. Default to 'watch' or 'reject' "
        "unless the thesis survives your best attempt to break it. Grounds you can't refute in the "
        "pack are not the same as grounds that are actually solid."
    ),
    "evidence_auditor": (
        f"{_SHARED_PREAMBLE}\n"
        "Your role: EVIDENCE AUDITOR. Check every claim in the brief against evidence_refs and the "
        "pack. Flag anything asserted with more confidence than the evidence supports — a single "
        "self-reported claim treated as fact, a benchmark number from one source presented as "
        "settled, a maturity/adoption claim with no usage evidence behind it. 'adopt' only if the "
        "brief's confidence genuinely matches what the pack shows; overreach earns 'reject', "
        "thin-but-honest earns 'watch'."
    ),
    "mechanism_reviewer": (
        f"{_SHARED_PREAMBLE}\n"
        "Your role: MECHANISM REVIEWER. Judge counter_mechanism and observables specifically. Is "
        "counter_mechanism a real, specific argument for why the thesis might be wrong — or "
        "generic hedging that could apply to any brief? Are the observables genuinely falsifiable "
        "with a concrete, dated, checkable statement — or vague enough to never be wrong? 'reject' "
        "boilerplate; 'adopt' only when both are specific to this entity."
    ),
}


@dataclass
class CouncilStats:
    candidates: int = 0
    briefs_drafted: int = 0  # forced because the entity had no live brief yet
    reviewed: int = 0  # entities with all 3 verdicts stored (this run or already present)
    skipped: int = 0  # already had all 3 verdicts
    cost_usd: Decimal = field(default_factory=lambda: Decimal(0))

    def as_note(self) -> str:
        return (
            f"candidates={self.candidates} briefs_drafted={self.briefs_drafted} "
            f"reviewed={self.reviewed} skipped={self.skipped} cost=${self.cost_usd:.4f}"
        )




def run_council(
    session: Session,
    as_of: datetime,
    *,
    top_n: int = 10,
    entity_id: int | None = None,
) -> CouncilStats:
    """Run the three-perspective council review. ``entity_id`` forces one entity (bypassing the
    momentum ranking); otherwise the top ``top_n`` entities by momentum/velocity percentile that
    do not yet have all three verdicts are reviewed, drafting an ImpactBrief first for any that
    don't have one yet (the momentum ranking is independent of the weekly gate, so a top-momentum
    entity may not have cleared the gate's own budget)."""
    stats = CouncilStats()
    candidates = [entity_id] if entity_id is not None else _top_by_momentum(session, top_n, as_of)
    stats.candidates = len(candidates)

    for cid in candidates:
        if entity_id is None and _has_full_council(session, cid):
            stats.skipped += 1
            continue

        if _latest_live_brief(session, cid) is None:
            run_brief(session, as_of, entity_id=cid)
            stats.briefs_drafted += 1

        brief_row = _latest_live_brief(session, cid)
        if brief_row is None:
            continue  # brief failed validation even on force — nothing to review

        pack = build_brief_pack(session, cid, as_of)
        review_doc = pack.markdown + "\n\n# Drafted impact brief (under review)\n" + _render_brief(
            brief_row["brief"]
        )

        for role in ROLES:
            if _has_verdict(session, brief_row["id"], role):
                continue
            verdict, model, cost = _generate(role, review_doc)
            stats.cost_usd += cost
            if model == "fallback":
                # Don't persist a failed generation as if it were a real verdict — leaving no row
                # is what makes _has_verdict's skip-check retry this role on the next `council`
                # run, instead of a validation failure silently becoming a permanent "watch".
                continue
            _store(session, cid, brief_row["id"], verdict, model=model, cost=cost)

        stats.reviewed += 1
    return stats


def _generate(role: CouncilRole, review_doc: str) -> tuple[dict[str, Any], str, Decimal]:
    schema = council_tool_schema()
    fallback = {
        "stance": "watch",
        "confidence": "low",
        "reasoning": "Mock council member: no live model configured, so no independent judgement "
        "is asserted here beyond the neutral default.",
    }
    result = complete_council(_ROLE_PROMPT[role], review_doc, schema, fallback=fallback)
    content = {**result.content, "role": role}
    try:
        verdict = CouncilVerdict.model_validate(content)
        return verdict.model_dump(), result.model, result.cost_usd
    except ValidationError:
        # Fail closed rather than storing malformed output. model="fallback" is the caller's
        # (run_council's) signal NOT to persist this row — leaving no row is what lets the next
        # `council` run retry this role, instead of a one-time validation failure becoming a
        # permanent, indistinguishable-from-real "watch" verdict.
        return {**fallback, "role": role}, "fallback", result.cost_usd


def _top_by_momentum(session: Session, top_n: int, as_of: datetime) -> list[int]:
    """Entities ranked by the velocity percentile (``momentum_states.inputs->>'P'``) as of
    ``as_of``, independent of the significance gate — the "top N potential and rising" population.
    As-of correct (invariant 2): only rows with ``day <= as_of`` are eligible, so a hindcast run
    can't see momentum that hadn't happened yet."""
    rows = session.execute(
        text(
            """
            SELECT entity_id FROM (
              SELECT DISTINCT ON (entity_id) entity_id, (inputs->>'P')::float AS p
              FROM momentum_states
              WHERE day <= :as_of
              ORDER BY entity_id, day DESC
            ) latest
            WHERE p IS NOT NULL
            ORDER BY p DESC
            LIMIT :n
            """
        ),
        {"n": top_n, "as_of": as_of.date()},
    ).scalars()
    return [int(r) for r in rows]


def _has_full_council(session: Session, entity_id: int) -> bool:
    brief_row = _latest_live_brief(session, entity_id)
    if brief_row is None:
        return False
    n = session.execute(
        text("SELECT COUNT(*) FROM council_verdicts WHERE impact_brief_id = :b"),
        {"b": brief_row["id"]},
    ).scalar_one()
    return n >= len(ROLES)


def _has_verdict(session: Session, impact_brief_id: int, role: str) -> bool:
    row = session.execute(
        text(
            "SELECT 1 FROM council_verdicts WHERE impact_brief_id = :b AND role = :r"
        ),
        {"b": impact_brief_id, "r": role},
    ).first()
    return row is not None


def _latest_live_brief(session: Session, entity_id: int) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                "SELECT id, brief FROM impact_briefs WHERE entity_id = :e "
                "AND status IN ('draft', 'published') ORDER BY version DESC LIMIT 1"
            ),
            {"e": entity_id},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def _render_brief(brief: dict[str, Any]) -> str:
    lines = [f"- {k}: {v}" for k, v in brief.items()]
    return "\n".join(lines)


def _store(
    session: Session,
    entity_id: int,
    impact_brief_id: int,
    verdict: dict[str, Any],
    *,
    model: str,
    cost: Decimal,
) -> None:
    session.execute(
        text(
            """
            INSERT INTO council_verdicts
              (entity_id, impact_brief_id, role, stance, confidence, reasoning, model, cost_usd)
            VALUES
              (:e, :b, :role, :stance, :confidence, :reasoning, :model, :cost)
            ON CONFLICT (impact_brief_id, role) DO NOTHING
            """
        ),
        {
            "e": entity_id,
            "b": impact_brief_id,
            "role": verdict["role"],
            "stance": verdict["stance"],
            "confidence": verdict["confidence"],
            "reasoning": verdict["reasoning"],
            "model": model,
            "cost": cost,
        },
    )
