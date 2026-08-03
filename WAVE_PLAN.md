# Wave Radar — convergence detection

*Plan, not built. Written 2026-08-03, branch `claude/novi-feature-xtb4lc`. Companion to
`GRAPH_PLAN.md` — same discipline: write the reasoning down so it isn't re-derived next session.*

---

## Why this file exists

Every stage in the pipeline looks at **one entity at a time**. `score` computes a momentum state per
entity. `gate` scores candidates individually and ranks them. `changes` diffs entity by entity. There
is no component anywhere in `src/seismo/` that asks a question about a *population* of entities.

So when six independent projects converged on the same idea in three weeks, the system said nothing.
A human opened `/graph?trending=true`, clicked through entity by entity, and wrote
`AGENT_GUARDRAIL_WAVE.md` by hand. All the data was already in Postgres.

That is the gap. Not a missing data source — a missing *kind of question*.

## What it detects, in one sentence

Multiple **independent**, **young** entities entering the same problem space inside a short window —
convergence of unrelated builders, as distinct from one project's growth or one team's output.

## The finding it must reproduce

`AGENT_GUARDRAIL_WAVE.md`, week of 2026-07-20. Six entities: `uipath/coder_eval`,
`termaxa/termaxa`, `hyperlogue/r3`, `video-db/open-record-replay`,
`pierreolivierbonin/verbatimeter`, `skyphusion-labs/postern`. All small, all new, all built to *not
trust an AI agent's output or actions at face value*.

Three structural facts about that finding drive the entire design, and each one kills an obvious
implementation:

### 1. Members do not point at each other

Every semantic edge goes to a *different* neighbour outside the group:

```
hyperlogue/r3                  → elliot-rosen/adversarial-review
termaxa/termaxa                → ourbando/gatewarden
uipath/coder_eval              → ozperium/agentspec
pierreolivierbonin/verbatimeter→ swp0569/rag-llm-consistency-gate
```

**Connected components over `entity_semantic_edges` returns four disjoint pairs and zero waves.**
The relationship is second-order: members are similar *to similar things*, not to each other. This
is expected and will recur — brand-new repos in the same space genuinely don't reference each other,
because none of them knows the others exist. That is exactly what makes the convergence interesting.

### 2. The wave crosses both categories and themes

Members split `agent-framework` (4) and `rag-framework` (2). In `seed/categories.yaml` those map to
themes **`agent tooling`** and **`retrieval & memory`** respectively — different narrative clusters.

So grouping by category fails, and grouping by theme fails too. Category can only be a weak prior,
never the grouping key.

### 3. None of them is categorized as what it actually is

`seed/categories.yaml` has `guardrails` and `ai-security` slugs sitting under the `AI security`
theme. Not one of the six landed there — `assign_category()` is deterministic keyword matching, and
these projects describe themselves in agent/RAG vocabulary.

This is worth stating plainly because it is a second, unplanned payoff: **a wave whose members are
scattered across categories is evidence that the controlled vocabulary is missing a category, or
that its keywords are stale.** Wave output should feed back into `seed/categories.yaml` the same way
`map_gaps` feeds back into `exposure_map/`.

**Acceptance test for the whole feature:** given a fixture reproducing this shape, the detector emits
exactly one wave with all six members. If it needs the members to point at each other, or to share a
category, it has failed.

## Algorithm

Deterministic end to end. No LLM decides membership (invariant 4).

### Step 1 — candidate set

Entities where, as of the run's `as_of`:

- `first_seen` within `wave_max_age_days` (180) — reuse `EntityFacts.first_seen` from
  `trajectory/cohorts.py`, which is already as-of correct and survives merges
- first evidence lands inside the rolling window `wave_window_days` (30)
- not `dormant` (must have registered at least `simmering` at some point in the window)

No gate-pass requirement. The gate spends a budget of 5 briefs a week; a wave is a different object
and should be able to contain entities the gate never had room for. This is deliberate — coupling
wave membership to gate passes would make the feature a re-render of the gate.

### Step 2 — neighbourhood projection

For each candidate, build its **semantic neighbourhood**: the set of `dst_label` values from
`entity_semantic_edges` in both directions, above `wave_min_edge_confidence`. Labels, not entity ids
— the table's endpoints are nullable on purpose, because an edge may anchor on a concept ("MCP",
"Claude Code") that is not a tracked entity, and the label always survives.

Two candidates are **linked** when any of these hold:

- they share a neighbour label (normalized)
- their neighbours share a category
- one is the other's neighbour (the direct case — rare among young entities, but free to support)

This is a bipartite projection: entity → neighbour-label → entity. It is what makes fact #1 above
tractable, and it is the single most important line in this document.

### Step 3 — cluster

Connected components over the *linked* relation from step 2 (not over raw edges). Clusters below
`wave_min_members` (4) are discarded.

### Step 4 — independence filter

This is half the feature's value, and it runs over the deterministic spine (`entity_graph_edges`),
never over model judgments. A cluster member is dropped, and the cluster re-evaluated against
`wave_min_members`, when:

