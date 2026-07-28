"""Wikidata team enrichment (WIKIDATA_ENRICHMENT_PLAN.md Phase 2) — resolution guards, claim
pruning, draft building, and target selection.

Network is faked with ``httpx.MockTransport`` serving canned action-API responses — zero live
calls, `min_interval_s=0` so nothing sleeps. The DB test rides ``clean_db`` like the other
resolve-adjacent suites.
"""

from __future__ import annotations

import itertools
import json
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from seismo.collectors.wikidata import (
    WikidataClient,
    WikidataTarget,
    enrich_targets,
    prune_claims,
    resolve_org,
    resolve_person,
    resolve_person_by_login,
    resolve_qid,
    select_targets,
)

_UID = itertools.count(1)
NOW = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)


# --- canned Wikidata API -------------------------------------------------------


def _item(qid: str, target_qid: str | None = None, **extra: Any) -> dict:
    """A wikibase-item statement pointing at ``target_qid`` (or a raw datavalue via extra)."""
    value: Any = {"entity-type": "item", "id": target_qid} if target_qid else extra["value"]
    return {"mainsnak": {"datavalue": {"value": value}}, **extra.get("more", {})}


def _time_qualifier(prop: str, time: str) -> dict:
    return {prop: [{"datavalue": {"value": {"time": time}}}]}


# Mira: human, employed by Thinking Machines (current) and OpenAI (ended 2020).
MIRA = {
    "labels": {"en": {"value": "Mira Murati"}},
    "descriptions": {"en": {"value": "Albanian-American business executive"}},
    "claims": {
        "P31": [_item("s", "Q5")],
        "P108": [
            _item("s", "QTM"),
            {
                "mainsnak": {"datavalue": {"value": {"entity-type": "item", "id": "QOAI"}}},
                "qualifiers": _time_qualifier("P582", "+2020-06-01T00:00:00Z"),
            },
        ],
        "P2037": [{"mainsnak": {"datavalue": {"value": "mmurati"}}}],
    },
}
# An unrelated footballer sharing the name — must be rejected by the P31/relevance guards.
FOOTBALLER = {
    "labels": {"en": {"value": "Mira Murati"}},
    "descriptions": {"en": {"value": "Albanian footballer"}},
    "claims": {"P31": [_item("s", "Q5")]},
}
THINKING_MACHINES = {
    "labels": {"en": {"value": "Thinking Machines Lab"}},
    "descriptions": {"en": {"value": "American artificial intelligence company"}},
    "claims": {
        "P31": [_item("s", "Q4830453")],
        "P112": [_item("s", "QMIRA")],
        "P571": [{"mainsnak": {"datavalue": {"value": {"time": "+2025-02-01T00:00:00Z"}}}}],
    },
}

# A bare-"researcher" item — human, exact name, but no specific tech/business signal. The wrong
# Xiaowei Chi (a TCM-hospital researcher) matched an ML author through exactly this shape.
GENERIC = {
    "labels": {"en": {"value": "Yuming Li"}},
    "descriptions": {"en": {"value": "researcher (ORCID 0009-0004-4414-6682)"}},
    "claims": {"P31": [_item("s", "Q5")]},
}

# Google's Blogger platform: business by P31, exact label for handle "blogger", but the
# description reads nothing like a tech/research org — the org relevance guard must reject it.
BLOGGER = {
    "labels": {"en": {"value": "Blogger"}},
    "descriptions": {"en": {"value": "social network and blogging platform by Google"}},
    "claims": {"P31": [_item("s", "Q4830453")]},
}

