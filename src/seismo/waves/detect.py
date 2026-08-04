"""Wave detection — the only stage that asks a question about a *population* of entities.

Every other stage is per-entity: ``score`` computes one entity's momentum, ``gate`` ranks candidates
one at a time, ``changes`` diffs entity by entity. This one looks for a shape that no single-entity
rule can see — several unrelated people starting on the same idea at once.

**Fully deterministic.** No LLM decides membership, strength, or merging (invariant 4). A checkpoint
may later *name* a wave; the wave exists, is scored, and renders before any model is called.

The clustering rule is the whole design, and it is not the obvious one. In the known case
(``AGENT_GUARDRAIL_WAVE.md``) none of the six members carried a semantic edge to any other member —
each pointed at a *different* outside neighbour, because brand-new projects in one space genuinely
don't know about each other yet. Connected components over ``entity_semantic_edges`` returns four
disjoint pairs and zero waves. So membership is computed over a **neighbourhood projection**:
entity → neighbour label → entity. Two candidates link when they share a neighbour, or their
neighbours share a category, or (rarely, and free to support) one is the other's neighbour.

Category is a weak prior, never the grouping key: those same six members spanned ``agent-framework``
and ``rag-framework``, which map to two different themes in ``seed/categories.yaml``. Grouping by
category or by theme would have split the wave in half.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from seismo.config import settings
from seismo.trajectory.cohorts import EntityFacts, entity_facts
from seismo.waves import independence
from seismo.waves.continuity import persist_wave

_WS = re.compile(r"\s+")


def normalize_label(label: str) -> str:
    """Neighbour labels are free text from a model pass, so ``LangChain`` and ``langchain  ``
    must collapse to one key, or the projection silently fails to link members that share one."""
    return _WS.sub(" ", label.strip().lower())


@dataclass
class Candidate:
    entity_id: int
    first_seen: date
    category: str | None
    neighbours: set[str] = field(default_factory=set)
    neighbour_categories: set[str] = field(default_factory=set)


@dataclass
class WaveStats:
    as_of: datetime
    candidates: int = 0
    clusters_found: int = 0
    below_min_members: int = 0
    collapsed_members: int = 0
    waves_written: int = 0
    waves_new: int = 0

    def as_note(self) -> str:
        return (
            f"as_of={self.as_of.date()} candidates={self.candidates} "
            f"clusters={self.clusters_found} (below_min={self.below_min_members}) "
            f"collapsed_members={self.collapsed_members} "
            f"waves={self.waves_written} (new={self.waves_new})"
        )


def _candidates(session: Session, as_of: datetime) -> dict[int, Candidate]:
    """Young entities whose first evidence lands inside the rolling window.

    ``entity_facts`` is reused rather than re-deriving age: it is already as-of correct and folds a
    merged entity's history into its canonical survivor, so a merge can't reset an entity's age and
    smuggle an old project into a wave of new ones."""
    facts: dict[int, EntityFacts] = entity_facts(session, as_of)
    as_of_day = as_of.date()
    window_start = as_of_day - timedelta(days=settings.wave_window_days)
    max_age = timedelta(days=settings.wave_max_age_days)

    out: dict[int, Candidate] = {}
    for eid, f in facts.items():
        if f.first_seen < window_start:
            continue  # appeared before the window — not part of *this* convergence
        if as_of_day - f.first_seen > max_age:
            continue
        out[eid] = Candidate(entity_id=eid, first_seen=f.first_seen, category=f.category)

    if settings.wave_require_momentum and out:
        # Open question 1 in WAVE_PLAN.md — default off, because on a cold-start database almost
        # nothing has left dormant yet and requiring it would make the feature silently return
        # nothing. Turn on once momentum has real history.
        rows = session.execute(
            text(
                """
                SELECT DISTINCT entity_id FROM momentum_states
                WHERE entity_id = ANY(:ids) AND day <= :day AND state <> 'dormant'
                """
            ),
            {"ids": list(out), "day": as_of_day},
        ).scalars()
        keep = set(rows)
        out = {k: v for k, v in out.items() if k in keep}
    return out


def _attach_neighbourhoods(session: Session, cands: dict[int, Candidate], as_of: datetime) -> None:
    """Fill each candidate's neighbour labels from ``entity_semantic_edges``, both directions.

    Edges are stored one-way, and an edge may anchor on a concept ("MCP") that is not a tracked
    entity — which is why labels, not entity ids, are the projection key. The nullable endpoint is
    a feature here: a concept both members point at is exactly the link we want to find."""
    if not cands:
        return
    # NOTE on as-of: derived edges are deliberately NOT filtered by ``created_at``. Invariant 2
    # governs *events* — ``created_at`` here is when the model pass ran, not when the similarity
    # became true, and a semantic edge carries no domain date at all. Filtering on it would mean a
    # wave could never be replayed for any date before the graph was last rebuilt, which is not
    # honesty but breakage. The as-of guarantee is enforced where events are actually read:
    # candidate selection (first evidence <= as_of) and the observation search. Known consequence,
    # same shape as momentum_states being rewritten each score run: replaying a past date uses
    # today's graph to interpret that day's entities.
    rows = session.execute(
        text(
            """
            SELECT src_entity_id, dst_entity_id, src_label, dst_label, dst_entity_id AS dst_id
            FROM entity_semantic_edges
            WHERE confidence_score >= :minconf
              AND (src_entity_id = ANY(:ids) OR dst_entity_id = ANY(:ids))
            """
        ),
        {"minconf": settings.wave_min_edge_confidence, "ids": list(cands)},
    ).mappings()

    neighbour_entity_ids: set[int] = set()
    pending: list[tuple[int, str, int | None]] = []
    for r in rows:
        if r["src_entity_id"] in cands:
            pending.append(
                (r["src_entity_id"], normalize_label(r["dst_label"]), r["dst_entity_id"])
            )
            if r["dst_entity_id"]:
                neighbour_entity_ids.add(r["dst_entity_id"])
        if r["dst_entity_id"] in cands:
            pending.append(
                (r["dst_entity_id"], normalize_label(r["src_label"]), r["src_entity_id"])
            )
            if r["src_entity_id"]:
                neighbour_entity_ids.add(r["src_entity_id"])

    # A neighbour's own category is the second link route: two candidates whose *different*
    # neighbours sit in the same category still describe the same problem space.
    ncat: dict[int, str | None] = {}
    if neighbour_entity_ids:
        ncat = {
            row_id: cat
            for row_id, cat in session.execute(
                text("SELECT id, category FROM entities WHERE id = ANY(:ids)"),
                {"ids": sorted(neighbour_entity_ids)},
            ).all()
        }

    for eid, label, neighbour_id in pending:
        if neighbour_id in cands:
            continue  # a link to another candidate is handled as a direct link, not a neighbour
        cands[eid].neighbours.add(label)
        if neighbour_id and (cat := ncat.get(neighbour_id)):
            cands[eid].neighbour_categories.add(cat)


def _direct_links(
    session: Session, cands: dict[int, Candidate], as_of: datetime
) -> set[frozenset[int]]:
    """Candidate pairs joined by a semantic edge directly. Rare among brand-new entities — the
    known wave had none — but supporting it costs one query and misses nothing."""
    if not cands:
        return set()
    rows = session.execute(
        text(
            """
            SELECT src_entity_id, dst_entity_id FROM entity_semantic_edges
            WHERE confidence_score >= :minconf
              AND src_entity_id = ANY(:ids) AND dst_entity_id = ANY(:ids)
            """
        ),
        {"minconf": settings.wave_min_edge_confidence, "ids": list(cands)},
    ).all()
    return {frozenset((s, d)) for s, d in rows if s != d}


def _cluster(
    cands: dict[int, Candidate], direct: set[frozenset[int]]
) -> list[tuple[list[int], dict[int, dict[str, list[str]]]]]:
    """Union-find over the linked relation. Returns clusters with, per member, why it linked in."""
    parent = {i: i for i in cands}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    reasons: dict[int, dict[str, list[str]]] = {
        i: {"shared_neighbours": [], "shared_neighbour_categories": [], "direct": []} for i in cands
    }

    ids = list(cands)
    for idx, a in enumerate(ids):
        for b in ids[idx + 1 :]:
            ca, cb = cands[a], cands[b]
            linked = False
            if shared := ca.neighbours & cb.neighbours:
                for label in sorted(shared):
                    reasons[a]["shared_neighbours"].append(label)
                    reasons[b]["shared_neighbours"].append(label)
                linked = True
            if shared_cat := ca.neighbour_categories & cb.neighbour_categories:
                for cat in sorted(shared_cat):
                    reasons[a]["shared_neighbour_categories"].append(cat)
                    reasons[b]["shared_neighbour_categories"].append(cat)
                linked = True
            if frozenset((a, b)) in direct:
                reasons[a]["direct"].append(str(b))
                reasons[b]["direct"].append(str(a))
                linked = True
            if linked:
                union(a, b)

    groups: dict[int, list[int]] = {}
    for i in ids:
        groups.setdefault(find(i), []).append(i)

    out = []
    for members in groups.values():
        if len(members) < 2:
            continue  # a lone candidate links to nothing; not a cluster at any threshold
        deduped = {
            m: {k: sorted(set(v)) for k, v in reasons[m].items() if v} for m in sorted(members)
        }
        out.append((sorted(members), deduped))
    return out


def _strength(
    members: list[int], first_seen: dict[int, date], breadth: dict[int, int]
) -> tuple[float, dict[str, object]]:
    """``size × breadth × tightness``, deliberately shaped like the gate's ``M × R × N``: bounded
    components, each separately inspectable, no parameter hidden inside a model."""
    n = len(members)
    # Saturating: 4 members -> 0.6, 6 -> 0.8, 10+ -> 1.0. Past ten, more members add little.
    size = min(1.0, 0.6 + 0.05 * max(0, n - settings.wave_min_members) * 2)

    breadths = sorted(breadth.get(m, 0) for m in members)
    median_breadth = breadths[len(breadths) // 2] if breadths else 0
    # A wave of single-evidence-type entities is a weaker claim, for the same reason
    # breakout_min_breadth exists: one channel can be gamed, two independent ones much less so.
    breadth_factor = min(1.0, 0.4 + 0.3 * median_breadth)

    days = sorted(first_seen[m] for m in members)
    span = max(1, (days[-1] - days[0]).days)
    # Four entities in a week is a sharper signal than four spread over a month.
    tightness = max(0.3, 1.0 - (span / max(1, settings.wave_window_days)) * 0.7)

    strength = round(size * breadth_factor * tightness, 4)
    return strength, {
        "size": round(size, 4),
        "breadth": round(breadth_factor, 4),
        "tightness": round(tightness, 4),
        "members": n,
        "median_evidence_breadth": median_breadth,
        "span_days": span,
    }


def _evidence_breadth(session: Session, ids: list[int], as_of: datetime) -> dict[int, int]:
    """Distinct collectors that have touched each entity — the cheap, deterministic stand-in for
    evidence-type breadth, read the same way the Radar computes its source list."""
    if not ids:
        return {}
    rows = session.execute(
        text(
            """
            SELECT l.entity_id, count(DISTINCT r.source) AS n
            FROM entity_links l JOIN raw_events r ON r.id = l.raw_event_id
            WHERE l.rule = 'attach' AND r.occurred_at <= :as_of AND l.entity_id = ANY(:ids)
            GROUP BY l.entity_id
            """
        ),
        {"as_of": as_of, "ids": ids},
    ).all()
    return {eid: int(n) for eid, n in rows}


def run_waves(session: Session, as_of: datetime | None = None) -> WaveStats:
    """Detect waves as of ``as_of`` and persist them, preserving identity across runs.

    Re-runnable and as-of correct: the same ``as_of`` produces the same clusters, and a wave that
    already exists keeps its id and ``first_seen`` rather than being minted afresh every day."""
    as_of = as_of or datetime.now(UTC)
    stats = WaveStats(as_of=as_of)

    cands = _candidates(session, as_of)
    stats.candidates = len(cands)
    if len(cands) < settings.wave_min_members:
        return stats

    _attach_neighbourhoods(session, cands, as_of)
    direct = _direct_links(session, cands, as_of)
    clusters = _cluster(cands, direct)
    stats.clusters_found = len(clusters)

    first_seen = {i: c.first_seen for i, c in cands.items()}
    for members, reasons in clusters:
        verdicts = independence.evaluate(session, members, first_seen, as_of)
        independent = [m for m in members if verdicts[m].independent]
        stats.collapsed_members += len(members) - len(independent)

        if len(independent) < settings.wave_min_members:
            stats.below_min_members += 1
            continue

        breadth = _evidence_breadth(session, independent, as_of)
        strength, components = _strength(independent, first_seen, breadth)
        categories: set[str] = {c for m in independent if (c := cands[m].category)}
        components["categories"] = sorted(categories)
        components["collapsed"] = len(members) - len(independent)

        _, created = persist_wave(
            session,
            member_ids=independent,
            first_seen={m: first_seen[m] for m in independent},
            link_reasons={m: reasons.get(m, {}) for m in independent},
            independence={m: verdicts[m].as_dict() for m in independent},
            strength=strength,
            components=components,
            as_of=as_of,
        )
        stats.waves_written += 1
        stats.waves_new += int(created)
    return stats