| Check | Signal | Why it disqualifies |
|---|---|---|
| shared author | both have a `built_by` edge to the same person entity | one team, not convergence |
| dependency | a `depends_on` path between two members | an ecosystem around one project, not parallel invention |
| shared owner | identical GitHub owner in the anchor (`gh:owner/repo`) | monorepo split, or one org's product line |
| fork lineage | fork/rename relation on the anchor | a copy is not an independent data point |

Every check is recorded per member in `wave_members.independence_checks`, passed or failed, so a
wave can be audited the way `gate_decisions` can — trust comes from seeing what was excluded.

Without this filter the first "wave" the system ships will be five microservices from one company,
and the feature loses credibility in week one.

### Step 5 — strength

```
strength = size_factor × breadth_factor × tightness_factor
```

- **size_factor** — independent members past the minimum, saturating (4 → 0.6, 6 → 0.8, 10+ → 1.0)
- **breadth_factor** — median `evidence_breadth` across members. A wave of GitHub-only repos is a
  weaker claim than one where members also show attention or usage evidence. Same logic that makes
  `breakout_min_breadth` the defense against gamed metrics.
- **tightness_factor** — how compressed the window is. Four entities in 7 days beats four in 30.

Deliberately the same shape as the gate's `M × R × N`: bounded components, each independently
inspectable, no free parameters hidden inside a model.

### Step 6 — identity across runs

**The problem the other five steps hide.** This runs daily; clusters recompute from scratch; member
sets shift as new entities land. If a wave gets a new id every day, the `/waves` page shows churn
instead of a story, and `first_seen` resets constantly.

Rule: a newly computed cluster is matched to the highest-overlap existing wave. If overlap
≥ `wave_continuity_overlap` (0.5 of the smaller set), it **is** that wave — keep the id, keep
`first_seen`, append new members with their own `joined_at`. Otherwise mint a new wave.

Consequences to accept: two waves can merge over time (the loser is marked `merged_into`, never
deleted), and a wave can go quiet without dissolving. Same append-only discipline as everywhere else —
membership history is a record, not a current-state cache.

## Data model — migration 0013

```
wave_clusters
  id                bigint pk
  label             text null          -- LLM-authored; null until named
  label_model       text null
  first_seen        date not null      -- earliest member joined_at, never rewritten
  last_active       date not null
  window_days       int  not null
  strength          real not null
  components        jsonb not null     -- size/breadth/tightness, same spirit as gate_decisions
  merged_into       bigint null fk → wave_clusters.id
  as_of             timestamptz not null
  created_at        timestamptz

wave_members
  wave_id             bigint fk → wave_clusters.id
  entity_id           bigint fk → entities.id
  joined_at           date not null
  link_reason         jsonb not null   -- which shared neighbour labels linked it in
  independence_checks jsonb not null   -- every check, passed and failed
  unique (wave_id, entity_id)
```

⚠️ **Both tables go into `_CLEAR_TABLES` in `tests/conftest.py`, before `entities`.** `STATE.md`
records this breaking the suite three separate times. `wave_members` before `wave_clusters`, both
before `entities`.

## Where it hooks in

**Pipeline** — new stage in `scripts/daily.sh` after `score`, before `gate`:

```
… derive-edges → snapshot → score → waves → comprehend → gate → brief → changes
```

After `score` because it reads momentum states. Before `gate` only for ordering clarity — **in v1
the gate does not read waves at all.** Feeding wave membership into the significance score is a
plausible v2 (an entity in a strong wave is arguably more significant), but that is a change to the
chokepoint the whole architecture exists to protect, and it deserves its own decision entry.

**Module** — `src/seismo/waves/`:

```
detect.py        candidate set, projection, clustering, strength
independence.py  the four checks, over entity_graph_edges only
continuity.py    step 6 — matching today's clusters to existing waves
```

Placement note: `waves/` is a peer of `trajectory/` and `significance/`, not a subpackage of
`graph/`. `graph/` mints edges; this consumes them.

**CLI** — `seismo waves --as-of` (re-runnable, same contract as `gate`: recompute the day's view
from scratch, preserve wave identity through `continuity.py`).

**API** — `/waves` (list, `strength` desc) and `/waves/{id}` (members with link reasons and
independence results). Both take `as_of` via the existing `get_as_of` dependency in `api/app.py`.
Plus a `waves: list[WaveChip]` field on the entity dossier.

**Dashboard** — `dashboard/app/waves/page.tsx`, and a panel on the entity page following the
`RelatedEntities.tsx` pattern.

The page has one job the graph page cannot do: **show why these entities belong together when they
have no edges to each other.** Rendering a wave as a normal node-link graph would show six
disconnected dots and communicate nothing. It should render as a cluster card — members listed with
the neighbour label that linked each one in, the independence checks visible, a timeline of
`joined_at` so the convergence reads as an event in time rather than a list.

**Changes feed** — new `changes_daily` kinds `wave_formed` and `wave_joined`, so a new wave surfaces
in the daily diff instead of only on its own page. Cheap: `memory/changes.py` already takes an
arbitrary `kind`.

## The naming checkpoint — sixth LLM checkpoint, optional

