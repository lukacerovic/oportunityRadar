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
    source: str = typer.Option(
        "github", help="Registry to deep-poll ('github', 'hf', 'pypi')."
    ),
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
    missing: bool = typer.Option(
        False, "--missing", help="Only repos with NO README yet — self-completing daily coverage."
    ),
) -> None:
    """Enrichment (§16) — fetch repo READMEs as ``repo_readme`` events so comprehension packs are
    substantial, not just the one-line GitHub description. Fetch is per-repo rate-limited (5000/hr
    authenticated); scope with ``--limit`` / ``--carded-only`` / ``--missing`` — do not blast the
    full universe. Run ``resolve`` then ``comprehend`` after to regenerate the enriched cards."""
    from seismo.collectors.base import Window
    from seismo.collectors.github import GitHubCollector
    from seismo.collectors.runner import persist_drafts
    from seismo.collectors.targets import (
        select_carded_targets,
        select_targets,
        select_unenriched_targets,
    )
    from seismo.db import session_scope

    with record_pipeline_run("enrich-readmes"):
        with session_scope() as session:
            if missing:
                targets = select_unenriched_targets(session, "github", "repo_readme", limit=limit)
            elif carded_only:
                targets = select_carded_targets(session, "github", limit=limit)
            else:
                targets = select_targets(session, "github", limit=limit)
        # Fetch outside any open transaction (the poll can take minutes over many repos).
        drafts = GitHubCollector().readmes(targets, Window.last(1.0))
        with session_scope() as session:
            new = persist_drafts(session, drafts)
        typer.echo(
            f"[enrich-readmes] {len(targets)} repos → {len(drafts)} READMEs, {new} new events "
            f"(run `seismo resolve` then `seismo comprehend` to regenerate cards)"
        )


@app.command(name="enrich-contributors")
def enrich_contributors(
    limit: int = typer.Option(None, help="Cap the number of repos to enrich (rate budget)."),
) -> None:
    """Enrichment (Feature 1) — fetch each repo's top contributors as a ``repo_contributors``
    event, the record the ``derive-edges`` step turns into ``built_by`` (person → repo) graph
    edges. Targets repos with no contributors event yet (self-completing). Run ``resolve`` then
    ``derive-edges`` after to mint the edges."""
    from seismo.collectors.base import Window
    from seismo.collectors.github import GitHubCollector
    from seismo.collectors.runner import persist_drafts
    from seismo.collectors.targets import select_unenriched_targets
    from seismo.db import session_scope

    with record_pipeline_run("enrich-contributors"):
        with session_scope() as session:
            targets = select_unenriched_targets(
                session, "github", "repo_contributors", limit=limit
            )
        drafts = GitHubCollector().contributors(targets, Window.last(1.0))
        with session_scope() as session:
            new = persist_drafts(session, drafts)
        typer.echo(
            f"[enrich-contributors] {len(targets)} repos → {len(drafts)} contributor sets, "
            f"{new} new events (run `seismo resolve` then `seismo derive-edges`)"
        )


@app.command(name="enrich-launches")
def enrich_launches(
    limit: int = typer.Option(None, help="Cap the number of launches to enrich (rate budget)."),
) -> None:
    """Enrichment (Wave-3) — fetch the launch page behind each HN-native launch (``web``-anchored
    entity like Kimi) as a ``launch_page`` event, so its comprehension card has real content
    instead of just a headline. Best-effort: JS-only / paywalled pages are skipped. Run ``resolve``
    then ``comprehend`` after to card the enriched launches."""
    from seismo.collectors.launches import LaunchEnricher, select_launch_targets
    from seismo.collectors.runner import persist_drafts
    from seismo.db import session_scope

    with record_pipeline_run("enrich-launches"):
        with session_scope() as session:
            targets = select_launch_targets(session, limit=limit)
        # Fetch outside any open transaction (the page fetches can take a while over many URLs).
        drafts = LaunchEnricher().fetch(targets)
        with session_scope() as session:
            new = persist_drafts(session, drafts)
        typer.echo(
            f"[enrich-launches] {len(targets)} launches → {len(drafts)} pages, {new} new events "
            f"(run `seismo resolve` then `seismo comprehend` to card them)"
        )


