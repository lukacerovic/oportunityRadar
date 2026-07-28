# Competitive landscape — is anyone else building Seismograph?

*Research date: 2026-07-27. Five parallel research passes (~190 web searches) across VC deal-sourcing,
tech-trend radars, AI/OSS monitoring, alt-data investment research, and academic prior art.
Findings are dated — vendors move. Re-check before betting anything important on this.*

## Short answer

**No one is building the whole thing.** Every component has prior art, some of it strong. The
*combination* — build-side signal ingestion → cross-registry entity resolution → cohort-normalized
momentum with hysteresis → deterministic significance gate with an attention budget → a
mechanism-tagged exposure brief that explicitly refuses to predict prices — was not found anywhere,
in any of the five categories searched.

The sharpest dividing line: **everyone who ingests developer signal uses it to find companies to
invest in. Nobody uses it to ask who else is economically exposed.** That output shape is the
genuinely unoccupied ground.

---

## Closest analogue per component

| Seismograph component | Closest thing that exists | Why it isn't the same |
|---|---|---|
| Multi-source build-signal ingestion | **SignalFire "Beacon"** (GitHub + patents + jobs, "millions of OSS projects") | Internal-only, never sold. Resolves to a *talent graph* (who worked where), not to durable project entities. |
| Cross-registry entity resolution | **ecosyste.ms** — 293M repos, 14.4M packages across 109 registries, plus an explicit `papers.ecosyste.ms` repo↔paper service | Free open infrastructure, and genuinely excellent — but it *stops* at resolution. No momentum, no gate, no briefs. See "opportunity" below. |
| ↑ (historical) | **Papers with Code** — ~80k papers linked to code | **Shut down July 2025.** Meta killed it; HF preserved only a trending-papers feed, not the linkage/leaderboard core. The best prior art in this space is dead. |
| Momentum measurement | **ROSS Index** (Runa Capital) — GitHub star growth, 90-day sliding window, open methodology + open dataset | Quarterly, single metric (stars), manual startup identification, and it exists as VC content marketing. No hysteresis states. |
| Daily automated GitHub analytics | **OSSInsight** (PingCAP) — 10B+ GitHub events, real-time, open source | GitHub-only. No cross-registry resolution, no exposure layer, momentum is just period-over-period arrows. |
| Momentum states (dormant→breakout) | **BERTrend** (RTE-France, ACL 2024) — classifies topics as noise / weak signal / strong signal | Text corpora only, 3 states, no hysteresis, no cohort normalization. Closest *conceptual* match to the state machine. |
| Maturity ladder | **TRL4ML / MLTRL** — 10-level readiness ladder for ML systems | **Manual human review** ("dedicated review periods"). Nobody infers ladder position from telemetry. Also explicitly cyclic, not linear. |
| Cohort percentile normalization | Standard scientometrics (decades old) | Well-trodden. No novelty claim here — but nobody applies it to OSS/AI artifact momentum. |
| Hysteresis on state transitions | Standard signal processing / trading regime detection | Well-trodden generic pattern, transplanted. Not novel, just uncommon in this domain. |
| LLM council with role-based voting | **ChatEval**, "Debate or Vote" (2025), "Minority Sentinel" (2026) | Crowded active research area. Note: "Debate or Vote" finds majority voting accounts for most of multi-agent debate's gains — mild validation of the deterministic-vote choice over a 4th synthesizing LLM. |
| Exposure brief (who/mechanism/direction) | **CB Insights** market-map / "disruption" reports | Human analyst narrative, published periodically. No mechanism taxonomy, no event traceability, no gate. |
| Entity → ticker exposure mapping | **Kensho** (S&P Global) — NERD links entities to tickers/suppliers | Built to correlate signals to **price moves** for trading. Ingests transcripts/news, never code. Diametrically opposed stance. |
| Hindcast validation | **"Hindcast: Replaying Prediction Markets to Evaluate LLM Forecasters"** (arXiv 2607.14051, 2026) | Near-identical name and concept — freeze data at t₀, replay, score. Different domain (Polymarket/Reddit), evaluates a single LLM not a pipeline. |
| Whole-system, OSS | **agents-radar** (GitHub, 586 commits, actively maintained) — 10 sources incl. GitHub/HN/arXiv/HF/ProductHunt, daily via Actions | LLM-summarized *digest*. No entity resolution, no velocity scoring, no cohort ranking, no gate. Represents a whole genre of "LLM writes a daily AI digest" repos. |

---

## What is genuinely unusual about our design

1. **Five-evidence-type corroboration framework** (attention / participation / usage / commitment /
   commercialization) applied to *the same resolved entity*, with breadth explicitly valued over
   amplitude. Each channel has separate prior art. Nobody unifies them per-entity.
