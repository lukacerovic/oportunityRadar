# Seismograph — 13 Corrections, Amendments & Resolved Decisions

*Phase 2.5 output. This document is **authoritative**. Where it contradicts docs 00–12, this document wins, and the affected doc carries a pointer banner to the relevant `A-n` amendment. It does two things: (1) fixes concrete correctness bugs and internal contradictions found in review; (2) closes every open decision in idea-spec §13 so nothing blocks the build.*

*Reading rule for the builder: read this document immediately after doc 01 (build plan) and before writing any code. Each amendment states the problem, the ruling, and the exact change to make (schema, config key, or rule).*

---

## Part A — Corrections & amendments

Each amendment has a stable id (`A-1`…`A-12`), a severity, the affected docs, and an implementable resolution. Severity: **BLOCKER** (build is wrong without it), **CORRECTNESS** (produces silently wrong results), **HARDENING** (robustness/scale), **CLARIFICATION** (removes ambiguity).

### A-1 — Exposure map & `reach_links` must exist before the gate  *(BLOCKER — docs 01, 07, 08)*

**Problem.** The Significance gate (doc 07, Stage 6) computes its **Reach** component purely from `reach_links`. But `reach_links` are derived at load time from the exposure-map YAML (`seismo load-map`, doc 08 §1), and the exposure map is scheduled in doc 08 = Stage 7, *after* the gate. As sequenced, the gate can never pass anything and its exit criterion is unreachable.

**Ruling.** Split the exposure-map work into two parts and move the first part earlier:

1. **`load-map` machinery + a minimal first slice** (the YAML schema, the Pydantic loader, `reach_links` derivation, and **8 companies + the top ~10 category→reach mappings**) become a **prerequisite of Stage 6**. Concretely, they are built at the **start of Stage 6**, before the gate functions are wired. The minimal slice is specified in doc 14 §6.
2. **Full 30-company curation** stays in Stage 7 as the long pole.

**Changes to make.**
- Doc 01 Stage 6 checklist gains a first item: *"Exposure-map loader + `reach_links` derivation + minimal 8-company slice (doc 14 §6) loaded."*
- Doc 01 stage-map dependency arrow: Stage 6 now depends on *the loader + minimal slice* of doc 08, not the whole doc. Stage 7 remains "full map + impact checkpoint."
- The `seismo load-map` command (doc 02 §7 CLI) is available from Stage 6 onward.

**Exit criterion addition (Stage 6):** the gate passes at least one entity on live data whose category has a mapped reach surface, and suppresses an equally-hot entity whose category is unmapped (which appears in the map-gaps list).

---

### A-2 — The as-of discipline must cover the entity/link/merge/category graph, not just events  *(CORRECTNESS — docs 02, 04, 06, 11)*

**Problem.** `as_of` purity (doc 02 §5) is enforced on `raw_events.occurred_at` and on `entity_metrics_daily`, but **entity resolution is not as-of–aware**. `entity_links` and merges are stamped with `created_at` (our clock), and merges (`entities.merged_into`) carry no evidence timestamp at all. So `seismo score --as-of 2024-05-31`, run today, reads the entity graph *as it exists now* — including merges and theme/category assignments that were only justified by evidence that appeared **after** 2024-05-31. That is future knowledge leaking into every hindcast.

Worse, the existing purity CI test (doc 06 §5 — "run score for a past date twice a week apart, expect identical output") **does not catch this**: between two runs the graph is stable, so both runs leak identically. The test guards `ingested_at` leaks in metrics; it is blind to entity-graph time travel.

**Ruling.** Every graph-shaping decision records the `occurred_at` of the evidence that justified it, and the canonical-entity resolver is parameterized by `as_of`.

**Schema changes (migration 0002).**

