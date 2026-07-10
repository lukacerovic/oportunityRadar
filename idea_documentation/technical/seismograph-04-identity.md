# Seismograph — 04 Identity Layer (Entity Resolution)

*Implements idea-spec §5 Layer 2. Turns a stream of events from many registries into biographies of things. Output: `entities`, `entity_links`, populated `entity_merge_queue`, theme assignments.*

> **Amended by doc 13 A-2 (critical) + A-4.** The entity graph must be **as-of correct**, or every hindcast leaks future knowledge. Migration 0002 (authored at the start of this stage) adds: `entity_links.evidence_occurred_at`, an `entity_merges` table (`justified_at` = MAX occurred_at of supporting evidence; `entities.merged_into` becomes a convenience denormalization never read by as-of code), `entity_category_history` (category is time-versioned because it drives cohorts), and `entity_themes.effective_at`. Merges/links/category resolve through `canonical_entity_id(entity_id, as_of)` / `category_asof(entity_id, as_of)`, which apply only decisions justified by evidence `occurred_at <= as_of`. The graph-purity test (a link justified by a post-`as_of` event must be invisible at `as_of`) is a **DoD item for this stage** and replaces the weak twice-a-week test as the authoritative purity guard. Migration 0002 also adds `entities.tracking_tier`/`tier_reviewed_at` for the A-4 lifecycle (`seismo retier`). Cold-start `resolve --cold-start` precision-first queue mode: doc 14 §8.

---

## DR-04.1 — Deterministic rules over ML dedupe libraries
**Data Engineer:** the linkage evidence in this domain is unusually explicit — registries literally point at each other (paper→code links, model cards citing arXiv IDs, PyPI `project_urls`). Hand-written rules over that evidence hit high precision with full explainability. **ML Engineer:** libraries like splink/dedupe shine on fuzzy person/address data, which this is not. **Verdict:** ordered deterministic rules R1–R6 with per-rule confidence; `pg_trgm` only as the last, lowest-confidence rule; no ML matcher in v1. *Revisit trigger: merge-queue precision <60% for two consecutive months.*

## DR-04.2 — Merges are reversible, always
An entity merge writes `merged_into` on the loser and keeps every link row untouched. Unmerge = clear the pointer. Nothing is ever rewritten or deleted. **Adversarial Reviewer:** this makes queries slightly more annoying (must follow `merged_into`). **Verdict:** accepted — one `canonical_entity_id()` SQL function/CTE hides it, and irreversibility is how identity systems die.

---

## 1. Pipeline position

`seismo resolve` runs after collection, before snapshots. Steps: (1) sweep unlinked `raw_events`, (2) attach each to an entity or create one, (3) run cross-entity rules to find same-thing pairs, (4) auto-merge high band, queue mid band, (5) assign themes.

## 2. Event → entity attachment

Each source has a **native anchor** that maps to an entity candidate:

| Source | Anchor | Entity type |
|---|---|---|
| github | `owner/repo` | project |
| arxiv | arXiv ID | paper |
| hf | `org/model` | model |
| pypi / npm | package name | project (distribution facet) |
| hn / reddit | the *linked URL's* anchor, else none | attaches to linked entity |

Rule: an HN story about `github.com/x/y` attaches to the project entity for `x/y` (creating it if unseen — attention can precede our discovery). Stories with no resolvable link attach to nothing; they remain raw context, searchable but unowned.

## 3. Cross-registry link rules (ordered, first match sets confidence)

| Rule | Evidence | Conf. |
|---|---|---|
| **R1** URL exact | README / model card / package `project_urls` contains the other registry's canonical URL | 0.99 |
| **R2** Declared ID | HF card `arxiv:` tag; arXiv `comments` field contains GitHub URL; paper page linked from README badges | 0.97 |
| **R3** Registry metadata | PyPI/npm `project_urls.homepage/repository` → GitHub | 0.97 |
| **R4** Owner + name | same org/author handle AND normalized-name equality across registries | 0.85 |
| **R5** Name + temporal | normalized-name equality AND creation dates within 30 days | 0.72 |
| **R6** Fuzzy name | `similarity(name_a, name_b) > 0.65` via `pg_trgm`, same entity_type-compatible pair | 0.55 |

Name normalization: lowercase, strip punctuation/emoji, drop suffixes (`-dev`, `.py`, `-official`), collapse whitespace. Keep the function pure and unit-tested — it is load-bearing.

**Bands:** ≥0.90 auto-merge (link rows record which rule fired); 0.60–0.89 → `entity_merge_queue` with the evidence JSON rendered for a human; <0.60 discard (but the link row is kept for audit).

**Direction of merge:** survivor = the entity with the earliest `created_at` among those with a `project` or `model` anchor (registry anchors beat paper anchors; papers merge *into* projects, not vice versa).

## 4. The merge queue UI contract (built in doc 10, Stage 5)

Each queue item shows: both entities' names, sources, top events, the rule + evidence snippet, and three buttons — Merge / Not same / Skip. Decisions write `status` + `decided_at`; merged pairs also emit a training breadcrumb (`evidence`, `decision`) so future threshold tuning has ground truth. Target throughput: a 20-item queue clears with morning coffee.

## 5. Categories and themes

**Category** = controlled vocabulary on `entities.category`, assigned by keyword/topic rules over README/abstract/card text (deterministic, ~30 values: `inference-runtime`, `agent-framework`, `vector-db`, `code-assistant`, `model-foundation`, `model-efficiency`, `eval-tooling`, `data-pipeline`, …). Categories drive cohorts (doc 06) and reach (doc 07) — keep the vocabulary in one YAML file in the repo, versioned.

**Themes** = curated clusters (~15 to start: *efficient inference*, *open weights frontier*, *agent tooling*, *retrieval & memory*, *code generation*, *AI security*, …). Assignment: category→theme default mapping + manual overrides in the dashboard. Themes are narrative objects; categories are computational objects. Don't collapse them.

## 6. Failure modes handled explicitly
1. **Forks & mirrors:** GitHub payload `fork=true` → never a discovery seed; link to parent entity as `fork_of`.
2. **Name collisions** (common single-word names): R5/R6 require type compatibility and land in the queue, never auto-merge.
3. **Renames:** GitHub redirects old slugs — collector records `renamed` event; identity adds alias row in `attrs.aliases` and keeps the uid mapping.
4. **Monorepos / umbrella orgs:** entity = repo, not org; org is a separate `org` entity linked `maintained_by`. Prevents "everything by Google is one entity."

## 7. Definition of done
- [ ] R1–R6 implemented, each with unit tests on synthetic fixtures
- [ ] Reversible merge + `canonical_entity_id()` helper + tests
- [ ] Queue populated end-to-end; curation UI stub reachable
- [ ] Theme/category YAML vocabularies committed
- [ ] **Hindcast check:** DeepSeek backfill resolves paper (2405.04434) + `deepseek-ai` GitHub repos + HF models into one canonical entity via R1/R2 only
- [ ] Sampled queue precision ≥80% at the 0.60–0.89 band (else retune thresholds before Stage 3)
