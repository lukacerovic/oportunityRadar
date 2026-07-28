# Session handoff — Wikidata team graph, ✨ explanations, and the Layer-2 plan

*Written 2026-07-28, end of a long session on branch `feature/graph-enrichment` (merged to
`main` mid-session as `2ad426a`; everything after that is uncommitted — see "Repo state").
Purpose: give the next session full context + a precise, ready-to-execute plan for Layer 2
(artifact ↔ artifact relations).*

---

## Part 1 — What this session built

### 1.1 Wikidata team enrichment (the "who is behind it" layer) — SHIPPED, live data

- **Collector** `src/seismo/collectors/wikidata.py`: rate-limited (1 req/s, UA from
  `collectors/http.py`), resilient (per-call retry + per-target catch — an hour-long batch
  survives dropped connections). Match paths: **Path 0** direct QID fetch (stubs minted from
  claims; zero ambiguity; self-heals entity_type from P31), **A** GitHub login via P2037
  (exact), **B** person name search (guards: P31=Q5 + exact label + SPECIFIC tech/business
  words — generic "researcher" rejected after a wrong-namesake incident), **C** HF org handle →
  HF org display name (`hf_org_display_name`) → org search (org-class P31 + org-relevance
  guard — "blogger"→Blogger incident). **Skip, never guess** is the law; ambiguity skips.
- **Properties fetched** (see `KEPT_PROPS`): employment P108 (+P580/P582 dates, role
  qualifiers), founders P112, leadership P169/P1037/P488/P3320, education P69, doctoral
  lineage P184/P185, notable works P800, positions P39 (+"of" qualifier), ownership
  P127/P749/P355, investors P1951, works' P178 developer / P1324 source repo / P275 license /
  P277 language, org products P1056, financials P2139/P2226, X P2002 / Mastodon P4033,
  employee count P1128, HQ P159, industry P452, inception/dissolved P571/P576, website P856,
  GitHub P2037, ORCID P496. Quantity units get currency labels. **Wikipedia lead paragraph**
  fetched via enwiki sitelink → `payload.wiki_intro`. Labels fetch is chunked (>50 QIDs bug
  fixed).
- **Derive** (`src/seismo/graph/edges.py`): edge types now — `authored_by` (paper→person from
  arXiv payloads), `built_by`, `employed_by`/`formerly_at` (with `start_date`/`end_date`
  columns, migration 0014), `founded`, `educated_at`, `advised_by`, `subsidiary_of`,
  `owned_by`, `invested_in`, `notable_work`, `produces` (org→work), `developed_by` (model→org
  via HF handle stored on the entity as `attrs.hf_org_handle`; work→org via P178),
  `source_repo` (work→TRACKED repo only, via `anchor_from_url` — never mints repos). Entity
  types now include `org` and `work`. All as-of pure, evidence-ref'd, idempotent.
- **Target selection** (`select_targets`): budget split — half QID frontier (**ordered by
  graph degree DESC**, hubs first; the frontier self-expands faster than any budget drains
  it), half persons (GitHub-login persons FIRST — fresh paper authors are minted by thousands
  daily and would starve the exact-match path) + HF org handles. Daily budget: 200
  (`WIKIDATA_LIMIT` in daily.sh).
- **Cards** (`identity/resolve.py::_wikidata_card` → `entities.attrs.wikidata`): description,
  **wiki** (Wikipedia intro), positions ("CTO — OpenAI (2022–2024)"), website, inception,
  dissolved, employees, **revenue**, **market_cap**, **twitter**, HQ, industry, occupation,
  awards, license, language. Served on graph nodes as `info`; rendered in the node panel.
  Logo (P154) was explicitly DECLINED by the user — no images.

### 1.2 Graph UI

- Server-side search `/graph?q=` (2-hop subgraph around ILIKE matches; matched-but-edgeless
  entities still returned); trending default capped to top-30 seeds (`?top=`); family edge
  colors (employment orange, education lime, notable-work/produces rose, ownership fuchsia,
  project links teal, LLM purple); person/org/work node colors; node profile panel; legend
  below canvas; perf (Barnes-Hut >500 nodes, label threshold, stable module-level
  SIGMA_SETTINGS — inline settings crash sigma on re-render); parallel edges merged
  ("founded + employed_by"); hover label dark-on-white fix. Dashboard graph cache is 60s.

### 1.3 ✨ Graph explanations — SHIPPED

- `graph_explanations` table (migration 0013), one narration per entity, `subgraph_hash`
  fingerprints the pack → **regenerate only when the graph changed** (daily step
  `explain-graphs --limit 10` in daily.sh) or `--force`. On-demand via POST
  `/graph/explain?entity_id=` (panel "Generate now").
