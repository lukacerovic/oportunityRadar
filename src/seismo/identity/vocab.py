"""Category + theme vocabularies (doc 04 §5), loaded from the versioned YAML in ``seed/``.

Category is the computational key (cohorts, reach); theme is the narrative cluster. Assignment
of a category is deterministic keyword matching (:func:`assign_category`) over an entity's text;
theme defaults from the category's ``theme:`` mapping. Both vocabularies are cached — they are
small and change only via a git edit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

_SEED_DIR = Path(__file__).resolve().parents[3] / "seed"
UNCATEGORIZED = "uncategorized"


@dataclass(frozen=True)
class Category:
    slug: str
    keywords: tuple[str, ...]
    theme: str
    matchers: tuple[re.Pattern[str], ...]


@dataclass(frozen=True)
class Theme:
    name: str
    description: str


@lru_cache(maxsize=1)
def themes() -> dict[str, Theme]:
    raw = yaml.safe_load((_SEED_DIR / "themes.yaml").read_text()) or []
    return {t["name"]: Theme(t["name"], t.get("description", "")) for t in raw}


@lru_cache(maxsize=1)
def categories() -> tuple[Category, ...]:
    """Load categories in file order (order = assignment priority). Validates theme references."""
    raw = yaml.safe_load((_SEED_DIR / "categories.yaml").read_text()) or []
    known_themes = set(themes())
    out: list[Category] = []
    for c in raw:
        theme = c["theme"]
        if theme not in known_themes:
            raise ValueError(f"category {c['slug']!r} references unknown theme {theme!r}")
        kws = tuple(c.get("keywords") or [])
        # Word-boundary, case-insensitive; optional trailing 's' so a keyword also matches its
        # plural ('ai agent' -> 'ai agents'). Boundaries still keep 'rag' out of 'storage'.
        matchers = tuple(re.compile(rf"\b{re.escape(k)}s?\b", re.IGNORECASE) for k in kws)
        out.append(Category(c["slug"], kws, theme, matchers))
    slugs = [c.slug for c in out]
    if len(slugs) != len(set(slugs)):
        raise ValueError("duplicate category slug in seed/categories.yaml")
    return tuple(out)


@lru_cache(maxsize=1)
def _category_index() -> dict[str, Category]:
    return {c.slug: c for c in categories()}


def theme_for_category(slug: str) -> str:
    cat = _category_index().get(slug)
    return cat.theme if cat else UNCATEGORIZED


def assign_category(text: str) -> str:
    """Deterministic category from free text (README/abstract/card). First keyword hit in file
    priority order wins; falls back to ``uncategorized`` when nothing matches (doc 04 §5)."""
    if not text:
        return UNCATEGORIZED
    for cat in categories():
        if any(m.search(text) for m in cat.matchers):
            return cat.slug
    return UNCATEGORIZED


def category_slugs() -> tuple[str, ...]:
    """All controlled category slugs plus ``uncategorized`` — the allowed set for the LLM card's
    ``category`` field (doc 05 §1). Sorted for a stable JSON-schema enum."""
    return tuple(sorted({c.slug for c in categories()} | {UNCATEGORIZED}))
