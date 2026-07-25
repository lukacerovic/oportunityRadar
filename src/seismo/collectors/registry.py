"""Collector registry + source groups matching the scheduling matrix (doc 03 §3)."""

from __future__ import annotations

from collections.abc import Callable

from seismo.collectors.arxiv import ArxivCollector
from seismo.collectors.base import BaseCollector
from seismo.collectors.github import GitHubCollector
from seismo.collectors.hf import HuggingFaceCollector
from seismo.collectors.hn import HackerNewsCollector
from seismo.collectors.openrouter import OpenRouterCollector
from seismo.collectors.pypi import PyPICollector

# Factories so a collector (and its HTTP client) is built only when actually run.
FACTORIES: dict[str, Callable[[], BaseCollector]] = {
    "github": GitHubCollector,
    "hn": HackerNewsCollector,
    "arxiv": ArxivCollector,
    "hf": HuggingFaceCollector,
    "pypi": PyPICollector,
    "openrouter": OpenRouterCollector,
}

# Timer groups (doc 03 §3). ``hf`` is the 4th evidence type (usage, A-5); it joins ``all`` but not
# the ``fast`` daily group — its live discovery is broader/noisier, run it on its own cadence.
# ``pypi`` is track/enrich-only (its ``discover`` is empty), so ``fast`` buys nothing — it joins
# ``all`` alongside ``hf`` on the same rationale. The pricing watcher (5th type) lands next.
# ``openrouter`` is discover-only market evidence on the same daily cadence as hf/pypi — its
# rankings points land weekly, so ``fast`` buys nothing.
GROUPS: dict[str, list[str]] = {
    "fast": ["github", "hn", "arxiv"],
    "all": ["github", "hn", "arxiv", "hf", "pypi", "openrouter"],
}


def build(source: str) -> BaseCollector:
    if source not in FACTORIES:
        raise KeyError(f"unknown source {source!r}; known: {sorted(FACTORIES)}")
    return FACTORIES[source]()


def resolve_sources(selector: str) -> list[str]:
    """Map a CLI selector ('all', a group name, or a single source) to source keys."""
    if selector in GROUPS:
        return GROUPS[selector]
    if selector in FACTORIES:
        return [selector]
    raise KeyError(f"unknown source/group {selector!r}")
