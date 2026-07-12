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
- **Hugging Face** — an org-scoped fetch (``?author=<org>``); each model's ``createdAt`` places its
  birth in history, giving the identity ref + the ``usable_artifact`` maturity rung. Models created
  after the case window are dropped (no future leak).

Documented gaps (doc 11 §1): Wayback pricing, PyPI-BQ.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from seismo.collectors.arxiv import ArxivCollector
from seismo.collectors.base import BaseCollector, RawEventDraft, TrackTarget, Window
from seismo.collectors.github import GitHubCollector
from seismo.collectors.hf import HuggingFaceCollector
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


def load_hf(
    session: Session,
    orgs: list[str],
    window: Window,
    *,
    collector: HuggingFaceCollector | None = None,
) -> int:
    """Load the case orgs' HF models by author, dropping any created after the case window.

    A seed may be a bare author (``mattshumer``) or a full model id (``mattshumer/Reflection-...``);
    either way we fetch by *author* (the part before ``/``), which returns the whole org incl. the
    named model. A model born after ``window.until`` would be a future leak into the replay, so it
    is excluded (createdAt-scoped); everything at/before the window keeps its real birth date."""
    if not orgs:
        return 0
    authors = list(dict.fromkeys(o.split("/", 1)[0] for o in orgs))  # de-dup, order-preserving
    col = collector or HuggingFaceCollector()
    drafts = [d for d in col.fetch_by_author(authors) if d.occurred_at < window.until]
    return persist_drafts(session, _as_backfill(drafts))


def load_github_readmes(
    session: Session,
    github_seeds: list[str],
    window: Window,
    *,
    collector: GitHubCollector | None = None,
) -> int:
    """Fetch the seed repos' READMEs so identity can unify them (doc 04 R1).

    The GH Archive backfill only carries stars + a bare ``repo_discovered`` (no description /
    homepage / README), so a repo seeded for a hindcast is an identity *island* — nothing links it
    to the paper or model. Its README, though, cites the arXiv id (e.g. DeepSeek-V2's README →
    ``2405.04434``), which ``references`` extracts as an R1 github→arxiv link, collapsing
    repo+paper+model into one entity. Only ``owner/repo`` seeds are fetched (an org handle has no
    README). One call per repo — cheap, unlike the star firehose.

    Crucially the fetched README event is **backdated to ``window.since``**: the live enrichment
    stamps ``occurred_at=now()`` (README text isn't an as-of metric, §16), but here that now-dated
    R1 merge would be invisible at a past hindcast as-of (``canonical_entity_id`` only follows
    merges ``justified_at <= as_of``). Dating it at the window start makes the identity link visible
    throughout the case — the arXiv citation was present from the repo's first day anyway."""
    repos = [s for s in github_seeds if "/" in s]
    if not repos:
        return 0
    col = collector or GitHubCollector()
    targets = [TrackTarget(entity_id=0, source="github", native_id=r) for r in repos]
    drafts = [
        d.model_copy(update={"occurred_at": window.since, "origin": "backfill"})
        for d in col.readmes(targets, window)
    ]
    return persist_drafts(session, drafts)