```sql
-- 1. Links carry the source-time of their evidence, not just our-time.
ALTER TABLE entity_links ADD COLUMN evidence_occurred_at TIMESTAMPTZ;
--   For event→entity and cross-registry rules: = the linking raw_event's occurred_at.
--   For rules driven by two events (R4/R5/R6): = MAX(occurred_at) of the supporting events.
--   Backfill existing rows from their raw_event before enforcing NOT NULL.

-- 2. Merges become first-class, time-stamped, and reversible with provenance.
CREATE TABLE entity_merges (
  loser_id     BIGINT PRIMARY KEY REFERENCES entities(id),
  survivor_id  BIGINT NOT NULL REFERENCES entities(id),
  justified_at TIMESTAMPTZ NOT NULL,   -- MAX(occurred_at) of the supporting link evidence
  rule         TEXT NOT NULL,
  confidence   REAL NOT NULL,
  decided_by   TEXT NOT NULL,          -- 'auto' | 'human'
  decided_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  active       BOOLEAN NOT NULL DEFAULT true   -- unmerge = set false; nothing deleted
);
--   entities.merged_into stays as a convenience denormalization of the CURRENT graph,
--   maintained from entity_merges where active. It is never read by as-of code paths.

-- 3. Category is time-versioned (it drives cohorts, which must be as-of correct).
CREATE TABLE entity_category_history (
  id BIGSERIAL PRIMARY KEY,
  entity_id BIGINT NOT NULL REFERENCES entities(id),
  category TEXT NOT NULL,
  effective_at TIMESTAMPTZ NOT NULL,   -- occurred_at of the text/event that drove assignment
  evidence_event BIGINT REFERENCES raw_events(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
--   entities.category stays as the CURRENT value; as-of code reads the history.
```

`entity_themes` gains `effective_at TIMESTAMPTZ` (occurred_at of the assigning evidence; manual overrides use the override time, which is acceptable because themes are narrative, not computational — see the pragmatic note below).

**Resolver.** Replace the ad-hoc `merged_into` chase with:

```sql
-- canonical_entity_id(entity_id, as_of): follow only merges justified by evidence <= as_of.
WITH RECURSIVE chain(id) AS (
  SELECT :entity_id
  UNION
  SELECT m.survivor_id
  FROM entity_merges m JOIN chain c ON m.loser_id = c.id
  WHERE m.active AND m.justified_at <= :as_of
)
SELECT max(id) FROM chain;   -- survivor is deterministic per merge direction (doc 04 §3)
```

Category as-of: `category_asof(entity_id, as_of)` = the `entity_category_history` row with the greatest `effective_at <= as_of`; if none, cohort falls back to `entity_type`-only (doc 06 DR-06.3 fallback), never to a future-assigned category.

**Pragmatic scope for v1.** Links, merges, and category **must** be as-of correct (they change cohorts and metric attribution). Theme membership **should** be, but because themes are narrative (never fed into scoring — doc 04 §5), v1 may resolve themes at present-time in the dashboard without corrupting any assertion. Record `effective_at` anyway so this can tighten later at zero migration cost.

**New CI test (replaces the weak twice-a-week test as the authoritative one; keep both).**
> Insert entity A and entity B. Insert a linking event with `occurred_at = as_of + 1 day` that would merge them. Assert `canonical_entity_id(A, as_of) != canonical_entity_id(B, as_of)` (kept separate) **and** `canonical_entity_id(A, as_of + 1 day) == canonical_entity_id(B, as_of + 1 day)` (merged). Do the same for category: a category-changing README event dated after `as_of` must not change `category_asof(as_of)`.

This is now a Stage 2 exit criterion (doc 04 DoD) and a hard gate on the DeepSeek hindcast meaning anything.

---

### A-3 — Cold start is a first-class phase, specified in doc 14  *(BLOCKER — docs 01, 03, 04, 06)*

**Problem.** Every layer doc describes steady state. None describes bringing an **empty** database to life: seeding the initial tracked universe, warming cohorts to the ≥8 minimum before momentum means anything, and surviving the one-time merge-queue flood.

**Ruling.** Cold start is **doc 14** (new), inserted as an explicit **Stage 1.5** between Observation and Identity hardening. Its exit criteria gate Stage 3 (Trajectory): you may not trust a momentum state computed against a cohort of three. See doc 14 for the seed list, the historical discovery sweep, provisional-state handling, and the cold-start queue triage mode.

