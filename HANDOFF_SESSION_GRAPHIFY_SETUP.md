# Session handoff — graphify knowledge graph + project CLAUDE.md

*Written 2026-07-29 on branch `feature/enrich-graph-pt2`. This session changed **no
application code** — it set up tooling so future Claude sessions navigate the repo cheaply
instead of re-reading files. Read `CLAUDE.md` (new, auto-loaded) and this file, then continue
with the pending work from `HANDOFF_SESSION_GRAPH_ENRICHMENT.md` / `HANDOFF.md` §33.*

---

## What this session did

### 1. Built the graphify knowledge graph (`graphify-out/`, gitignored, derived)

- Full `/graphify` run over the repo: **2,603 nodes, 6,054 edges, 175 communities**
  (2,192 code symbols via free AST extraction + 418 doc concepts via 4 LLM subagents,
  ~1.16M input tokens one-time — logged in `graphify-out/cost.json`).
- Outputs: `graphify-out/graph.json` (queryable), `graph.html` (open in browser),
  `GRAPH_REPORT.md` (audit: god nodes, surprising connections, suggested questions).
- Top communities were hand-labeled: Significance Gate, Impact Briefs, Exposure Map Engine,
  Entity Resolution, LLM Provider Layer, Metrics & Time Series, Hindcast Tests, etc.
- God nodes (core abstractions by degree): Hand-curated Day-1 Seed Universe (145 edges),
  `RawEventDraft` (74), `TrackTarget` (40), `session_scope()` (36), `RateLimiter` (34).
- Known blemish, acceptable: health check reported **685 dangling-endpoint edges**
  (doc-extracted concepts referencing IDs that aren't nodes) + ~225 collapsed duplicate
  edges. Graph is fully usable; would only matter if we ever push it to Neo4j.
- Doc-extraction results are cached in `graphify-out/cache/` — a rebuild only re-extracts
  changed files. **Keep fresh with `/graphify . --update` after big changes** (code
  re-extraction is free/no-LLM; only changed docs cost tokens).
- `preza.txt` / `preza-short.txt` were listed by git status but no longer exist on disk;
  they were skipped. One sensitive file was auto-skipped by design.

### 2. Created the project `CLAUDE.md` (new file, at repo root — **not yet committed**)

Auto-loaded into every future session. Contains: one-paragraph project summary, the
**graph-first navigation rule** (query `graphify-out/graph.json` before reading source),
repo layout, doc index (COMMANDS/HANDOFF/DECISIONS/DATA_EXPLAINED), key commands, and the
hard constraints (tests share the Postgres DB with the pipeline — never run concurrently,
run pytest by file; no LLM SDK outside `src/seismo/checkpoints/`; Ollama + `.env` required;
never `alembic downgrade` a DB with data).

Decision recorded: **no project SKILL.md for now** — no repeated multi-step ritual justifies
one yet; graphify is already a global skill and `COMMANDS.md` covers procedures. Revisit if
the same multi-step instructions get retyped across sessions (candidate: a `/daily-run`
skill wrapping `./scripts/daily.sh` + bookkeeping check + gate summary).

## How the next session should work (the point of all this)

1. `CLAUDE.md` loads automatically — no need to tell Claude anything.
2. Structural/architecture questions → `/graphify query "<question>"` against the existing
   graph (a few hundred tokens) instead of exploring `src/`.
3. Only open the specific files the graph points to.
4. End of a heavy code session → `/graphify . --update` to refresh the map.

## Repo state at handoff

- Branch `feature/enrich-graph-pt2`, clean except: **`CLAUDE.md` untracked (should be
  committed)** and `daily-command.txt` modified (user's own edit, not from this session).
- `graphify-out/` and `briefs/` remain gitignored/derived — regenerate, never commit.
- Nothing in `src/`, `tests/`, `alembic/`, or the dashboard was touched.

## Pending from before (unchanged, still the real work queue)

- Layer-2 artifact↔artifact relations plan: `HANDOFF_SESSION_GRAPH_ENRICHMENT.md` Part 2.
- `HANDOFF.md` §33: overnight pytest result check → sanity-layer commit decision; comprehend
  backlog path (Ollama vs Anthropic key). Also §30 `llm.py` provenance bug, Reddit OAuth,
  card-quality audit (§31/§32).
