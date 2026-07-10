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
    source: str = typer.Option("all", help="Source key, or 'all'."),
    window: str = typer.Option("1d", help="Collection window."),
) -> None:
    """Layer 1 — record raw events (doc 03)."""
    with record_pipeline_run(f"collect:{source}"):
        typer.echo(f"[collect] source={source} window={window} — not implemented yet")


@app.command()
def resolve(cold_start: bool = typer.Option(False, "--cold-start")) -> None:
    """Layer 2 — entity resolution + merge queue (doc 04)."""
    with record_pipeline_run("resolve"):
        typer.echo(f"[resolve] cold_start={cold_start} — not implemented yet")


@app.command()
def snapshot() -> None:
    """Layer 4 — entity_metrics_daily (doc 06)."""
    _stub("snapshot", _parse_as_of(None))


@app.command()
def score(as_of: str = typer.Option(None, help="ISO date; default now.")) -> None:
    """Layer 4 — trajectory + momentum states (doc 06)."""
    _stub("score", _parse_as_of(as_of))


@app.command()
def comprehend() -> None:
    """Layer 3 — comprehension checkpoint (doc 05)."""
    _stub("comprehend", _parse_as_of(None))


@app.command()
def gate(week: str = typer.Option(None, help="ISO week, e.g. 2026-W28.")) -> None:
    """Layer 5 — significance gate (doc 07)."""
    with record_pipeline_run("gate"):
        typer.echo(f"[gate] week={week} — not implemented yet")


@app.command()
def brief(entity_id: int = typer.Option(..., help="Entity to brief.")) -> None:
    """Layer 6 — impact checkpoint (doc 08)."""
    with record_pipeline_run(f"brief:{entity_id}"):
        typer.echo(f"[brief] entity_id={entity_id} — not implemented yet")


@app.command()
def hindcast(case: str = typer.Option(..., help="Case name, e.g. deepseek.")) -> None:
    """Validation harness (doc 11)."""
    with record_pipeline_run(f"hindcast:{case}"):
        typer.echo(f"[hindcast] case={case} — not implemented yet")


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
