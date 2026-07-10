"""Name normalization — pure and load-bearing (doc 04 §3).

Every name-based link rule (R4–R6) compares *normalized* names, so this function's exact
behavior defines who is "the same thing" by name. Keep it pure, deterministic, and unit-tested;
a change here silently reshapes the merge queue. It never touches the DB.
"""

from __future__ import annotations

import re

# Suffixes that are noise for identity, not signal: packaging/repo conventions that the same
# project appends inconsistently across registries (langchain vs langchain-official vs …).
_DROP_SUFFIXES = (
    "-dev",
    "-official",
    "-project",
    "-python",
    "-py",
    "-js",
    "-ai",
    ".py",
    ".js",
    ".git",
)

# Keep alphanumerics and internal spaces; everything else (punctuation, emoji, symbols) is noise.
_KEEP = re.compile(r"[a-z0-9 ]+")
_WS = re.compile(r"\s+")


def normalize_name(name: str) -> str:
    """Lowercase, strip punctuation/emoji, drop packaging suffixes, collapse whitespace.

    Deterministic and idempotent: ``normalize_name(normalize_name(x)) == normalize_name(x)``.
    Returns ``""`` for input that is all noise (caller must treat empty as "no name match").
    """
    lowered = name.strip().lower()
    # Separators that commonly stand in for spaces become spaces before we drop punctuation,
    # so "deep_seek" and "deep-seek" and "deep seek" all normalize alike.
    lowered = lowered.replace("_", " ").replace("-", " ").replace("/", " ").replace(".", " ")
    kept = "".join(_KEEP.findall(lowered))
    collapsed = _WS.sub(" ", kept).strip()

    # Drop known suffixes iteratively (a name may carry more than one, e.g. "foo-py-dev").
    # Suffix matching uses the original-with-separators spelling, so we re-derive tokens.
    changed = True
    while changed:
        changed = False
        for suffix in _DROP_SUFFIXES:
            token = suffix.lstrip("-.").strip()
            if token and collapsed.endswith(" " + token):
                collapsed = collapsed[: -(len(token) + 1)].strip()
                changed = True
    return collapsed
