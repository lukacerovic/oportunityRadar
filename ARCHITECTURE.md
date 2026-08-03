# Seismograph — how the whole thing works

*The one document to read if you want to understand the system rather than a piece of it.
For build history read `HANDOFF.md`; for the authoritative design decisions read
`idea_documentation/technical/seismograph-13-corrections-and-decisions.md`.*

---

## 1. The question it answers

Most technology monitoring watches where technology is *talked about* — news, funding rounds,
analyst reports. Seismograph watches where technology is **built**: commits, papers, model
releases, package publishes, launch threads.

From that raw signal it maintains a living picture of the frontier, and for the small number of
technologies that cross a significance bar it produces an **impact brief**: who is economically
exposed, through what mechanism, in which direction, and what observable would prove the thesis
wrong.

Two hard positions that shape everything downstream:

- **It explains exposure; it never predicts prices.** Analyst, not trader. Every commercial peer
  in this space does the opposite (see `COMPETITIVE_LANDSCAPE.md`).
- **Every claim traces to a raw event.** No summary is trusted that can't be walked back to the
  commit, paper, or comment it came from.

## 2. The five invariants

These are enforced forever. Breaking one is a design bug, not a preference.

1. **Raw events are immutable.** Every event carries `occurred_at` (source time) and `ingested_at`
   (our time). Nothing edits or deletes them — later judgments are appended as separate rows.
2. **Everything downstream takes an `as_of`** and may only read events with `occurred_at <= as_of`.
   This is what makes replaying a past day a pure function rather than a guess.
3. **LLM calls exist only in `src/seismo/checkpoints/`.** CI greps for SDK imports elsewhere
   (`scripts/check_llm_import.sh`).
4. **Collectors never reason. Scorers never fetch. Checkpoints never decide what gets attention.**
   Each layer does one job and hands off.
5. **Every merge, gate decision, and brief is logged with its inputs** — including the ones that
   were rejected. Trust in the gate comes from being able to inspect what it *didn't* show you.

## 3. The pipeline

`scripts/daily.sh` runs these in order. Each stage is also a standalone CLI command.

```
collect → track → resolve → sanity → derive-edges → snapshot → score → gate → changes
```

| Stage | What it does | Layer |
|---|---|---|
| **collect** | Pull raw events from every source. Failures isolate per-source — arXiv timing out doesn't stop GitHub. | Observation |
| **track** | Re-poll *known* entities for today's counts (stars, forks, downloads). This is what makes velocity measurable. | Observation |
| **resolve** | Attach events to durable entities across registries. The hard problem — see §5. | Identity |
| **sanity** | Judge whether freshly-collected free text is legible, on-topic content or spam. Append-only. | Quality |
| **derive-edges** | Mint deterministic graph edges (`built_by`, `cited`, `depends_on`) from events. | Graph |
| **snapshot** | Write per-entity daily metric rows for the whole replayed history. | Trajectory |
| **score** | Compute momentum states from velocity percentiles within cohorts. | Trajectory |
| **gate** | Decide which entities earn a brief this week, under a fixed budget. | Significance |
| **changes** | Deterministic diff of what moved today. No LLM. | Memory |

Stages run **outside** the daily loop because they cost money or time:
`comprehend` (cards), `brief` (impact briefs), `council` (independent review), `community-research`
(discussion synthesis), `enrich-*` (fetch READMEs/contributors/metadata), `calibrate`, `hindcast`.

## 4. Core ontology

- **Event** — immutable, uninterpreted. "This repo had 412 stars at this timestamp."
- **Entity** — durable identity across registries. One entity may be a GitHub repo *and* an arXiv
  paper *and* a HuggingFace model.
- **Momentum state** — recomputed daily: `dormant · simmering · accelerating · breakout · fading`,
  with hysteresis so a single spike doesn't flip the state.
- **Maturity ladder** — `idea_paper → public_code → usable_artifact → distribution →
  commercialization → institutional_adoption` (`trajectory/ladder.py`). v1 tops out at
  `distribution` until the pricing and jobs collectors ship.
- **Impact thesis** — versioned. A brief is never edited in place; a new version supersedes it.

### The five evidence types

| Type | Source | Live? |
|---|---|---|
| attention | Hacker News | ✅ |
| participation | GitHub | ✅ |
| usage | HuggingFace, PyPI, OpenRouter | ✅ |
| commitment | job postings | ❌ not built |
| commercialization | pricing pages | ❌ not built |

**Corroboration breadth beats amplitude.** A `breakout` requires ≥2 distinct evidence types
(`BREAKOUT_MIN_BREADTH=2`) — a GitHub-only entity cannot reach it no matter how fast it rises.
This is the architectural defense against gamed metrics, and it matters more than it sounds:
independent research documents millions of fake GitHub stars, and every competitor keying on star
counts alone is measuring a partly-poisoned signal. See `DATA_SOURCE_OPTIONS.md` for how the two
missing types would be filled.

## 5. Identity — the hard part

The same technology appears as a repo, a paper, a model card, and a package, under different names.
Resolving those into one durable entity is what makes momentum measurable at all.

`identity/` handles this: `anchors.py` (source-specific identity refs like `gh:owner/repo`,
`hf:org/model`, `arxiv:2401.12345`), `normalize.py`, `resolve.py` (rules R1–R6), `triage.py`
(discovery triage), `vocab.py` (controlled category vocabulary), `seed.py`.

Merges are queued and audited, never silent. A wrong merge is worse than a missed one — it fuses two
technologies' histories into a fiction.

## 6. Trajectory — momentum, done relatively

Raw growth is meaningless without a peer group. A repo gaining 200 stars means something very
different for a week-old agent framework than for a decade-old compiler.

