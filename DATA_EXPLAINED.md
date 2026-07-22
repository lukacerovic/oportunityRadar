# DATA_EXPLAINED.md

*A complete guide to the Seismograph data platform: what we store, why we store it, how each
source is collected and tracked, what the data lets us achieve, how the app consumes it, and
what we should build next given the data we actually hold.*

Generated: 2026-07-15. Live database snapshot: PostgreSQL 16 (`seismograph`), ~2.1M rows across 23 tables.

---

## 0. The one-paragraph version

Seismograph is a **daily monitor of where technology is *built*** — GitHub, Hacker News, arXiv,
and Hugging Face. It ingests raw activity from those places, resolves it into durable **entities**
(projects, papers, models), tracks each entity's **trajectory through time** (stars, forks,
attention, momentum, maturity), filters the flood down to the handful that clear a **significance
gate**, and for those produces **evidence-linked "impact briefs"** that map a rising technology to
the **revenue lines of 30 public companies** (NVDA, AMD, MSFT, GOOGL, …). The whole system is
**append-only and time-aware**: we can reconstruct exactly what we knew on any past date, which is
what makes the predictions honest and back-testable.

---

## 1. The core design principle: immutable, time-aware layers

Everything below rests on five invariants (from `README.md`, enforced in CI):

1. **Raw events are immutable.** Every event carries `occurred_at` (source time) and `ingested_at` (our time).
2. **Every downstream computation takes an `as_of`** and may only read events with `occurred_at <= as_of`. This is what lets us re-run the pipeline "as if it were March 3rd" and prove a prediction wasn't hindsight.
3. **LLM calls are quarantined** to `src/seismo/checkpoints/` only.
4. **Separation of concerns:** collectors never reason; scorers never fetch; checkpoints never decide what gets attention.
5. **Everything is logged** with its inputs — every merge, gate decision, and brief.

The data is organised into **six layers**, and the tables map directly onto them:

```
Layer 1  RAW OBSERVATIONS   raw_events                         ← what we collect (immutable)
Layer 2  DURABLE THINGS     entities, entity_links, merges,    ← what those events are ABOUT
                            category_history, themes
Layer 3  TRAJECTORY         entity_metrics_daily,              ← how each thing moves over time
                            momentum_states, maturity_promotions
Layer 4  COMPREHENSION      comprehension_cards                ← what each thing IS (LLM)
Layer 5  SIGNIFICANCE       gate_decisions, changes_daily      ← what deserves attention
Layer 6  IMPACT             impact_briefs, brief_scores        ← the "so what" for markets
         REFERENCE          exposure_companies, reach_links    ← the market map
         BOOKKEEPING         collector_runs, pipeline_runs,     ← operational audit trail
                            hindcast_runs, calibration_snapshots
```

---

## 2. What we store, table by table

### Layer 1 — Raw observations

#### `raw_events` — **22,607 rows** · the immutable ground truth
Spans **2026-01-12 → 2026-07-15**. Every observation from every source lands here first, with the
**full source payload preserved verbatim as JSONB**. Nothing is ever mutated or deleted.

| Column | Meaning |
|--------|---------|
| `source` | `github` / `hn` / `arxiv` / `seed` (soon `hf`) |
| `source_event_uid` | de-dup key, e.g. `repo_discovered:1294821660` |
| `event_type` | `repo_discovered`, `repo_snapshot`, `story`, `paper_published`, `seed_anchor`, `repo_readme` |
| `occurred_at` | when it happened at the source |
| `ingested_at` | when we saw it |
| `origin` | `live` (22,412) or `seed` (195 bootstrap anchors) |
| `payload` | the raw JSON blob |

Current composition:

| Source | Events | Event types |
|--------|--------|-------------|
| **github** | 18,015 | `repo_discovered` (10,590), `repo_snapshot` (7,385), `repo_readme` (40) |
| **hn** | 2,397 | `story` |
| **arxiv** | 2,000 | `paper_published` |
| **seed** | 195 | `seed_anchor` |

