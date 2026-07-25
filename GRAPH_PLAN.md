# Graph integration plan — not built yet, this is the plan

*Written 2026-07-25, branch `feature/signaltracker-port`. Context: `HANDOFF.md` §31–32.*

## Current state (why this file exists)

The knowledge-graph work from 2026-07-25 produced two things that are **stored but not used**:

- `entity_semantic_edges` (Postgres, migration 0009) — 283 model-reasoned edges
  (`semantically_similar_to` / `conceptually_related_to`), 212 of them resolved to real entity
  pairs. Grep confirms nothing outside `src/seismo/models.py` (the table definition itself) reads
  this table. No consumer exists.
- `graphify-out/graph.json` (2,654 nodes, full graph + community detection) — local disk only,
  gitignored, dated 2026-07-25 11:59. A one-time snapshot with no refresh cadence. It will not
  regenerate itself, and regenerating it is expensive (the build burned through two Claude
  session-limit walls and ~30 subagent runs — not something to rerun casually or put in `daily.sh`
  as-is).

Nothing below is built. This is the plan for *if/when* it's worth building, so the reasoning isn't
lost between sessions.

## Three concrete hook points, cheapest first

### 1. "Related entities" panel on the entity page (cheapest — data already exists)

**What:** a small section on `dashboard/app/entity/[id]/page.tsx` listing other tracked entities
`entity_semantic_edges` says are similar, with the relation and confidence shown.

**Where it hooks in:**
- New API query in `src/seismo/api/app.py`, alongside the existing entity-dossier endpoint:
  `SELECT dst_entity_id, dst_label, relation, confidence_score FROM entity_semantic_edges WHERE
  src_entity_id = :id` (and the mirror direction, since edges aren't stored both ways).
- New field on the entity dossier response model, new small React component (`RelatedEntities.tsx`
  following the `MarketImpact.tsx` pattern already in the codebase).

**Effort:** small — the data is already there, this is pure plumbing. No new LLM cost.

**Value:** turns the graph from "I queried it by hand once" into something a user actually sees.
Low risk since it's read-only and additive.

### 2. Market-crowding signal for the impact-brief pack

**What:** when `impact_pack.py`'s `build_brief_pack()` assembles what the brief-drafting LLM sees,
add a line like "N other tracked entities solve the same problem" pulled from
`entity_semantic_edges`, so the brief can reason about competitive crowding — something no single-
entity rule can currently detect.

**Where it hooks in:** `src/seismo/checkpoints/impact_pack.py`, a new `_crowding_block()` alongside
the existing `_map_block()`/`_momentum_block()`, added to the `parts` list in `build_brief_pack()`.

**Effort:** small-medium. Requires the brief pack's determinism/versioning discipline
(`BRIEF_PACK_VERSION`) to be respected — bump the version if this changes what the model sees, per
the existing convention.

**Value:** medium. Only pays off for entities whose semantic edges are populated (currently 212
entities, out of ~1,938 that got briefed at all) — a real but partial win until the graph is
refreshed on a wider slice.

### 3. Council's evidence_auditor cross-checks claims against similar entities

**What:** the `evidence_auditor` role in `src/seismo/checkpoints/council.py` currently judges a
brief in isolation. It could additionally be shown "here's what 2-3 similar entities' briefs claim"
and asked whether this entity's claims are consistent or suspiciously stronger with no more
evidence.

**Where it hooks in:** `run_council()` in `council.py` — extend `review_doc` with a
`_similar_entities_block()` built from `entity_semantic_edges` before calling
`complete_council()` for the `evidence_auditor` role specifically (not the other two roles, to
keep their prompts focused).

**Effort:** medium. Real design question: what if the similar entities have *no* brief yet, or
their brief is also a mock placeholder (as all 5 tested today were)? Needs a fallback that doesn't
silently degrade to "found no comparison, ignore this check."

**Value:** highest of the three, but also the most speculative — untested whether cross-entity
comparison actually improves verdict quality, or just adds tokens. Prototype on a handful of
entities with real (non-mock) briefs before committing to it.

## The refresh-cadence problem (blocks all three at scale)

All three hooks above only help for the ~212 entities the 2026-07-25 graph snapshot actually
resolved. New entities scraped after that date have zero semantic edges until the graph is rebuilt,
and rebuilding is currently a manual, session-limit-prone, multi-subagent `/graphify` run — not
something that fits `daily.sh`'s "no LLM cost, runs unattended" discipline.

Before investing in consumers (above), worth deciding: is this an occasional manual re-run (accept
staleness, rerun monthly-ish), or does it need a cheaper deterministic alternative (e.g. embedding-
similarity search over comprehension cards, no LLM subagents at all) for anything beyond a one-time
proof of concept? That decision should come before building consumer #2 or #3, since both assume a
graph that's reasonably current.

## Explicit non-goals

- Do **not** merge `entity_semantic_edges` into `entity_graph_edges`. That table is the
  deterministic spine (invariant 4 — collectors never reason); mixing model judgements into it
  destroys the guarantee that makes it trustworthy. This was already decided once (HANDOFF §31) —
  don't re-litigate it.
- Do **not** wire graph regeneration into `daily.sh` as-is. It's too expensive and too likely to
  hit session limits unattended. Solve the refresh-cadence question above first.
