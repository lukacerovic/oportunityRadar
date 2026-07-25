"""Velocity and cohort percentiles (doc 06 §2) — the ``P`` input to the state machine.

Velocity is the 7-day change of each metric's value (a slope for counters, a level-delta for
levels). Each entity's velocity is then ranked *within its cohort* (doc 06 DR-06.3) as a
percentile — absolute velocity is meaningless across ages/types, only relative velocity is. The
composite ``P`` an entity carries is the **max** of its per-metric percentiles across the
usage/participation metrics; attention is excluded from the composite by design (idea-spec
principle 3) though it still counts toward breadth.

As-of correctness (doc 06 §5, doc 13 A-2): velocities use only ``entity_metrics_daily`` rows on
days ≤ ``as_of``; cohort membership is evaluated once at ``as_of`` (canonical id + category +
age), so ``score --as-of D`` is a pure function of events ≤ D — identical on re-run. Ranking a
past day D' compares each member's velocity *at D'*, so momentum at D' is still period-correct.

DR-06.1 note: the heavy per-day 7-day window is computed set-wise; the percentile *ranking* is
done in Python because cohort membership is itself as-of-dependent (which SQL ``percent_rank``
over the present-time graph would get wrong). Python orchestrates; the metric math stays set-wise.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from seismo.config import settings
from seismo.db import canonical_entity_id
from seismo.trajectory.cohorts import EntityFacts, entity_facts
from seismo.trajectory.metrics import (
    ADOPTION_METRICS,
    ATTENTION_METRICS,
    BREADTH_METRIC,
    COMPOSITE_METRICS,
)

VELOCITY_LAG_DAYS = 7


@dataclass
class DaySignal:
    """Everything the state machine needs for one entity on one day (doc 06 §4)."""

    p: float = 0.0  # composite velocity percentile (max over composite metrics)
    count_60: int = 0  # composite metrics with pctl >= 0.60
    count_80: int = 0
    count_95: int = 0
    breadth: int = 0  # evidence_breadth value
    cohort_n: int = 0  # size of the cohort used for ranking
    cohort_key: str = ""
    provisional: bool = False  # cohort under min size even after fallback (doc 14 §5)
    attention_p: float = 0.0  # mean cohort pctl of attention-group metrics present today
    adoption_p: float = 0.0  # mean cohort pctl of adoption-group metrics present today
    hype_gap: float = 0.0  # attention_p - adoption_p (talk minus real usage; idea-spec principle 3)


@dataclass
class VelocityData:
    facts: dict[int, EntityFacts]
    signals: dict[int, dict[date, DaySignal]] = field(default_factory=dict)

    def days(self, entity_id: int) -> list[date]:
        return sorted(self.signals.get(entity_id, {}))


def compute(session: Session, as_of: datetime) -> VelocityData:
    """Build per-entity, per-day :class:`DaySignal`s from the metric table as of ``as_of``."""
    facts = entity_facts(session, as_of)
    series = _load_series(session, as_of)  # metric -> entity -> {day: value}
    breadth = series.get(BREADTH_METRIC, {})

    # 7-day-change velocities per ranked metric. Composite metrics feed the momentum ``p``;
    # attention metrics are ranked too (for the hype gap) but stay OUT of the composite ``p``.
    velocity: dict[str, dict[int, dict[date, Decimal]]] = {}
    for metric in COMPOSITE_METRICS | ATTENTION_METRICS:
        velocity[metric] = _velocities(series.get(metric, {}))

    cohort_of = _assign_cohorts(facts, as_of.date())
    data = VelocityData(facts=facts)
    data.signals = _build_signals(velocity, breadth, cohort_of, facts)
    return data


def _load_series(session: Session, as_of: datetime) -> dict[str, dict[int, dict[date, Decimal]]]:
    rows = session.execute(
        text(
            """
            SELECT metric, entity_id, day, value
            FROM entity_metrics_daily
            WHERE day <= :as_of_day
            """
        ),
        {"as_of_day": as_of.date()},
    ).all()
    series: dict[str, dict[int, dict[date, Decimal]]] = defaultdict(lambda: defaultdict(dict))
    canonical: dict[int, int] = {}
    for metric, entity_id, day, value in rows:
        if entity_id not in canonical:
            canonical[entity_id] = canonical_entity_id(session, entity_id, as_of)
        cid = canonical[entity_id]
        existing = series[metric][cid].get(day)
        series[metric][cid][day] = value if existing is None else max(existing, value)
    return series


def _velocities(by_entity: dict[int, dict[date, Decimal]]) -> dict[int, dict[date, Decimal]]:
    """vel7(D) = value(D) − value at-or-before (D−7). Baseline 0 when the entity has no earlier
    observation (a young series' whole level is its growth)."""
    out: dict[int, dict[date, Decimal]] = {}
    for entity_id, day_values in by_entity.items():
        days = sorted(day_values)
        vel: dict[date, Decimal] = {}
        for d in days:
            target = d - timedelta(days=VELOCITY_LAG_DAYS)
            prior = Decimal(0)
            for pd in days:
                if pd <= target:
                    prior = day_values[pd]
                else:
                    break
            vel[d] = day_values[d] - prior
        out[entity_id] = vel
    return out


def _assign_cohorts(
    facts: dict[int, EntityFacts], as_of_day: date
) -> dict[int, tuple[str, int, bool]]:
    """Map each entity to (cohort_key_str, cohort_n, provisional). Full ``(type, category, age)``
    key when it has ≥ min members; else fall back to ``(type, age)``; still thin ⇒ provisional
    (doc 14 §5)."""
    min_size = settings.cohort_min_size
    primary_sizes: dict[tuple[str, str, str], int] = defaultdict(int)
    fallback_sizes: dict[tuple[str, str], int] = defaultdict(int)
    for f in facts.values():
        primary_sizes[f.cohort_key(as_of_day)] += 1
        fallback_sizes[f.fallback_key(as_of_day)] += 1

    out: dict[int, tuple[str, int, bool]] = {}
    for eid, f in facts.items():
        pk = f.cohort_key(as_of_day)
        if primary_sizes[pk] >= min_size:
            out[eid] = (str(pk), primary_sizes[pk], False)
            continue
        fk = f.fallback_key(as_of_day)
        n = fallback_sizes[fk]
        out[eid] = (str(fk), n, n < min_size)
    return out


def _build_signals(
    velocity: dict[str, dict[int, dict[date, Decimal]]],
    breadth: dict[int, dict[date, Decimal]],
    cohort_of: dict[int, tuple[str, int, bool]],
    facts: dict[int, EntityFacts],
) -> dict[int, dict[date, DaySignal]]:
    # cohort_key_str -> list of member entity ids (from facts, all trackable members).
    members: dict[str, list[int]] = defaultdict(list)
    for eid in facts:
        members[cohort_of[eid][0]].append(eid)

    signals: dict[int, dict[date, DaySignal]] = defaultdict(dict)

    # Percentile per (metric, entity, day): rank each entity's vel7 among ALL cohort members.
    pctls = {
        metric: _metric_percentiles(by_entity, cohort_of, members)
        for metric, by_entity in velocity.items()
    }

    # Composite ``p`` and tier counts: max/tally over the composite metrics only — attention is
    # ranked above but deliberately excluded here (idea-spec principle 3; it feeds hype, not p).
    for metric in COMPOSITE_METRICS:
        for eid, day_pctl in pctls.get(metric, {}).items():
            for d, pctl in day_pctl.items():
                sig = signals[eid].setdefault(d, _new_signal(cohort_of[eid]))
                sig.p = max(sig.p, pctl)
                if pctl >= settings.momentum_p_simmering:
                    sig.count_60 += 1
                if pctl >= settings.momentum_p_accelerating:
                    sig.count_80 += 1
                if pctl >= settings.momentum_p_breakout:
                    sig.count_95 += 1

    # Hype gap: attention-group mean pctl minus adoption-group mean pctl, per (entity, day). A
    # group with no metric present that day defaults to 0.0 (idea-spec: missing group is 0, not
    # None) — never skip the entity. Ported from z-score space into percentile space.
    attn = _group_pctls(ATTENTION_METRICS, pctls)
    adopt = _group_pctls(ADOPTION_METRICS, pctls)
    for eid in set(attn) | set(adopt):
        e_attn, e_adopt = attn.get(eid, {}), adopt.get(eid, {})
        for d in set(e_attn) | set(e_adopt):
            a_p, u_p, gap = _hype_signal(e_attn.get(d, []), e_adopt.get(d, []))
            sig = signals[eid].setdefault(d, _new_signal(cohort_of.get(eid, ("", 0, False))))
            sig.attention_p = a_p
            sig.adoption_p = u_p
            sig.hype_gap = gap

    # Fold breadth onto existing signal days (and create bare signal days for breadth-only info).
    for eid, day_values in breadth.items():
        for d, v in day_values.items():
            sig = signals[eid].setdefault(d, _new_signal(cohort_of.get(eid, ("", 0, False))))
            sig.breadth = int(v)
    return signals


def _metric_percentiles(
    by_entity: dict[int, dict[date, Decimal]],
    cohort_of: dict[int, tuple[str, int, bool]],
    members: dict[str, list[int]],
) -> dict[int, dict[date, float]]:
    """Cohort percentile of each entity's vel7 per day: rank among ALL cohort members (missing =
    0), mirroring SQL percent_rank (ties share the lower rank; lone cohort ⇒ 0). Records only the
    days an entity actually has a velocity."""
    out: dict[int, dict[date, float]] = defaultdict(dict)
    days_by_cohort: dict[str, set[date]] = defaultdict(set)
    for eid, vel in by_entity.items():
        days_by_cohort[cohort_of[eid][0]].update(vel)
    for ckey, days in days_by_cohort.items():
        member_ids = members[ckey]
        for d in days:
            values = [by_entity.get(m, {}).get(d, Decimal(0)) for m in member_ids]
            ranks = _percent_ranks(values)
            for m, pctl in zip(member_ids, ranks, strict=True):
                if d in by_entity.get(m, {}):
                    out[m][d] = pctl
    return out


def _group_pctls(
    metric_names: frozenset[str],
    pctls: dict[str, dict[int, dict[date, float]]],
) -> dict[int, dict[date, list[float]]]:
    """Collect a group's per-metric percentiles into ``entity -> day -> [pctl, ...]``."""
    acc: dict[int, dict[date, list[float]]] = defaultdict(lambda: defaultdict(list))
    for metric in metric_names:
        for eid, day_pctl in pctls.get(metric, {}).items():
            for d, pctl in day_pctl.items():
                acc[eid][d].append(pctl)
    return acc


def _hype_signal(
    attention_pctls: list[float], adoption_pctls: list[float]
) -> tuple[float, float, float]:
    """(attention_p, adoption_p, hype_gap) from a day's group percentiles. Each group value is the
    mean of its present metrics; an empty group is 0.0 (idea-spec: missing group defaults to 0.0,
    not None). ``hype_gap = attention_p - adoption_p``."""
    a_p = sum(attention_pctls) / len(attention_pctls) if attention_pctls else 0.0
    u_p = sum(adoption_pctls) / len(adoption_pctls) if adoption_pctls else 0.0
    return a_p, u_p, a_p - u_p


def _new_signal(cohort: tuple[str, int, bool]) -> DaySignal:
    return DaySignal(cohort_key=cohort[0], cohort_n=cohort[1], provisional=cohort[2])


def _percent_ranks(values: list[Decimal]) -> list[float]:
    """SQL ``percent_rank`` semantics: (#strictly-less)/(n−1); 0.0 for n≤1 and for tied minima."""
    n = len(values)
    if n <= 1:
        return [0.0] * n
    return [sum(1 for other in values if other < v) / (n - 1) for v in values]
