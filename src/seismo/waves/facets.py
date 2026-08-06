"""Facets over waves — theme, outcome, lead time.

A wave is **not** nested under a category, and this module exists to keep it that way. The known
convergence spanned ``agent-framework`` and ``rag-framework``, which map to two different themes in
``seed/categories.yaml``. Browsing a category tree and descending into it would have shown four of
the six members under "agent tooling" and the other two somewhere else — the finding would be cut in
half by the navigation itself.

So category and theme are **filters applied to whole waves**, never parents of them. A wave matches
a theme when *any* member's category maps to it, which means one wave legitimately appears under two
themes. That is correct, not a duplicate.

The vocabulary in ``seed/`` stays the single source of truth: themes are derived through
``vocab.theme_for_category`` at read time rather than denormalized onto the wave, so re-categorizing
an entity or editing the vocabulary takes effect without a migration or a re-run.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from seismo.identity.vocab import categories, theme_for_category


def categories_for_theme(theme: str) -> list[str]:
    """Every category slug that maps to ``theme``. Empty list = unknown theme, which callers must
    treat as "match nothing" rather than "match everything" — silently ignoring a bad filter would
    show the user a full list they believe is filtered."""
    wanted = theme.strip().lower()
    return sorted(c.slug for c in categories() if c.theme.lower() == wanted)


def themes_for_categories(cats: list[str | None]) -> list[str]:
    """The distinct themes a wave touches, given its members' categories."""
    out = {theme_for_category(c) for c in cats if c}
    return sorted(out)


def wave_themes(session: Session, wave_ids: list[int]) -> dict[int, list[str]]:
    """wave_id -> the themes its members touch. One query for a page of waves, not one per wave."""
    if not wave_ids:
        return {}
    rows = session.execute(
        text(
            """
            SELECT wm.wave_id, e.category
            FROM wave_members wm JOIN entities e ON e.id = wm.entity_id
            WHERE wm.wave_id = ANY(:ids) AND e.category IS NOT NULL
            """
        ),
        {"ids": wave_ids},
    ).all()
    by_wave: dict[int, list[str | None]] = {}
    for wave_id, category in rows:
        by_wave.setdefault(int(wave_id), []).append(category)
    return {wid: themes_for_categories(cats) for wid, cats in by_wave.items()}