ENTITIES: dict[str, dict] = {
    "QMIRA": MIRA,
    "QTM": THINKING_MACHINES,
    "QFOOT": FOOTBALLER,
    "QGEN": GENERIC,
    "QBLOG": BLOGGER,
}
SEARCH: dict[str, list[dict]] = {
    "Mira Murati": [
        {"id": "QMIRA", "label": "Mira Murati", "description": MIRA["descriptions"]["en"]["value"]},
        {"id": "QFOOT", "label": "Mira Murati", "description": "Albanian footballer"},
    ],
    "thinking machines": [
        {
            "id": "QTM",
            "label": "Thinking Machines Lab",
            "description": "American artificial intelligence company",
        }
    ],
    "Thinking Machines Lab": [
        {
            "id": "QTM",
            "label": "Thinking Machines Lab",
            "description": "American artificial intelligence company",
        }
    ],
    "John Smith": [
        {"id": "QMIRA", "label": "Mira Murati", "description": "executive"},  # label mismatch
    ],
    "Yuming Li": [
        {
            "id": "QGEN",
            "label": "Yuming Li",
            "description": "researcher (ORCID 0009-0004-4414-6682)",
        },
    ],
    "blogger": [
        {
            "id": "QBLOG",
            "label": "Blogger",
            "description": "social network and blogging platform by Google",
        },
    ],
}
STATEMENT_HITS: dict[str, str] = {'haswbstatement:"P2037=mmurati"': "QMIRA"}
LABELS: dict[str, str] = {
    "QTM": "Thinking Machines Lab",
    "QOAI": "OpenAI",
    "QMIRA": "Mira Murati",
}


def _handler(request: httpx.Request) -> httpx.Response:
    p = request.url.params
    action = p.get("action")
    if action == "query":
        hit = STATEMENT_HITS.get(p.get("srsearch", ""))
        return httpx.Response(200, json={"query": {"search": [{"title": hit}] if hit else []}})
    if action == "wbsearchentities":
        return httpx.Response(200, json={"search": SEARCH.get(p.get("search", ""), [])})
    if action == "wbgetentities":
        ids = p.get("ids", "").split("|")
        if p.get("props") == "labels":
            ents = {
                q: {"labels": {"en": {"value": LABELS[q]}}} for q in ids if q in LABELS
            }
        else:
            ents = {q: ENTITIES[q] for q in ids if q in ENTITIES}
        return httpx.Response(200, json={"entities": ents})
    return httpx.Response(400, json={"error": f"unexpected action {action}"})


def _client() -> WikidataClient:
    return WikidataClient(
        client=httpx.Client(transport=httpx.MockTransport(_handler)), min_interval_s=0
    )


# --- resolution guards ---------------------------------------------------------


def test_login_path_is_exact() -> None:
    res = resolve_person_by_login(_client(), "mmurati")
    assert res is not None
    assert res.qid == "QMIRA" and res.match_rule == "p2037"


def test_login_miss_returns_none() -> None:
    assert resolve_person_by_login(_client(), "ghost-login") is None


def test_person_search_rejects_irrelevant_namesake_and_accepts_unique() -> None:
    """Two humans share the name; only the executive passes relevance — unique ⇒ accepted."""
    res = resolve_person(_client(), "Mira Murati")
    assert res is not None
    assert res.qid == "QMIRA" and res.match_rule == "person_search"


def test_person_search_skips_on_label_mismatch() -> None:
    assert resolve_person(_client(), "John Smith") is None


def test_person_search_rejects_generic_researcher_description() -> None:
    """A bare-'researcher' namesake must NOT match — no specific tech/business signal."""
    assert resolve_person(_client(), "Yuming Li") is None


def test_person_search_skips_when_ambiguous() -> None:
    """If BOTH namesakes read relevant, uniqueness fails — skip, never guess."""
    FOOTBALLER["descriptions"]["en"]["value"] = "Albanian software engineer"
    SEARCH["Mira Murati"][1]["description"] = "Albanian software engineer"
    try:
        assert resolve_person(_client(), "Mira Murati") is None
    finally:
        FOOTBALLER["descriptions"]["en"]["value"] = "Albanian footballer"
        SEARCH["Mira Murati"][1]["description"] = "Albanian footballer"


def test_org_search_accepts_handle_as_label_prefix() -> None:
    res = resolve_org(_client(), "thinking-machines")
    assert res is not None
    assert res.qid == "QTM" and res.match_rule == "org_search"


def test_qid_target_fetches_directly_without_guards() -> None:
    """A claim-target stub (person minted from an org's P112, wikidata anchor already known)
    is fetched by QID — no search, no guards, full employer history in the draft."""
    res = resolve_qid(_client(), "QMIRA")
    assert res is not None and res.match_rule == "qid" and res.label == "Mira Murati"

    target = WikidataTarget(
        kind="qid",
        query="QMIRA",
        anchor={"registry": "wikidata", "native_id": "QMIRA"},
        entity_type="person",
    )
    result = enrich_targets(_client(), [target], now=NOW)
    assert result.skipped == 0 and len(result.drafts) == 1
    draft = result.drafts[0]
    assert draft.payload["anchor"] == {"registry": "wikidata", "native_id": "QMIRA"}
    assert any(e.get("end") for e in draft.payload["claims"]["P108"])