**Change to make.** Doc 01 stage map inserts *Stage 1.5 — Cold-start bring-up (doc 14)* after Stage 1; Stage 3's entry condition becomes "cold-start exit criteria (doc 14 §7) met."

---

### A-4 — The tracking set must be bounded (de-tracking lifecycle)  *(HARDENING — docs 03, 02)*

**Problem.** Discovery adds entities forever; nothing ever leaves the daily tracking set. Every tracked repo/model/package is polled daily regardless of whether it has been dead for a year. The tracking set grows monotonically, most of the API budget is spent on `dormant`/`fading` junk, and GitHub Search (30 req/min) / REST (5000 req/h) ceilings eventually break.

**Ruling.** Entities carry a **tracking tier** that governs poll cadence, recomputed nightly.

**Schema (migration 0002).**
```sql
ALTER TABLE entities ADD COLUMN tracking_tier TEXT NOT NULL DEFAULT 'active';  -- active|slow|archived
ALTER TABLE entities ADD COLUMN tier_reviewed_at TIMESTAMPTZ;
```

**Tiering rules** (`seismo retier`, runs in the daily pipeline before `snapshot`):
- **active** (polled daily): `age < 30d` **OR** current state ∈ {simmering, accelerating, breakout} **OR** a maturity promotion in the last 90d **OR** a published brief in the last 180d.
- **slow** (polled weekly, on the `collect-slow` timer): not active **AND** any event in the last 90d (typically `fading`).
- **archived** (not polled at all): no event in 90d **AND** state ∈ {dormant, fading}.

**Revival.** `seismo resolve` promotes any entity back to **active** the moment a *new inbound event* attaches to it (an HN link, a fresh release, a new paper citing it). Revival is free because inbound events arrive through discovery/attention collectors, which never stop.

**Collector change (doc 03 §2, `track()`):** `track()` receives only `active` targets on the fast/usage timers and only `slow` targets on the weekly timer. Archived entities are invisible to tracking but fully preserved and instantly revivable.

**Budget check to run at cold-start exit and quarterly:** report `count(*) by tracking_tier` and multiply active-tier count by per-source per-entity request cost; assert daily GitHub tracking requests < 4000/h (headroom under the 5000 ceiling). Surface in `seismo doctor`.

---

### A-5 — The v1 evidence model is 3 types / 4 rungs; tune thresholds accordingly  *(CORRECTNESS — docs 03, 06, 11)*

**Problem.** The 5-evidence-type / 6-rung design is the intellectual core, but in v1 only **3 evidence types are collectable** (attention=HN, participation=GitHub, usage=HF/PyPI) — commitment (jobs) and commercialization (pricing) are Wave 3 (doc 03 §2.7–2.8). Consequences: `evidence_breadth` maxes at 3, yet `breakout` requires `B ≥ 3` (doc 06 §4) — i.e. *all* available types at once; and the ladder's top two rungs (`commercialization`, `institutional_adoption`) are **unreachable live**. Yet the DeepSeek hindcast (H2) leans on the commercialization promotion, which the harness supplies via a Wayback pricing seed — so H2 passing would **not** prove the live pipeline can reach that state.

**Ruling — two parts.**

1. **Promote the pricing/changelog watcher (doc 03 §2.8) out of Wave 3 into v1 "Wave 2.5"** (built in Stage 1, after HF/PyPI). Rationale: it restores a 4th evidence type and, critically, the `commercialization` rung — the single most economically meaningful promotion (someone is charging money), which the gate's Reach logic and the whole "commitment beats attention" thesis depend on. It is cheap (weekly `httpx` + `trafilatura` + content hash) and legally clean. **Jobs (commitment) stays in Wave 3** — Greenhouse/Lever JSON is fine but lower marginal signal and higher curation cost.

2. **Make the breakout breadth bar config-driven and set it correctly for the collector set that is actually live:**
   ```
   SEISMO_BREAKOUT_MIN_BREADTH = 2   # while ≤3 evidence types are live
                                     # raise to 3 once the pricing watcher (4th type) ships
   ```
   Doc 06 §4 `breakout` entry condition becomes: `promo_30d ≥ 2` **OR** (`P ≥ 0.95` **AND** `B ≥ SEISMO_BREAKOUT_MIN_BREADTH`).

