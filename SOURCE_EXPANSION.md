# Source expansion — where the wave layer's data should come from

*Written 2026-08-07. Companion to `WAVE_PLAN.md` / `LEAD_TIME_PLAN.md`, which describe the engine.
This is about its fuel.*

**Status of every verdict below: desk research, not a live probe.** The container this was written in
blocks outbound connections to most of these hosts at the network-policy layer (`connect_rejected`
for `hn.algolia.com`, `api.npmjs.org`, `api.deps.dev`, `packages.ecosyste.ms`), so nothing here has
been confirmed the way `DECISIONS.md` confirmed Substack and killed Reddit. `scripts/probe_sources.py`
runs that verification locally and writes fixtures. **Probe before building — and drop rather than
work around, exactly as the Reddit and OpenRouter decisions did.**

One live result did get through: `crates.io` returned 200 with real data.

---

## The three blockers, and what would actually fix each

A wave needs three things to exist. Each is currently starved by a different gap.

| Blocker | Symptom today | Root cause |
|---|---|---|
| **1. Linking** | `clusters=0` — no wave ever forms | `entity_semantic_edges` is a one-off manual LLM pass; 283 edges, dated 2026-07-25, no refresh |
| **2. Discovery** | Entities never enter the system | GitHub search covers 5 topics: `llm, agents, rag, inference, ai-agents` |
| **3. Grading** | Everything reads `unmeasurable` | `track --source pypi` is not in `daily.sh`; npm not collected at all |

---

## Blocker 1 — linking. Replace the LLM pass with embeddings.

This is the one that matters most, and the fix is a **category change, not a bigger version of the
same thing.**

Today a wave's membership depends on a model having once judged two things similar. That is
expensive, unrepeatable, and quietly at odds with invariant 4 — the graph the wave reads *is* a
model's judgment, even though the wave stage itself calls no LLM.

**Proposal: a local embedding pass over comprehension cards / READMEs, stored in `pgvector`.**

- Deterministic and repeatable: same text in, same vector out. It can run in `daily.sh`.
- $0 and offline — a local model (`bge-large-en-v1.5` class, 1024-dim) needs no API.
- 18,360 entities is small for pgvector; HNSW indexes handle far more, and the whole thing lives in
  the Postgres you already run rather than a second service.
- Fits the existing table: `entity_semantic_edges` already carries `model` and `confidence_score`,
  so an embedding-derived edge is `model="bge-…"` with cosine distance as the score, sitting beside
  the LLM-derived rows without pretending to be them.

**The honest caveat**, and it is not small: embedding similarity measures *"this text resembles that
text"*, not *"these solve the same problem"*. Two guardrail tools written in different vocabularies
may sit far apart; a tutorial repo and a real tool may sit close. The threshold has to be calibrated
against the known guardrail wave before this is trusted — if it can't reproduce that finding, it
isn't a replacement.

**Recommended shape:** keep both. Embeddings become the dense, daily, deterministic layer; the LLM
pass stays an occasional enrichment on top. `GRAPH_PLAN.md` already floats exactly this and calls it
the open question — this is the answer to it.

---

## Blocker 2 — discovery. The firehose is already half-built.

`collectors/backfill_gharchive.py` exists and streams **GH Archive**, the complete public GitHub
event stream, mapping `CreateEvent` → `repo_discovered` and `WatchEvent` → `repo_star`. It is used
for historical backfill and scoped to target orgs "so a month is tractable, not the firehose".

That is the discovery mechanism you want, pointed at the present instead of the past. Every public
repo creation, with no dependency on the author having tagged their repo `agents`.

Two cheaper steps first, in order:

1. **Widen `TOPICS`.** Five is arbitrary. `mcp`, `evals`, `guardrails`, `agent-tools`,
   `llmops`, `vector-search`, `fine-tuning` are all live GitHub topics. One line, immediate effect.
2. **Keyword pass over GH Archive `CreateEvent`s**, daily window. Heavier (hourly gz files), but it
   is the only route to repos whose authors never set a topic — which is most brand-new repos, and
   therefore exactly the population a wave is made of.

**ecosyste.ms** is the third option and possibly the best value: 293M repos and 14.4M packages across
109 registries, free, ~5,000 req/hr, purpose-built for this. `DATA_SOURCE_OPTIONS.md` already
researched it for the dependency graph. Licensing needs settling first — that doc records their
`/commercial` and `/terms` pages contradicting each other, and the open item is one email.

