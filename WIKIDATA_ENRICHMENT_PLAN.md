# Wikidata team-enrichment — implementation plan (Phases 1–4 SHIPPED 2026-07-28)

*Written 2026-07-28, updated same day after design discussion. Goal: for every item we collect
(paper / repo / model / launch), know the team behind it — who built it, where they work(ed),
what they founded — so "who is behind this" becomes a signal for judging potential.*

**Status: Phases 1–4 implemented and verified** (`test_graph_edges.py`, `test_wikidata.py`;
first real run minted 10,283 ``authored_by`` edges / 9,372 person entities). Phase 5 (HN org
extraction) is still open. One design amendment from live acceptance: the Path B relevance
guard was TIGHTENED — generic academic descriptions ("researcher", "scientist", "professor")
no longer qualify; a match needs a specific tech/business word ("computer", "machine learning",
"executive", "founder", …). Reason: a bare-"researcher" namesake (a TCM-hospital Xiaowei Chi)
matched an ML author on the first live run — exactly the wrong-edge failure the plan warns
about. Expect very low Path B yield on common names; that is the intended trade.

Every code fact below (event types, payload keys, function names, line refs) was verified
against the codebase on the date above.

## 0. The acceptance example (the whole feature in one picture)

We collected an arXiv paper from Thinking Machines Lab. When this feature is done, the graph
around that paper must read:

```
paper ──authored_by──▶ person "Mira Murati"        (Phase 1 — from data we already store)
person "Mira Murati" ──founded──▶ org "Thinking Machines Lab"   (Phases 2–3 — via Wikidata)
person "Mira Murati" ──formerly_at──▶ org "OpenAI"              (Phases 2–3 — via Wikidata)
```

and `dashboard`'s graph page must render those nodes and edges.

### Why NOT "look the paper itself up in Wikidata by name"

Considered and rejected. Wikidata covers *notable people and organizations* well, but has
essentially no items for fresh arXiv papers, new repos, or HF models — exactly what we track.
A per-item title lookup would return empty ~95% of the time. The design below is a **two-hop
chain**: (1) extract people/org *names* from data we already collect, (2) resolve those names
through Wikidata, where they DO exist.

## 1. Where this lives in the architecture

Pipeline enrichment; the graph is the first consumer. Same shape as READMEs / HF cards:

1. **`enrich-wikidata`** — new Wave-3 enrichment step (sibling of `enrich-hn`,
   `enrich-readmes`). Fetches Wikidata items for person/org names and stores them as
   `raw_events`. *Collectors record; they never interpret* — this step stays dumb.
2. **`resolve`** — existing step, extended with a `wikidata` anchor registry.
3. **`derive-edges`** — existing step (`src/seismo/graph/edges.py`), extended with new
   derivations that turn stored claims into typed edges. Interpretation happens ONLY here.
4. **Consumers** — graph API/page (nearly free: `src/seismo/api/app.py` ~line 1338 reads
   `entity_graph_edges` generically by `edge_type`). Later: entity-dossier "Team" panel,
   significance-gate team-pedigree factor (out of scope, data will be ready).

Daily-run placement (`scripts/daily.sh`, inside the `SKIP_ENRICH` block):

```
collect → track → resolve → enrich-launches/hn/readmes/hf → enrich-wikidata
        → resolve-enrich → derive-edges → snapshot → score → …
```

Note: `derive-edges` exists as a CLI command today but is NOT in `daily.sh` — Phase 4 adds it,
otherwise new edges only appear when someone runs it by hand.

## 2. Hop 1 — extracting people/org names per source (all local, already collected)

| Source | What we extract | Where it already sits | Determinism |
|---|---|---|---|
| arXiv | author names | `paper_published` event payload, key `authors` (list of name strings — `src/seismo/collectors/arxiv.py:114`) | exact |
| GitHub | contributor logins | `repo_contributors` events; already minted as `person` entities with `github:user:<login>` anchors by `_derive_built_by` | exact |
| Hugging Face | org handle | the model id itself (`thinking-machines/incling` → `thinking-machines`), key `id` in model payloads | exact |
| HN launch | org/product name | free text of title / enriched launch page — needs extraction | fuzzy — **deferred to last** |

## 3. Hop 2 — resolving names via Wikidata (three match paths)

Disambiguation is the whole risk ("John Smith" problem). Rule: **skip, never guess** — a wrong
"Mira Murati" edge is worse than a missing one. Every skip is recorded.