So velocity is scored as a **percentile within a cohort** = `(kind, category, age bucket)`. Cohorts
need a minimum size (`cohort_min_size=8`) or the entity is capped at `simmering` during warm-up.

Momentum inputs per entity (visible in `momentum_states.inputs`): `P` (velocity percentile),
`breadth` (evidence types), `promo_30d` (ladder promotions), `raw_tier`/`smoothed_tier` (hysteresis),
`cohort_key`, `cohort_n`, `provisional`.

**Known artifact:** the hand-seeded catalog of well-known tools (LangChain, vLLM, Qdrant…) reads as
`accelerating` because tracking on them only recently began — cold start, not real surging. Don't
read raw momentum state as ground truth on its own; cross-check against the gate.

## 7. Significance — the gate

Fully deterministic, **no LLM** (DR-07.1). Letting a model rank importance would reintroduce vibes at
the exact chokepoint the attention budget exists to protect.

```
Score = M × (0.4 + 0.6·R) × (0.4 + 0.6·N)
```

- **M — Momentum:** the week's peak state (breakout=1.0, accelerating=0.7) scaled by peak velocity
  percentile.
- **R — Reach:** does the entity's category touch the exposure map? **R=0 is a hard exclusion**, not
  a floor — a zero-reach entity is never scored, gets an `unmapped_reach` decision, and rolls into
  the weekly **map-gaps** list, which forces the exposure map to grow deliberately.
- **N — Novelty:** pioneer proxy. First-3 in the (category, age<180d) cohort → 1.0; small cohort →
  0.6; crowded → 0.3. Clones in crowded categories rank low even when fast.

Top-K (`briefs_per_week`, default 5) pass. **Every** candidate gets a `gate_decisions` audit row with
the full component breakdown — passed or suppressed.

## 8. LLM checkpoints

Five, all in `checkpoints/`, all forced-tool-call with a Pydantic contract and post-validation:

| Checkpoint | Produces | Notes |
|---|---|---|
| `sanity` | content-quality verdict per raw event | append-only; never mutates `raw_events` |
| `comprehend` | structured entity card | category from controlled vocab, maturity from the ladder |
| `impact` | the brief | requires a `counter_mechanism` and ≥1 falsifiable observable |
| `council` | 3 independent reviews | `skeptic` / `evidence_auditor` / `mechanism_reviewer` |
| `community` | cross-source community verdict | Luka's layer; own provider/model settings |

**The council aggregates by deterministic majority vote** (`council_vote.py`) — never a 4th LLM call,
so cost never compounds and a 3-way split stays `split` instead of being smoothed into fake consensus.

Providers are pluggable: `mock` (deterministic, $0) · `ollama` (local, $0) · `anthropic` (prod).
Dev and CI cost nothing. Budgets are enforced per-checkpoint — `sanity` has its own `$5` ceiling
separate from the global `$30` so a checkpoint that runs over *every* scraped row can't starve the
ones that run over a handful of triggered entities.

## 9. Code map

```
src/seismo/
  collectors/    (15) github · arxiv · hf · pypi · hn · openrouter · launches · wikidata
                      + targets/runner/registry, backfill_gharchive
  identity/       (7) anchors · normalize · resolve · triage · vocab · seed
  trajectory/     (7) snapshot · score · states · ladder · cohorts
  significance/   (3) gate · exposure
  checkpoints/   (10) sanity · comprehend · impact · council · llm · contracts · evidence
  community/     (11) github · hackernews · huggingface · verdict · summarize · relevance
  graph/          (2) edges — deterministic spine
  memory/         (4) changes · calibration · scoring
  hindcast/       (6) replay the system against historical cutoffs
  api/            (3) FastAPI read + curation
  models.py           SQLAlchemy ORM — every table
  cli.py              29 Typer commands
  config.py           pydantic-settings, reads .env
```

## 10. Surfaces

**CLI** — 29 commands. `uv run seismo --help`. See `COMMANDS.md`.

**API** (`uv run seismo serve`, :8000) — the *only* door to the knowledge graph:
`/radar` `/entities/{id}` `/briefs` `/briefs/{id}` `/gate/{week}` `/changes/{day}` `/graph`
`/search` `/queue` `/calibration` `/health`

**Dashboard** (`cd dashboard && npm run dev`, :3000) — Next.js 14:
`/` (Radar) · `/entity/[id]` · `/brief/[id]` · `/gate/[week]` · `/changes/[day]` · `/graph` · `/queue`

The graph page renders two visually distinct edge kinds and **never merges them**: teal
`deterministic` (built_by/cited/depends_on — every row justified by a raw event) and purple
`LLM-reasoned` (semantically_similar_to/conceptually_related_to). One is provable, the other is a
model's judgment; collapsing them into one line style would be a lie.

## 11. Validation

**Hindcast** (`hindcast/`) — replay the system against a frozen historical cutoff and check whether
it *would* have caught a known event. Proven green on Reflection-70B and DeepSeek. This is the
honest test: not "does it produce output" but "would it have been right."

**Calibration** (`memory/calibration.py`) — breakout-survival and fade-reaccel rates, measured, not
assumed. Needs ≥90 days of history to read anything.

**Brief forward-scoring** (`memory/scoring.py`) — every brief's observables are auto-evaluated
against system metrics when their horizon arrives.

## 12. Where to go next

- **Current state and live numbers** → `STATE.md`
- **Build history, session by session** → `HANDOFF.md`
- **Every CLI command explained** → `COMMANDS.md`
- **What the data actually means** → `DATA_EXPLAINED.md`
- **Design decisions and why** → `DECISIONS.md`, `idea_documentation/technical/`
- **Who else builds this** → `COMPETITIVE_LANDSCAPE.md`
- **What sources to add next** → `DATA_SOURCE_OPTIONS.md`
