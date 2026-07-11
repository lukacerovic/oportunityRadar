"""``seismo`` — the single CLI entrypoint (Typer).

Each stage subcommand is idempotent for its ``(stage, as_of)`` and records a ``pipeline_runs``
row (doc 02 §7). Stage 0 ships ``doctor`` fully; the pipeline stages are wired skeletons that
record their run and will be filled in their respective stages (docs 03–09).
"""

from __future__ import annotations

from datetime import UTC, datetime

import typer

from seismo.bookkeeping import record_pipeline_run
from seismo.config import settings
from seismo.health import run_checks

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Seismograph CLI.")


def _parse_as_of(value: str | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _stub(stage: str, as_of: datetime) -> None:
    with record_pipeline_run(stage, as_of):
        typer.echo(f"[{stage}] not implemented yet (recorded pipeline_run, as_of={as_of.date()})")


# --- pipeline stage skeletons (filled in later stages) ---------------------


@app.command()
def collect(
    source: str = typer.Option(
        "all", help="Source key ('github'|'hn'|'arxiv') or group ('fast'|'all')."
    ),
    window: str = typer.Option("1d", help="Discovery window in days, e.g. '1d' or '7d'."),
) -> None:
    """Layer 1 — discover and record raw events (doc 03). Failures are isolated per source."""
    from seismo.collectors.base import Window
    from seismo.collectors.registry import build, resolve_sources
    from seismo.collectors.runner import run_collector

    days = float(window.rstrip("d"))
    win = Window.last(days)
    sources = resolve_sources(source)
    with record_pipeline_run(f"collect:{source}"):
        for key in sources:
            result = run_collector(build(key), win, mode="discover")
            status = "ok" if result.ok else f"FAIL ({result.error})"
            typer.echo(f"[collect] {key}: {result.events_new} new events — {status}")


@app.command()
def track(
    source: str = typer.Option("github", help="Registry to deep-poll ('github')."),
    limit: int = typer.Option(None, help="Cap the number of targets (testing / rate budget)."),
) -> None:
    """Layer 1 tracking — daily ``*_snapshot`` for known entities (doc 03 DR-03.3).

    Builds the metric time series the trajectory layer needs. Polls active-tier, unmerged entities
    that carry the source's anchor; failures are isolated per source like ``collect``."""
    from seismo.collectors.base import Window
    from seismo.collectors.registry import build
    from seismo.collectors.runner import run_collector
    from seismo.collectors.targets import select_targets
    from seismo.db import session_scope

    with record_pipeline_run(f"track:{source}"):
        with session_scope() as session:
            targets = select_targets(session, source, limit=limit)
        result = run_collector(build(source), Window.last(1.0), mode="track", targets=targets)
        status = "ok" if result.ok else f"FAIL ({result.error})"
        typer.echo(
            f"[track] {source}: {len(targets)} targets, {result.events_new} snapshots — {status}"
        )


@app.command(name="enrich-readmes")
def enrich_readmes(
    limit: int = typer.Option(None, help="Cap the number of repos to enrich (rate budget)."),
    carded_only: bool = typer.Option(
        False, "--carded-only", help="Only repos that already have a comprehension card (§16 win)."
    ),
) -> None:
    """Enrichment (§16) — fetch repo READMEs as ``repo_readme`` events so comprehension packs are
    substantial, not just the one-line GitHub description. Fetch is per-repo rate-limited (5000/hr
    authenticated); scope with ``--limit`` / ``--carded-only`` — do not blast the full universe.
    Run ``resolve`` then ``comprehend`` after to regenerate the enriched cards."""
    from seismo.collectors.base import Window
    from seismo.collectors.github import GitHubCollector
    from seismo.collectors.runner import persist_drafts
    from seismo.collectors.targets import select_carded_targets, select_targets
    from seismo.db import session_scope

    with record_pipeline_run("enrich-readmes"):
        with session_scope() as session:
            targets = (
                select_carded_targets(session, "github", limit=limit)
                if carded_only
                else select_targets(session, "github", limit=limit)
            )
        # Fetch outside any open transaction (the poll can take minutes over many repos).
        drafts = GitHubCollector().readmes(targets, Window.last(1.0))
        with session_scope() as session:
            new = persist_drafts(session, drafts)
        typer.echo(
            f"[enrich-readmes] {len(targets)} repos → {len(drafts)} READMEs, {new} new events "
            f"(run `seismo resolve` then `seismo comprehend` to regenerate cards)"
        )


@app.command()
def sweep(
    days: int = typer.Option(None, help="Historical span in days; default COLDSTART_SWEEP_DAYS."),
    chunk: int = typer.Option(30, help="Discovery window size per step (days)."),
    source: str = typer.Option("fast", help="Collector group ('fast'|'all') or a single source."),
) -> None:
    """Cold-start historical sweep (doc 14 §7): loop discovery over past windows to seed the
    universe, then resolve --cold-start. Star *history* (GH Archive) is a separate heavy job —
    see ``backfill-stars``. Idempotent: re-running inserts zero duplicate events."""
    from datetime import timedelta

    from seismo.collectors.base import Window
    from seismo.collectors.registry import build, resolve_sources
    from seismo.collectors.runner import run_collector
    from seismo.db import session_scope
    from seismo.identity.resolve import resolve as run_resolve

    span = days if days is not None else settings.coldstart_sweep_days
    sources = resolve_sources(source)
    now = datetime.now(UTC)
    total = 0
    with record_pipeline_run(f"sweep:{source}"):
        offset = 0
        while offset < span:
            until = now - timedelta(days=offset)
            since = now - timedelta(days=min(offset + chunk, span))
            for key in sources:
                result = run_collector(
                    build(key), Window(since=since, until=until), mode="discover"
                )
                total += result.events_new
                status = "ok" if result.ok else f"FAIL ({result.error})"
                typer.echo(
                    f"[sweep] {since.date()}..{until.date()} {key}: +{result.events_new} — {status}"
                )
            offset += chunk
        with session_scope() as session:
            stats = run_resolve(session, cold_start=True)
    typer.echo(f"[sweep] {span}d done — {total} new events; {stats.as_note()}")


@app.command(name="backfill-stars")
def backfill_stars(
    since: str = typer.Option(..., help="ISO date, inclusive (e.g. 2024-01-01)."),
    until: str = typer.Option(..., help="ISO date, exclusive."),
    repos: str = typer.Option(
        None, help="Comma-separated owner/repo or org names; default = all tracked github entities."
    ),
) -> None:
    """GH Archive star-history backfill for hindcast momentum (doc 11). Reconstructs ``repo_star``
    events → the cumulative ``gh_stars`` series a past-dated ``score`` needs.

    HEAVY: scans the full hourly GH Archive firehose (~120 MB/hr) across the window — hours of
    network and hundreds of GB for long spans. Scope tightly (a case's org + a few months)."""
    from seismo.collectors.backfill_gharchive import backfill, hourly_stamps
    from seismo.collectors.base import Window
    from seismo.collectors.targets import select_targets
    from seismo.db import session_scope

    win = Window(since=_parse_as_of(since), until=_parse_as_of(until))
    if repos:
        targets = {r.strip().lower() for r in repos.split(",") if r.strip()}
    else:
        with session_scope() as session:
            targets = {t.native_id for t in select_targets(session, "github")}
    hours = len(hourly_stamps(win))
    typer.echo(
        f"[backfill-stars] {win.since.date()}..{win.until.date()} = {hours} hourly archives, "
        f"{len(targets)} targets. This downloads the full firehose per hour — be patient."
    )
    with record_pipeline_run("backfill-stars", win.since):
        n = backfill(win, targets)
    typer.echo(f"[backfill-stars] persisted {n} backfill events (run resolve → snapshot → score).")


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Bind host."),
    port: int = typer.Option(8000, help="Bind port."),
    reload: bool = typer.Option(False, "--reload", help="Auto-reload (dev)."),
) -> None:
    """Layer 6 — run the read + curation API for the dashboard (doc 10). Behind Caddy in prod."""
    import uvicorn

    uvicorn.run("seismo.api.app:app", host=host, port=port, reload=reload)