@app.command(name="enrich-hf")
def enrich_hf(
    limit: int = typer.Option(None, help="Cap the number of models to enrich (rate budget)."),
) -> None:
    """Enrichment (Wave-3) — fetch each Hugging Face model's card (README) as a ``model_readme``
    event, so HF models have readable content to comprehend instead of just download counts.
    Targets models with no card yet (self-completing). Run ``resolve`` then ``comprehend`` after."""
    from seismo.collectors.hf import HuggingFaceCollector
    from seismo.collectors.runner import persist_drafts
    from seismo.collectors.targets import select_unenriched_targets
    from seismo.db import session_scope

    with record_pipeline_run("enrich-hf"):
        with session_scope() as session:
            targets = select_unenriched_targets(session, "hf", "model_readme", limit=limit)
        drafts = HuggingFaceCollector().model_cards(targets)
        with session_scope() as session:
            new = persist_drafts(session, drafts)
        typer.echo(
            f"[enrich-hf] {len(targets)} models → {len(drafts)} cards, {new} new events "
            f"(run `seismo resolve` then `seismo comprehend` to card them)"
        )


@app.command(name="enrich-pypi")
def enrich_pypi(
    limit: int = typer.Option(None, help="Cap the number of packages to enrich (rate budget)."),
) -> None:
    """Enrichment — fetch each PyPI package's JSON metadata as a ``pypi_metadata`` event, recording
    ``requires_dist``/``project_urls``/``summary`` (the dependency list a later step turns into
    typed graph edges). Targets packages with no metadata event yet (self-completing). Run
    ``resolve`` then ``comprehend`` after."""
    from seismo.collectors.pypi import PyPICollector
    from seismo.collectors.runner import persist_drafts
    from seismo.collectors.targets import select_unenriched_targets
    from seismo.db import session_scope

    with record_pipeline_run("enrich-pypi"):
        with session_scope() as session:
            targets = select_unenriched_targets(session, "pypi", "pypi_metadata", limit=limit)
        drafts = PyPICollector().metadata(targets)
        with session_scope() as session:
            new = persist_drafts(session, drafts)
        typer.echo(
            f"[enrich-pypi] {len(targets)} packages → {len(drafts)} metadata events, {new} new "
            f"(run `seismo resolve` then `seismo comprehend` to card them)"
        )


@app.command(name="enrich-hn")
def enrich_hn(
    min_points: int = typer.Option(100, help="Only enrich stories at/above this HN score."),
    limit: int = typer.Option(None, help="Cap the number of discussions to fetch (rate budget)."),
) -> None:
    """Enrichment (Wave-3) — fetch the *discussion* under each entity's high-signal HN story (the
    comments where people explain what a thing is) as an ``hn_discussion`` event, so cards reflect
    what the community actually said. Run ``resolve`` then ``comprehend`` after."""
    from seismo.collectors.launches import HnDiscussionEnricher, select_hn_targets
    from seismo.collectors.runner import persist_drafts
    from seismo.db import session_scope

    with record_pipeline_run("enrich-hn"):
        with session_scope() as session:
            targets = select_hn_targets(session, min_points=min_points, limit=limit)
        drafts = HnDiscussionEnricher().fetch(targets)
        with session_scope() as session:
            new = persist_drafts(session, drafts)
        typer.echo(
            f"[enrich-hn] {len(targets)} stories → {len(drafts)} discussions, {new} new events "
            f"(run `seismo resolve` then `seismo comprehend` to card them)"
        )