- Generation: `src/seismo/graph/explain.py`. Subgraph = **person-mediated expansion** (3
  rounds; orgs expand only at hop-1 when focus is an artifact) so the pack matches what the
  page shows (early version narrated 161 nodes while the page showed 22). Interior edges only.
  Sections: overview / key_people / organizations / **industry_context** (the ONE section
  allowed to use model world-knowledge — comparisons like OpenAI vs the focus org) / signals.
- Provider: `SEISMO_GRAPH_EXPLAIN_PROVIDER=claude_cli` in `.env` (bills the Claude Code
  subscription; ~$0.09–0.36 bookkeeping per narration). Tests run with
  `SEISMO_LLM_PROVIDER=mock SEISMO_GRAPH_EXPLAIN_PROVIDER=mock`.
- Panel `dashboard/components/ExplainPanel.tsx` with a dependency-free markdown-lite renderer.

### 1.4 Repo & data state, ops lessons (READ THIS)

- **UNCOMMITTED**: everything after `2ad426a` (explain feature, Wikidata v2, migrations
  0013+0014, panel, tests, this file). **First task next session: commit** (user has been
  offered repeatedly; get their go, commit to main, push).
- Data now: ~1,540 wikidata events, ~22.4k graph edges, 2 stored narrations, QID queue ~3.5k
  (hub-first, 200/day — the long tail intentionally never fully drains).
- **Never wipe wikidata events again.** A wipe deletes team edges → zeroes graph degree → the
  hub-first ordering feeds on noise and the core (OpenAI, Mira) starves; this burned ~2h and
  needed a hand-targeted repair (`repair_core_enrich.py` pattern: build qid `WikidataTarget`s
  for a named list + all works). For future property expansions implement **staleness
  re-fetch** (e.g. `fetch_version` in payload; re-fetch where version < N) — edges stay put.
- Tests share the PROD Postgres (`tests/conftest.py` clean_db DELETEs in a rolled-back txn):
  never run DB tests concurrently with pipeline commands or each other; each clean_db test
  costs 60–120s. Fast wikidata/explain tests: `-k "not select_targets"` (instant).
- API changes require restarting `uv run seismo serve` (no auto-reload); run it from repo
  root (a serve started elsewhere misses `.env` → mock provider wrote a junk narration once).
- Suite env quirk: sanity/explain tests assert `model == "mock"` — always prefix
  `SEISMO_LLM_PROVIDER=mock SEISMO_GRAPH_EXPLAIN_PROVIDER=mock`.

---

## Part 2 — LAYER 2: artifact ↔ artifact relations (the next build)

**Goal.** Today the graph answers "who built X and where did they come from". Layer 2 makes it
answer **"what does X build on, who builds on X, and is an ecosystem forming around it"** —
ecosystem formation is the strongest early signal that something is becoming a platform. The
✨ narrations pick all of it up automatically (they read the graph).

Priority order (2.1 → 2.4). 2.1–2.3 need **zero new APIs** and reuse existing patterns
verbatim; 2.4 is the first new source.

### 2.1 `fine_tuned_from` — model lineage from HF base_model tags (NO network)

- **Data already on disk**: ~80+ `model_discovered` raw events whose `payload.tags` contain
  `base_model:...` entries. Tag formats seen on HF: `base_model:org/name` AND qualified forms
  `base_model:finetune:org/name`, `base_model:quantized:org/name`, `base_model:merge:...`,
  `base_model:adapter:...` — parse: strip the `base_model:` prefix, then if the remainder
  contains another `:` and the pre-colon token is one of
  {finetune,quantized,merge,adapter}, strip that too; what remains is the HF model id
  (lowercase it — HF anchors are lowercased).
- **Implementation**: new `_derive_lineage(session, as_of, anchor_map, canonical, stats)` in
  `src/seismo/graph/edges.py`, modeled on `_derive_depends_on`: iterate
  `_attached_events(session, "model_discovered", as_of)` (check whether `model_snapshot`
  events also carry `tags` — if yes iterate both, dedupe per entity), for each base-model id
  look up `anchor_map.get(f"hf:{base_id}")` — **link only if tracked, never mint** (same rule
  as depends_on: an untracked base is not evidence we stand behind); canonicalize both ends;
  upsert edge `fine_tuned_from` (derived model → base model); skip self-loops. New EdgeStats
  field + docstring line + wire into `derive_edges()` + edges_upserted sum.
- **Tests** (`tests/test_graph_edges.py`, copy `test_depends_on_links_tracked_only`): tracked
  base → edge; untracked base → nothing minted; qualified tag forms parse; idempotent rerun.
- **UI**: nothing required (falls into teal "project links" family); optionally mention in
  legend line.
- **Value**: "N fine-tunes on one base this week" = what the ecosystem bets on, visible
  before stars move. (A later query/panel can rank bases by recent descendant count.)

### 2.2 model → paper edges from HF `arxiv:` tags (NO network)

