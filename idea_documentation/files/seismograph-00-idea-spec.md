# Seismograph — Idea Specification (v1)

*Working name: **Seismograph** — a market crash is the earthquake; this instrument reads the foreshocks. Rename at will (open decision, §13).*

*Status: Phase 1 output. This document pins down WHAT the system is and WHY each part exists. It deliberately makes no technology choices. Phase 2 derives the technical architecture from this spec.*

---

## 1. What this is

Seismograph is a daily monitoring and analysis system over the places where technology is **built** rather than reported — GitHub, arXiv, Hugging Face, PyPI, Hacker News, Reddit, job boards, changelogs, and pricing pages. It maintains a living picture of the technology frontier, tracks every emerging entity through time, and, for the entities that cross a significance bar, produces explained impact analyses: which industries, markets, and listed companies are exposed, through what mechanism, in which direction, and what to watch to know whether the thesis is holding.

It serves two goals:

1. **Awareness** — stay accurately informed about what is emerging and in which direction the field is moving.
2. **Consequence** — understand the economic impact pathways of what is emerging: which fields, markets, and companies are affected, and why.

**Explicit non-goals.** Seismograph is an analyst, not a scout and not a trader. It does not source startups or deals. It does not generate trading signals, and it never predicts prices or the timing of market moves. Its unit of value is a correct, auditable explanation, delivered while it is still early.

---

## 2. Purpose → design consequences

Four consequences follow directly from the purpose and hold everywhere in the system:

**Daily heartbeat.** One collection-and-analysis run per day. No streaming, no intraday racing. The system's edge is understanding weeks-to-months ahead of the mainstream narrative, not hours ahead of a price move.

**Explanation-first.** Every output must be human-legible and evidence-linked. A claim without a traceable chain back to raw observations does not ship. Quality of reasoning beats speed everywhere.

**Exposure, not prices.** The impact layer explains who is exposed and through what mechanism. It never forecasts what a stock will do or when.

**Attention-budgeted.** The reader can deeply process only a handful of items per week. All outputs are ranked against a fixed attention budget; the system earns trust by what it *doesn't* surface.

---

## 3. The product: one dashboard, four views

The primary interface is a web dashboard, refreshed by the daily run. Its four views are four projections of the same underlying knowledge:

**Radar (field view).** Themes and their member entities, each with a momentum state. Answers: *what is going on, and in which direction is the field moving?*

**Dossiers (entity view).** One page per entity: what it is, who is behind it, what it claims, its full event timeline, current maturity stage and momentum state. Answers: *give me context and explanation for this thing.*

**Impact Briefs (consequence view).** Structured exposure analyses for entities that passed the significance gate. Answers: *who does this affect, how, and what would prove or disprove it?*

**Changes (time view).** The daily/weekly delta: what appeared, what accelerated, what faded, which prior briefs were revised or scored. Dashboards show *state*; this view shows *change* — the system telling you when its beliefs moved.

---

## 4. Core ontology

Five object types, with strict promotion rules between them:

| Object | Definition | Mutability |
|---|---|---|
| **Event** | A single timestamped observation from a source ("repo X gained 400 stars on date D", "paper P published"). | Immutable, never interpreted at ingest |
| **Entity** | The durable thing events attach to: project/tool, model, paper/technique, organization, person. | Long-lived, accumulates biography |
| **Theme** | A named cluster of entities ("efficient inference", "agent tooling"). First-class object — direction-of-field questions are theme questions. | Curated + assisted |
| **Momentum state** | Legible classification of an entity's trajectory (§8). | Recomputed daily |
| **Impact thesis** | Structured claim linking a significant entity to exposed parties via a named mechanism (§7). | Versioned, scored over time |

**Evidence types.** Sources are classified by what they *testify to*, because corroboration across evidence types is worth far more than volume within one:

| Evidence type | What it proves | Example sources |
|---|---|---|
| Attention | The discourse noticed | Hacker News, Reddit, X |
| Participation | People are contributing effort | GitHub stars/forks/contributors |
| Usage | People actually run it | Hugging Face downloads, PyPI/npm installs |
| Commitment | Organizations are spending money on it | Job postings, enterprise case studies |
| Commercialization | Someone is charging for it | Pricing pages, API launch announcements |

---

## 5. The seven layers

### Layer 1 — Observation
*Core question: what happened today at each source?*

Collectors poll each source on the daily run and record raw events — timestamped, source-attributed, uninterpreted. Observation is dumb and lossless by design: the interpretive model will improve over time, and re-reading old evidence with new eyes is only possible if the evidence was stored raw. Collectors never reason; they only record.

### Layer 2 — Identity
*Core question: which entity does this event belong to?*

Every event must attach to an entity (or spawn a new one). This is the hardest data problem in the system, because one thing wears many names: DeepSeek-V2 is an arXiv ID, a GitHub org, a Hugging Face repo, a dozen HN threads, and a pricing page — one biography scattered across five registries. Linkage evidence: shared URLs, paper↔code links, author handles, README cross-references, name similarity as a last resort. Ambiguous matches are queued for human confirmation rather than guessed. Entities are also assigned to themes here.