**Why we store it:** this is the single source of truth and the reason the system can be trusted.
Because raw events are never overwritten, any bug in a scorer or a bad LLM call can be fixed and the
entire downstream stack rebuilt from scratch, deterministically. It's also what powers **hindcast**
(§7): the same production code runs over old events at old `as_of` dates.

---

### Layer 2 — Durable entities (the "things")

Raw events are noise; entities are the signal. One entity is one real-world thing that many events
refer to.

#### `entities` — **13,915 rows**

| Entity type | Count |
|-------------|-------|
| project | 11,815 |
| paper | 2,078 |
| model | 21 |
| org | 1 |

Auto-categorised into ~30 functional categories: `agent-framework` (3,428), `rag-framework`
(1,626), `eval-tooling` (621), `inference-runtime` (613), `code-assistant` (582),
`model-efficiency` (508), `multimodal-model` (482), `model-foundation` (405), … and 4,024 still
`uncategorized`. Each entity has a `tracking_tier` (`active` / `slow` / `archived`) so the system
can bound how many things it re-observes daily.

#### Supporting identity/graph tables (all time-versioned so the graph is rebuildable at any `as_of`):
- **`entity_links` — 22,058** — connects an entity to the events that justify it, with a `rule` and a `confidence`. Carries `evidence_occurred_at` so the graph can be rebuilt as of any date.
- **`entity_merges` — 5** — append-only, **reversible** dedup records ("these two entities are the same"). As-of code reads this, never the `entities.merged_into` convenience column.
- **`entity_merge_queue` — 7** — candidate merges awaiting a confidence threshold or human decision.
- **`entity_category_history` — 13,944** — the category an entity had *at each point in time* (categories drift; cohorts and reach depend on the value *as of* the date being analysed).
- **`themes` — 15** + **`entity_themes` — 13,943** — cross-cutting topic tags on entities.

**Why we store it:** entities are the spine the whole product hangs on. A trajectory, a comprehension
card, a gate decision, and a brief are all *about an entity*. The time-versioning exists because
without it, an as-of analysis would silently use *today's* category/merge state and cheat.

---

### Layer 3 — Trajectory (how each thing moves)

This is the largest data by volume — the daily heartbeat of every tracked entity.

#### `entity_metrics_daily` — **269,311 rows** · the raw time-series
Long-format `(entity_id, metric, day) → value`. Metrics currently tracked:

| Metric | Rows | Span | What it is |
|--------|------|------|------------|
| `evidence_breadth` | 247,849 | Jan → Jul | # of distinct evidence sources backing the entity |
| `gh_stars` | 7,499 | Jul 11 → 15 | GitHub star *level* (re-observed, not diffed) |
| `gh_forks` | 7,499 | Jul 11 → 15 | GitHub fork *level* |
| `hn_points_7d` | 6,464 | Feb → Jul | rolling 7-day Hacker News attention |