2. **Telemetry-inferred maturity ladder.** TRL4ML proves the ladder concept; nobody automates the
   rung inference from public signals.
3. **Deterministic significance gate + hard weekly attention budget.** Everything else in the market
   is a continuous feed, dashboard, or top-N list. Nothing found gates on a threshold *and* caps output.
4. **Mechanism-tagged exposure briefs with a mandatory counter-mechanism and a falsifying observable.**
   Not found anywhere, in any category. This is the single most distinctive artifact.
5. **Explicit refusal to predict prices/outcomes.** Every commercial peer does the opposite by design —
   CB Insights' Mosaic Score, Correlation Ventures, ARK, Kensho, Similarweb all exist *to* predict.
   Being the only non-predictive one is a positioning choice, not an accident.
6. **Hindcast against a checklist of named historical events** (DeepSeek, Reflection-70B). Academic
   emerging-tech-detection papers validate against a single domain case study, not an event checklist.

## What is well-trodden (no novelty claim)

GitHub star-velocity prediction (Borges & Hora 2016, GitEvolve 2020, OSSInsight), HN→GitHub attention
transfer (two separate 2025 papers measuring exactly this), arXiv weak-signal detection (BERTrend,
WISDOM), percentile cohort normalization (textbook scientometrics), hype-cycle/S-curve theory
(Rogers-era), multi-agent LLM voting (crowded 2025-26 area), backtesting (universal), and
"LLM-summarizes-many-sources-daily" tools (an entire genre).

---

## Three findings that should change what we do

### 1. The fake-star problem is real, measured, and directly threatens our momentum signal

Independent research — "Six Million (Suspected) Fake Stars on GitHub" (arXiv 2412.13459), plus
Socket.dev's ~3.7M fake-star finding — documents active, large-scale star manipulation, much of it
promoting spam and malware. Separately, industry commentary notes founders now deliberately game
stars *because* VCs scrape them.

**This validates the sanity layer we just built** (which caught two real spam campaigns on its first
full run) and argues for taking it further. It also means the entire GitHub-star-based competitor set
(ROSS Index, OSSInsight, the trending aggregators) is measuring a partly-poisoned signal with no
documented countermeasure. Corroboration-breadth-over-amplitude is not just an elegant principle here
— it's the specific architectural defense against this exact attack. Worth stating that explicitly in
the design docs.

### 2. `ecosyste.ms` may be a free upgrade to our entity resolution, not a competitor

It is non-profit open infrastructure with free rate-limited APIs (5,000 req/hr): 293M repos, 14.4M
packages across 109 registries, 7B GitHub events, 889M commits, *and* a purpose-built
`papers.ecosyste.ms` service indexing OSS mentioned in academic papers. Same founder as libraries.io.

That is precisely the repo↔package↔paper resolution problem we solve ourselves. Worth an evaluation
spike: does it resolve entities we currently miss, and can it become an input rather than a
reimplementation? It has no momentum/gate/brief layer, so there's no competitive conflict — it's
plumbing we might be rebuilding unnecessarily.

### 3. Papers with Code's death left a real gap

The most prominent paper↔code linkage service in the world shut down in July 2025 and its
leaderboard/SOTA core was never preserved. The closest academic replacement (SemRepo, 2026 — 81M
triples, 200k repos linked to publications) is a static one-off dump with undisclosed matching
methodology. Nobody is running this as a living service. If our entity resolution works well, that
capability has standalone value beyond our own pipeline.

---

## Honest caveats

- Vendor pricing is mostly non-public (AlphaSense, Hebbia, YipitData, Harmonic, CB Insights…);
  figures quoted in the research are secondary-source estimates.
- Several of the closest ingestion analogues (SignalFire Beacon, EQT Motherbrain, >commit's platform,
  Rocketship's algorithm) are **internal-only tools at investment firms**. We can only see what they
  publish about themselves. The possibility that a fund has built something closer internally and
  simply never discussed it is real and unfalsifiable from outside.
- AlphaSignal markets itself with language closest to ours ("real-time ranking system," "knowledge
  graph of AI drawn in real time") but publishes zero methodology. Cannot verify whether that's a
  system or editorial judgment in system-shaped marketing copy.
- No comprehensive 2026 analyst comparison exists for "AI-native technology-scouting SaaS," so a
  stealth entrant could match us more closely than anything surfaced here.
- Patent literature was not searched exhaustively. One snippet — "Trend monitoring of code
  repositories and related information" — surfaced and was not investigated. Worth a follow-up if
  patent exposure ever matters.