### Path 0 — known QID → direct fetch (added post-ship; highest priority, zero ambiguity)
Entities minted as claim targets (a founder from P112, an employer org from P108) carry a
``wikidata:<QID>`` anchor but were never fetched themselves — without this path Mira Murati
stayed a dead-end stub with no employment history. ``select_targets`` queues them FIRST and
``resolve_qid`` fetches by id, no search, no guards. This creates a deliberate frontier crawl
(Mira → OpenAI → OpenAI's people → …) bounded by the daily cap.

### Path A — GitHub login → person (deterministic)
Wikidata property **P2037 = GitHub username**. Query:
`GET https://www.wikidata.org/w/api.php?action=query&list=search&srsearch=haswbstatement:"P2037=<login>"&format=json`
A hit is an exact match — no scoring. Input: person entities carrying a `github:user:*` anchor.

### Path B — person name → person (guarded search)
`GET …api.php?action=wbsearchentities&search=<name>&language=en&type=item&format=json`
Accept a candidate ONLY if ALL guards pass:
- `P31` (instance of) = `Q5` (human);
- relevance: item description/claims mention AI/ML/software/research keywords, OR the item is
  connected (P108/P112/P1416) to an org or person we already track;
- uniqueness: exactly one candidate passes the guards.
Input: `person_name:*`-anchored persons (paper authors from Phase 1).

### Path C — org name → org → its people (guarded search; org coverage ≫ paper coverage)
Same `wbsearchentities` flow, guards adapted:
- `P31` in an accept-list of org classes (business `Q4830453`, research institute `Q31855`,
  AI lab, laboratory, software company `Q1058914`, startup `Q1762059` — finalize list in code);
- relevance + uniqueness as Path B.
From the org item read the team directly: `P112` (founded by), `P169` (CEO), `P1037`
(director/manager). This yields "founded by Mira Murati" even when no author name matched —
and is the ONLY path for HN-launch items. Input: HF org handles (Phase 2), extracted HN org
names (Phase 5).

### Claims fetched for any resolved QID (one call)
`GET …api.php?action=wbgetentities&ids=<QID>&props=claims|labels|descriptions&languages=en&format=json`

| Property | Meaning | Used for |
|---|---|---|
| P108 | employer (+ qualifiers P580 start, P582 end) | `employed_by` / `formerly_at` |
| P112 | founded by (on the org) | `founded` (inverted) |
| P169 / P1037 / P488 / P3320 | CEO / director / chair / board | `employed_by` (role in edge attrs later, v1: plain edge) |
| P2037 | GitHub username | back-link person ↔ existing github anchor |
| P496 | ORCID | stored for future author dedupe |
| P571 / P856 | org inception / website | org entity `attrs` |

Prune payloads to exactly these properties, and **include the English labels of claim-target
QIDs** (employer names etc.) so `derive-edges` never has to fetch.

## 4. Design decisions

- **D1 — new anchor registry `wikidata`**: `attrs.anchors.wikidata = "<QID>"`. QIDs anchor both
  persons and orgs, so the event payload carries `entity_type` explicitly —
  `src/seismo/identity/anchors.py` already supports payload-provided entity_type (~line 233).
  The QID is the *strong* identity; `person_name:*` duplicates fold into it later via the
  existing merge machinery (do NOT build custom dedupe now).
- **D2 — new entity type `org`** (existing types: project, paper, model, product, person).
  Minted by `derive-edges` on first sight — same as persons/papers today — anchored
  `wikidata:<QID>`, `canonical_name` = Wikidata label, `attrs` carrying description/website.
- **D3 — new edge types**, upserted on `(src, dst, edge_type)` like the existing three:

  | edge_type | direction | derived from |
  |---|---|---|
  | `authored_by` | paper → person | `paper_published.authors` (local, Phase 1) |
  | `employed_by` | person → org | P108 claim without end-date qualifier |
  | `formerly_at` | person → org | P108 claim with P582 end date |
  | `founded` | person → org | org's P112 claim, inverted |

- **D4 — raw event shape**: `source="wikidata"`, `event_type="wikidata_entity"`,
  `source_event_uid = f"{qid}:{fetch_date}"` (snapshot-style — refreshable, deduped per day).
  Payload: `qid`, `entity_type`, `label`, `description`, `match_rule`
  (`"p2037" | "person_search" | "org_search"`), `match_evidence` (login / search term + guards
  passed), pruned `claims` (per §3 table, with target labels).
- **D5 — API etiquette**: free, no key, but REQUIRES a descriptive User-Agent
  (`OpportunityRadar/0.1 (contact email)`). Reuse `RateLimiter`
  (`src/seismo/collectors/base.py`) at ~1 req/s. Daily cap `--limit` (default 200) with the
  NOT-EXISTS un-enriched-targets pattern the other enrich steps use.
- **D6 — as-of purity**: new derivations follow the same invariants as the existing three —
  read only events `occurred_at <= as_of`, canonicalize every endpoint through
  `canonical_entity_id`, mint entities born at first-evidence time, skip self-loops, attach
  the justifying raw_event id in `evidence_refs`. `tests/test_graph_purity.py` conventions apply.

## 5. Implementation phases

Execute in order; each phase lands independently, is testable on its own, and ends with a
runnable acceptance check.

### Phase 1 — `authored_by` edges from data we already have (no network)

Files: `src/seismo/graph/edges.py`, `tests/test_graph_edges.py`.

- [ ] Add `_derive_authored_by(session, as_of, anchor_map, canonical, stats)` modeled line-for-
      line on `_derive_cited`:
      - iterate `_attached_events(session, "paper_published", as_of)`;
      - for each name in `payload["authors"]` (strip empties, dedupe within the paper):
        `_get_or_create(session, anchor_map, "person_name", _slugify(name), "person", name,
        occurred)` — import/reuse `_slugify` from `seismo.identity.anchors`;
      - `_upsert_edge(session, paper, person, "authored_by", raw_id, occurred.date())`;
      - canonicalize both ends; skip self-loops (defensive, same comment style as existing).
- [ ] Extend `EdgeStats`: `authored_by: int = 0`, include in `as_note()` and in
      `edges_upserted` sum; call the new fn from `derive_edges()`.
- [ ] Update the module docstring (it enumerates derived relations — keep it truthful).
- [ ] Register `person_name` in `_ENTITY_TYPE` (`identity/anchors.py:46`) → `"person"` if the
      resolver needs it (check how `person_name` anchors behave in resolve before assuming).
- [ ] Tests in `test_graph_edges.py`, mirroring the existing derive tests: minting; idempotent
      re-run (same edge count); as-of purity (paper event after `as_of` → nothing); same author
      on two papers → one person, two edges; empty/whitespace author names skipped.

**Accept:** `uv run seismo derive-edges` on the real DB shows `authored_by>0`, and a collected
paper's authors appear as person nodes on the graph page (they will, once Phase 4 legend lands;
until then verify via SQL: `SELECT * FROM entity_graph_edges WHERE edge_type='authored_by' LIMIT 5`).