(Designed to also hold `hf_downloads_30d` once the HF collector's data flows.)

#### `momentum_states` — **785,961 rows** · the classified daily state
For every entity, every day, a momentum tier with hysteresis (see §5 for the algorithm):

| State | Rows | Meaning |
|-------|------|---------|
| `dormant` | 782,442 | flat / no signal |
| `accelerating` | 2,891 | sustained rise |
| `simmering` | 396 | early stir |
| `breakout` | 232 | strong, broad-based surge |

Each row stores the `score` and the `inputs` JSONB (the raw signals `P`, breadth, counts behind the
classification) so any state is auditable.

#### `maturity_promotions` — **12,821 rows** · the lifecycle ladder
Append-only record of each rung an entity has climbed. Rungs (from `trajectory/ladder.py`):
`idea_paper` → `public_code` → `usable_artifact` → `distribution`, with `commercialization` and
`institutional_adoption` reserved for when pricing/jobs collectors ship. A reached rung is **never
withdrawn** — a project can *fade* (a momentum state) but it does not *un-ship*.

**Why we store it:** momentum answers *"is this heating up right now?"* and maturity answers *"how
far along is it?"* — two orthogonal axes. A paper can be accelerating but still `idea_paper`; a tool
can be `distribution`-stage but dormant. The gate needs both. Storing the full daily series (not just
the latest) is what makes the sparklines, the back-testing, and the "peak state this week" logic
possible.

---

### Layer 4 — Comprehension (what each thing *is*)

#### `comprehension_cards` — **96 rows** · structured LLM understanding
For entities that warrant it, an LLM reads an evidence pack and emits a **strictly-validated JSON
card**: `what_it_is`, `function`, `who_is_behind`, `category` (+ `category_disputed`),
`maturity_stage`, `claimed_advantage`, `replaces_or_enables`, `confidence`, `open_questions`, and
`evidence_refs` (pointers back to raw events). Each card is versioned and records its `model`,
`cost_usd`, and `status`. Most so far ran on the `mock`/local providers ($0), so many fields honestly
read *"not established by evidence."*

**Why we store it:** this is the bridge from *signals* to *meaning*. The gate and the brief need to
know what a thing actually does, and the `evidence_refs` keep every claim traceable to a raw event —
no ungrounded hallucinations.

---

### Layer 5 — Significance (what deserves attention)

#### `gate_decisions` — **809 rows** · the weekly filter
A weekly arithmetic gate over three components (see §5). It is deliberately brutal:

| Decision | Count |
|----------|-------|
| `suppressed` | 804 |
| `pass` | 5 |

Every decision — pass or suppress — stores the full `components` JSONB breakdown, so the gate is
fully auditable ("why was this suppressed? → `unmapped_reach`").

#### `changes_daily` — **4,577 rows** · the human-readable changelog
Plain-language daily diffs, e.g. *"Online Data Selection Is Implicit Alignment survived the 7-day
gate."* Kinds include `new_entity`, state transitions, etc. This is what a daily digest reads from.

**Why we store it:** attention is the scarce resource (both human and LLM budget). The gate exists to
protect it — turning 13,915 entities into ~5 briefs/week. Persisting every suppress decision with its
reasoning is what builds *trust* in the gate and generates the "map-gaps" list that tells us where the
exposure map needs to grow.

---

### Layer 6 — Impact (the market "so what")

#### `impact_briefs` — **11 rows** · the flagship deliverable
For a gated entity, a structured, evidence-linked thesis mapping the technology to public-company
revenue. Versioned, with `model`/`cost_usd`/`status` (`draft`/`failed`/`reviewed`). Each brief JSONB
contains: `summary`, `horizon`, `confidence`, `mechanisms`, `exposures[]` (ticker/sector + revenue
line + direction + magnitude), a `transmission_path[]` (from technology → company → revenue line),
`observables[]` (what to watch to confirm/refute), and a `counter_mechanism` (why it might *not* play
out). This is the intellectual core of the product.

#### `brief_scores` — **0 rows** · accuracy ledger (wired, not yet populated)
Where each brief eventually gets graded: did the predicted observable materialise? did a falsifier
trip? This is how the product proves it's calibrated over time.

**Why we store it:** this is the product's reason to exist — converting "a new agent framework is
trending" into "here is the specific, falsifiable way it could touch CRM's subscription revenue, on a
3-year horizon, and here's what would prove me wrong."

---

### Reference data — the market map

#### `exposure_companies` — **30 rows** · the watchlist
Curated public tech companies, grouped by sector, each with a `doc` JSONB describing its revenue
lines and threat surface:
- **semiconductors:** NVDA, AMD, ASML, TSM, ARM, AVGO
- **software-infrastructure:** MSFT, ORCL, NET, MDB, DDOG, CFLT, DOCN
- **software-application:** CRM, ADBE, PLTR, NOW, SNOW, INTU, SHOP, TEAM, U, WDAY, PATH
- **interactive-media:** GOOGL, META · **internet-retail:** AMZN · **consumer-hardware:** AAPL · **networking:** ANET · **security:** CRWD

#### `reach_links` — **133 rows** · category → revenue-line map
The rules that connect a *technology category* to a *company revenue line* and a *relation*
(`enablement` / `substitution_partial` / …), with a `core` flag. Examples:
`rag-framework → GOOGL search_advertising (substitution_partial, core)`,
`on-device-runtime → AAPL iphone (enablement)`,
`observability → DDOG subscription (enablement)`,
`model-foundation → ASML euv_systems (enablement)`.

**Why we store it:** this is the domain knowledge that turns a tech signal into a market thesis. It's
loaded from versioned YAML (`exposure_map/`), and the gate's **reach** component is computed directly
from it. When an entity's category has *no* reach link, the gate flags `unmapped_reach` — deliberately
forcing the map to grow.

---

### Bookkeeping — the operational audit trail

- **`collector_runs` — 51** — every collection run: source, timing, `ok`, `events_new`, `error`. (Latest: github pulled 1,447 new events tonight, 2026-07-15 22:05.)
- **`pipeline_runs` — 134** — every pipeline stage execution with its `as_of`.
- **`hindcast_runs` — 0** — the regression ledger (wired, not yet run): does today's code, run over old history, still reproduce a known case?
- **`calibration_snapshots` — 2** — accuracy metrics over time (`breakout_survival`, `fade_reaccel`) — currently empty samples.

**Why we store it:** operability and honesty. When a source breaks or a run is skipped, the trail
shows it. Hindcast + calibration are how the system earns the right to say "our breakouts survive X%
of the time."

---

## 3. How we collect and track each source

Each source has its own collector in `src/seismo/collectors/`. Every collector does two distinct
jobs — **discover** (find new things in a time window) and **track** (re-observe things we already
know) — and each provides a distinct *type of evidence*.

### GitHub (`github.py`) — *participation evidence*
- **Discover:** the Search API (`/search/repositories`) for repos created in the window under broad topic seeds (`llm`, `agents`, `rag`, `inference`, `ai-agents`), 3 pages × 100 each, plus late-discovery of risers. → `repo_discovered` events.
- **Track:** a daily `repo_snapshot` (stars, forks, size, …) for every known repo — this is what feeds `gh_stars`/`gh_forks` as **levels** (re-observed, never diffed as counters).
- **Enrich:** `repo_readme` (bounded to 20k chars) for the comprehension pack.
- **Auth:** optional `SEISMO_GITHUB_TOKEN` — 10 req/min unauth, 30 auth. Rate-limited at ~2s between calls. This is our highest-volume source (18k events).

### Hacker News (`hn.py`) — *attention evidence*
- **Discover only** (HN doesn't need tracking — points are captured at story time). Uses the free Algolia `search_by_date` API, no key, **fully historical** — which makes it the *hindcast workhorse*.
- **Capture strategy:** URL-based (higher precision) for stories linking to `github.com`, `arxiv.org`, `huggingface.co`, plus a keyword net (`llm`, `agent`, `inference`, `rag`, `transformer`, …), above a `POINTS_FLOOR` of 50. → `story` events feeding `hn_points_7d`.

### arXiv (`arxiv.py`) — *capability-claim evidence*
- **Discover only.** The export API (Atom/XML), across 10 categories (`cs.AI`, `cs.CL`, `cs.LG`, `cs.SE`, `cs.IR`, `stat.ML`, `cs.CR`, `cs.MA`, `cs.CV`, `cs.DC`), sorted by submission date. Polite ~1 req/3s. → `paper_published` events.
- **Bonus:** the paper `comment` field often carries the GitHub link — gold for identity resolution (linking a paper entity to its code entity).

### Hugging Face (`hf.py`) — *usage evidence* (collector shipped; data still flowing in)
- **Discover:** the public Hub API for models with a relevant pipeline tag AND real traction (`DOWNLOADS_FLOOR` 1000, `LIKES_FLOOR` 10) — because the Hub creates thousands of near-empty clones daily, a pipeline tag alone is not signal.
- **Track:** `downloads` as the `hf_downloads_30d` metric (a rolling 30-day *level*). `createdAt` also promotes the `usable_artifact` maturity rung and is natively historical (feeds the hindcast birth loader).

### Seed / backfill
- **`seed_anchor`** (195 events, origin=`seed`) bootstraps identity with known anchors.
- **`backfill_gharchive.py`** replays historical GH Archive data for hindcast.

**How runs are orchestrated:** `collectors/runner.py` + `registry.py` + `targets.py` drive a daily
window, dedup by `source_event_uid`, and write one `collector_runs` audit row per run. A `Window` +
`RateLimiter` + shared `httpx` client keep every source polite and reproducible.

**The four evidence types, deliberately:** participation (GitHub), attention (HN), capability-claim
(arXiv), usage (HF). Any one alone is gameable; together they cross-validate — which is exactly what
`evidence_breadth` measures and what the gate rewards.

---

## 4. Why we store all of this — the core value of the data

The value is **not** any single table — it's the **time-aware chain** from raw signal to falsifiable
market thesis:

1. **We can reconstruct the past exactly.** Immutable events + as-of computation mean we can prove what we knew on any date. No other competitor position can be back-tested honestly; ours can (hindcast).
2. **We compress an unmanageable firehose into a handful of decisions.** 22.6k events → 13.9k entities → ~5 gate passes/week → briefs. The value is the *funnel*, and the fact that every narrowing step is logged and auditable.
3. **We connect two worlds that normally don't talk.** Open-source build activity (GitHub/arXiv/HF/HN) ↔ public-market revenue lines (30 companies). The `reach_links` map is proprietary domain knowledge.
4. **Every claim is grounded.** `evidence_refs` chain every card and brief back to immutable events. This is the difference between "an LLM thinks…" and "here is the evidence, at this date."
5. **It compounds.** Every day adds another slice to 786k momentum readings and 269k metric points. Trajectory data only gets more valuable — you can't back-fill attention you didn't capture.

**In one line: the core value is a defensible, back-testable early-warning system that turns where
technology is being built into specific, falsifiable predictions about public-company revenue.**

---

## 5. The algorithms the data feeds (analyses we currently have)

### Momentum classification (`trajectory/states.py`)
Four tiers — `dormant → simmering → accelerating → breakout` — with **hysteresis** (promotion needs
the entry condition sustained; demotion needs the exit condition for 7 consecutive days) so states
don't flap. `fading` is a special overlay (was ≥ simmering, now below the fade floor 14 days, or
inactive 30 days). New entities in a cold cohort are **capped at `simmering`** during warm-up — you
can't manufacture a breakout from three data points. Breakout requires either ≥2 maturity promotions
in 30 days, or a top-percentile signal *with* sufficient evidence breadth.

### Maturity ladder (`trajectory/ladder.py`)
Event-triggered, idempotent, monotonic promotions up the rungs. Recorded with the exact evidence
event that triggered each rung.

### The significance gate (`significance/gate.py`)
Weekly, arithmetic, and transparent:
```
Score = M × (0.4 + 0.6·R) × (0.4 + 0.6·N)
```
- **M (Momentum):** the week's peak state (breakout=1.0, accelerating=0.7) scaled by peak signal `P`.
- **R (Reach):** from the exposure map. **Zero reach = hard exclusion** (never scored, → `unmapped_reach`, → map-gaps list). Among eligible entities R ∈ {0.5, 1.0} (1.0 if it touches a `core` line or ≥3 lines).
- **N (Novelty):** cohort-relative — fast movers in a *sparse* category score ~0.6; crowded-category clones score ~0.3 even when fast.

Top-K (`briefs_per_week`) of the eligible set pass. Every entity gets an audit row.

### Impact reasoning (`checkpoints/impact.py`, `impact_pack.py`)
Assembles an evidence pack (card + trajectory + reach links + company docs) and an LLM emits the
strict brief schema, including the `transmission_path` and `counter_mechanism`.

### Hindcast & calibration (`hindcast/`, `memory/calibration.py`)
Pinned validation cases replay the *production* pipeline over backfilled history at past `as_of`
dates and assert the case still reproduces (or still suppresses). Calibration snapshots track whether
breakouts actually survived.

---

## 6. How the data is used in the app (in detail)

There are two surfaces: a **FastAPI backend** (`src/seismo/api/app.py`) that reads the tables, and a
**Next.js dashboard** (`dashboard/`) that renders them.

### API endpoints → what they serve

| Endpoint | Reads from | Purpose |
|----------|-----------|---------|
| `GET /health` | `collector_runs`, `pipeline_runs` | is the pipeline green? |
| `GET /radar` | `entities` + `momentum_states` + `entity_metrics_daily` | the main board: rising entities, filterable |
| `GET /entities/{id}` | almost everything | full **dossier**: metrics series, momentum history, maturity ladder, card, brief |
| `GET /queue` | `entity_merge_queue` | pending merge decisions |
| `POST /queue/...` | `entity_merges` | resolve a merge |
| `GET /gate/{week}` | `gate_decisions` | the week's pass/suppress list with component breakdown |
| `GET /briefs`, `GET /briefs/{id}` | `impact_briefs` | list + full brief |
| `POST /briefs/...` | `impact_briefs`, `brief_scores` | review/score a brief |
| `GET /changes/{day}` | `changes_daily` | the daily changelog |
| `GET /calibration` | `calibration_snapshots` | accuracy over time |
| `GET /briefs/{id}/score-packet` | brief + observables | the packet a human uses to grade a brief |
| `GET /search` | `entities` | find an entity |

### Dashboard components → what they render (`dashboard/components/`)
- **`Sparkline` / `MetricChart`** ← `entity_metrics_daily` (stars/forks/HN points over time).
- **`StateChip`** ← `momentum_states` (the current dormant/…/breakout badge).
- **`MaturityLadder`** ← `maturity_promotions` (which rungs are lit).
- **`CardPanel`** ← `comprehension_cards` (what it is / who's behind it / claimed advantage).
- **`EntityCard`** ← the `/radar` and `/entities` join.
- **`BriefActions` / `BriefScoring`** ← `impact_briefs` + `brief_scores` (read the thesis, grade it).
- **`Kpi`** ← health/counts. **`InfoModal`** (`lib/help.ts`) ← per-field explanations.

### A concrete end-to-end walkthrough
Take entity **#2857 — "Linear Attention Architectures" (arXiv paper)**:
1. **Collected:** arXiv `paper_published` event → `raw_events`, payload with title/authors/abstract.
2. **Resolved:** became entity #2857, `entity_type=paper`, category `inference-runtime`, linked via `entity_links` to its raw event; the GitHub link in the paper `comment` could merge it with a code entity.
3. **Tracked:** daily `evidence_breadth`; if it trends on HN, `hn_points_7d` climbs; `momentum_states` classifies it each day.
4. **Comprehended:** a `comprehension_card` (v1) recorded `maturity_stage=idea_paper`, `category=inference-runtime`, `evidence_refs=[710]`.
5. **Gated:** its category maps (via `reach_links`) to semiconductors → it can be scored.
6. **Briefed:** three brief versions (`ollama qwen2.5 3b→7b`) produced a thesis: *linear-attention architectures → AMD datacenter revenue, direction ambiguous, magnitude marginal, 3y+ horizon,* with a `transmission_path` (paper → AMD → AMD `datacenter` line), an `observable` ("how fast do cloud providers adopt this"), and a `counter_mechanism` (AMD's chiplet cost advantage).
7. **Surfaced:** appears in `/briefs`, rendered by `BriefActions`, ready for a human to grade via `/briefs/2857/score-packet`.

The **5 entities that actually passed the gate** so far: `hmbown/codewhale` (inference-runtime),
`affaan-m/ecc` (workflow-orchestration), `rtk-ai/rtk`, `sickn33/agentic-awesome-skills`,
`waooai/waoowaoo` (all agent-framework) — each score ≈ 0.406.

Recent **breakouts** (2026-07-15) include `jamiepine/voicebox`, `kiliczsh/genui` (agent-framework),
`clear-sights/makoto` (guardrails) — several still `uncategorized`, which is itself a signal that the
categoriser needs attention (see §8).

---

## 7. What we can achieve with this data

Given what we hold, the platform can already (or can readily) support:

- **Understand** — for any entity: what it is, who's behind it, how mature, how it relates to markets — all evidence-grounded.
- **Monitor** — a live radar of rising build activity across four ecosystems, refreshed daily.
- **Detect early** — breakout classification surfaces surges *before* they're obvious, with hysteresis to avoid false alarms.
- **Filter** — the gate turns 13.9k entities into a handful worth human attention, with full reasoning.
- **Predict** — falsifiable impact briefs tying tech to specific company revenue lines and horizons.
- **Track over time** — 786k momentum readings + 269k metric points give trajectory, not just snapshots.
- **Back-test** — hindcast replays the exact pipeline over history; calibration quantifies hit-rate.
- **Find map gaps** — `unmapped_reach` suppressions tell us exactly where the market map is blind.

---

## 8. What we should add — driven by the data we actually have

Prioritised by the *quality and shape of the data we already possess*:

### High priority — the data is there, the layer is thin
1. **Real LLM cards & briefs.** 96 cards and 11 briefs, almost all `mock`/`ollama` — so most fields read "not established by evidence." The evidence packs are rich; switching checkpoints to the `anthropic` provider is the single biggest quality unlock. (11 briefs is proof-of-concept, not product.)
2. **Populate hindcast & calibration.** `hindcast_runs` = 0, `brief_scores` = 0, `calibration_snapshots` = empty samples. We have 6 months of immutable history — we can back-test *today*. Without this we can't claim the predictions are calibrated, which is the whole differentiator.
3. **Fix the categoriser.** 4,024 entities `uncategorized`, and several *breakouts* are uncategorized — meaning our highest-signal entities can't be gated (no category → no reach → excluded). This directly caps the funnel's output.

### Medium priority — extend coverage the schema already anticipates
4. **Land HF metrics in the series.** The collector ships but `hf_downloads_30d` isn't yet in `entity_metrics_daily`; usage evidence is the one cross-check we're thinnest on.
5. **Grow the reach map from the gaps list.** Only 133 links / 30 companies. The `unmapped_reach` suppressions are a ready-made backlog of exactly which categories need mapping.
6. **The reserved maturity rungs.** `commercialization` (pricing) and `institutional_adoption` (jobs) are declared but need their collectors — they'd make the ladder far more predictive of real-world adoption.

### Lower priority — depth once the core is proven
7. **Automated brief scoring loop** — close the `observables → brief_scores` cycle so calibration self-updates.
8. **More sources** — PyPI/npm downloads (the README's stated ambition) would add a second usage signal.
9. **Cohort analytics** — with 786k momentum rows we can compute category-level base rates (what % of `agent-framework` breakouts survive 30 days?) to sharpen the novelty component.

---

## 9. Summary table — the whole database at a glance

| Table | Rows | Layer | Role |
|-------|-----:|-------|------|
| `raw_events` | 22,607 | 1 | immutable observations (github/hn/arxiv/seed) |
| `entities` | 13,915 | 2 | durable things (projects/papers/models) |
| `entity_links` | 22,058 | 2 | entity ↔ evidence |
| `entity_category_history` | 13,944 | 2 | time-versioned category |
| `entity_themes` | 13,943 | 2 | topic tags |
| `entity_merges` / `_queue` | 5 / 7 | 2 | reversible dedup |
| `themes` | 15 | 2 | topic vocabulary |
| `entity_metrics_daily` | 269,311 | 3 | daily metric time-series |
| `momentum_states` | 785,961 | 3 | daily momentum classification |
| `maturity_promotions` | 12,821 | 3 | lifecycle ladder |
| `comprehension_cards` | 96 | 4 | LLM structured understanding |
| `gate_decisions` | 809 | 5 | weekly significance filter (5 pass) |
| `changes_daily` | 4,577 | 5 | human-readable changelog |
| `impact_briefs` | 11 | 6 | market-impact theses |
| `brief_scores` | 0 | 6 | accuracy ledger (empty) |
| `exposure_companies` | 30 | ref | public-company watchlist |
| `reach_links` | 133 | ref | category → revenue-line map |
| `collector_runs` | 51 | ops | collection audit trail |
| `pipeline_runs` | 134 | ops | pipeline audit trail |
| `hindcast_runs` | 0 | ops | regression ledger (empty) |
| `calibration_snapshots` | 2 | ops | accuracy over time (empty samples) |

*Everything above is reconstructable from `raw_events` alone — which is the point.*