def test_org_handle_resolves_via_hf_display_name() -> None:
    """A no-word-boundary handle like 'thinkingmachines' finds nothing on Wikidata directly —
    enrich_targets must resolve it through the HF display-name lookup instead."""
    target = WikidataTarget(
        kind="org_handle", query="thinkingmachines", anchor=None, entity_type="org"
    )
    result = enrich_targets(
        _client(), [target], now=NOW, org_name_lookup=lambda h: "Thinking Machines Lab"
    )
    assert result.skipped == 0 and len(result.drafts) == 1
    assert result.drafts[0].payload["qid"] == "QTM"
    assert result.drafts[0].payload["org_handle"] == "thinkingmachines"


def test_org_search_rejects_non_tech_namesake() -> None:
    """A generic-word handle matching a famous non-tech-org namesake must be skipped — the HF
    handle 'blogger' matched Google's Blogger platform on the first live run."""
    assert resolve_org(_client(), "blogger") is None


# --- claim pruning ---------------------------------------------------------------


def test_prune_claims_splits_current_and_former_employers() -> None:
    pruned = prune_claims(MIRA["claims"], LABELS)
    employers = pruned["P108"]
    assert {"qid": "QTM", "label": "Thinking Machines Lab"} in employers
    former = next(e for e in employers if e["qid"] == "QOAI")
    assert former["end"].startswith("+2020")
    assert pruned["P2037"] == [{"value": "mmurati"}]
    assert "P999" not in pruned  # only KEPT_PROPS survive


def test_prune_claims_positions_roles_and_card() -> None:
    """P39 positions keep their 'of' org + dates; P108 keeps a role qualifier; the resolve-side
    card renders them as human-readable titles ('CTO — OpenAI (2022–2024)')."""
    from seismo.collectors.wikidata import claim_target_qids
    from seismo.identity.resolve import _wikidata_card

    claims = {
        "P39": [
            {
                "mainsnak": {"datavalue": {"value": {"entity-type": "item", "id": "QCTO"}}},
                "qualifiers": {
                    "P642": [{"datavalue": {"value": {"entity-type": "item", "id": "QOAI"}}}],
                    "P580": [{"datavalue": {"value": {"time": "+2022-05-00T00:00:00Z"}}}],
                    "P582": [{"datavalue": {"value": {"time": "+2024-09-00T00:00:00Z"}}}],
                },
            }
        ],
        "P108": [
            {
                "mainsnak": {"datavalue": {"value": {"entity-type": "item", "id": "QOAI"}}},
                "qualifiers": {
                    "P2868": [{"datavalue": {"value": {"entity-type": "item", "id": "QCTO"}}}]
                },
            }
        ],
    }
    labels = {"QCTO": "chief technology officer", "QOAI": "OpenAI"}
    pruned = prune_claims(claims, labels)

    assert pruned["P39"][0]["of_label"] == "OpenAI"
    assert pruned["P39"][0]["end"].startswith("+2024")
    assert pruned["P108"][0]["role_label"] == "chief technology officer"
    # Qualifier items are label-fetch targets too, not just claim targets.
    assert {"QCTO", "QOAI"} <= set(claim_target_qids(pruned))

    card = _wikidata_card({"qid": "QX", "description": "exec", "claims": pruned})
    assert "chief technology officer — OpenAI (2022–2024)" in card["positions"]
    assert "chief technology officer — OpenAI" in card["positions"]


def test_prune_claims_keeps_quantity_values() -> None:
    """P1128 employee count is a quantity datavalue — kept as a plain string."""
    claims = {"P1128": [{"mainsnak": {"datavalue": {"value": {"amount": "+30", "unit": "1"}}}}]}
    assert prune_claims(claims, {})["P1128"] == [{"value": "30"}]


