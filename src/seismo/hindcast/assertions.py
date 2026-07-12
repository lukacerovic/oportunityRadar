"""Hindcast assertion evaluators (doc 11 §2) — pinned, schema-level checks over the pipeline output.

Each evaluator reads the *structured* result the production pipeline already wrote (entity graph,
``momentum_states``, ``gate_decisions``, ``impact_briefs``) and returns pass/fail with a human
sentence for the trace report. Nothing here matches prose: an LLM brief is checked for the presence
of a mechanism *enum* value and a ticker *reference*, never for its wording (DR-11.2). That is what
lets a case run forever in CI without flapping on model stochasticity.

Entity references are anchor keys (``registry:native_id``, e.g. ``github:deepseek-ai/deepseek-v2``)
resolved to their canonical entity **at the as-of instant** — a hindcast never sees a future merge
(doc 13 A-2), so the resolution goes through :func:`canonical_entity_id`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from seismo.db import canonical_entity_id
from seismo.hindcast.case import Assertion, Case
from seismo.significance.gate import parse_week


@dataclass
class AssertionResult:
    id: str
    type: str
    passed: bool
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "type": self.type, "passed": self.passed, "detail": self.detail}


def _end_of_day(d: date) -> datetime:
    return datetime.combine(d, datetime.max.time()).replace(tzinfo=UTC)


def _resolve_ref(session: Session, ref: str, as_of: datetime) -> int | None:
    """Anchor key ``registry:native_id`` → canonical entity id at ``as_of``, or ``None`` if no
    entity carries that anchor. GitHub native ids are stored lowercased (doc 04), so we try the
    given casing and a lowercased fallback."""
    if ":" not in ref:
        return None
    registry, native_id = ref.split(":", 1)
    row = session.execute(
        text(
            "SELECT id FROM entities WHERE attrs->'anchors'->>:reg IN (:nid, :nid_lower) "
            "ORDER BY id LIMIT 1"
        ),
        {"reg": registry, "nid": native_id, "nid_lower": native_id.lower()},
    ).first()
    if row is None:
        return None
    return canonical_entity_id(session, int(row[0]), as_of)


def evaluate(
    session: Session, case: Case, assertion: Assertion, *, default_as_of: datetime
) -> AssertionResult:
    """Dispatch one assertion to its evaluator. ``default_as_of`` is the case's pinned brief instant
    (or window end) — the as-of used when an assertion does not name its own."""
    p = assertion.params
    handlers = {
        "identity": _eval_identity,
        "momentum": _eval_momentum,
        "gate": _eval_gate,
        "brief": _eval_brief,
        "brief_absent": _eval_brief_absent,
    }
    handler = handlers[assertion.type]
    passed, detail = handler(session, p, default_as_of)
    return AssertionResult(assertion.id, assertion.type, passed, detail)


def _asof_from(p: dict[str, Any], default_as_of: datetime) -> datetime:
    raw = p.get("as_of")
    if raw is None:
        return default_as_of
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return _end_of_day(raw)
    if isinstance(raw, str):
        return _end_of_day(date.fromisoformat(raw))
    return default_as_of


# --- identity (H1a) ---------------------------------------------------------


def _eval_identity(
    session: Session, p: dict[str, Any], default_as_of: datetime
) -> tuple[bool, str]:
    refs = p.get("refs") or []
    if not refs:
        return False, "malformed: identity assertion needs a non-empty 'refs' list"
    as_of = _asof_from(p, default_as_of)
    resolved: dict[str, int | None] = {ref: _resolve_ref(session, ref, as_of) for ref in refs}
    missing = [r for r, e in resolved.items() if e is None]
    if missing:
        return False, f"unresolved refs {missing} at {as_of.date()}"
    ids = set(resolved.values())
    if len(ids) != 1:
        return False, f"refs resolve to {len(ids)} distinct entities: {resolved}"
    (eid,) = ids
    return True, f"all {len(refs)} refs → single entity {eid} at {as_of.date()}"


# --- momentum (H1b) ---------------------------------------------------------


def _eval_momentum(
    session: Session, p: dict[str, Any], default_as_of: datetime
) -> tuple[bool, str]:
    ref = p.get("entity")
    states = p.get("states") or []
    mode = str(p.get("mode") or "reached")
    if not ref or not states:
        return False, "malformed: momentum assertion needs 'entity' and 'states'"
    if mode not in ("reached", "never"):
        return False, f"malformed: momentum 'mode' must be reached|never, got {mode!r}"
    as_of = _asof_from(p, default_as_of)
    eid = _resolve_ref(session, str(ref), as_of)
    if eid is None:
        return False, f"entity {ref!r} did not resolve at {as_of.date()}"
    hit = session.execute(
        text(
            "SELECT state, day FROM momentum_states "
            "WHERE entity_id = :e AND day <= :d AND state = ANY(:states) "
            "ORDER BY day LIMIT 1"
        ),
        {"e": eid, "d": as_of.date(), "states": list(states)},
    ).first()
    top = session.execute(
        text(
            "SELECT state, day FROM momentum_states WHERE entity_id = :e AND day <= :d "
            "ORDER BY day DESC LIMIT 1"
        ),
        {"e": eid, "d": as_of.date()},
    ).first()

    if mode == "never":
        # The true "hype ≠ momentum" invariant for a flop: the entity must NEVER have reached any of
        # these (forbidden) states. Require real momentum history so it can't pass vacuously.
        if top is None:
            return False, f"entity {eid} has no momentum rows — 'never' can't be graded"
        if hit is not None:
            return (
                False,
                f"entity {eid} reached forbidden {hit[0]!r} on {hit[1]} (≤ {as_of.date()})",
            )
        return True, f"entity {eid} never reached {states} (last state {top[0]!r} on {top[1]})"

    if hit is not None:
        return True, f"entity {eid} reached {hit[0]!r} on {hit[1]} (≤ {as_of.date()})"
    seen = f"last state {top[0]!r} on {top[1]}" if top else "no momentum rows"
    return False, f"entity {eid} never reached {states} by {as_of.date()} ({seen})"


# --- gate (H3 / pass) -------------------------------------------------------


def _eval_gate(session: Session, p: dict[str, Any], default_as_of: datetime) -> tuple[bool, str]:
    ref = p.get("entity")
    expected = p.get("decision")
    if not ref or expected not in ("pass", "suppressed"):
        return False, "malformed: gate assertion needs 'entity' and decision pass|suppressed"
    as_of = _asof_from(p, default_as_of)
    eid = _resolve_ref(session, str(ref), as_of)
    if eid is None:
        return False, f"entity {ref!r} did not resolve at {as_of.date()}"

    week_clause = ""
    params: dict[str, Any] = {"e": eid}
    week = p.get("week")
    if week is not None:
        week_clause = " AND week = :w"
        params["w"] = parse_week(str(week))

    rows = session.execute(
        text(
            "SELECT decision, components->>'reason' AS reason FROM gate_decisions "
            "WHERE entity_id = :e" + week_clause
        ),
        params,
    ).all()
    decisions = [r[0] for r in rows]
    passed_rows = [r for r in rows if r[0] == "pass"]

    if expected == "pass":
        if passed_rows:
            return True, f"entity {eid} passed the gate ({len(passed_rows)} pass row(s))"
        return False, f"entity {eid} has no gate 'pass' row (decisions: {decisions or 'none'})"

    # expected == "suppressed": the entity must never have been briefed. That holds both when the
    # gate wrote an explicit suppressed row AND when the entity never became a candidate (a
    # simmering attention spike is not accelerating/breakout, so the gate never scores it).
    if passed_rows:
        return False, f"entity {eid} PASSED the gate — must have been suppressed"
    want_reason = p.get("reason")
    if want_reason is not None:
        reasons = {r[1] for r in rows if r[0] == "suppressed"}
        if str(want_reason) not in reasons:
            return False, f"entity {eid} not suppressed for reason {want_reason!r} (saw {reasons})"
        return True, f"entity {eid} suppressed ({want_reason})"
    if rows:
        return True, f"entity {eid} suppressed by the gate (no pass row)"
    return True, f"entity {eid} never a gate candidate (never accelerating/breakout) — not briefed"


# --- brief (H2) -------------------------------------------------------------


def _latest_brief(session: Session, entity_id: int) -> dict[str, Any] | None:
    row = session.execute(
        text(
            "SELECT brief FROM impact_briefs WHERE entity_id = :e "
            "AND status IN ('draft', 'published') ORDER BY version DESC LIMIT 1"
        ),
        {"e": entity_id},
    ).first()
    return None if row is None else dict(row[0])


def _eval_brief(session: Session, p: dict[str, Any], default_as_of: datetime) -> tuple[bool, str]:
    ref = p.get("entity")
    if not ref:
        return False, "malformed: brief assertion needs 'entity'"
    as_of = _asof_from(p, default_as_of)
    eid = _resolve_ref(session, str(ref), as_of)
    if eid is None:
        return False, f"entity {ref!r} did not resolve at {as_of.date()}"
    brief = _latest_brief(session, eid)
    if brief is None:
        return False, f"entity {eid} has no draft/published brief"

    failures: list[str] = []
    mechanisms = set(brief.get("mechanisms") or [])
    exposures = brief.get("exposures") or []
    ticker_refs = {str(e.get("ref", "")).upper() for e in exposures if e.get("kind") == "ticker"}
    observables = brief.get("observables") or []

    superset = p.get("mechanisms_superset")
    if superset:
        missing = set(superset) - mechanisms
        if missing:
            failures.append(f"mechanisms missing {sorted(missing)} (have {sorted(mechanisms)})")

    intersect = p.get("mechanisms_intersect")
    if intersect and not (set(intersect) & mechanisms):
        failures.append(f"mechanisms ∩ {intersect} empty (have {sorted(mechanisms)})")

    need_tickers = p.get("exposures_include_tickers")
    if need_tickers:
        missing_t = {t.upper() for t in need_tickers} - ticker_refs
        if missing_t:
            failures.append(
                f"exposures missing tickers {sorted(missing_t)} (have {sorted(ticker_refs)})"
            )

    any_ticker = p.get("exposures_include_any_ticker")
    if any_ticker and not ({t.upper() for t in any_ticker} & ticker_refs):
        failures.append(f"no exposure ticker in {any_ticker} (have {sorted(ticker_refs)})")

    if p.get("counter_mechanism_nonempty"):
        cm = str(brief.get("counter_mechanism") or "").strip()
        if not cm:
            failures.append("counter_mechanism is empty")

    if p.get("observables_nonempty") and not observables:
        failures.append("observables is empty")

    if p.get("observables_have_horizon"):
        no_horizon = [o for o in observables if not str(o.get("horizon") or "").strip()]
        if not observables:
            failures.append("no observables to carry a horizon")
        elif no_horizon:
            failures.append(f"{len(no_horizon)} observable(s) missing a horizon")

    if failures:
        return False, f"entity {eid} brief: " + "; ".join(failures)
    return True, f"entity {eid} brief satisfies all {_count_checks(p)} declared facts"


def _count_checks(p: dict[str, Any]) -> int:
    keys = (
        "mechanisms_superset",
        "mechanisms_intersect",
        "exposures_include_tickers",
        "exposures_include_any_ticker",
        "counter_mechanism_nonempty",
        "observables_nonempty",
        "observables_have_horizon",
    )
    return sum(1 for k in keys if p.get(k))


# --- brief_absent (H3, flop) ------------------------------------------------


def _eval_brief_absent(
    session: Session, p: dict[str, Any], default_as_of: datetime
) -> tuple[bool, str]:
    ref = p.get("entity")
    if not ref:
        return False, "malformed: brief_absent assertion needs 'entity'"
    as_of = _asof_from(p, default_as_of)
    eid = _resolve_ref(session, str(ref), as_of)
    if eid is None:
        # An entity that never even resolved certainly has no brief — vacuously suppressed.
        return True, f"entity {ref!r} never resolved — no brief possible"
    n = session.execute(
        text("SELECT COUNT(*) FROM impact_briefs WHERE entity_id = :e"),
        {"e": eid},
    ).scalar_one()
    if n == 0:
        return True, f"entity {eid} has no brief of any status"
    return False, f"entity {eid} has {n} brief(s) — a flop must be brief-free"