---

## Blocker 3 — grading. Two changes, one of them nearly free.

**`track --source pypi` is missing from `daily.sh`.** The collector exists and works; it simply never
runs. That alone is why every outcome reads `unmeasurable`. One line.

**npm is not collected at all**, which is the gap `LEAD_TIME_PLAN.md` flags as making JS waves
permanently unmeasurable. `api.npmjs.org/downloads/point/last-week/{pkg}` is free, needs no key, and
mirrors the PyPI collector's shape almost exactly.

### The better adoption metric, and it isn't downloads

**deps.dev (Google Open Source Insights)** publishes **dependent counts** — how many packages depend
on a given package — for npm, PyPI, Go, Cargo and Maven, free and unauthenticated.

That is a materially better signal than downloads for what this product claims:

- Downloads are inflated by CI runs, mirrors, and bots. A package can have millions of downloads and
  no human users.
- A *dependent* is somebody deciding to build on it. It is slow, deliberate, and far harder to game.

Given that this system's whole architectural stance is corroboration-breadth over amplitude, and that
its own competitive research documents millions of fake GitHub stars, a hard-to-game adoption metric
is worth more here than a bigger one.

`crates.io` (verified 200 live) covers Rust with its own download and reverse-dependency counts.

---

## Blocker 3b — lead time. One parameter unlocks the best text you have.

`collectors/hn.py` requests `tags: "story"`. **Hacker News comments are on the same free endpoint,
same shape, via `tags=comment`** — no key, generous limits, fully historical.

This matters more than it sounds. Insight shows up in comments long before it shows up in a title.
The example that motivated this whole feature — someone saying *"nobody is solving this"* under an
unrelated thread — is exactly the shape of event the collector currently cannot see. The lead-time
claim is weakest precisely where comments would make it strongest.

**Two real costs before this ships:**

- **Volume.** Comments outnumber stories by roughly an order of magnitude, and every text event flows
  through the `sanity` checkpoint, which has its own `$5` monthly ceiling. A relevance pre-filter
  (keyword or embedding) has to sit in front of ingestion, not behind it.
- **Noise.** `POINTS_FLOOR = 50` cannot apply — comments rarely carry points. The filter has to be
  content-based, and a bad filter here fills the record with fake foresight.

Also still open from `DECISIONS.md`: **Substack is a recorded GO and was never built.** It is the only
pure-commentary surface in the design and the natural second entry in `observers._SOURCES`.

**Lobsters** is worth probing as a third: small, high signal-to-noise, JSON endpoints, authored and
timestamped.

---

## Priority

| # | Change | Effort | Unblocks |
|---|---|---|---|
| 1 | `track --source pypi` + `enrich-contributors` + `enrich-pypi` into `daily.sh` | 3 lines | grading + 2 of 3 independence checks |
| 2 | Widen GitHub `TOPICS` | 1 line | discovery breadth |
| 3 | HN `tags=comment` + relevance pre-filter | small-medium | lead time — the product's core claim |
| 4 | Embeddings + pgvector for semantic edges | medium | **waves existing at all** |
| 5 | npm downloads collector | small | JS waves stop being unmeasurable |
| 6 | deps.dev dependent counts | medium | a gaming-resistant adoption metric |
| 7 | Substack collector (already GO) | small | second commentary surface |
| 8 | GH Archive as daily discovery | large | untagged repos |

Items 1–3 are a day's work between them and fix the symptoms. **Item 4 is the only one that decides
whether the feature works at all** — everything else improves a system that currently produces zero
waves.

## Before building any of it

```bash
uv run python scripts/probe_sources.py            # live check + fixtures under tests/fixtures/
uv run python scripts/probe_sources.py --json     # machine-readable summary
```

Record the verdicts in `DECISIONS.md` the way the 2026-07-23 market-source spike did — one entry per
source, GO or NO-GO with the evidence, and **drop rather than work around**.

**Sources for the desk research above:**
[ecosyste.ms API](https://ecosyste.ms/api) ·
[deps.dev API announcement](https://blog.deps.dev/api/) ·
[deps.dev v3 features](https://blog.deps.dev/api-v3/) ·
[npm registry API](https://api-docs.npmjs.com/) ·
[HN Algolia API guide](https://cotera.co/articles/hacker-news-api-guide) ·
[pgvector overview](https://supabase.com/docs/guides/database/extensions/pgvector)