def test_qid_fetch_corrects_guessed_entity_type() -> None:
    """A P127 owner minted as 'org' that turns out to be a human (P31=Q5) gets its payload
    entity_type corrected at fetch time, so edges derive from the right side."""
    target = WikidataTarget(
        kind="qid",
        query="QMIRA",  # human in the fixtures
        anchor={"registry": "wikidata", "native_id": "QMIRA"},
        entity_type="org",  # the wrong guess
    )
    result = enrich_targets(_client(), [target], now=NOW)
    assert result.drafts[0].payload["entity_type"] == "person"


# --- draft building ----------------------------------------------------------------


def test_enrich_targets_builds_drafts_and_counts_skips() -> None:
    targets = [
        WikidataTarget(
            kind="person_name",
            query="Mira Murati",
            anchor={"registry": "person_name", "native_id": "mira-murati"},
            entity_type="person",
        ),
        WikidataTarget(
            kind="org_handle", query="thinking-machines", anchor=None, entity_type="org"
        ),
        WikidataTarget(
            kind="person_name",
            query="John Smith",  # guard-rejected above
            anchor={"registry": "person_name", "native_id": "john-smith"},
            entity_type="person",
        ),
    ]
    result = enrich_targets(_client(), targets, now=NOW)

    assert result.skipped == 1
    assert len(result.drafts) == 2
    person, org = result.drafts
    assert person.source == "wikidata" and person.event_type == "wikidata_entity"
    assert person.source_event_uid == "QMIRA:2026-07-28"
    # The person event attaches to the EXISTING person entity, not a new wikidata one.
    assert person.payload["anchor"] == {"registry": "person_name", "native_id": "mira-murati"}
    assert person.payload["entity_type"] == "person"
    assert any(e.get("end") for e in person.payload["claims"]["P108"])
    # The unknown org anchors on its QID so resolve mints it; handle recorded for dedupe.
    assert org.payload["anchor"] == {"registry": "wikidata", "native_id": "QTM"}
    assert org.payload["org_handle"] == "thinking-machines"
    assert org.payload["claims"]["P112"] == [{"qid": "QMIRA", "label": "Mira Murati"}]


# --- target selection (DB) -----------------------------------------------------------


def test_select_targets_paths_and_exclusions(clean_db: Session) -> None:
    session = clean_db

    def entity(name: str, etype: str, anchors: dict[str, str]) -> int:
        return int(
            session.execute(
                text(
                    "INSERT INTO entities (entity_type, canonical_name, created_at, attrs) "
                    "VALUES (:t, :n, :c, CAST(:a AS JSONB)) RETURNING id"
                ),
                {"t": etype, "n": name, "c": NOW, "a": json.dumps({"anchors": anchors})},
            ).scalar_one()
        )

    login_person = entity("alice", "person", {"github": "user:alice"})
    entity("Mira Murati", "person", {"person_name": "mira-murati"})
    entity("incling", "model", {"hf": "thinking-machines/incling"})
    enriched = entity("Bob Done", "person", {"person_name": "bob-done"})
    raw = int(
        session.execute(
            text(
                "INSERT INTO raw_events "
                "(source, source_event_uid, event_type, occurred_at, payload)"
                " VALUES ('wikidata', :u, 'wikidata_entity', :o, CAST('{}' AS JSONB)) RETURNING id"
            ),
            {"u": f"test:{next(_UID)}", "o": NOW},
        ).scalar_one()
    )
    session.execute(
        text(
            "INSERT INTO entity_links (entity_id, raw_event_id, rule, confidence, "
            "evidence_occurred_at) VALUES (:e, :ev, 'attach', 1.0, :o)"
        ),
        {"e": enriched, "ev": raw, "o": NOW},
    )
    session.flush()

    targets = select_targets(session, limit=50)

    by_kind = {t.kind: t for t in targets}
    assert by_kind["person_login"].query == "alice"
    assert by_kind["person_login"].anchor == {"registry": "github", "native_id": "user:alice"}
    assert by_kind["person_name"].query == "Mira Murati"
    assert by_kind["org_handle"].query == "thinking-machines"
    assert by_kind["org_handle"].anchor is None
    # The already-enriched person is excluded (NOT EXISTS on wikidata_entity links).
    assert all(t.query != "Bob Done" for t in targets)
    assert login_person  # silence unused warning; ids asserted via anchors above
