"""Case-scoped historical loaders for the hindcast harness (doc 11 §1).

Each loader is idempotent and window/seed-scoped: it fetches only what a case needs and writes
ordinary ``raw_events`` rows the replay then treats exactly like live events (DR-11.1). Rows are
stamped ``origin='backfill'`` so a future ``--reload`` can scope-wipe just this case's history.

Coverage today:
- **GitHub** — the GH Archive star firehose (HEAVY; see ``collectors.backfill_gharchive``).
- **Hacker News** — the Algolia API is natively historical, so the live collector *is* the loader:
  we point its ``discover`` at the case window. This is the attention signal a flop like
  Reflection-70B rides on.
- **arXiv** — a targeted fetch of the case's seed paper ids (``discover`` can't page to a past
  window, but a case pins exact ids).

Documented gaps (doc 11 §1): Hugging Face (``createdAt`` + downloads), Wayback pricing, PyPI-BQ.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from seismo.collectors.arxiv import ArxivCollector
from seismo.collectors.base import BaseCollector, RawEventDraft, Window
from seismo.collectors.hn import HackerNewsCollector
from seismo.collectors.runner import persist_drafts


def _as_backfill(drafts: list[RawEventDraft]) -> list[RawEventDraft]:
    """Mark loaded events as backfill; the natural key is unchanged, so persist stays idempotent."""
    return [d.model_copy(update={"origin": "backfill"}) for d in drafts]


def load_hn(session: Session, window: Window, *, collector: BaseCollector | None = None) -> int:
    """Load historical Hacker News stories over the case window (Algolia is natively historical).

    ``collector`` is injectable for tests; production builds a real :class:`HackerNewsCollector`."""
    col = collector or HackerNewsCollector()
    return persist_drafts(session, _as_backfill(col.discover(window)))


def load_arxiv(
    session: Session, arxiv_ids: list[str], *, collector: ArxivCollector | None = None
) -> int:
    """Load the case's seed arXiv papers by id (targeted fetch — see ArxivCollector.fetch_ids)."""
    if not arxiv_ids:
        return 0
    col = collector or ArxivCollector()
    return persist_drafts(session, _as_backfill(col.fetch_ids(arxiv_ids)))