@app.command(name="enrich-wikidata")
def enrich_wikidata(
    limit: int = typer.Option(200, help="Cap the number of entities to enrich (rate budget)."),
) -> None:
    """Team enrichment (WIKIDATA_ENRICHMENT_PLAN.md) — resolve person/org entities to Wikidata
    items and record their claims (employer history, founders) as ``wikidata_entity`` events.
    Guarded matching: ambiguous names are skipped, never guessed. Targets only still-un-enriched
    entities, so daily runs steadily complete coverage. Run ``resolve`` (attaches the events,
    mints new orgs) then ``derive-edges`` (mints employed_by/formerly_at/founded edges) after."""
    from seismo.collectors.runner import persist_drafts
    from seismo.collectors.wikidata import (
        WikidataClient,
        enrich_targets,
        hf_org_display_name,
        select_targets,
    )
    from seismo.db import session_scope

    with record_pipeline_run("enrich-wikidata"):
        with session_scope() as session:
            targets = select_targets(session, limit=limit)
        # Fetch outside any open transaction (2-3 rate-limited calls per target adds up).
        result = enrich_targets(
            WikidataClient(), targets, org_name_lookup=hf_org_display_name
        )
        with session_scope() as session:
            new = persist_drafts(session, result.drafts)
        typer.echo(
            f"[enrich-wikidata] {len(targets)} targets → {len(result.drafts)} resolved, "
            f"{result.skipped} skipped, {new} new events "
            f"(run `seismo resolve` then `seismo derive-edges` to mint team edges)"
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


@app.command()
def triage(
    limit: int = typer.Option(None, help="Cap the number of candidates this run (cost budget)."),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Compute stats without writing decisions or changing tiers."
    ),
) -> None:
    """Layer 2 — continuous discovery triage (Feature 6). Runs AFTER ``resolve`` and BEFORE
    ``track``: decides which freshly-minted discovery entities are worth tracking and archives the
    rest (flips ``tracking_tier`` active → archived), so ``track``/enrichment only spend on
    substantive entities. Escalates to the LLM (``complete_triage``) when configured, else falls
    back to a deterministic stars/downloads threshold. Pure + no network; idempotent per entity."""
    from seismo.db import session_scope
    from seismo.identity.triage import run_triage

    with record_pipeline_run("triage"):
        with session_scope() as session:
            stats = run_triage(session, limit=limit, dry_run=dry_run)
        typer.echo(
            f"[triage] {stats.candidates} candidates → track={stats.tracked} "
            f"skip={stats.skipped} (ai={stats.by_ai} threshold={stats.by_threshold})"
        )


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


@app.command(name="explain-graphs")
def explain_graphs(
    limit: int = typer.Option(10, help="Top trending entities to (re)narrate this run."),
    entity_id: int = typer.Option(None, help="Explain ONE entity's subgraph (bypasses ranking)."),
    force: bool = typer.Option(
        False, "--force", help="Regenerate even if the subgraph is unchanged."
    ),
) -> None:
    """AI-narrated graph context (graph_explanations) — who the people in an entity's
    relationship graph are, why each org appears, what the team pedigree signals. Regenerates
    ONLY entities whose subgraph changed since the stored narration (hash check), so daily runs
    are near-free once coverage exists. Provider: ``SEISMO_GRAPH_EXPLAIN_PROVIDER``
    (claude_cli recommended — narrative synthesis needs a stronger model than the $0 cards)."""
    from seismo.db import session_scope
    from seismo.graph.explain import explain_entity, run_explain

    with record_pipeline_run("explain-graphs"):
        with session_scope() as session:
            if entity_id is not None:
                outcome, cost = explain_entity(session, entity_id, force=force)
                typer.echo(f"[explain-graphs] entity={entity_id} — {outcome} (${cost:.4f})")
                return
            stats = run_explain(session, limit=limit, force=force)
        typer.echo(f"[explain-graphs] {stats.as_note()}")


@app.command(name="derive-edges")
def derive_edges_cmd(as_of: str = typer.Option(None, help="ISO date; default now.")) -> None:
    """Layer 2 — typed entity-graph edges (Feature 1). Pure + as-of correct: derives ``built_by`` /
    ``cited`` / ``depends_on`` edges from already-collected contributors/README/PyPI evidence. No
    network. Run after ``resolve`` (so merges are settled) and the relevant ``enrich-*`` steps."""
    from seismo.db import session_scope
    from seismo.graph.edges import derive_edges

    when = _parse_as_of(as_of)
    with record_pipeline_run("derive-edges", when):
        with session_scope() as session:
            stats = derive_edges(session, when)
        typer.echo(f"[derive-edges] as_of={when.date()} — {stats.as_note()}")


