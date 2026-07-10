"""Pipeline-run bookkeeping — every stage records why it ran and whether it worked.

Implements global invariant 5 (doc 01 §1): every stage is auditable. Each stage subcommand
wraps its body in :func:`record_pipeline_run`, which writes a ``pipeline_runs`` row with
timing and outcome, even on failure.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from seismo.db import session_scope
from seismo.models import PipelineRun


@contextmanager
def record_pipeline_run(stage: str, as_of: datetime | None = None) -> Iterator[None]:
    started = datetime.now(UTC)
    ok = False
    notes: str | None = None
    try:
        yield
        ok = True
    except Exception as exc:  # record the failure, then re-raise
        notes = f"{type(exc).__name__}: {exc}"[:500]
        raise
    finally:
        with session_scope() as session:
            session.add(
                PipelineRun(
                    stage=stage,
                    as_of=as_of,
                    started_at=started,
                    finished_at=datetime.now(UTC),
                    ok=ok,
                    notes=notes,
                )
            )