**Safety check against the flop-negative.** Reflection-70B has attention only (B=1; attention is excluded from the velocity composite by design, doc 06 §2). With `MIN_BREADTH = 2` it still cannot reach breakout, so H3 (gate suppression) is unaffected. DeepSeek has participation + usage (B=2) plus promotions, so it reaches breakout with `MIN_BREADTH = 2`. Both hindcasts hold.

**Change to make.** Doc 03 scheduling matrix (§3) adds the pricing watcher to `seismo-collect-usage` (weekly sub-cadence) as v1, not Wave 3. Doc 06 §4 uses the config key. Doc 11 notes that H2's commercialization rung is now also reachable live, not only via Wayback.

---

### A-6 — Gate Reach: `R = 0` is a hard exclusion, not a 0.4 floor  *(CLARIFICATION — doc 07)*

**Problem.** Doc 07 contradicts itself. §2 says an unmapped/zero-reach category means "the gate can't pass it" (hard exclusion → map-gaps list), and "a zero-reach entity can't buy its way in with pure momentum." But the score formula `M × (0.4 + 0.6·R) × (0.4 + 0.6·N)` floors the reach factor at **0.4** when `R = 0`, which lets a high-momentum, zero-reach entity pass.

**Ruling — hard exclusion (matches the spec's intent that the map must grow deliberately):**
- **Eligibility precedes scoring.** An entity is gate-*eligible* only if `R > 0` (its category maps to ≥1 reach surface). `R = 0` entities are never scored, never passed; they are written to `gate_decisions` with `decision='suppressed'`, `components.reason='unmapped_reach'`, and aggregated into the weekly **map-gaps** list.
- Among eligible entities, `R ∈ {0.5, 1.0}` and the formula stands (the `0.4 + 0.6·R` floor now only ever applies within eligible entities, and the `0.4 + 0.6·N` floor still legitimately prevents novelty from zeroing a real thesis).

**Change to make.** Doc 07 §2 Reach paragraph states the eligibility gate explicitly; §2 score paragraph notes the formula is evaluated only over eligible entities. Add a unit test: `R=0` entity with `M=1.0` is suppressed with reason `unmapped_reach`.

---

### A-7 — Observables must carry a measurability tag  *(CORRECTNESS — docs 08, 09)*

**Problem.** A brief's `observables` are its epistemic core, but most are things the system **cannot measure** ("avg tokens per customer"). Forward-scoring therefore collapses entirely onto the manual quarterly ritual, and the checkpoint is free to emit falsifiers nothing can ever watch.

**Ruling.** Structure the observable and prefer machine-measurable ones.

**Contract change (doc 08 §2, `checkpoints/contracts.py`):**
```python
class Observable(BaseModel):
    statement: str                                   # "avg tokens per active customer falls"
    source: Literal["system", "manual"]              # can the pipeline watch this?
    system_metric: str | None                        # if source=system: which metric/event it maps to
    horizon: Literal["quarters", "1-2y", "3y+"]
    direction_if_thesis_holds: Literal["up", "down", "flat"]

class ImpactBrief(BaseModel):
    ...
    observables: list[Observable]                    # was list[str]
    ...
```

**System-prompt addition (doc 08 §3):** *"Prefer observables the system already tracks: maturity promotions, pricing-page changes, download/usage velocity, star/fork velocity, new job mentions. For each, set `source='system'` and name the `system_metric`. Use `source='manual'` only when no tracked signal can test the claim."*

**Post-validation (soft):** require ≥1 observable overall (hard); **log** a warning (not a rejection) if zero `source='system'` observables — surfaced in the doc 05/08 quality loop as a prompt-quality signal.

**Scoring payoff (doc 09 §2):** the scoring screen auto-evaluates `source='system'` observables from metric history before the operator judges the `manual` ones — some falsifiers become auto-trippable, tightening calibration.

---

### A-8 — Pin the model for hindcast; separate live vs. hindcast model config  *(CORRECTNESS — docs 05, 08, 11)*

**Problem.** The checkpoints use "Claude Sonnet class" (a moving target); "green forever" hindcast assertions (doc 11 DR-11.2) will eventually break for model reasons unrelated to code.

**Ruling.** Two config keys, and hindcast pins an exact snapshot:
```
SEISMO_MODEL_LIVE     = <current Sonnet-class snapshot id>   # live pipeline
SEISMO_MODEL_HINDCAST = <pinned snapshot id>                 # hindcast suite only
```
The hindcast runner (doc 11 §4) forces `SEISMO_MODEL_HINDCAST`. Assertions remain schema-level (mechanisms/exposures/field-presence), never prose (doc 11 §2) — that is what makes 3/3 stable. A model bump is a **deliberate re-baselining event**: bump `SEISMO_MODEL_HINDCAST`, re-run all cases, review the diff, commit the new baseline with a note in the calibration report (doc 09 §4). It is never a silent CI change.

---

### A-9 — Add security/agent/vision arXiv categories  *(CLARIFICATION — doc 03)*

**Problem.** arXiv categories `cs.AI, cs.CL, cs.LG, cs.SE, cs.IR, stat.ML` (doc 03 §2.3) under-feed the *AI security* and *agent tooling* themes.

**Ruling.** Extend to: `cs.AI, cs.CL, cs.LG, cs.SE, cs.IR, stat.ML, cs.CR, cs.MA, cs.CV, cs.DC`. (`cs.CR` security, `cs.MA` multi-agent, `cs.CV` vision, `cs.DC` distributed/systems for inference-infra.) Category list lives in the collector config so it is tunable without a deploy.

---

### A-10 — Add a search surface  *(CLARIFICATION — doc 10, 02)*

**Problem.** Doc 04 §2 promises unlinked stories are "searchable but unowned," but no search endpoint or UI exists.

**Ruling — minimal v1 search:**
- Postgres FTS: a generated `tsvector` on `entities(canonical_name, attrs->>'aliases')` and a GIN index; plus `pg_trgm` on `canonical_name` (extension already present). For raw events, index the small set of text-bearing payload keys (`title`, `description`, `abstract`) via an expression GIN index.
- `GET /search?q=&type=` (doc 10 §1) → entities first (trigram + FTS rank), then unowned events. No new page required in Stage 5; a header search box that routes to a results list is a Stage 8 add. The endpoint ships in Stage 5 so the API contract is stable.

---

### A-11 — "Day" is the UTC calendar date of `occurred_at`  *(CLARIFICATION — docs 03, 06)*

Snapshot uids (`native_id:date`, doc 03 §1) and `entity_metrics_daily.day` (doc 06 §1) use **the UTC calendar date of `occurred_at`**, always. State it in the collector base contract so no collector invents a local-time date and creates off-by-one duplicate snapshots.

---

### A-12 — Budget-refuse degrades gracefully; distinguish `pending` from `failed`  *(CORRECTNESS — docs 05, 07, 08, 12)*

**Problem.** When the monthly LLM ceiling is hit, doc 05 §4 marks calls `failed`. But a budget refusal is not a quality failure, and the downstream effect (gate/brief acting on a missing card) is untraced.

**Ruling.**
- Introduce a `pending` status distinct from `failed`. Ceiling reached → the checkpoint call is **not attempted**; the card/brief request is recorded `pending` (retried automatically next window when budget resets or the ceiling is raised). `failed` is reserved for **validation** failures after retry (a genuine quality problem).
- **Gate never briefs an entity without a current comprehension card.** If the gate selects an entity whose card is `pending`, the brief request is deferred (stays queued) rather than run on stale/absent comprehension; the deferral is logged on the `gate_decisions` row.
- `seismo doctor` reports `pending` counts separately from `failed`, and alerts if `pending` is non-zero for >48h (means the ceiling is chronically too low — raise `SEISMO_LLM_BUDGET_USD` or investigate volume).

---

### A-13 — Pluggable LLM provider: `mock` / `ollama` / `anthropic` (cheap dev & test)  *(HARDENING — docs 02, 05, 08, 11)*

**Goal.** Don't spend Anthropic credits to build and test the plumbing. Use a **local Ollama** model during setup/dev, a **zero-cost deterministic mock** for the automated test suite, and **Anthropic (Claude Sonnet class)** for production and for the *semantic* hindcast assertions. Switching is a one-line config change; **the two-checkpoint invariant is preserved** — we swap the backend *behind* the checkpoints, we do not add call sites.

**Why three, not two.** A 7–8B local model is fine for exercising *plumbing* (does the tool schema round-trip? does the Pydantic validation+retry path fire? does cost logging work?) but it cannot be graded on *analytical correctness*. The DeepSeek H2 assertion checks that the brief names `cost_collapse` + `commoditization` and NVDA/MSFT-class exposure (doc 11 §2) — a small local model will fail that unreliably, producing false red CI. So:
- **`mock`** — the default for the automated unit/contract suite. Returns registered, schema-valid canned payloads keyed by `(checkpoint, entity_ref)` from `tests/fixtures/llm/`. No network, no daemon, fully deterministic, **$0**. This is what runs in CI on every commit.
- **`ollama`** — local development, manual exploration, and opt-in *integration/plumbing* tests (pytest marker `-m llm_local`). Exercises a real generation + structured-output + retry loop against a live model. Offline, **$0**.
- **`anthropic`** — production, and the **semantic** hindcast assertion **H2 only** (which is pinned to `SEISMO_MODEL_HINDCAST`, A-8). This is the only path that spends credits.

**Credit reality (why this makes tests genuinely cheap).** Most of the pipeline — collectors, identity, trajectory, gate, changes, and the hindcast assertions **H1 (momentum) and H3 (flop suppression)** — has **no LLM in it at all** (docs 06/07/09 are fully deterministic). Only comprehension and impact call a model, and only **H2** among the hindcast assertions needs Claude. So even in "real" mode the spend is a handful of calls; in day-to-day dev and CI it is **$0**.

**The one module (`checkpoints/llm.py`) — still the only place any LLM SDK is imported.**
```python
# checkpoints/llm.py — the ONLY module that talks to any LLM provider. Invariant 3 still holds:
# CI greps that NEITHER anthropic NOR ollama is imported outside src/seismo/checkpoints/.
class LLMResult(BaseModel):
    data: dict                       # raw parsed tool/JSON output, pre-Pydantic-validation
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float = 0.0            # 0.0 for mock and ollama

class LLMProvider(Protocol):
    # schema = SomeCard.model_json_schema(); the SAME schema drives all three backends
    def structured(self, *, system: str, user: str, schema: dict,
                   max_tokens: int, temperature: float) -> LLMResult: ...

def get_provider(settings) -> LLMProvider:
    return {"mock": MockProvider,
            "ollama": OllamaProvider,
            "anthropic": AnthropicProvider}[settings.LLM_PROVIDER](settings)
```
- **AnthropicProvider:** single forced tool whose input schema = the Pydantic `model_json_schema()`, `tool_choice` forced (doc 05 DR-05.2 unchanged); computes `cost_usd`.
- **OllamaProvider:** `POST {OLLAMA_HOST}/api/chat` with `format=<the same JSON schema>` (Ollama's structured-output constraint), `options={temperature, seed}` for reproducibility; `cost_usd=0`.
- **MockProvider:** looks up a canned payload by `(checkpoint, entity_ref)`; raises a clear error if a fixture is missing (forces tests to declare their expected I/O); `cost_usd=0`.

`comprehension.py` and `impact.py` each call `get_provider(settings).structured(...)`, then run the **existing** Pydantic-validate → one-retry-with-error → mark `failed` path (doc 05 DR-05.2). A malformed Ollama output flows through the identical retry, so the local path hardens the same code the production path uses.

**Config keys (add to Part C):**
```
LLM_PROVIDER   = "mock"                       # mock | ollama | anthropic; prod sets "anthropic"
OLLAMA_HOST    = "http://localhost:11434"
OLLAMA_MODEL   = "qwen2.5:7b-instruct"        # strong JSON/structured adherence; `ollama pull` it once
                                              # (llama3.1:8b is a fine alternative)
```
`MODEL_LIVE` / `MODEL_HINDCAST` (A-8) remain the Anthropic snapshot ids and are only consulted when `LLM_PROVIDER="anthropic"`.

**Test-tier matrix (what runs where):**

| Suite | Provider | Cost | When |
|---|---|---|---|
| Unit + contract (default `pytest`) | `mock` | $0 | every commit / CI |
| Integration plumbing (`-m llm_local`) | `ollama` | $0 | local, before merging checkpoint changes |
| Hindcast H1 (momentum), H3 (flop) | none (deterministic) | $0 | CI, always |
| Hindcast **H2** (brief semantics) | `anthropic` + `MODEL_HINDCAST` | small | pre-release / nightly, not every commit |
| Production pipeline | `anthropic` + `MODEL_LIVE` | v1 volume ~$10–30/mo | live |

**CI invariant update (doc 02 §1 grep).** Broaden the invariant-3 grep to catch *any* provider SDK outside the checkpoints package:
```bash
grep -rnE "import (anthropic|ollama)" src/seismo --include="*.py" \
  | grep -v "src/seismo/checkpoints/" && exit 1 || exit 0
```

**Build-order note.** Implement `checkpoints/llm.py` with `mock` + `ollama` in **Stage 4** (Comprehension) — you develop the entire comprehension checkpoint against local Ollama and mock, spending nothing. Wire `anthropic` and run H2 against Claude only when you reach the Stage 7 exit criterion. This means you can build and test Stages 0–6 end-to-end without an Anthropic key at all; the key first becomes strictly necessary for the H2 hindcast and go-live.

---

## Part B — Resolved open decisions (closes idea-spec §13)

| # | Decision | Resolution |
|---|---|---|
| 1 | **Name** | **Seismograph** is confirmed as the v1 name. It is referenced as a single constant `SEISMO_PRODUCT_NAME` and the CLI/package stay `seismo`; a later rename touches one config value + the dashboard header, nothing structural. |
| 2 | **v1 exposure-map roster** | **Final 30, below.** Per-company template fields are fixed by the doc 08 §1 YAML schema (no additions in v1). |
| 3 | **Hindcast cases** | DeepSeek (pinned) + **Ollama** as the mid-size positive (recommended default; operator may veto — nothing else depends on the specific pick) + **Reflection-70B** as the flop negative. See rationale below. |
| 4 | **Budget numbers** | `BRIEFS_PER_WEEK = 5`, `BREAKOUT_CALLOUTS_PER_DAY = 1`. Unused weekly brief budget does **not** carry forward (doc 07 DR-07.2). |
| 5 | **Changes-view cadence** | **Daily deltas + a Monday week-over-week rollup, both deterministic** (no LLM), exactly as doc 09 §1 already implements. A weekly *narrative* checkpoint is explicitly deferred and, if ever added, becomes a registered third checkpoint (doc 09 DR-09.1) — never smuggled in. |
| 6 | **Human-in-the-loop** | Briefs are **draft → human review → publish** in v1 (doc 08 DR-08.2). Auto-publish is unlocked only after two quarters of forward scoring show acceptable calibration (doc 09 §4), and that unlock is recorded in a calibration report. |

### Final v1 exposure-map roster (30)

```
Semis & hardware (7):        NVDA AMD TSM AVGO ASML ARM ANET
Hyperscalers & platforms(6): MSFT AMZN GOOGL META AAPL ORCL
Software / substitutable (6):CRM ADBE NOW TEAM WDAY INTU
Data & infra (5):            SNOW MDB DDOG NET CFLT
AI-exposed / applied (6):    PLTR SHOP U DOCN PATH CRWD
```
(27 from doc 08 §1 + **ARM**, **ANET** for AI-datacenter networking/compute exposure, **PATH** for automation-substitution exposure, and **CRWD** as a security-adjacent name that the `cs.CR`/AI-security theme will point at; net 30.) The **cold-start minimal 8** to unblock the gate (A-1, doc 14 §6) are: `NVDA MSFT GOOGL AMZN META AMD AVGO SNOW`.

### Hindcast mid-size positive — why Ollama (default), with an alternate

**Recommended: Ollama.** It is the canonical mid-size developer-tool breakout of 2024: a clean GH Archive trail (`ollama/ollama`), an unambiguous maturity climb (public code → usable artifact → broad distribution), a genuine multi-evidence-type momentum arc, and it is instantly recognizable as a validation demo. It exercises R1/R3 identity links and the full trajectory/breakout path.

**Caveat and how it's handled.** Ollama has no traditional *pricing page*, so it does **not** exercise the `commercialization` promotion trigger. That trigger is already covered by the **DeepSeek** case (pricing captured via Wayback, and now also live per A-5). Therefore the Ollama case asserts the ladder up to **`distribution`** plus a non-provisional **breakout**, and does *not* assert `commercialization`.

**Alternate if you specifically want commercialization coverage inside the mid-size case: Continue.dev** — OSS IDE assistant with an npm/registry footprint, a clean GH trail, and a real pricing page (team tiers) that appeared in 2024. Pick this only if you want a second, independent commercialization-trigger test; otherwise Ollama is simpler and higher-signal.

The case YAML (doc 11 §2 format) can be authored once the operator confirms the pick; no other stage depends on which is chosen.

---

## Part C — Config keys introduced or confirmed here

Add to `pydantic-settings` (doc 02 §6), env prefix `SEISMO_`:

```
PRODUCT_NAME            = "Seismograph"
LLM_PROVIDER            = "mock"     # A-13: mock | ollama | anthropic; prod = "anthropic"
OLLAMA_HOST             = "http://localhost:11434"   # A-13
OLLAMA_MODEL            = "qwen2.5:7b-instruct"       # A-13
MODEL_LIVE              = "<sonnet-class snapshot id>"   # used only when LLM_PROVIDER="anthropic"
MODEL_HINDCAST          = "<pinned snapshot id>"        # used only when LLM_PROVIDER="anthropic"
BRIEFS_PER_WEEK         = 5
BREAKOUT_CALLOUTS_PER_DAY = 1
BREAKOUT_MIN_BREADTH    = 2          # → 3 after the pricing watcher (4th evidence type) ships
LLM_BUDGET_USD          = <monthly ceiling>
COHORT_MIN_SIZE         = 8          # doc 06 DR-06.3
COHORT_WARMUP_STATE_CAP = "simmering" # doc 14 §4: provisional states cap here until cohort matures
TRACKING_ARCHIVE_DAYS   = 90         # A-4
PENDING_ALERT_HOURS     = 48         # A-12
```

---

## Part D — Build-readiness checklist (what "the docs are ready" means)

The documentation set is build-ready when all of the following are true (they are, as of this document):

- [x] Every idea-spec §13 open decision is closed (Part B).
- [x] The Stage 6/7 ordering bug is resolved with a concrete minimal-slice prerequisite (A-1).
- [x] As-of purity is defined over the entity graph, with schema, resolver, and a test that actually catches the leak (A-2).
- [x] Cold start is a specified stage with seed data and exit criteria (A-3 → doc 14).
- [x] The tracking set is bounded by an explicit lifecycle (A-4).
- [x] Thresholds match the collectors that are actually live in v1 (A-5, A-6).
- [x] Observables are structured and measurability-tagged (A-7).
- [x] Hindcast is reproducible across model drift (A-8).
- [x] Remaining ambiguities (arXiv cats, search, day boundary, budget-refuse) are pinned (A-9…A-12).
- [x] LLM provider is pluggable so dev/CI cost $0 and only production/H2 spend credits (A-13).

**Reading order for the builder (supersedes doc 01 §5):**
`00 idea-spec → 01 build-plan → 13 corrections-and-decisions (this) → 14 cold-start → 02 foundation → 03 observation → 04 identity → 05 comprehension → 06 trajectory → 07 significance → 08 impact → 09 memory → 10 dashboard → 11 validation → 12 operations.`

Migrations affected by this document: **0001** (core schema, doc 02) is unchanged; **0002** adds A-2 (`evidence_occurred_at`, `entity_merges`, `entity_category_history`, `entity_themes.effective_at`) and A-4 (`entities.tracking_tier`, `tier_reviewed_at`). Author 0002 at the *start* of Stage 2 (Identity), before any resolution code runs.
