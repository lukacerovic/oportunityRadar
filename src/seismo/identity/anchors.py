"""Native anchors and cross-registry references extracted from raw-event payloads (doc 04 §2–3).

Two pure jobs, no DB:
- :func:`primary_anchor` — the registry object an event *is about* (github repo, arXiv paper,
  the URL an HN story points at). This drives event->entity attachment.
- :func:`references` — canonical URLs / declared IDs an event's payload *mentions* that point at
  a different registry. These drive the high-precision link rules R1–R3.

Collectors never interpret (invariant 4); all of this interpretation lives here, downstream.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

# Registries we can anchor. hf/pypi/npm land with Wave-2 collectors but the parsers are ready.
Registry = str


@dataclass(frozen=True)
class Anchor:
    """A stable identity for one registry object. ``key`` is the dedupe/lookup key."""

    registry: Registry
    native_id: str
    entity_type: str
    display_name: str

    @property
    def key(self) -> str:
        return f"{self.registry}:{self.native_id}"


@dataclass(frozen=True)
class Reference:
    """An outbound pointer from one entity's evidence to another registry's anchor."""

    anchor_key: str
    rule: str  # R1 | R2 | R3
    evidence: str  # human-readable snippet for the merge-queue UI / audit


_ENTITY_TYPE = {
    "github": "project",
    "pypi": "project",
    "npm": "project",
    "arxiv": "paper",
    "hf": "model",
    "web": "product",  # name-anchored launch with no tracked registry (doc 04 §2, Wave-3)
}

# A registry-less HN launch at or above this score is promoted to a first-class ``web`` entity
# instead of being dropped as unowned context — otherwise a self-hosted model like Kimi (whose
# launch links only to kimi.com) stays invisible despite a 641-point front-page story.
_HN_LAUNCH_FLOOR = 100

# Drop the "Show HN:" / "Launch HN:" framing before reading the product name; skip Ask/Tell HN,
# which are discussions, not launches.
_HN_SHOW_PREFIX = re.compile(r"^\s*(?:show|launch)\s+hn\s*:\s*", re.IGNORECASE)
_HN_ASK_PREFIX = re.compile(r"^\s*(?:ask|tell)\s+hn\b", re.IGNORECASE)
# A launch/release signal is what separates a product announcement ("Kimi K3 is now live") from a
# random popular opinion/news post ("The Singularity will occur"). Promotion requires one — or a
# Show/Launch HN framing — so we don't mint an entity for every short-titled front-page story.
_HN_LAUNCH_SIGNAL = re.compile(
    r"\b(?:launch\w*|releas\w*|announc\w*|introduc\w*|unveil\w*|debut\w*|"
    r"is\s+(?:now\s+)?(?:live|out|here|available)|now\s+available|"
    r"go(?:es)?\s+(?:live|ga)|general\s+availability|ships?|shipped|open[-\s]?sourc\w*)\b",
    re.IGNORECASE,
)
# The product name is the head phrase before the predicate begins — a verb, a preposition, or a
# delimiter.
_HN_NAME_CUT = re.compile(
    r"\s+(?:is|are|was|were|now|by|for|with|to|from|in|on|"
    r"launch\w*|releas\w*|announc\w*|introduc\w*|unveil\w*|debut\w*|"
    r"available|live|out|ships?|shipped|hits?|reaches?|passes?|tops?|beats?|"
    r"surpass\w*|goes?|gets?|becomes?|adds?|supports?)\b",
    re.IGNORECASE,
)


def _launch_name(title: str) -> str | None:
    """Best-effort product/launch name from an HN story title, or ``None`` if it doesn't read like
    a named launch (so we don't mint junk entities from opinion/question/news posts)."""
    if not title or _HN_ASK_PREFIX.search(title):
        return None
    has_show = bool(_HN_SHOW_PREFIX.search(title))
    t = _HN_SHOW_PREFIX.sub("", title).strip()
    # A launch needs an explicit Show/Launch HN framing or a release-signal verb in the title.
    if not has_show and not _HN_LAUNCH_SIGNAL.search(t):
        return None
    # Cut at the first delimiter (":", "-", "–", "—", ",", "?", "(") or predicate word.
    for delim in (":", " - ", " – ", " — ", ",", "?", "("):
        idx = t.find(delim)
        if idx > 0:
            t = t[:idx]
    m = _HN_NAME_CUT.search(t)
    head = (t[: m.start()] if m else t).strip(" -–—:,")
    words = head.split()
    # Require a short, name-like head: 1–4 tokens. Longer heads are sentences, not product names.
    if not words or len(words) > 4:
        return None
    slug = re.sub(r"[^a-z0-9]+", "-", head.lower()).strip("-")
    return head if slug else None


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")

# arXiv ids: 2405.04434 (new scheme) or math.GT/0309136 (old). Version suffix stripped.
_ARXIV_ID = re.compile(r"\b(\d{4}\.\d{4,5})(v\d+)?\b")
_GITHUB_URL = re.compile(r"github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)", re.IGNORECASE)


def _norm_repo(full_name: str) -> str:
    """Canonical github native id: lowercase 'owner/repo', trailing '.git'/slash stripped."""
    return full_name.strip().strip("/").removesuffix(".git").lower()


def anchor_from_url(url: str) -> Anchor | None:
    """Parse a single URL into an :class:`Anchor`, or ``None`` if it isn't a known registry."""
    if not url:
        return None
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    path = urlparse(url).path.strip("/")
    if host.endswith("github.com"):
        parts = path.split("/")
        if len(parts) >= 2 and parts[0] and parts[1]:
            repo = _norm_repo(f"{parts[0]}/{parts[1]}")
            return Anchor("github", repo, "project", repo)
    elif host.endswith("arxiv.org"):
        m = _ARXIV_ID.search(path)
        if m:
            return Anchor("arxiv", m.group(1), "paper", m.group(1))
    elif host.endswith("huggingface.co"):
        parts = path.split("/")
        # Skip HF route prefixes so /models/org/name and /org/name both resolve.
        if parts and parts[0] in {"models", "datasets", "spaces"}:
            parts = parts[1:]
        if len(parts) >= 2 and parts[0] and parts[1]:
            mid = f"{parts[0]}/{parts[1]}".lower()
            return Anchor("hf", mid, "model", mid)
    elif host.endswith("pypi.org"):
        parts = path.split("/")
        if len(parts) >= 2 and parts[0] == "project" and parts[1]:
            return Anchor("pypi", parts[1].lower(), "project", parts[1].lower())
    elif host.endswith("npmjs.com"):
        parts = path.split("/")
        if parts and parts[0] == "package" and len(parts) >= 2:
            name = "/".join(parts[1:]).lower()
            return Anchor("npm", name, "project", name)
    return None


def primary_anchor(source: str, event_type: str, payload: dict[str, Any]) -> Anchor | None:
    """The registry object this event is about — the entity it should attach to (doc 04 §2)."""
    if source == "github":
        full = payload.get("full_name") or payload.get("repo")
        if full:
            repo = _norm_repo(str(full))
            owner = repo.split("/", 1)[0]
            # A repo whose "owner/name" is really just an org handle (backfill org events) is
            # still a project anchor; the org entity is a separate concern (doc 04 §6.4).
            return Anchor("github", repo, "project", repo if "/" in repo else owner)
        return None
    if source == "arxiv":
        aid = payload.get("arxiv_id")
        if aid:
            title = payload.get("title") or str(aid)
            return Anchor("arxiv", str(aid), "paper", str(title))
        return None
    if source == "hf":
        mid = payload.get("id") or payload.get("modelId")
        if mid:
            return Anchor("hf", str(mid).lower(), "model", str(mid))
        return None
    if source in {"pypi", "npm"}:
        name = payload.get("name")
        if name:
            return Anchor(source, str(name).lower(), "project", str(name))
        return None
    if source == "web":
        # A launch_page enrichment event carries the web slug of the entity it belongs to.
        slug = payload.get("slug")
        if slug:
            return Anchor("web", str(slug), "product", payload.get("name") or str(slug))
        return None
    if source == "enrich":
        # Generic enrichment (e.g. hn_discussion): the event carries the explicit anchor of the
        # entity it belongs to, so deep content attaches precisely regardless of registry.
        a = payload.get("anchor") or {}
        reg, nid = a.get("registry"), a.get("native_id")
        if reg and nid:
            etype = _ENTITY_TYPE.get(reg, "product")
            return Anchor(reg, str(nid), etype, payload.get("name") or str(nid))
        return None
    if source == "openrouter":
        # OpenRouter evidence belongs to the *model's* entity, not a registry of its own: the
        # payload's hugging_face_id routes to the HF entity; a proprietary model (no HF id) routes
        # via its display name to the same ``web`` product anchor an HN launch mints — "MoonshotAI:
        # Kimi K3" lands on ``web:kimi-k3``. A delisted rankings slug with neither stays unowned.
        hf_id = payload.get("hugging_face_id")
        if hf_id:
            return Anchor("hf", str(hf_id).lower(), "model", str(hf_id))
        name = payload.get("name")
        if name:
            # Strip the "Provider: " prefix and the "(free)"-style variant suffix.
            base = str(name).split(": ", 1)[-1]
            base = re.sub(r"\s*\([^)]*\)\s*$", "", base).strip()
            slug = _slugify(base)
            if slug:
                return Anchor("web", slug, "product", base)
        return None
    if source == "hn":
        # An HN story attaches to the entity behind its linked URL, if any (doc 04 §2).
        url_anchor = anchor_from_url(payload.get("url") or "")
        if url_anchor is not None:
            return url_anchor
        # No tracked registry — but a high-signal launch still deserves an entity (Wave-3). Mint a
        # name-based ``web`` anchor so its stories collapse into one entity and a later registry
        # artifact of the same name (e.g. an HF model) can be queued to merge in.
        if (payload.get("points") or 0) >= _HN_LAUNCH_FLOOR:
            name = _launch_name(payload.get("title") or "")
            if name:
                return Anchor("web", _slugify(name), "product", name)
        return None
    if source == "seed":
        a = payload.get("anchor") or {}
        reg, nid = a.get("registry"), a.get("native_id")
        if reg and nid:
            etype = payload.get("entity_type") or _ENTITY_TYPE.get(reg, "project")
            nid_norm = _norm_repo(str(nid)) if reg == "github" else str(nid).lower()
            return Anchor(reg, nid_norm, etype, payload.get("name") or nid_norm)
        return None
    return None


def references(source: str, payload: dict[str, Any]) -> list[Reference]:
    """Cross-registry pointers found in an event's payload (the R1–R3 evidence)."""
    refs: list[Reference] = []
    seen: set[str] = set()

    def add(anchor: Anchor | None, rule: str, evidence: str) -> None:
        if anchor and anchor.key not in seen:
            seen.add(anchor.key)
            refs.append(Reference(anchor.key, rule, evidence[:200]))

    if source == "arxiv":
        # R2 declared-ID: the arXiv comment/summary carries the code URL (doc 03 §2.3, doc 04 R2).
        for field in ("comment", "summary"):
            text = payload.get(field) or ""
            for m in _GITHUB_URL.finditer(text):
                repo = _norm_repo(m.group(1))
                add(Anchor("github", repo, "project", repo), "R2", f"arxiv {field}: {m.group(0)}")

    elif source == "github":
        # R1 URL-exact: the repo's own metadata cites the paper / package canonical URL.
        homepage = payload.get("homepage") or ""
        desc = payload.get("description") or ""
        # ``readme`` is the legacy key; a ``repo_readme`` enrichment event (§16) carries the body
        # under ``text`` — read both so a README's arXiv citation links the repo to its paper.
        readme = payload.get("readme") or payload.get("text") or ""
        blob = f"{homepage}\n{desc}\n{readme}"
        for m in _ARXIV_ID.finditer(blob):
            aid = m.group(1)
            add(Anchor("arxiv", aid, "paper", aid), "R1", f"github cites arxiv:{aid}")
        hp_anchor = anchor_from_url(homepage)
        if hp_anchor and hp_anchor.registry in {"pypi", "npm", "hf"}:
            add(hp_anchor, "R1", f"github homepage: {homepage}")

    elif source == "hf":
        # R2 declared-ID: HF card `arxiv:` tag and repo/base_model links.
        for tag in payload.get("tags") or []:
            if isinstance(tag, str) and tag.startswith("arxiv:"):
                aid = tag.split("arxiv:", 1)[1].strip()
                add(Anchor("arxiv", aid, "paper", aid), "R2", f"hf tag {tag}")

    elif source in {"pypi", "npm"}:
        # R3 registry-metadata: project_urls homepage/repository -> github.
        urls = payload.get("project_urls") or {}
        for label, url in urls.items() if isinstance(urls, dict) else []:
            anchor = anchor_from_url(str(url))
            if anchor and anchor.registry == "github":
                add(anchor, "R3", f"{source} project_urls.{label}: {url}")

    return refs
