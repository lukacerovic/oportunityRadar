"""Wikidata team enrichment (WIKIDATA_ENRICHMENT_PLAN.md) — who is behind what we track.

Two-hop design: hop 1 (names) already lives in our own data — arXiv author names, GitHub
contributor logins, HF org handles. This module is hop 2: resolve those names to Wikidata items
and record the items' claims as ``wikidata_entity`` raw events. Interpretation (minting orgs,
``employed_by``/``formerly_at``/``founded`` edges) happens downstream in ``derive-edges`` —
collectors record; they never interpret.

Three match paths, in order of trustworthiness:

- **P2037 (exact)** — Wikidata stores GitHub usernames as property P2037, so a person entity
  anchored ``github:user:<login>`` resolves deterministically via a ``haswbstatement`` search.
- **person search (guarded)** — ``wbsearchentities`` by author name. Accepted ONLY if the
  candidate is human (P31=Q5), its label matches the searched name, its description reads
  tech/research-adjacent, and exactly one candidate passes. Ambiguity ⇒ skip, never guess:
  a wrong "Mira Murati" edge costs more credibility than a missing one.
- **org search (guarded)** — same flow for HF org handles, with an org-class P31 accept-list.
  Orgs we don't track yet get their event anchored ``wikidata:<QID>`` so ``resolve`` mints the
  org entity; person events instead carry the person's EXISTING anchor (``person_name:*`` /
  ``github:user:*``) in the payload — the ``enrich``-source pattern — so evidence attaches to
  the entity we already have instead of minting a duplicate.

Etiquette: Wikidata is free and keyless but requires a descriptive User-Agent (``make_client``
provides ours) and politeness — one request/second via ``RateLimiter``, capped daily batches.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from seismo.collectors.base import RateLimiter, RawEventDraft
from seismo.collectors.http import make_client

API = "https://www.wikidata.org/w/api.php"
HF_ORG_URL = "https://huggingface.co/api/organizations/{handle}/overview"

# Claim properties kept in the pruned payload — everything derive-edges (and future consumers)
# reads. Anything else Wikidata returns is dropped at fetch time to keep raw_events lean.
KEPT_PROPS = {
    "P31",  # instance of (guards)
    # --- person <-> org relations (edges) ---
    "P108",  # employer (+ P580/P582 start/end qualifiers) -> employed_by / formerly_at
    "P112",  # founded by (on the org) -> founded, inverted
    "P169",  # chief executive officer -> employed_by
    "P1037",  # director / manager -> employed_by
    "P488",  # chairperson -> employed_by
    "P3320",  # board member -> employed_by
    "P69",  # educated at -> educated_at
    "P184",  # doctoral advisor -> advised_by
    "P185",  # doctoral student -> advised_by, inverted
    "P800",  # notable work -> notable_work (person -> work entity)
    "P39",  # position held ("CTO of OpenAI", with dates) -> person card 'positions'
    # --- ownership / backing (edges) ---
    "P749",  # parent organization -> subsidiary_of
    "P355",  # subsidiary -> subsidiary_of, inverted
    "P127",  # owned by -> owned_by
    "P1951",  # investor -> invested_in, inverted
    # --- identity back-links ---
    "P2037",  # GitHub username (back-link to our github:user:* anchors)
    "P496",  # ORCID (stored for future author dedupe)
    # --- display attributes (node panel, not edges) ---
    "P571",  # inception
    "P576",  # dissolved — a former employer that collapsed reads differently
    "P856",  # official website
    "P159",  # headquarters location
    "P452",  # industry
    "P106",  # occupation
    "P166",  # award received — credibility signal, shown on the person, not drawn as edges
    "P1128",  # employee count
}

_HUMAN = "Q5"
# P31 accept-list for orgs. Plain QID equality (no subclass reasoning — that would need SPARQL),
# so the list is deliberately broad; tune with real skip-rate data, not speculation.
ORG_CLASSES = {
    "Q43229",  # organization
    "Q4830453",  # business
    "Q783794",  # company
    "Q1058914",  # software company
    "Q1762059",  # startup
    "Q31855",  # research institute
    "Q483242",  # laboratory
    "Q163740",  # nonprofit organization
    "Q3918",  # university
}

# Relevance guard for person-search descriptions. Deliberately SPECIFIC: generic academic words
# ("researcher", "scientist", "professor") are excluded — a bare-"researcher" item sharing an
# author's name is exactly how the wrong Xiaowei Chi (a TCM-hospital researcher) matched an ML
# author during acceptance testing. Notable tech people carry a specific signal ("computer
# scientist", "business executive", "artificial intelligence researcher") and still pass.
# Word-boundary regex, not substring — a bare `"ai" in d` matches "tr·ai·ner"/"Ukr·ai·nian".
_RELEVANT_RE = re.compile(
    r"\b(?:ai|artificial intelligence|machine learning|deep learning|neural network\w*|"
    r"language model\w*|computer|software|informatic\w*|robotic\w*|technolog\w*|"
    r"developer|programmer|entrepreneur|business|executive|founder|chief)\b"
)
# Org descriptions get their own guard: the tech words above PLUS org-shaped words (orgs don't
# have the person-namesake problem, so "research"/"company" are safe here). Added after live
# acceptance: the HF handle "blogger" matched Google's Blogger platform — famous namesakes of
# generic-word handles pass the class+label guards, but their descriptions ("social network and
# blogging platform") don't read like a tech/research org, so this rejects them.
_ORG_RELEVANT_RE = re.compile(
    r"\b(?:ai|artificial intelligence|machine learning|deep learning|neural network\w*|"
    r"language model\w*|computer|software|informatic\w*|robotic\w*|technolog\w*|"
    r"company|startup|laborator\w*|research\w*|institute|university|"
    r"organization|organisation|enterprise|nonprofit)\b"
)


@dataclass(frozen=True)
class Resolution:
    """A name successfully matched to a Wikidata item."""

    qid: str
    label: str
    description: str
    match_rule: str  # 'p2037' | 'person_search' | 'org_search'
    match_evidence: str  # the login / search term, for the audit trail


@dataclass(frozen=True)
class WikidataTarget:
    """One entity (or HF org handle) queued for enrichment."""

    kind: str  # 'person_login' | 'person_name' | 'org_handle'
    query: str  # login, display name, or de-slugged handle
    anchor: dict[str, str] | None  # existing anchor the event should attach to (persons)
    entity_type: str  # 'person' | 'org'


@dataclass
class EnrichResult:
    drafts: list[RawEventDraft] = field(default_factory=list)
    skipped: int = 0


class WikidataClient:
    """Thin action-API wrapper: rate-limited GETs, no DB, no interpretation."""

    def __init__(self, *, client: httpx.Client | None = None, min_interval_s: float = 1.0):
        self._client = client or make_client()
        self._limiter = RateLimiter(min_interval_s)

    def _get(self, **params: Any) -> dict[str, Any]:
        self._limiter.wait()
        resp = self._client.get(API, params={"format": "json", **params})
        resp.raise_for_status()
        return resp.json()

    def search_by_github_login(self, login: str) -> str | None:
        """Exact P2037 statement search — a hit IS the person; no scoring."""
        data = self._get(
            action="query", list="search", srsearch=f'haswbstatement:"P2037={login}"', srlimit=2
        )
        hits = data.get("query", {}).get("search") or []
        return hits[0]["title"] if hits else None

    def search_items(self, term: str, *, limit: int = 5) -> list[dict[str, Any]]:
        """Label search — candidates with id/label/description, guards applied by callers."""
        data = self._get(
            action="wbsearchentities", search=term, language="en", type="item", limit=limit
        )
        return [
            {
                "qid": s.get("id", ""),
                "label": s.get("label", ""),
                "description": s.get("description", ""),
                "aliases": s.get("aliases") or [],
            }
            for s in data.get("search") or []
        ]

    def fetch_entities(self, qids: list[str]) -> dict[str, dict[str, Any]]:
        """Claims + label + description for up to 50 QIDs in ONE request."""
        if not qids:
            return {}
        data = self._get(
            action="wbgetentities",
            ids="|".join(qids[:50]),
            props="claims|labels|descriptions",
            languages="en",
        )
        return data.get("entities") or {}

    def fetch_labels(self, qids: list[str]) -> dict[str, str]:
        """English labels for claim-target QIDs (employer names etc.), one batched request."""
        if not qids:
            return {}
        data = self._get(
            action="wbgetentities", ids="|".join(sorted(set(qids))[:50]), props="labels",
            languages="en",
        )
        out: dict[str, str] = {}
        for qid, ent in (data.get("entities") or {}).items():
            label = (ent.get("labels") or {}).get("en", {}).get("value")
            if label:
                out[qid] = label
        return out


# --- pure claim helpers (unit-testable, no network) ---------------------------


def _claim_target(statement: dict[str, Any]) -> str | None:
    """The QID a wikibase-item statement points at, or None for novalue/other datatypes."""
    value = (statement.get("mainsnak") or {}).get("datavalue", {}).get("value")
    if isinstance(value, dict):
        return value.get("id")
    return None


def _qualifier_time(statement: dict[str, Any], prop: str) -> str | None:
    quals = (statement.get("qualifiers") or {}).get(prop) or []
    for qual in quals:
        value = qual.get("datavalue", {}).get("value")
        if isinstance(value, dict) and value.get("time"):
            return str(value["time"])
    return None


def _qualifier_item(statement: dict[str, Any], *props: str) -> str | None:
    """First item-QID qualifier among ``props`` (e.g. the 'of'/'employer' of a position)."""
    for prop in props:
        for qual in (statement.get("qualifiers") or {}).get(prop) or []:
            value = qual.get("datavalue", {}).get("value")
            if isinstance(value, dict) and value.get("id"):
                return str(value["id"])
    return None


def instance_of(claims: dict[str, Any]) -> set[str]:
    return {t for s in claims.get("P31") or [] if (t := _claim_target(s))}


def prune_claims(claims: dict[str, Any], labels: dict[str, str]) -> dict[str, Any]:
    """KEPT_PROPS only, each statement reduced to target qid+label (+start/end for P108) — so
    derive-edges never has to fetch and raw_events stay small."""
    pruned: dict[str, Any] = {}
    for prop in KEPT_PROPS:
        entries = []
        for statement in claims.get(prop) or []:
            value = (statement.get("mainsnak") or {}).get("datavalue", {}).get("value")
            if isinstance(value, dict) and value.get("id"):  # wikibase-item target
                entry: dict[str, Any] = {"qid": value["id"]}
                if value["id"] in labels:
                    entry["label"] = labels[value["id"]]
                if prop in ("P108", "P39"):
                    if start := _qualifier_time(statement, "P580"):
                        entry["start"] = start
                    if end := _qualifier_time(statement, "P582"):
                        entry["end"] = end
                # Job title on the employment / which org a position was held AT.
                if prop == "P108" and (role := _qualifier_item(statement, "P2868", "P794")):
                    entry["role_qid"] = role
                    if role in labels:
                        entry["role_label"] = labels[role]
                if prop == "P39" and (of := _qualifier_item(statement, "P642", "P108", "P2389")):
                    entry["of_qid"] = of
                    if of in labels:
                        entry["of_label"] = labels[of]
                entries.append(entry)
            elif isinstance(value, dict) and value.get("time"):  # P571 / P576 dates
                entries.append({"time": str(value["time"])})
            elif isinstance(value, dict) and value.get("amount"):  # P1128 quantity
                entries.append({"value": str(value["amount"]).lstrip("+")})
            elif isinstance(value, str):  # P2037 / P496 / P856 string values
                entries.append({"value": value})
        if entries:
            pruned[prop] = entries
    return pruned


def claim_target_qids(pruned: dict[str, Any]) -> list[str]:
    """Every QID whose English label the payload needs — claim targets plus the role/of
    qualifier items ("chief technology officer", the org a position was held at)."""
    out: list[str] = []
    for entries in pruned.values():
        for e in entries:
            for key in ("qid", "role_qid", "of_qid"):
                if e.get(key):
                    out.append(str(e[key]))
    return out


# --- guarded resolution --------------------------------------------------------


def _label_matches(candidate: dict[str, Any], term: str, *, exact: bool) -> bool:
    """Person names must match the label (or an alias) exactly; org handles only need to be a
    prefix/substring — 'thinking machines' should accept 'Thinking Machines Lab'."""
    term_l = term.lower().strip()
    labels = [str(candidate.get("label", ""))] + [str(a) for a in candidate.get("aliases", [])]
    if exact:
        return any(label.lower().strip() == term_l for label in labels if label)
    return any(term_l in label.lower() for label in labels if label)


def _relevant(description: str) -> bool:
    return bool(_RELEVANT_RE.search(description.lower()))


def resolve_qid(client: WikidataClient, qid: str) -> Resolution | None:
    """Direct fetch for an entity whose QID we already know (minted earlier from another item's
    claims — e.g. Mira Murati born from the Lab's P112). No search, no guards needed: the QID IS
    the identity. This is the second hop that turns claim-target stubs into full profiles."""
    ent = client.fetch_entities([qid]).get(qid)
    if not ent:
        return None
    label = (ent.get("labels") or {}).get("en", {}).get("value") or qid
    desc = (ent.get("descriptions") or {}).get("en", {}).get("value") or ""
    return Resolution(qid, label, desc, "qid", f"direct fetch {qid}")


def resolve_person_by_login(client: WikidataClient, login: str) -> Resolution | None:
    qid = client.search_by_github_login(login)
    if not qid:
        return None
    ent = client.fetch_entities([qid]).get(qid) or {}
    label = (ent.get("labels") or {}).get("en", {}).get("value") or login
    desc = (ent.get("descriptions") or {}).get("en", {}).get("value") or ""
    return Resolution(qid, label, desc, "p2037", f"github login {login!r}")


def _resolve_by_search(
    client: WikidataClient, term: str, *, want_org: bool
) -> Resolution | None:
    """Shared guarded search: P31 class check + label match (+ relevance for persons) must pass
    for EXACTLY ONE candidate, else skip. All candidates' claims come in one batched fetch."""
    candidates = [c for c in client.search_items(term) if c["qid"]][:3]
    if not candidates:
        return None
    entities = client.fetch_entities([c["qid"] for c in candidates])
    passing: list[Resolution] = []
    for cand in candidates:
        ent = entities.get(cand["qid"]) or {}
        classes = instance_of(ent.get("claims") or {})
        if want_org:
            ok = (
                bool(classes & ORG_CLASSES)
                and _label_matches(cand, term, exact=False)
                and bool(_ORG_RELEVANT_RE.search(cand["description"].lower()))
            )
            rule = "org_search"
        else:
            ok = (
                _HUMAN in classes
                and _label_matches(cand, term, exact=True)
                and _relevant(cand["description"])
            )
            rule = "person_search"
        if ok:
            passing.append(
                Resolution(
                    cand["qid"], cand["label"], cand["description"], rule, f"search {term!r}"
                )
            )
    return passing[0] if len(passing) == 1 else None  # ambiguous or empty ⇒ skip, never guess


def resolve_person(client: WikidataClient, name: str) -> Resolution | None:
    return _resolve_by_search(client, name, want_org=False)


def resolve_org(client: WikidataClient, handle_or_name: str) -> Resolution | None:
    return _resolve_by_search(client, handle_or_name.replace("-", " "), want_org=True)


def hf_org_display_name(handle: str, *, client: httpx.Client | None = None) -> str | None:
    """The org's human name from the HF overview API ('thinkingmachines' → 'Thinking Machines
    Lab'). Essential for disambiguation: the raw handle finds nothing on Wikidata (no word
    boundaries), and the de-hyphenated form can tie between namesakes (Thinking Machines
    Corporation, the defunct supercomputer maker, vs the Lab) — the display name picks the
    right one exactly. ``None`` on any failure; callers fall back to the handle."""
    try:
        resp = (client or make_client()).get(HF_ORG_URL.format(handle=handle))
        if resp.status_code != 200:
            return None
        name = (resp.json() or {}).get("fullname")
        return str(name) if name else None
    except (httpx.HTTPError, ValueError):
        return None


# --- target selection ------------------------------------------------------------


def select_targets(session: Session, *, limit: int | None = 200) -> list[WikidataTarget]:
    """Un-enriched entities, best-first: (1) anything already carrying a ``wikidata`` anchor —
    a claim-target stub like a founder or employer org, fetchable by QID with zero ambiguity;
    (2) persons via Path A/B (exact GitHub login beats fuzzy name search); (3) HF org handles.
    NOT-EXISTS on ``wikidata_entity`` links makes daily runs self-completing, mirroring the
    other enrich steps. Newest entities first — the person we minted yesterday belongs to the
    paper the user is looking at today. Note the deliberate frontier crawl: enriching Mira
    mints OpenAI, which next run enriches by QID, minting ITS people — the daily cap bounds
    how far this expands per day."""
    # (1) QID stubs — persons/orgs minted from another item's claims, never fetched themselves.
    qid_rows = session.execute(
        text(
            """
            SELECT e.id, e.entity_type, e.attrs->'anchors'->>'wikidata' AS qid
            FROM entities e
            WHERE e.attrs->'anchors' ? 'wikidata'
              AND e.entity_type IN ('person', 'org')
              AND e.merged_into IS NULL
              AND NOT EXISTS (
                SELECT 1 FROM entity_links l JOIN raw_events r ON r.id = l.raw_event_id
                WHERE l.entity_id = e.id AND r.event_type = 'wikidata_entity')
            ORDER BY e.id DESC
            """
            + ("LIMIT :limit" if limit is not None else "")
        ),
        {"limit": limit} if limit is not None else {},
    ).all()
    qid_targets = [
        WikidataTarget(
            kind="qid",
            query=str(qid),
            anchor={"registry": "wikidata", "native_id": str(qid)},
            entity_type=str(etype),
        )
        for _eid, etype, qid in qid_rows
        if qid
    ]
    # The qid frontier SELF-EXPANDS (each fetched org mints its parents/board as new stubs,
    # often faster than the fetch drains them), so it must not monopolize the budget — half
    # goes to the frontier, half to persons/handles, and leftover slack tops the frontier up.
    n_qid = len(qid_targets) if limit is None else min(len(qid_targets), max(1, limit // 2))
    remaining = None if limit is None else limit - n_qid

    targets: list[WikidataTarget] = []
    rows = session.execute(
        text(
            """
            SELECT e.id, e.canonical_name,
                   e.attrs->'anchors'->>'github' AS gh,
                   e.attrs->'anchors'->>'person_name' AS pname
            FROM entities e
            WHERE e.entity_type = 'person'
              AND e.merged_into IS NULL
              AND NOT (e.attrs->'anchors' ? 'wikidata')
              AND (e.attrs->'anchors'->>'github' LIKE 'user:%'
                   OR e.attrs->'anchors' ? 'person_name')
              AND NOT EXISTS (
                SELECT 1 FROM entity_links l JOIN raw_events r ON r.id = l.raw_event_id
                WHERE l.entity_id = e.id AND r.event_type = 'wikidata_entity')
            -- GitHub-login persons first: that path matches exactly (P2037), while name search
            -- mostly skips — and thousands of fresh paper authors are minted DAILY, so plain
            -- newest-first would starve the login queue forever.
            ORDER BY (e.attrs->'anchors'->>'github' LIKE 'user:%') DESC NULLS LAST, e.id DESC
            """
            + ("LIMIT :limit" if remaining is not None else "")
        ),
        {"limit": remaining} if remaining is not None else {},
    ).all()
    for _eid, name, gh, pname in rows:
        if gh and gh.startswith("user:"):
            targets.append(
                WikidataTarget(
                    kind="person_login",
                    query=gh.removeprefix("user:"),
                    anchor={"registry": "github", "native_id": gh},
                    entity_type="person",
                )
            )
        elif pname:
            targets.append(
                WikidataTarget(
                    kind="person_name",
                    query=str(name),
                    anchor={"registry": "person_name", "native_id": pname},
                    entity_type="person",
                )
            )

    # HF org handles ('thinking-machines/incling' -> 'thinking-machines') that no wikidata_entity
    # event mentions yet. The event will carry a wikidata:<QID> anchor, so resolve MINTS the org.
    handle_rows = session.execute(
        text(
            """
            SELECT DISTINCT split_part(e.attrs->'anchors'->>'hf', '/', 1) AS handle
            FROM entities e
            WHERE e.attrs->'anchors' ? 'hf' AND e.merged_into IS NULL
              AND NOT EXISTS (
                SELECT 1 FROM raw_events r
                WHERE r.event_type = 'wikidata_entity'
                  AND r.payload->>'org_handle' = split_part(e.attrs->'anchors'->>'hf', '/', 1))
            ORDER BY handle
            """
            + ("LIMIT :limit" if remaining is not None else "")
        ),
        {"limit": remaining} if remaining is not None else {},
    ).all()
    handles = [
        WikidataTarget(kind="org_handle", query=handle, anchor=None, entity_type="org")
        for (handle,) in handle_rows
        if handle
    ]
    if remaining is None:
        return qid_targets + targets + handles
    # Split the remaining budget between persons and org handles — thousands of un-enriched
    # paper authors would otherwise starve the org path forever. Each side tops up the other.
    n_handles = min(len(handles), max(1, remaining // 2))
    n_persons = min(len(targets), remaining - n_handles)
    n_handles = min(len(handles), remaining - n_persons)
    chosen = qid_targets[:n_qid] + targets[:n_persons] + handles[:n_handles]
    if len(chosen) < limit and len(qid_targets) > n_qid:  # unused slack -> more frontier
        chosen += qid_targets[n_qid : n_qid + (limit - len(chosen))]
    return chosen


# --- draft building ----------------------------------------------------------------


def enrich_targets(
    client: WikidataClient,
    targets: list[WikidataTarget],
    *,
    now: datetime | None = None,
    org_name_lookup: Any = None,  # (handle) -> display name | None; CLI passes hf_org_display_name
) -> EnrichResult:
    """Resolve each target and build one ``wikidata_entity`` draft per success. Skips (no match
    or ambiguous) are counted, not recorded — re-selection tomorrow retries them for free once
    they gain a wikidata anchor some other way, and unresolvable ones keep costing 2-3 calls,
    which the daily cap absorbs."""
    result = EnrichResult()
    fetched_at = now or datetime.now(UTC)
    for target in targets:
        if target.kind == "qid":
            resolution = resolve_qid(client, target.query)
        elif target.kind == "person_login":
            resolution = resolve_person_by_login(client, target.query)
        elif target.kind == "person_name":
            resolution = resolve_person(client, target.query)
        else:
            display = (org_name_lookup(target.query) if org_name_lookup else None) or target.query
            resolution = resolve_org(client, display)
        if resolution is None:
            result.skipped += 1
            continue

        entity = client.fetch_entities([resolution.qid]).get(resolution.qid) or {}
        raw_claims = entity.get("claims") or {}
        labels = client.fetch_labels(claim_target_qids(prune_claims(raw_claims, {})))
        pruned = prune_claims(raw_claims, labels)

        # Claim targets are minted with a GUESSED type (a P127 owner defaults to org but may be
        # a person like Musk); once we fetch the real item, its P31 is authoritative — let it
        # correct the guess so downstream edge derivation reads the claims from the right side.
        entity_type = target.entity_type
        classes = instance_of(raw_claims)
        if _HUMAN in classes:
            entity_type = "person"
        elif classes & ORG_CLASSES:
            entity_type = "org"

        payload: dict[str, Any] = {
            "qid": resolution.qid,
            "entity_type": entity_type,
            "label": resolution.label,
            "description": resolution.description,
            "match_rule": resolution.match_rule,
            "match_evidence": resolution.match_evidence,
            "claims": pruned,
            # Attachment: persons carry their EXISTING anchor; a new org carries its QID anchor
            # so resolve mints the org entity (see primary_anchor's 'wikidata' branch).
            "anchor": target.anchor
            or {"registry": "wikidata", "native_id": resolution.qid},
        }
        if target.kind == "org_handle":
            payload["org_handle"] = target.query  # what the NOT-EXISTS dedupe keys on
        result.drafts.append(
            RawEventDraft(
                source="wikidata",
                source_event_uid=f"{resolution.qid}:{fetched_at.date().isoformat()}",
                event_type="wikidata_entity",
                occurred_at=fetched_at,
                payload=payload,
            )
        )
    return result
