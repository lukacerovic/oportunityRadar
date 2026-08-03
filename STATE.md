# Where we are — 2026-07-28

*Snapshot of live state. Numbers are from the dev DB at the timestamp above; re-run the queries at
the bottom rather than trusting these once they age. For how the system works, read
`ARCHITECTURE.md`. For build history, `HANDOFF.md`.*

---

## Git

`origin/main` = `2ad426a`. Local and remote in sync.

Recent, newest first:

```
2ad426a  fix(graph): stable sigma settings + drop in-view search box
5609914  Merge feature/graph-enrichment
f006e46  fix(wikidata): prioritize exact GitHub-login targets in the person budget
b78db8d  adding wikidata source for graph enrichment
76d235a  merge: community research layer onto sanity checkpoint + graph search
810bb42  docs: HANDOFF §33, agent-guardrail trend, competitive + data-source research
0e68e65  feat(dashboard): graph search + trending-by-default
5b37aee  feat(sanity): content-quality checkpoint over freshly-collected text
47d2ac1  merge: community discussion research + AI summarizer onto main
```

Open branches on origin: `feature/community-discussion`, `feature/graph-enrichment`,
`feature/enrich-graph-pt2`.

## Database

Migration head: **0012**. Single alembic head, chain clean.

| Table | Rows | Note |
|---|---:|---|
| `raw_events` | 37,697 | immutable spine |
| `entities` | 18,360 | |
| `entity_links` | 37,749 | event → entity resolution |
| `momentum_states` | 971,757 | full replayed history, rewritten each `score` run |
| `changes_daily` | 10,515 | |
| `comprehension_cards` | 771 | **671 are qwen-authored with no review flag** — see risks |
| `gate_decisions` | 1,740 | every candidate, passed and suppressed |
| `content_sanity_checks` | 3,105 | 3,060 ok / 19 flagged / 26 reject |
| `entity_semantic_edges` | 283 | LLM-reasoned |
| `entity_graph_edges` | 199 | deterministic spine |
| `impact_briefs` | 24 | |
| `council_verdicts` | 18 | |
| `reach_links` | 133 | |
| `exposure_companies` | 30 | financials are **placeholders**, never cite as real |
| `entity_community_research` | 0 | Luka's layer wired, not yet run |

**Momentum distribution:** `dormant 17,644 · accelerating 356 · simmering 102 · breakout 54`

⚠️ Most of that `accelerating` count is the cold-start artifact — the hand-seeded catalog of
well-known tools reads as accelerating because tracking on them only recently began. Cross-check
against `gate_decisions` before treating any of it as a real signal.

## What works end to end

- Full daily pipeline: `collect → track → resolve → sanity → derive-edges → snapshot → score → gate → changes`
- All 5 LLM checkpoints (sanity, comprehend, impact, council, community) on pluggable providers
- FastAPI + Next.js dashboard rendering live data across 7 pages
- Hindcast validation green on Reflection-70B and DeepSeek
- **Full test suite: 237 passed, 0 errors** (1h29m, 2026-07-28)

## Latest substantive finding

This week's 5 gate-passed entities all tell the same story: `uipath/coder_eval`, `termaxa/termaxa`,
`hyperlogue/r3`, `video-db/open-record-replay`, `pierreolivierbonin/verbatimeter` — all small, new,
independent tools whose only job is to **not trust an AI agent's output or actions**. Code review,
shell-command gating, skill verification, groundedness checking. No deterministic edges link them
(all brand new), but each has a semantic edge to a *different* neighbouring project in the same
space — six independent data points converging on one shape.

Full walkthrough: `AGENT_GUARDRAIL_WAVE.md`.

## Known risks and gotchas

**Never run the test suite and the scrape pipeline against the same DB concurrently.** This caused
FK-violation errors twice on 2026-07-26 (`211 passed, 7 errors` and `63 passed, 2 errors`) that
looked like real bugs and were pure lock contention. Serialized, the same suite is fully green.

**671 qwen-authored comprehension cards are live with no review flag.** A direct comparison on the
same evidence found qwen rating an entity `confidence: high` / top maturity rung / zero open
questions, restating a vendor's self-reported benchmark as fact — where a stronger model rated it
`confidence: low`, flagged the claim as single-source, and listed 5 gaps. The failure signature is
mechanically checkable without an LLM: `confidence: high` + empty `open_questions` +
`evidence_breadth = 1`. **Writing that audit check is the highest-value open item.**

**Any new table with an `entities` / `raw_events` / `impact_briefs` FK must be added to
`_CLEAR_TABLES` in `tests/conftest.py`, before the table it references.** This has broken the suite
three separate times.

**Two branches both created migration `0011`** (sanity + community). Resolved by renumbering sanity
to `0012`. If you branch long-lived work, check `alembic heads` before merging.

**Exposure-map financials are placeholders.** Never quote them as real numbers.

## Open items, roughly by value

1. **Card-quality audit check** — the qwen overclaiming problem above. Mechanically detectable.
2. **Comprehend backlog** — 48 momentum-triggered + ~9.8k backlog entities uncarded. Needs Ollama
   installed locally or an Anthropic key; `claude_cli` is confirmed unviable (broken with `--bare`,
   ~$0.07/call without it).
3. **Two missing evidence types** — commitment (jobs) and commercialization (pricing). Four verified,
   free, legally-clean sources are researched and ready in `DATA_SOURCE_OPTIONS.md`. Note the HN
   surface is now Luka's community layer, so coordinate before building anything HN-adjacent.
4. **Email ecosyste.ms about licensing** — zero code, unblocks the dependency-graph integration.
   Their own `/commercial` and `/terms` pages contradict each other on commercial use.
5. **`pts/dl` unit-label bug** — `EvidenceList.tsx` hardcodes the unit, so 38.5M tokens renders as
   "38.5M pts/dl".
6. **Stray files committed to main** — `test.json`, `redit-api.txt`, `explain.txt`,
   `hf-data-collected.txt` look accidental. Worth confirming before deleting.

## Re-run these to refresh this file

```bash
git log --oneline -8
uv run alembic current
uv run seismo doctor

uv run python -c "
from seismo.db import session_scope
from sqlalchemy import text
q = lambda s, x: s.execute(text(x)).scalar()
with session_scope() as s:
    for t in ['raw_events','entities','comprehension_cards','impact_briefs','gate_decisions',
              'content_sanity_checks','entity_community_research','entity_graph_edges',
              'entity_semantic_edges','changes_daily']:
        print(f'{t:28s}', q(s, f'SELECT count(*) FROM {t}'))
    print(dict(s.execute(text('''
        SELECT state, count(*) FROM (
          SELECT DISTINCT ON (entity_id) entity_id, state
          FROM momentum_states ORDER BY entity_id, day DESC
        ) x GROUP BY state''')).all()))
"
```
