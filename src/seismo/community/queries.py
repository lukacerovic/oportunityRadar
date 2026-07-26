"""Anchor-based query generation for community research.

Produces the audit trail of *what we searched for* (persisted as ``query_set``) and the search
terms the text-search sources (Hacker News) actually issue. On-project sources (GitHub, Hugging
Face) list an entity's own channel directly and ignore these queries.
"""

from __future__ import annotations

import re

from seismo.community.targets import CommunityTarget

_SPACE_RE = re.compile(r"\s+")


def generate_queries(target: CommunityTarget, *, limit: int = 5) -> list[str]:
    queries: list[str] = []
    anchors = target.anchors

    gh = anchors.get("github")
    if gh:
        repo = gh.split("/")[-1]
        owner = gh.split("/")[0] if "/" in gh else target.owner
        _add(queries, f'"{gh}"')
        if owner and repo:
            _add(queries, f'"{repo}" "{owner}"')
        if repo:
            _add(queries, f'"{repo}" github')

    arxiv = anchors.get("arxiv")
    if arxiv:
        _add(queries, f'"arXiv:{arxiv}"')
        _add(queries, f'"{arxiv}"')

    hf = anchors.get("hf")
    if hf:
        model = hf.split("/")[-1]
        _add(queries, f'"{hf}"')
        _add(queries, f'"{model}" "Hugging Face"')

    web = anchors.get("web")
    if web:
        _add(queries, f'"{web}"')

    name = _clean(target.canonical_name)
    if name:
        _add(queries, f'"{name}"')
        keyword = _context_keyword(target)
        if keyword:
            _add(queries, f'"{name}" "{keyword}"')

    return queries[:limit]


def _add(queries: list[str], query: str) -> None:
    query = _clean(query)
    if query and query not in queries:
        queries.append(query)


def _clean(value: str) -> str:
    return _SPACE_RE.sub(" ", value).strip()


def _context_keyword(target: CommunityTarget) -> str | None:
    for value in (
        target.category,
        target.entity_type,
        (target.card or {}).get("maturity_stage") if target.card else None,
    ):
        if value:
            return str(value).replace("-", " ")
    return None

