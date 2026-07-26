# Testing plan — everything shipped on `feature/signaltracker-port` (now on `main`)

*Written 2026-07-25. Covers every feature merged in `1cfdbac`. Each section: how to actually click
through it, what "working" looks like, and an honest call on whether it's worth using as-is or
still a proof of concept. Setup once, then work top to bottom — later sections build on earlier
ones being confirmed healthy.*

## Setup (once)

```bash
# terminal 1
uv run seismo serve                    # http://127.0.0.1:8000
# terminal 2
cd dashboard && npm run dev            # http://localhost:3000 (or 3001 if busy)
# sanity check both are alive:
uv run seismo doctor                   # should print "All green"
curl -s http://127.0.0.1:8000/health | python3 -m json.tool
```

If `doctor` isn't green, stop here and fix that first — nothing below will read as a real test if
the DB/schema/provider check is already failing.

---

## 1. OpenRouter connector + identity anchoring

**What to test:** does OpenRouter usage evidence actually land on the *same* entity as its
GitHub/HN evidence, instead of creating a duplicate row.

1. `curl -s "http://127.0.0.1:8000/entities/22909" | python3 -m json.tool | head -30` — look for
   `evidence` containing a `"source": "openrouter"` item with a real `openrouter.ai` URL and a
   token count in `score`.
2. On the dashboard, open `/entity/22909` — the Sources panel should show "OpenRouter rankings"
   with a token count, unit should read **"tokens/wk"** (not "pts/dl" — that was a real bug, fixed).
3. Re-run `uv run seismo snapshot` and confirm `or_tokens_wk` still populates without duplicating
   rows (idempotency) — `select count(*) from entity_metrics_daily where metric='or_tokens_wk'`
   should stay stable across repeated snapshot runs on the same day.

**Honest assessment:** the anchoring mechanism itself is solid and unit-tested, but the *live*
data is thin by construction — the rankings endpoint is top-10-only, so most tracked entities will
never get OpenRouter evidence. Don't expect to see this fire often; when it does, it's meaningful
(a project already on your radar suddenly has real paid-usage numbers).

---

## 2. Activity page clustering/filter (`/changes/latest`)

1. Open `/changes/latest`. Find "Maturity promotions" (or whichever kind has 15+ rows that day).
2. Confirm it's now grouped into category buckets (e.g. "Agent Framework 121"), sorted largest
   first, each collapsed by default except small ones.
3. Type a partial name or category into the filter box — the matching group should auto-expand,
   others should collapse/hide.
4. Clear the filter — groups should return to their default collapsed/expanded state.

**Honest assessment:** this is a straightforward, low-risk UX fix for a real problem (372 rows in
one flat list was unusable). Works as intended — safe to rely on.

---

## 3. Gate page clustering/filter (`/gate/current`)

Same test as #2, but on the "Suppressed" section (typically 800+ rows). Confirm the "Passed"
section (small, budget-capped) stays a flat list — it shouldn't need grouping.

**Honest assessment:** same fix, same confidence level as #2.

---

## 4. Council review (`/brief/[id]`)

**What exists right now:** 5 entities (`3246`, `3310`, `3313`, `3314`, `3319`) have real,
hand-authored verdicts (tagged `model: claude-fable-5:direct`) — not live-LLM-generated, written
directly against the actual evidence pack as a demonstration of the mechanism.

1. Open `/brief/3246` and `/brief/3314` — confirm each shows a "Council review" section with an
   aggregate stance badge (Adopt/Watch/Reject/Split) and three role cards (Skeptic, Evidence
   Auditor, Mechanism Reviewer), each showing its own reasoning and `model` tag.
2. Open a brief with **no** council data (e.g. `/brief/5564`) — confirm the empty state renders
   ("Not yet reviewed...") instead of a broken section.
3. To see a *real* live-provider run (not hand-authored): `uv run seismo council --entity-id
   <some_id>` with `SEISMO_LLM_PROVIDER=mock` (free) or `ollama` (if you have it running) —
   confirm new verdicts appear on that entity's brief page, and re-running doesn't duplicate rows.

**Honest assessment:** the mechanism (3 independent calls, deterministic majority vote, no
self-judging) is real and tested, but the *content* you'll see today is a hand-built demo on 5
entities, not a running pipeline output. Don't mistake "the UI shows something" for "this ran
against a real batch" — it hasn't yet, by design (it's deliberately not in `daily.sh`, it's the
most expensive checkpoint).

---

## 5. Radar "Gated" filter

