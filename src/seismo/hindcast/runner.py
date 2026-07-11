"""Hindcast runner (doc 11 §4) — the production pipeline run over backfilled history.

There is no separate backtest engine (DR-11.1). The runner drives the *same* orchestrators every
daily heartbeat uses — resolve, snapshot, score, gate, comprehend, brief — with historical
``as_of`` dates, then evaluates the case's pinned assertions and writes a ``hindcast_runs`` row plus
a markdown trace report. If a threshold or link rule regresses so the system would no longer catch
the case, the assertions go red — a CI failure, not a postmortem (DR-11.2).

Loading (the heavy GH Archive backfill) is separated from replay. Replay is pure over whatever
events already sit in ``raw_events`` for the window, so tests drive the whole machine on small
synthetic data with ``reload=False``. ``--reload`` (the injected ``loader``) is the only path that
touches the network, and the default loader flags the firehose before it runs (doc 11 §1).

Resolve is run once before the daily replay, not per day: entity birth is the earliest evidence and
category ``effective_at`` is anchored to it (doc 04), so a single as-of-correct resolve over the
full window produces the same entity graph as an incremental one — and every downstream read
(snapshot, score, gate, brief) already filters by ``as_of`` (doc 02 §5, doc 13 A-2).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from seismo.hindcast.assertions import AssertionResult, _resolve_ref, evaluate
from seismo.hindcast.case import Case
from seismo.hindcast.report import render_report

# A loader takes the session + case and mutates ``raw_events`` (and appends any warnings). Injected
# in tests to seed synthetic data; the default one hits the GH Archive firehose (heavy).
Loader = Callable[[Session, Case, list[str]], None]


@dataclass
class HindcastResult:
    case: str
    passed: bool
    total: int = 0
    failed: int = 0
    results: list[AssertionResult] = field(default_factory=list)
    report: str = ""
    warnings: list[str] = field(default_factory=list)
    run_id: int | None = None

    def as_note(self) -> str:
        verdict = "PASS" if self.passed else "FAIL"
        return (
            f"case={self.case} {verdict} {self.total - self.failed}/{self.total} assertions "
            f"(run_id={self.run_id})"
        )


def _end_of_day(d: date) -> datetime:
    return datetime.combine(d, datetime.max.time()).replace(tzinfo=UTC)


def _days(window_from: date, window_to: date, step: int) -> list[date]:
    out: list[date] = []
    cur = window_from
    while cur <= window_to:
        out.append(cur)
        cur += timedelta(days=step)
    return out


def _weeks(window_from: date, window_to: date) -> list[date]:
    """ISO-week Mondays overlapping the window."""
    out: list[date] = []
    cur = window_from - timedelta(days=window_from.weekday())  # Monday of the first week
    while cur <= window_to:
        out.append(cur)
        cur += timedelta(days=7)
    return out


def default_loader(session: Session, case: Case, warnings: list[str]) -> None:
    """The real historical loader (doc 11 §1). Only reached behind ``--reload``. Hacker News and
    arXiv are cheap (natively historical / targeted); GitHub star history via the GH Archive
    firehose is HEAVY (hundreds of GB for a long window). Sources without a loader are recorded as
    gaps, not silently skipped."""
    from seismo.collectors.backfill_gharchive import backfill
    from seismo.collectors.base import Window
    from seismo.hindcast.loaders import load_arxiv, load_hn

    window = Window(since=_end_of_day(case.window.from_), until=_end_of_day(case.window.to))

    # Hacker News — the Algolia API is natively historical, so the live collector is the loader.
    n_hn = load_hn(session, window)
    warnings.append(f"Hacker News: loaded {n_hn} historical stories over the case window.")

    # arXiv — targeted fetch of the case's seed papers (discover can't page back to a window).
    if case.seeds.arxiv:
        n_arxiv = load_arxiv(session, case.seeds.arxiv)
        warnings.append(f"arXiv: loaded {n_arxiv} seed paper(s) {case.seeds.arxiv}.")

    # GitHub star history — HEAVY firehose; only worth it for a pinned case.
    if case.seeds.github:
        warnings.append(
            "HEAVY: backfilling GitHub star history from the GH Archive firehose for "
            f"{case.seeds.github} over {case.window.from_}..{case.window.to} — hundreds of GB "
            "for a long window."
        )
        targets = {t.lower() for t in case.seeds.github}
        n = backfill(window, targets)
        warnings.append(f"GH Archive backfill inserted {n} star/discovery events.")

    for label, seeds in (
        ("Hugging Face createdAt + downloads", case.seeds.hf_orgs),
        ("Wayback pricing", case.seeds.wayback),
        ("PyPI BigQuery", case.seeds.pypi),
    ):
        if seeds:
            warnings.append(f"loader gap: {label} backfill not implemented — seeds {seeds} unmet.")


def run_hindcast(
    session: Session,
    case: Case,
    *,
    reload: bool = False,
    loader: Loader | None = None,
    comprehend: bool = True,
    step_days: int = 1,
    store: bool = True,
) -> HindcastResult:
    """Replay the pipeline over the case window and evaluate its pinned assertions.

    ``reload`` runs the (heavy) loader first; default ``False`` replays whatever is already in
    ``raw_events``. ``loader`` overrides the default network loader (tests inject synthetic data).
    ``comprehend``/``brief`` steps use the configured LLM provider — force ``mock`` in tests.
    """
    warnings: list[str] = []
    if reload:
        (loader or default_loader)(session, case, warnings)
        session.flush()

    window_end = _end_of_day(case.window.to)
    brief_as_of = _end_of_day(case.brief.as_of) if case.brief else None
    default_as_of = brief_as_of or window_end

    _replay(session, case, step_days)
    if case.brief:
        _run_brief_step(session, case, brief_as_of, comprehend=comprehend)  # type: ignore[arg-type]
    session.flush()

    results = [evaluate(session, case, a, default_as_of=default_as_of) for a in case.assertions]
    failed = sum(1 for r in results if not r.passed)

    trace, trace_label = _momentum_trace(session, case, default_as_of)
    report = render_report(
        case,
        results,
        warnings=warnings,
        trace=trace,
        trace_label=trace_label,
        brief_as_of=brief_as_of,
    )

    result = HindcastResult(
        case=case.name,
        passed=failed == 0,
        total=len(results),
        failed=failed,
        results=results,
        report=report,
        warnings=warnings,
    )
    if store:
        result.run_id = _store_run(session, case, result, brief_as_of)
    return result


def _replay(session: Session, case: Case, step_days: int) -> None:
    """The heartbeat, historicised: one as-of-correct resolve, then snapshot+score for each day,
    then the gate for each week the window touches (doc 11 §4)."""
    from seismo.identity.resolve import resolve
    from seismo.significance.gate import run_gate
    from seismo.trajectory.metrics import run_snapshot
    from seismo.trajectory.score import run_score

    window_end = _end_of_day(case.window.to)
    resolve(session, now=window_end)
    session.flush()

    for d in _days(case.window.from_, case.window.to, step_days):
        as_of = _end_of_day(d)
        run_snapshot(session, as_of)
        run_score(session, as_of)
    session.flush()

    for week_start in _weeks(case.window.from_, case.window.to):
        run_gate(session, week_start, now=window_end)
    session.flush()


def _run_brief_step(
    session: Session, case: Case, brief_as_of: datetime, *, comprehend: bool
) -> None:
    """Comprehend then force-brief the pinned case entity at ``brief_as_of`` (doc 11 §2). The brief
    is forced by entity id (``brief --entity-id``), bypassing the gate's top-K budget — the case
    pins exactly which entity it grades."""
    from seismo.checkpoints.comprehend import run_comprehend
    from seismo.checkpoints.impact import run_brief

    assert case.brief is not None
    eid = _resolve_ref(session, case.brief.entity, brief_as_of)
    if eid is None:
        return  # unresolved seed — the brief assertion will report the miss
    if comprehend:
        run_comprehend(session, brief_as_of, entity_id=eid)
        session.flush()
    run_brief(session, brief_as_of, entity_id=eid)
    session.flush()


def _momentum_trace(
    session: Session, case: Case, default_as_of: datetime
) -> tuple[list[tuple[date, str, float | None]], str | None]:
    """Per-day state trace of the case's primary entity (the brief target, else the first entity an
    assertion names) — the demo artifact (doc 11 §4)."""
    ref = None
    if case.brief:
        ref = case.brief.entity
    else:
        for a in case.assertions:
            candidate = a.params.get("entity")
            if candidate:
                ref = str(candidate)
                break
    if ref is None:
        return [], None
    eid = _resolve_ref(session, ref, default_as_of)
    if eid is None:
        return [], ref
    rows = session.execute(
        text(
            "SELECT day, state, score FROM momentum_states WHERE entity_id = :e AND day <= :d "
            "ORDER BY day"
        ),
        {"e": eid, "d": default_as_of.date()},
    ).all()
    trace = [(r[0], r[1], float(r[2]) if r[2] is not None else None) for r in rows]
    return trace, f"{ref} (entity {eid})"


def _store_run(
    session: Session, case: Case, result: HindcastResult, brief_as_of: datetime | None
) -> int:
    import json

    row = session.execute(
        text(
            """
            INSERT INTO hindcast_runs
              (case_name, window_from, window_to, brief_as_of, passed, total, failed,
               results, report)
            VALUES
              (:c, :wf, :wt, :bao, :passed, :total, :failed, CAST(:results AS JSONB), :report)
            RETURNING id
            """
        ),
        {
            "c": case.name,
            "wf": case.window.from_,
            "wt": case.window.to,
            "bao": brief_as_of,
            "passed": result.passed,
            "total": result.total,
            "failed": result.failed,
            "results": json.dumps([r.as_dict() for r in result.results]),
            "report": result.report,
        },
    ).scalar_one()
    return int(row)