@app.command()
def comprehend(
    as_of: str = typer.Option(None, help="ISO date; default now."),
    entity: int = typer.Option(None, help="Force a card for one entity id (skips the trigger)."),
    limit: int = typer.Option(None, help="Cap candidates this run (cost control)."),
    backlog: bool = typer.Option(
        False, "--backlog", help="Card uncarded entities that already have collected content "
        "(abstracts / READMEs / discussions), regardless of momentum — clears the arXiv/HF backlog."
    ),
) -> None:
    """Layer 3 — comprehension checkpoint 1 (doc 05). Provider pluggable; dev/CI = mock ($0)."""
    from seismo.checkpoints.comprehend import run_comprehend
    from seismo.db import session_scope

    when = _parse_as_of(as_of)
    with record_pipeline_run("comprehend", when):
        with session_scope() as session:
            stats = run_comprehend(session, when, entity_id=entity, limit=limit, backlog=backlog)
        typer.echo(
            f"[comprehend] provider={settings.llm_provider} as_of={when.date()} — {stats.as_note()}"
        )


@app.command()
def sanity(
    as_of: str = typer.Option(None, help="ISO date; default now."),
    limit: int = typer.Option(None, help="Cap candidates this run (cost control; default 500)."),
) -> None:
    """Content-sanity checkpoint — judges freshly-collected README/model-card/launch/discussion/
    abstract text for legibility and on-topic-ness (never mutates raw_events). Provider pluggable;
    dev/CI = mock ($0). Not a collector step (doc 03 §1: collectors record, they never interpret) —
    run this after collection/enrichment, e.g. in daily.sh."""
    from seismo.checkpoints.sanity import run_sanity
    from seismo.db import session_scope

    when = _parse_as_of(as_of)
    with record_pipeline_run("sanity", when):
        with session_scope() as session:
            stats = run_sanity(session, when, limit=limit)
        typer.echo(
            f"[sanity] provider={settings.llm_provider} as_of={when.date()} — {stats.as_note()}"
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
def waves(
    as_of: str = typer.Option(None, help="ISO date; default now."),
    skip_observers: bool = typer.Option(False, help="Detect only; skip the early-mention search."),
    skip_outcomes: bool = typer.Option(False, help="Detect only; skip the took-hold scoring."),
) -> None:
    """Wave Radar (``WAVE_PLAN.md``) — detect several *independent* young entities entering the
    same problem space at once, then find who mentioned them earliest and whether it took hold.

    Deterministic and re-runnable: no LLM (invariant 4), and a wave keeps its id and ``first_seen``
    across runs so the record stays a record rather than churn."""
    from seismo.db import session_scope
    from seismo.waves import run_observers, run_outcomes, run_waves

    at = _parse_as_of(as_of)
    with record_pipeline_run("waves", at):
        with session_scope() as session:
            stats = run_waves(session, at)
        typer.echo(f"[waves] {stats.as_note()}")
        if not skip_observers:
            with session_scope() as session:
                obs = run_observers(session, at)
            typer.echo(f"[waves] observers: {obs['observations']} over {obs['waves']} waves")
        if not skip_outcomes:
            with session_scope() as session:
                out = run_outcomes(session, at)
            typer.echo(f"[waves] outcomes: {out['outcomes']} rows over {out['waves']} waves")


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
def council(
    top_n: int = typer.Option(
        10, "--top", help="Review the top N entities by momentum (velocity percentile)."
    ),
    entity_id: int = typer.Option(None, help="Force a council review for one entity."),
    as_of: str = typer.Option(None, help="ISO date; default now."),
) -> None:
    """Layer 6b — council review (doc 08 §5). Three independent LLM perspectives (skeptic,
    evidence auditor, mechanism reviewer) each deliberate separately on an entity's impact brief,
    drafting one first if needed. Ranked by momentum, independent of the weekly significance
    gate's own budget. Three calls per brief — expensive by design, so it is never run from
    ``daily.sh``; invoke explicitly for a small top-N watchlist."""
    from seismo.checkpoints.council import run_council
    from seismo.db import session_scope

    when = _parse_as_of(as_of)
    with record_pipeline_run("council", when):
        with session_scope() as session:
            stats = run_council(session, when, top_n=top_n, entity_id=entity_id)
        typer.echo(
            f"[council] provider={settings.llm_provider} as_of={when.date()} — {stats.as_note()}"
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
            mark = (
                typer.style("PASS", fg=typer.colors.GREEN)
                if r.passed
                else typer.style("FAIL", fg=typer.colors.RED)
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


@app.command(name="community-research")
def community_research(
    source: str = typer.Option(
        "all",
        help="github | hf | hn | summary (AI cross-source verdict) | all (collect then summarize).",
    ),
    as_of: str = typer.Option(None, help="ISO date; default now."),
    limit: int = typer.Option(None, help="Max entities to research this run."),
    entity_id: int = typer.Option(None, help="Research one entity for debugging."),
    force: bool = typer.Option(False, "--force", help="Ignore refresh cadence."),
    redo_before: str = typer.Option(
        None,
        "--redo-before",
        help=(
            "summary only: re-summarize entities whose newest verdict predates this ISO "
            "timestamp. Use this (not --force) to redo the backlog in --limit batches — it "
            "terminates, and keeps the append-only verdict history."
        ),
    ),
    concurrency: int = typer.Option(
        1, "--concurrency", help="summary only: parallel LLM calls (the loop is network-bound)."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Print selected targets and queries; do not call any source."
    ),
    no_summarize: bool = typer.Option(
        False, "--no-summarize", help="Search/fetch only; skip comment fetch for API testing."
    ),
) -> None:
    """Community enrichment (doc 15): find what the community says about existing entities.

    Sources are GitHub (issues + discussions), Hugging Face (model discussions), and Hacker News
    (relevance search). Each is researched independently on its own per-source cadence; ``all``
    runs every source. This never re-collects what the item collectors already gather."""
    from seismo.community.runner import run_community_research
    from seismo.community.sources import SUMMARY_STEP, resolve_sources
    from seismo.community.verdict import FORCE_LIMIT_ERROR, run_community_synthesis
    from seismo.db import session_scope

    when = _parse_as_of(as_of)
    redo_cutoff = _parse_as_of(redo_before) if redo_before else None
    unsafe_force = force and limit is not None and entity_id is None
    if unsafe_force and SUMMARY_STEP in resolve_sources(source):
        raise typer.BadParameter(FORCE_LIMIT_ERROR)
    for src in resolve_sources(source):
        with record_pipeline_run(f"community-research:{src}", when):
            # The cross-source verdict reads what the collectors wrote; it has no external client.
            if src == SUMMARY_STEP:
                if dry_run:
                    typer.echo("[community-research] source=summary dry_run=true (no synthesis)")
                    continue
                with session_scope() as session:
                    sstats = run_community_synthesis(
                        session,
                        as_of=when,
                        limit=limit,
                        entity_id=entity_id,
                        force=force,
                        redo_before=redo_cutoff,
                        concurrency=concurrency,
                        # The paid path finally respects the configured ceiling (it never did).
                        budget_usd=settings.llm_budget_usd,
                        checkpoint=True,  # long paid run: keep what we already paid for
                    )
                typer.echo(
                    f"[community-research] source=summary as_of={when.date()} — {sstats.as_note()}"
                )
                continue
            with session_scope() as session:
                stats = run_community_research(
                    session,
                    source=src,
                    as_of=when,
                    limit=limit,
                    entity_id=entity_id,
                    force=force,
                    dry_run=dry_run,
                    no_summarize=no_summarize,
                )
            typer.echo(
                f"[community-research] source={src} as_of={when.date()} — {stats.as_note()}"
            )
            if dry_run and stats.dry_targets:
                for target, queries in stats.dry_targets[:20]:
                    typer.echo(f"  {target.entity_id} {target.canonical_name} ({target.state})")
                    for query in queries:
                        typer.echo(f"    - {query}")


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