@app.command()
def resolve(cold_start: bool = typer.Option(False, "--cold-start")) -> None:
    """Layer 2 — entity resolution + merge queue (doc 04).

    ``--cold-start`` defers R4–R6 to the deferred bucket (doc 14 §8)."""
    from seismo.db import session_scope
    from seismo.identity.resolve import resolve as run_resolve

    with record_pipeline_run("resolve"):
        with session_scope() as session:
            stats = run_resolve(session, cold_start=cold_start)
        typer.echo(f"[resolve] cold_start={cold_start} — {stats.as_note()}")


@app.command(name="seed-load")
def seed_load() -> None:
    """Cold-start — load the hand-curated seed universe (doc 14 §3). Idempotent."""
    from seismo.db import session_scope
    from seismo.identity.seed import seed_load as run_seed_load

    with record_pipeline_run("seed-load"):
        with session_scope() as session:
            stats = run_seed_load(session)
        typer.echo(
            f"[seed-load] entities={stats.entities_in_file} events={stats.events_emitted} "
            f"new={stats.events_new} (run `seismo resolve --cold-start` next)"
        )


@app.command()
def snapshot(as_of: str = typer.Option(None, help="ISO date; default now.")) -> None:
    """Layer 4 — rebuild entity_metrics_daily from *_snapshot events (doc 06 §1)."""
    from seismo.db import session_scope
    from seismo.trajectory.metrics import run_snapshot

    when = _parse_as_of(as_of)
    with record_pipeline_run("snapshot", when):
        with session_scope() as session:
            stats = run_snapshot(session, when)
        typer.echo(f"[snapshot] as_of={when.date()} — {stats.as_note()}")


