"""Collector registry + source groups matching the scheduling matrix (doc 03 §3)."""

from __future__ import annotations

from collections.abc import Callable

from seismo.collectors.arxiv import ArxivCollector
from seismo.collectors.base import BaseCollector
from seismo.collectors.github import GitHubCollector
from seismo.collectors.hf import HuggingFaceCollector
from seismo.collectors.hn import HackerNewsCollector

# Factories so a collector (and its HTTP client) is built only when actually run.
FACTORIES: dict[str, Callable[[], BaseCollector]] = {
    "github": GitHubCollector,
    "hn": HackerNewsCollector,
    "arxiv": ArxivCollector,
    "hf": HuggingFaceCollector,
}

# Timer groups (doc 03 §3). ``hf`` is the 4th evidence type (usage, A-5); it joins ``all`` but not
# the ``fast`` daily group — its live discovery is broader/noisier, run it on its own cadence.
# The pricing watcher (5th type) lands next.
GROUPS: dict[str, list[str]] = {
    "fast": ["github", "hn", "arxiv"],
    "all": ["github", "hn", "arxiv", "hf"],
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