### Phase 2 — `enrich-wikidata` step (fetch + store, no interpretation)

Files: new `src/seismo/collectors/wikidata.py`, `src/seismo/cli.py`,
`src/seismo/identity/anchors.py`, `src/seismo/collectors/targets.py` (only if a new selector is
needed), new `tests/test_wikidata.py`, fixtures under `tests/fixtures/`.

- [ ] `WikidataClient` in `collectors/wikidata.py`: httpx client with the D5 User-Agent +
      `RateLimiter(1.0)`; methods `search_by_github_login(login)`, `search_person(name)`,
      `search_org(name)`, `fetch_claims(qid)` — each returning parsed dicts, no DB access.
- [ ] Resolver functions implementing §3 guards, returning
      `(qid, match_rule, match_evidence) | None` — pure, unit-testable against fixtures.
- [ ] Target selection (in `wikidata.py`, not `targets.py`, unless a generic selector fits):
      - persons with a `github:user:*` anchor, no `wikidata` anchor, no prior
        `wikidata_entity` event (NOT EXISTS) → Path A;
      - persons with a `person_name:*` anchor, same exclusions → Path B;
      - HF-derived org handles: distinct `<org>` prefixes of tracked `hf:*` anchors that have
        no matching org entity yet → Path C;
      - order by recency/momentum of the entities they touch (notable teams first), cap by limit.
- [ ] Draft builder → one `RawEventDraft` per resolved target (shape per D4). Skips recorded
      (log line + counted in the echo summary; no event row for skips in v1).
- [ ] CLI `@app.command(name="enrich-wikidata")` mirroring `enrich_readmes`
      (`cli.py:85-126`): `record_pipeline_run("enrich-wikidata")` → select targets in a
      `session_scope` → **fetch outside any open transaction** → `persist_drafts` → echo
      `[enrich-wikidata] X targets → Y resolved, Z skipped, N new events (run seismo resolve
      then seismo derive-edges)`.