@app.command()
def score(as_of: str = typer.Option(None, help="ISO date; default now.")) -> None:
    """Layer 4 — maturity ladder + velocity percentiles + momentum states (doc 06)."""
    from seismo.db import session_scope
    from seismo.trajectory.score import run_score

    when = _parse_as_of(as_of)
    with record_pipeline_run("score", when):
        with session_scope() as session:
            stats = run_score(session, when)
        typer.echo(f"[score] as_of={when.date()} — {stats.as_note()}")


@app.command()
def comprehend(
    as_of: str = typer.Option(None, help="ISO date; default now."),
    entity: int = typer.Option(None, help="Force a card for one entity id (skips the trigger)."),
    limit: int = typer.Option(None, help="Cap candidates this run (cost control)."),
) -> None:
    """Layer 3 — comprehension checkpoint 1 (doc 05). Provider pluggable; dev/CI = mock ($0)."""
    from seismo.checkpoints.comprehend import run_comprehend
    from seismo.db import session_scope

    when = _parse_as_of(as_of)
    with record_pipeline_run("comprehend", when):
        with session_scope() as session:
            stats = run_comprehend(session, when, entity_id=entity, limit=limit)
        typer.echo(
            f"[comprehend] provider={settings.llm_provider} as_of={when.date()} — {stats.as_note()}"
        )


@app.command(name="load-map")
def load_map_cmd(
    path: str = typer.Option("exposure_map", help="Directory of company YAML files."),
    strict: bool = typer.Option(
        False, "--strict", help="Exit non-zero if any file fails validation."
    ),
) -> None:
    """Layer 6/A-1 — validate the exposure-map YAML and load companies + reach_links (doc 08 §1).

    Idempotent + authoritative: each company's reach_links are rebuilt from its YAML on every load.
    Unblocks the significance gate (doc 07); unmapped categories are expected (map-gaps)."""
    from seismo.db import session_scope
    from seismo.significance.exposure import load_map

    with record_pipeline_run("load-map"):
        with session_scope() as session:
            stats = load_map(session, path)
        typer.echo(f"[load-map] {stats.as_note()}")
        for err in stats.errors:
            typer.echo(typer.style(f"  ERROR {err}", fg=typer.colors.RED))
    if strict and stats.errors:
        raise typer.Exit(code=1)


@app.command()
def gate(
    week: str = typer.Option(None, help="ISO week, e.g. 2026-W28; default current week."),
) -> None:
    """Layer 5 — deterministic significance gate (doc 07). Picks ≤K briefs/week via M×R×N; writes a
    ``gate_decisions`` audit row for every candidate (passed + suppressed). No LLM (DR-07.1)."""
    from seismo.db import session_scope
    from seismo.significance.gate import parse_week, run_gate

    week_start = parse_week(week)
    with record_pipeline_run("gate", _parse_as_of(week_start.isoformat())):
        with session_scope() as session:
            stats = run_gate(session, week_start)
        typer.echo(f"[gate] {stats.as_note()}")


@app.command()
def brief(
    entity_id: int = typer.Option(None, help="Force a brief for one entity (bypasses the gate)."),
    week: str = typer.Option(None, help="ISO week, e.g. 2026-W28; briefs the whole passed queue."),
    as_of: str = typer.Option(None, help="ISO date; default now (or the week's end when --week)."),
    limit: int = typer.Option(None, help="Cap the number of passed entities briefed."),
) -> None:
    """Layer 6 — impact checkpoint (doc 08). LLM checkpoint 2: draft an evidence-linked exposure
    brief for each entity the significance gate passed (or one forced with ``--entity-id``). Briefs
    are stored ``draft`` for human review before publish (DR-08.2)."""
    from seismo.checkpoints.impact import run_brief, week_as_of
    from seismo.db import session_scope
    from seismo.significance.gate import parse_week

    week_start = parse_week(week) if week else None
    if as_of is not None:
        when = _parse_as_of(as_of)
    elif week_start is not None:
        when = week_as_of(week_start)
    else:
        when = _parse_as_of(None)

    with record_pipeline_run("brief", when):
        with session_scope() as session:
            stats = run_brief(
                session, when, entity_id=entity_id, week_start=week_start, limit=limit
            )
        typer.echo(
            f"[brief] provider={settings.llm_provider} as_of={when.date()} — {stats.as_note()}"
        )