- **Data on disk**: same events; tags like `arxiv:2405.04434` (14+ models). Today these feed
  only the R2 reference/merge-queue path (`identity/anchors.py::references`) — they never
  become graph edges.
- **Implementation**: inside the same `_derive_lineage` loop: for each `arxiv:` tag,
  `_get_or_create` the paper (registry `arxiv`, entity_type `paper` — EXACTLY like
  `_derive_cited` mints papers, reuse the same anchor key format and `papers_created`
  counter), upsert edge **`cited`** (model → paper; reuse the existing edge type — it already
  means "artifact cites paper", keeping the family teal and the API/UI untouched).
- **Tests**: model + arxiv tag → cited edge + paper minted; dedupe of repeated tags.
- **Value**: closes the loop *paper → code → model*. A paper that has models within weeks is
  "materializing", not just interesting — precisely the early-potential definition.

### 2.3 Activate `depends_on` — run enrich-pypi (config only)

- `seismo enrich-pypi` exists (`cli.py`, ~line 205) but has NEVER run → 0 `pypi_metadata`
  events → 0 depends_on edges, though the derivation is implemented and tested.
- **Do**: add to `scripts/daily.sh` inside the SKIP_ENRICH block (before `resolve-enrich`):
  `run "enrich-pypi" uv run seismo enrich-pypi --limit "${PYPI_LIMIT:-200}"` (verify the
  command's actual options first). Run one manual pass + `resolve` + `derive-edges` to seed.
- **Caveat**: coverage = entities carrying a `pypi` anchor; if few exist the edge count will
  be honest-but-small. Check `SELECT count(*) FROM entities WHERE attrs->'anchors' ? 'pypi'`.

### 2.4 OpenAlex — paper affiliations + citation velocity (FIRST NEW SOURCE)

The largest lever, in two phases. OpenAlex is free, keyless; etiquette = `mailto=` param
(email in `collectors/http.py::CONTACT`) and polite rate (reuse `RateLimiter`, ~5–10 req/s
allowed but 2/s is plenty).

- **Fetch**: `GET https://api.openalex.org/works/arXiv:{arxiv_id}` per tracked paper (an
  `enrich-openalex` step patterned EXACTLY on `enrich-wikidata`: NOT-EXISTS un-enriched
  selection, daily cap, event_type `openalex_work`, payload anchored via the `enrich`-style
  explicit anchor `{"registry":"arxiv","native_id":...}` so resolve attaches to the paper).
  Keep in payload: `authorships` (author display_name, ORCID, institutions with **ROR id** +
  display_name + country), `cited_by_count`, `counts_by_year`, `referenced_works` (OpenAlex
  W-ids), `topics`, own OpenAlex `id`.
- **Phase A — affiliations (graph)**: derive `affiliated_with` (person → org) edges:
  authors matched to our `person_name:` entities by slug (they were minted from the same
  arXiv author strings, so slugs align); institutions minted as orgs anchored by a NEW
  registry `ror:<id>` (add to derive's `_get_or_create` usage; a later Wikidata merge can
  fold ror-orgs into wikidata-orgs via the merge machinery — do NOT build custom dedupe).
  This gives EVERY paper a team+institution picture, not just Wikidata-famous authors.
- **Phase B — citation velocity (radar, the real prize)**: papers currently have NO tracked
  metric, so they can never trend. Add a metric to `trajectory/metrics.py` METRIC_SPECS:
  name `oa_citations`, kind `cumulative`, evidence_type `usage` (or a new `scholarly` type —
  check doc 06 conventions), source `openalex`, event_type `openalex_work`, value field
  `cited_by_count`, composite=True. Then re-fetching each paper every ~7 days (staleness
  re-fetch in the target selector: `occurred_at < now - 7d`) creates the time series →
  velocity → cohort percentile → papers can reach `accelerating`/`breakout` and pass the
  gate. **This makes the paper phase — the earliest phase — measurable for the first time.**
- **Paper→paper citations**: `referenced_works` are OpenAlex ids; store the paper's own
  OpenAlex id in `attrs` at absorb, then derive `builds_on` edges only BETWEEN TRACKED papers
  by joining stored OpenAlex ids. Do this after A+B; it needs no extra fetching.
- **Tests**: fixture-driven (httpx.MockTransport, zero live calls — copy
  `tests/test_wikidata.py` structure).

### Suggested execution order for the next session

1. Commit the current uncommitted work FIRST (ask user; main + push).
2. 2.1 + 2.2 in one PR-sized change (one new derive fn + tests) → run `derive-edges` live →
   verify lineage edges on the graph page.
3. 2.3 (daily.sh line + one manual seed run).
4. 2.4 phase A, then phase B (metric), then paper→paper.
5. After 2.4B lands, revisit the significance gate: papers will start appearing as
   candidates; check cohort behavior (doc 06) before trusting the first week of paper states.