### Layer 3 — Comprehension
*Core question: what is this thing?*

When a new entity appears (or materially changes), produce its comprehension card: category, function, claimed advantage, what it would replace or enable, maturity stage, who is behind it. Output is **structured claims plus a readable summary** — the summary is for the human, the structured claims are what downstream layers compute on. This is a bounded language-model checkpoint: fixed schema in, fixed schema out, with the entity's collected evidence as the only input.

### Layer 4 — Trajectory
*Core question: is this becoming real?*

Three measurements, combined into a momentum state (§8):

1. **Cohort-relative velocity.** Absolute numbers lie across categories; momentum means outpacing entities of the same type and age.
2. **Maturity-ladder promotions.** idea/paper → public code → usable artifact → distribution (package registry) → commercialization (pricing) → institutional adoption. Crossing a stage is stronger evidence than growing within one, because each promotion means a different kind of commitment materialized.
3. **Corroboration breadth.** How many independent evidence types are currently active. An HN spike alone is marketing; HN + PyPI growth + job postings is adoption.

Plus **survival gates**: does the entity still clear its bar 30/60/90 days later? Most things die; persistence is signal.

### Layer 5 — Significance
*Core question: does this deserve the reader's attention now?*

A fixed budget (starting point: ≤5 new impact briefs per week, ≤1 breakout call-out per day — tunable, §13) forces ranking instead of spam. Significance = momentum × economic reach (does it plausibly touch the exposure map?) × novelty (a new capability class, or the 400th RAG framework?). Entities below the bar keep being tracked silently — nothing is thrown away, it just doesn't interrupt.

### Layer 6 — Impact
*Core question: who is exposed, and through what mechanism?*

For entities that pass the gate, produce an impact thesis constrained by two structures: the **exposure map** (§6) and the **mechanism taxonomy** (§7). The language-model checkpoint here fills a fixed schema — it never free-associates. The system explains exposure; it does not predict prices.

### Layer 7 — Memory & synthesis
*Core question: how did the worldview change?*

Theme narratives get updated as entities move through them. Old briefs are revisited and scored: did the exposure materialize, did a falsifier trip? The Changes view reports deltas in belief, not just new items. This is what separates Seismograph from every newsletter: it remembers what it believed and tells you when its beliefs change.

---

## 6. The exposure map (public-markets edition)

The impact layer cannot name affected companies without a representation of who sells what. The exposure map is that representation. It is the system's compounding long-term asset, and it is deliberately small and hand-curated at the start.

**Universe.** Listed technology companies and megacaps, roughly 30–50 names at v1 (final list: open decision, §13). Illustrative categories: semiconductors and hardware (NVDA, AMD, TSM, AVGO, ASML); hyperscalers and platforms (MSFT, AMZN, GOOGL, META, AAPL); software incumbents most substitutable by AI (ADBE, CRM, NOW, TEAM, WDAY); data and infrastructure (SNOW, MDB, DDOG, NET); plus a handful of category-specific names as themes demand.

**Structure per company:**

- **Revenue lines**, taken from disclosed segment reporting (10-K segments, earnings-call framing) — this grounds every thesis in auditable public filings.
- **Dependencies and inputs** — what the company consumes (compute, models, distribution channels, developer attention).
- **Threat surface** — what could substitute for each revenue line, and what the company's moat actually is.
- **Sensitivity notes** — free-form analyst notes on where the map-maintainer believes fragility sits.

**Private companies.** Private companies (Anthropic, OpenAI, and every startup Seismograph monitors) exist as *entities* and appear inside transmission chains, but final exposure statements resolve to listed names or sector-level classes. Example: a token-efficiency tool's threat to Anthropic is expressed through listed proxies and backers (GOOGL, AMZN) or as a class statement ("per-token API revenue models").

**Maintenance.** Each name is touched at least quarterly, with earnings season as the natural refresh trigger. A stale map is one of the five failure modes (§11).

---

## 7. Mechanism taxonomy and the impact-brief schema

Every impact thesis must name at least one transmission mechanism from a closed taxonomy:

1. **Substitution** — a cheaper or better replacement for something people currently pay for. (Token-efficiency tooling vs. premium model plans.)
2. **Cost-structure collapse** — an input cost drops sharply, eroding a margin or a moat. (DeepSeek-class training efficiency vs. the frontier-capex thesis.)
3. **Layer commoditization** — a differentiated layer becomes open or standard; value migrates up or down the stack. (Open weights commoditizing the model layer, shifting value to inference infra and applications.)
4. **Enablement / demand creation** — a new capability makes previously non-viable use cases viable, creating demand somewhere else in the chain.
5. **Dependency & concentration risk** — an entity becomes load-bearing for many others; its failure, capture, or repricing propagates.

**The impact-brief schema.** Mechanism(s); explicit transmission path traced through the exposure map (entity → capability change → affected revenue line); affected parties (listed names or sector classes); direction and rough magnitude class; confidence; **the strongest counter-mechanism, stated fairly**; observables and falsifiers with a horizon; evidence links back to raw events.