1. Open `/` (Radar). Confirm a "📋 Gated" pill appears next to the state filters, with a count.
2. Click it — the grid should shrink to only entities that have ever passed the significance gate.
3. Compare against "🔥 Taking off" (top of the same page, momentum-only) — confirm they're
   genuinely different sets (as of today: none of the top-5 breakout entities are gated).
4. Click into a gated entity's card — confirm the small 📋 badge shows next to its name even when
   the filter isn't active.

**Honest assessment:** cheap, safe, does exactly what it says. The real value is conceptual —it
makes visible that momentum and "earned a brief" are not the same thing, which is easy to forget
when only one of the two views exists.

---

## 6. The knowledge graph (`/graph`, on `graph_feature` branch)

**What shipped:** a new `/graph` page rendering `entity_graph_edges` (deterministic) +
`entity_semantic_edges` (LLM-reasoned) via sigma.js/WebGL (`@react-sigma/core` + `graphology` +
`graphology-layout-forceatlas2`), backed by a new `GET /graph` endpoint.

1. Open `/graph` — confirm the node/edge count in the header matches
   `curl -s localhost:8000/graph | python3 -c "import sys,json;d=json.load(sys.stdin);print(len(d['nodes']),len(d['edges']))"`
   (678 nodes / 482 edges as of this writing).
2. Confirm the legend: teal lines = deterministic, purple = LLM-reasoned — and that both actually
   appear (199 deterministic + 283 reasoned edges exist).
3. Confirm the two largest visible hub nodes are `mohammadi-hadi/awesome-explainable-nlp` and
   `hasson827/awesome-dlms-post-training` — these were independently identified as the top "god
   nodes" by the original `graphify` analysis (114 and 46 edges respectively), so seeing them as
   the biggest circles here is the cross-check that the pipeline → DB → API → frontend chain is
   carrying the real data, not a placeholder.
4. Click a node — a panel should open top-right with its label, category, connection count, and
   (for a tracked entity, not a bare concept) an "Open entity →" button.
5. Grey nodes are concepts (e.g. "Claude Code", "MCP") an LLM pass named but that aren't
   themselves tracked entities — clicking one should show the panel with no "Open entity" button.

**A real gotcha hit while building this, worth knowing if the page ever breaks:** sigma.js touches
`WebGL2RenderingContext` at import time, which doesn't exist under Next's server-side render — the
actual component (`GraphView.tsx`) must be loaded through `GraphViewLoader.tsx`
(`next/dynamic(..., {ssr:false})`) or the page 500s. If `/graph` ever 500s with
`WebGL2RenderingContext is not defined` in the server log, that wrapper got bypassed somewhere.

**Honest assessment:** the page works and is verified against real data (confirmed via Playwright
screenshots + direct API checks, not just "it compiled"). But "does it make sense to use" is still
the open question from `GRAPH_PLAN.md` — the underlying data is a one-time snapshot (2026-07-25),
not refreshed automatically, and this page is the *first* consumer of `entity_semantic_edges`
ever, not evidence that the data itself is operationally valuable yet. Now that it's visible,
that's the actual question to sit with: do the patterns it surfaces (e.g. cross-category
similarity) look worth acting on, or is this a nice visualization of data nobody will revisit?

---

## 7. Code-review fixes (mostly backend — CLI/API testable, not much frontend surface)

These don't have dedicated UI, but are worth a quick pass since they change real behavior:

1. `SEISMO_LLM_PROVIDER=claude_cli uv run seismo doctor` — should now say `OK llm` instead of
   "unknown provider."
2. `uv run seismo doctor` — should report **26** core tables, not 19.
3. `uv run seismo triage --limit 5` (safe — it's never been run against real data) — confirm it
   completes without archiving anything with zero metrics (check `stats.deferred` in the CLI
   output vs `stats.skipped`).
4. `/changes/2026-07-20` — the category label on each row should reflect what the category was
   *that day*, not today's (mostly invisible unless an entity has actually been recategorized
   since — a low-frequency case, but worth knowing the fix exists).

**Honest assessment:** these were real bugs (verified by two independent reviewers + my own
DB-level checks), all now covered by the existing test suites (213/213 passing). Low risk, already
verified — nothing new to worry about here, just listed for completeness.

---

## Overall recommendation

Sections 2, 3, 5, and 7 are safe to consider "done" — low-risk fixes/features, already verified
multiple ways. Sections 1 and 4 work correctly but are currently running on thin/demo data, not a
real operational cadence — don't judge their long-term value from today's snapshot alone. Section
6 is the one item where "should we keep building on this" is a real open question worth actually
sitting with once the graph page exists to look at.