@app.command()
def changes(as_of: str = typer.Option(None, help="ISO date; default now.")) -> None:
    """Layer 7 — the Changes view (doc 09 §1). Deterministic, templated daily deltas (state moves,
    promotions, brief lifecycle, Monday gate rollup) → ``changes_daily``. No LLM (DR-09.1)."""
    from seismo.db import session_scope
    from seismo.memory.changes import compute_changes

    when = _parse_as_of(as_of)
    with record_pipeline_run("changes", when):
        with session_scope() as session:
            stats = compute_changes(session, when)
        typer.echo(f"[changes] {stats.as_note()}")


@app.command()
def calibrate(as_of: str = typer.Option(None, help="ISO date; default now.")) -> None:
    """Layer 7 — momentum-call review (doc 09 §3). Automated: breakout-survival + fade-reaccel
    ratios → ``calibration_snapshots`` (the calibration track record the dashboard trends)."""
    from seismo.db import session_scope
    from seismo.memory.calibration import run_momentum_review

    when = _parse_as_of(as_of)
    with record_pipeline_run("calibrate", when):
        with session_scope() as session:
            stats = run_momentum_review(session, when)
        typer.echo(f"[calibrate] {stats.as_note()}")
        for note in stats.notes:
            typer.echo(f"  note: {note}")


@app.command()
def hindcast(
    case: str = typer.Option(..., help="Case name, e.g. deepseek (hindcast/cases/<case>.yaml)."),
    reload: bool = typer.Option(
        False, "--reload", help="Run the historical loader first (HEAVY: GH Archive firehose)."
    ),
    step_days: int = typer.Option(1, help="Days per replay step; 1 = daily (as-of correct)."),
    report_path: str = typer.Option(None, help="Write the markdown trace report to this file."),
) -> None:
    """Validation harness (doc 11) — replay the pipeline over a case window and grade its pinned
    assertions. ``--reload`` backfills seeds first (the GH Archive star firehose is hundreds of GB;
    scope tightly). Without it, the replay grades whatever is already in ``raw_events``."""
    from seismo.db import session_scope
    from seismo.hindcast.case import load_case_by_name
    from seismo.hindcast.runner import run_hindcast

    parsed = load_case_by_name(case)
    with record_pipeline_run(f"hindcast:{case}"):
        with session_scope() as session:
            result = run_hindcast(session, parsed, reload=reload, step_days=step_days)
        typer.echo(f"[hindcast] {result.as_note()}")
        for r in result.results:
            mark = typer.style("PASS", fg=typer.colors.GREEN) if r.passed else typer.style(
                "FAIL", fg=typer.colors.RED
            )
            typer.echo(f"  {mark} {r.id} ({r.type}): {r.detail}")
        for w in result.warnings:
            typer.echo(typer.style(f"  note: {w}", fg=typer.colors.YELLOW))
    if report_path:
        from pathlib import Path

        Path(report_path).write_text(result.report)
        typer.echo(f"[hindcast] report written to {report_path}")
    if not result.passed:
        raise typer.Exit(code=1)


# --- health -----------------------------------------------------------------


@app.command()
def doctor() -> None:
    """Report a green/red health table. Exits non-zero if anything is red."""
    checks = run_checks()
    width = max(len(c.name) for c in checks)
    typer.echo(f"{settings.product_name} doctor\n")
    for c in checks:
        mark = (
            typer.style("OK  ", fg=typer.colors.GREEN)
            if c.ok
            else typer.style("FAIL", fg=typer.colors.RED)
        )
        typer.echo(f"  {mark}  {c.name.ljust(width)}  {c.detail}")
    failed = [c for c in checks if not c.ok]
    typer.echo("")
    if failed:
        typer.echo(typer.style(f"{len(failed)} check(s) failing.", fg=typer.colors.RED))
        raise typer.Exit(code=1)
    typer.echo(typer.style("All green.", fg=typer.colors.GREEN))


if __name__ == "__main__":
    app()