- [ ] `identity/anchors.py`: handle `source == "wikidata"` in `primary_anchor` — anchor
      registry `wikidata`, native id `qid`, entity_type from payload, display name = label.
- [ ] Tests (recorded JSON fixtures, zero live calls): P2037 exact hit; person search accepted
      by guards; ambiguous person (two candidates pass) → skip; org search with P31 accept-list;
      uid dedupe (same day re-run → 0 new events); resolve attaches the event and registers the
      `wikidata` anchor on the right entity.

**Accept:** `uv run seismo enrich-wikidata --limit 5 && uv run seismo resolve` → Wikidata
events attached to Phase-1 authors / contributor persons; skips visible in the echo summary.

### Phase 3 — affiliation edges + org minting

Files: `src/seismo/graph/edges.py`, `tests/test_graph_edges.py`.

- [ ] `_derive_affiliations(...)` over `_attached_events(session, "wikidata_entity", as_of)`:
      - person events: for each P108 claim → `_get_or_create` the org
        (`wikidata:<employer QID>`, type `org`, name from the pruned target label) → upsert
        `employed_by` (no P582) or `formerly_at` (P582 present);
      - org events: for each P112 claim → `_get_or_create` the person
        (`wikidata:<founder QID>`, type `person`) → upsert `founded` person → org;
        P169/P1037 targets → `employed_by`;
      - canonicalize, self-loop-skip, evidence_refs = the wikidata raw event, per D6.
- [ ] `EdgeStats` += `employed_by`, `formerly_at`, `founded`, `orgs_created`; docstring update.
- [ ] Tests: current-vs-former employer split on the P582 qualifier; founded inversion; two
      people sharing an employer → org minted once; as-of purity; idempotent re-run.

**Accept:** the §0 acceptance example holds end-to-end on real data — enrich a Thinking
Machines / Mira-adjacent entity, run resolve + derive-edges, and query
`entity_graph_edges` for the three expected edges.

### Phase 4 — pipeline + dashboard surfacing

Files: `scripts/daily.sh`, dashboard graph page component(s), `COMMANDS.md`, `DAILY.md`.

- [ ] `daily.sh`: inside the `SKIP_ENRICH` block add
      `run "enrich-wikidata" uv run seismo enrich-wikidata` (before `resolve-enrich`), and after
      `resolve-enrich` add `run "derive-edges" uv run seismo derive-edges`.
- [ ] Dashboard: add legend/colors for `authored_by` / `employed_by` / `formerly_at` /
      `founded` and node styling for `org` + `person` types wherever per-type styling lives on
      the graph page (locate via the component that consumes the graph API response;
      API side needs nothing — it's generic).
- [ ] Docs: new command in `COMMANDS.md`; new step in `DAILY.md`.

**Accept:** one full `./scripts/daily.sh` run produces new wikidata events + edges with no
failed steps, and the graph page renders the Mira cluster with a readable legend.

### Phase 5 (last — fuzzy) — HN-launch org extraction — **NOT BUILT YET**

Only phase touching free text; sequenced last deliberately.

- [ ] Extract candidate org/product names from enriched HN launch content (regex/heuristics
      first — "by <Org>", "from <Org>", domain root of the launch URL; NO LLM in v1).
- [ ] Feed candidates through Path C with the same guards; everything downstream (Phases 2–4
      machinery) is already built.
- [ ] Tests on a handful of real stored launch payloads.

**Accept:** at least one registry-less HN launch (e.g. a Kimi-style product) gains an org node
with team edges.

## 6. Risks / notes for the implementer

- **Coverage is intentionally partial.** Only notable people/orgs are in Wikidata; a long-tail
  GitHub dev won't resolve. That is fine — the signal IS "an ex-OpenAI founder touched this."
  Expect Path B precision > recall by design; revisit guards only with real skip-rate data.
- **`person_name` anchors are weak identity** (collisions/duplicates possible). Accepted for
  v1; QID becomes the strong identity; existing merge machinery is the escape hatch.
- **Freshness**: v1 fetches each entity once (snapshot uid allows re-fetch later; a >180-day
  staleness re-fetch is a one-line target-selection change, not v1).
- **Do not** add SPARQL in v1 — the action API covers everything above with simpler failure
  modes. SPARQL only becomes worth it for bulk backfills.
- **Check before coding Phase 1**: how `resolve` treats unknown anchor registries — if
  `person_name` entities minted by derive-edges would confuse the resolver's anchor map,
  align with how `_derive_built_by`'s `github:user:*` persons already behave (they set the
  precedent; follow it).
