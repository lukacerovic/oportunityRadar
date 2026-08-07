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

## Aggregator, not reseller — the distinction that decides what is safe

The instinct to find "one portal with many APIs in a good format" is right. The catch is that two
very different things answer to that description.

**A reseller** sits between you and somebody else's API. `DATA_SOURCE_OPTIONS.md` already rejected
RapidAPI on three concrete grounds, and they still hold: the platform is in run-off since the Nov
2024 Nokia acquisition (peak ~4M users / 40k APIs → "thousands" of users and "hundreds" of active
APIs); every job API on it is an unauthorized scraper, in a field where Proxycurl was made to delete
its entire dataset in 2025; and free tiers reportedly serve cached data rather than erroring, which
is silent degradation this pipeline could not detect. That last one is disqualifying on its own —
"every claim traces to a raw event" cannot survive an unauditable middleman.

**An aggregator** publishes its own normalized dataset and is often the canonical index of the thing
it covers. Provenance is intact because it *is* the source.

The portal this project actually wants is the second kind, and it is already in these docs:

| Aggregator | Covers | Replaces |
|---|---|---|
| **ecosyste.ms** | 109 registries, 293M repos, 14.4M packages, ~5k req/hr, AGPL, non-profit | npm + crates + Docker + much of discovery — **four collectors become one** |
| **deps.dev** | npm, PyPI, Go, Cargo, Maven — dependents, advisories, scorecards | per-registry dependency work |
| **OpenAlex** | scholarly output, CC0 | citation velocity |
| **GH Archive** | every public GitHub event | topic-limited discovery |

**The cheapest action on this entire page has no code in it:** settle the ecosyste.ms licensing
question. `STATE.md` lists it as an open item because their `/commercial` and `/terms` pages
contradict each other on commercial use. One email. If the answer is yes, six separate integrations
collapse into one. If it is no, you learn that before writing a collector instead of after.

---

## Fixing everything on the audit list

Every problem raised in the source audit, with what actually resolves it. Ordered by what unblocks
the most per hour spent, not by severity.

### Today — no code, only wiring

| Problem | Fix |
|---|---|
| Outcomes always `unmeasurable` | Add `track --source pypi` to `daily.sh` |
| `built_by` starved → shared-author check never fires | Add `enrich-contributors` to `daily.sh` |
| `depends_on` starved → dependency check never fires | Add `enrich-pypi` to `daily.sh` |
| Discovery misses untagged repos | Widen `TOPICS` in `collectors/github.py` beyond the current five |
| `entity_community_research` at 0 rows | Run the community layer — it is complete and has never executed |

Half a day, and it turns three of the five audit failures into working paths.

### This week — one email and one probe

| Problem | Fix |
|---|---|
| Six planned integrations, unclear licensing | Email ecosyste.ms. Zero code, largest unlock on the list. |
| Every source verdict is desk research | Run `scripts/probe_sources.py --save`, record each verdict in `DECISIONS.md` |

### The real blocker — semantic linking

| Problem | Fix |
|---|---|
| 283 stale edges → `clusters=0` → no waves at all | Local embedding pass into `pgvector`, written as `entity_semantic_edges` rows with `model="bge-…"` and cosine distance as `confidence_score` |

**Acceptance test before trusting it:** the embedding threshold must reproduce the six-member
guardrail wave. If it cannot, it is not a replacement, and that is a finding rather than a failure.

Keep the LLM pass as an occasional enrichment on top — dense deterministic layer underneath,
judgment layer above.

### Next — the product's core claim

| Problem | Fix |
|---|---|
| Lead time only sees HN titles | `tags=comment` on the same endpoint, **behind** a relevance pre-filter |
| Single commentary source | Build the Substack collector (already a recorded GO) |

The pre-filter is not optional: comments outrun stories by roughly an order of magnitude, every text
event flows through `sanity`'s `$5` ceiling, and `POINTS_FLOOR = 50` cannot apply to comments. A weak
filter here fills the archive with fake foresight, which is the one failure this feature cannot
survive.

### Then — measurement breadth

| Problem | Fix |
|---|---|
| JS waves permanently `unmeasurable` | npm downloads collector — or ecosyste.ms if the licence clears, which covers npm *and* five other registries |
| Downloads are gameable | deps.dev dependent counts as a second adoption metric |

### Calibration — only possible after the above

| Problem | Fix |
|---|---|
| Every threshold is a guess | Run against real data, tune, record each change in `DECISIONS.md` |
| `wave_require_momentum=False` is a workaround | Turn on once momentum has real history |
| No track record to show | Build page C after 3–4 waves have been graded — not before |

### Known and deliberately parked

| Problem | Position |
|---|---|
| Reverse causation in observer scoring | Unsolved. **Do not publish observer track records** until persistence-after-spike is implemented. Waves are unaffected. |
| Replay uses today's semantic graph | Accepted and documented. Filtering derived edges by `created_at` would break replay rather than make it honest. |
| Repo-wide lint/format drift, CI red on `main` | Real but unrelated. Deserves its own formatting-only commit, not a mixed one. |

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