The cluster exists, is scored, and is fully rendered **before any model is called.** The checkpoint
receives the members and their comprehension cards and returns one label plus one sentence:

```
{ "label": "agent-distrust tooling", "one_liner": "…", "confidence": "high|medium|low" }
```

Forced tool call with a Pydantic contract in `checkpoints/contracts.py`, post-validated, same as the
other five. If it fails, is skipped, or blows its budget, the wave still exists and renders as
`wave-3` with `label = null`. **Degradation must be visible, never silent.**

It gets its own budget ceiling in `config.py`, following the `sanity_llm_budget_usd` precedent —
though unlike sanity this runs over a handful of clusters, so the ceiling is small.

What it must never do: decide membership, decide strength, or merge waves. Those are steps 1–6, and
they are arithmetic.

## Thresholds — all guesses, all need calibration

| Setting | Proposed | Basis |
|---|---|---|
| `wave_window_days` | 30 | guardrail wave spanned ~19 days |
| `wave_max_age_days` | 180 | matches the gate's novelty cohort |
| `wave_min_members` | 4 | below 4 is coincidence; 6 would have been too strict for the known case |
| `wave_min_edge_confidence` | 0.5 | unvalidated |
| `wave_continuity_overlap` | 0.5 | unvalidated |

None of these can be set from this branch — they need a run against the real database, and ideally a
`hindcast`-style replay against known past convergences. Ship with these defaults in `config.py`,
expect to move them, and record the move in `DECISIONS.md`.

## Failure modes, honestly

**The graph is the fuel, and the tank is low.** 283 semantic edges across 18,360 entities, from a
one-time snapshot dated 2026-07-25 that does not refresh itself. Waves can only form where edges
exist. `GRAPH_PLAN.md` already flags the refresh-cadence problem as blocking its own three consumers;
this is a fourth consumer with the same dependency. **Wave Radar does not fix that problem and should
not pretend to.** The realistic v1 expectation is a small number of waves in the regions of the graph
that happen to be covered.

**A false wave is worse than no wave.** A convincing-looking cluster that turns out to be one team's
microservices does more damage than silence — it teaches the reader to distrust the page. This is why
the independence filter is not an optimization and why every check is stored rather than merely
applied.

**Category churn moves members between runs.** `assign_category()` is keyword matching over text that
grows as enrichment lands. Since category is only a weak prior here and not the grouping key, the
blast radius is limited — but member sets will wobble, and step 6 is what keeps that wobble from
becoming a new wave every day.

**Small clusters are statistically fragile.** Four members with a strength number attached carries an
air of precision the underlying data does not have. The UI should show member count at least as
prominently as `strength`, and should not render strength to more precision than it deserves.

## Testing

The suite needs a real Postgres (`tests/conftest.py` — window functions, `ON CONFLICT`, `pg_trgm`),
so all of this is fixture work against a live schema, matching how CI provisions `postgres:16`.

**Positive fixture — the acceptance test.** Six entities, no `built_by` overlap, no `depends_on`, two
categories across two themes, each with a semantic edge to a *different* neighbour where the
neighbours share a category. Must produce exactly one wave with six members. This fixture is the
whole design compressed into one test: it fails for any implementation that clusters on direct edges
or on category.

**Negative fixtures, one per independence check:**

- five repos, same GitHub owner → no wave
- four repos in a `depends_on` chain → no wave
- four repos with a shared `built_by` person → no wave
- a fork and its parent inside an otherwise valid cluster → wave forms, fork excluded

**Continuity fixtures:** cluster grows by one member across runs → same wave id, `first_seen`
unchanged, new member has its own `joined_at`. Cluster that shifts more than half its members → new
wave, old one retained.

**Determinism:** two runs at the same `as_of` produce byte-identical `wave_clusters` rows apart from
`created_at`. Same property the gate has.

## Explicit non-goals

- **No LLM decides membership, strength, or merging.** The naming checkpoint is cosmetic by
  construction. Invariant 4.
- **Do not write into `entity_semantic_edges` or `entity_graph_edges`.** This is a consumer. The
  spine stays deterministic (`GRAPH_PLAN.md` already settled this once — don't re-litigate).
- **Do not feed waves into the gate in v1.** Separate decision, separate entry in `DECISIONS.md`.
- **Do not attempt graph regeneration from here.** The refresh-cadence question is `GRAPH_PLAN.md`'s
  and remains open.
- **No price or market claims.** A wave is an observation about builders. The exposure map is
  reached, if ever, through the existing brief path — not from this page.

## Open questions for calibration

1. Should a wave require at least one member that ever reached `accelerating`/`breakout`, or is
   "several new things appeared at once" interesting on its own even at low momentum?
2. When members scatter across categories (as all six did), should the system emit a vocabulary-gap
   signal alongside the wave — the `map_gaps` pattern applied to `seed/categories.yaml`?
3. Does a wave decay? A cluster with no new members in 60 days is history, not radar. Archive it,
   collapse it, or leave it?
4. Is `strength` worth showing to the user at all in v1, or does member count plus the window carry
   the signal more honestly while the thresholds are still uncalibrated?
