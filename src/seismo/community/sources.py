"""Registry of community-discussion sources.

Each client conforms to the ``CommunityClient`` protocol (``applies_to`` / ``fetch_threads`` /
``comments`` / ``close``). The runner asks the registry for a client by source name; the CLI's
``all`` fans out over :data:`ALL_SOURCES`. Adding a source (Lobsters, Product Hunt, …) is a new
module + one line here — nothing else changes.
"""

from __future__ import annotations

from typing import Protocol

from seismo.community.github import GitHubCommunityClient
from seismo.community.hackernews import HackerNewsCommunityClient
from seismo.community.huggingface import HuggingFaceCommunityClient
from seismo.community.relevance import CommunityThread
from seismo.community.targets import CommunityTarget

# Order = the order "all" runs them: highest-precision (on-project) first. The cross-source
# ``summary`` verdict runs last (it reads what the collectors just wrote) — see verdict.py.
ALL_SOURCES = ["github", "hf", "hn"]
SUMMARY_STEP = "summary"


class CommunityClient(Protocol):
    source: str

    def applies_to(self, target: CommunityTarget) -> bool: ...
    def fetch_threads(
        self, target: CommunityTarget, queries: list[str], *, limit: int
    ) -> list[CommunityThread]: ...
    def comments(self, thread: CommunityThread, *, limit: int) -> list[str]: ...
    def close(self) -> None: ...


_FACTORIES = {
    "github": GitHubCommunityClient,
    "hf": HuggingFaceCommunityClient,
    "hn": HackerNewsCommunityClient,
}


def make_client(source: str) -> CommunityClient:
    try:
        return _FACTORIES[source]()
    except KeyError:
        raise ValueError(
            f"unknown community source {source!r}; expected one of {sorted(_FACTORIES)} or 'all'"
        ) from None


def resolve_sources(source: str) -> list[str]:
    """Expand a CLI ``--source`` value into concrete steps. ``all`` collects every source then runs
    the cross-source ``summary`` verdict last. ``summary`` runs only the verdict synthesis."""
    if source == "all":
        return [*ALL_SOURCES, SUMMARY_STEP]
    if source == SUMMARY_STEP:
        return [SUMMARY_STEP]
    if source not in _FACTORIES:
        raise ValueError(
            f"unknown community source {source!r}; "
            f"expected one of {sorted(_FACTORIES)}, '{SUMMARY_STEP}', or 'all'"
        )
    return [source]