The counter-mechanism field is mandatory because first-order stories are cheap. The canonical example: substitution says token-efficiency tooling shrinks spend per customer; the counter-mechanism is Jevons — cheaper effective tokens make more agent use cases viable and total volume may rise. A brief stating only one side is marketing; a brief stating both, with observables that would settle the disagreement ("average tokens per active customer over the next two quarters"), is intelligence.

---

## 8. Momentum states

The trajectory layer classifies every entity into a legible state, recomputed daily:

| State | Rough definition |
|---|---|
| **Dormant** | Exists; no meaningful activity in the window |
| **Simmering** | Steady above-cohort growth in one evidence type, no promotions |
| **Accelerating** | Above-cohort velocity in ≥2 evidence types, or a fresh maturity-ladder promotion |
| **Breakout** | Multiple promotions and/or top-percentile velocity with ≥3 evidence types active |
| **Fading** | Previously active; velocity below cohort and evidence types going quiet |

States, not raw scores, are the public interface of trajectory — the consumer is a reader. Raw scores exist underneath for ranking and for the historical record.

---

## 9. Validation

Validation is part of the idea, not an afterthought.

**Hindcasting.** Before trusting the system, replay it against a small case set using only information available at each historical moment:

- **DeepSeek arc** (canonical positive): the system must classify the entity as accelerating/breakout around the V2 release and its aggressive API pricing in May 2024 — many months before the January 2025 repricing, which is the *lagging* confirmation, not the target.
- **One mid-size developer-tool arc** (Graphify-type): detected early, tracked through maturity promotions, brief written at the significance crossing.
- **At least one hyped flop** (true-negative): an entity with a large attention spike that never converted to usage or commitment. The system must *not* have written a brief. A system that flags everything "catches" everything; the negative case is what makes the positive cases meaningful.

**Forward scoring.** Every brief is revisited quarterly: did the exposure materialize, did a falsifier trip, was the counter-mechanism the better story? Momentum calls are reviewed the same way (what fraction of "breakout" entities were still alive 90 days later?). Over a year this produces the rarest thing in this genre: a calibration track record for the reasoning layer itself.

**Collector health.** Sources change their formats and limits constantly. Collector health (last successful run, volume anomalies) is monitored as a first-class concern, because the most dangerous failure is silence that looks like calm.

---

## 10. Scope of v1

- **Observation universe:** the AI and developer-tooling frontier. Chosen because the operator's judgment can validate outputs there, both motivating examples live there, and evidence sources are richest there. Expansion to other tech verticals comes only after the pipeline earns trust.
- **Exposure universe:** listed tech and megacaps, ~30–50 names.
- **Cadence:** one daily run.
- **Interface:** web dashboard with the four views.
- **Data:** public sources only; the system runs on personal infrastructure, fully separate from any employer systems.
- **Explicitly deferred:** other tech sectors, non-US listings, intraday anything, push notifications, multi-user access.

---

## 11. Failure modes and their guards

| Failure mode | Guard |
|---|---|
| Drowning in volume | Significance gate + fixed attention budget |
| Mirroring hype | Corroboration across evidence types; attention alone never promotes |
| Hallucinated causality | Exposure map + closed mechanism taxonomy + mandatory counter-mechanism and falsifiers |
| Silent collector rot | Collector health monitoring as a first-class feature |
| Stale exposure map | Quarterly per-name refresh tied to earnings season |

---

## 12. Design principles (summary)

1. Observation is dumb and lossless; raw events are immutable.
2. The entity, not the news item, is the unit of analysis.
3. Sources are evidence types; corroboration breadth beats amplitude.
4. Stage promotions beat within-stage growth; cohort-relative beats absolute.
5. Language models operate only at bounded checkpoints with fixed schemas (comprehension, impact) — they never collect, never rank, never free-associate.
6. Every claim traces back to raw events; every thesis names its mechanism, its counter-mechanism, and its falsifiers.
7. Attention is budgeted; trust is earned by what is *not* surfaced.
8. The system remembers what it believed and reports when its beliefs change.

---

## 13. Open decisions

1. **Name.** "Seismograph" is the working suggestion; final call is the operator's.
2. **Final v1 exposure-map company list** (~30–50 names) and the per-company template's exact fields.
3. **Hindcast case list** — DeepSeek is fixed; choose the mid-size positive and the flop negative.
4. **Budget numbers** — briefs/week and breakout call-outs/day.
5. **Changes-view cadence** — daily deltas only, or daily deltas plus a weekly synthesis narrative.
6. **Human-in-the-loop** — recommendation: impact briefs are generated as *drafts for review* initially, promoted to auto-publish only after forward scoring shows the layer is calibrated.

---

## 14. What Phase 2 derives from this document

The technical architecture, layer by layer: the data model and storage design implied by §4–5; collector design, scheduling, and rate-limit strategy; the entity-resolution approach and its human-confirmation queue; the exact contracts of the two LLM checkpoints; the scoring computations behind §8; dashboard architecture for the four views; deployment, operations, and collector-health tooling. No stack choices exist yet — Phase 2 begins by deriving requirements from this spec, then chooses.
