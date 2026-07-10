# Seismograph — 14 Cold-Start Bring-Up

*Phase 2.5 output. Referenced by doc 13 A-3. This is **Stage 1.5**, inserted between Observation (Stage 1) and Trajectory (Stage 3). It answers the one question every other doc assumes away: how do you take an empty database to a state where momentum, cohorts, and the gate mean something? Its exit criteria (§7) are the entry gate for Stage 3.*

*Principle: cold start uses the **same code paths** as steady state — same collectors, same `resolve`, same `score`. There is no separate bootstrap engine (that would rot, exactly like the rejected backtest engine in doc 11 DR-11.1). Cold start is ordinary operation over (a) a hand-curated seed list and (b) a historical discovery sweep, with three temporary behaviors that switch off once the system is warm.*

---

## 1. The three cold-start problems

1. **Empty universe.** Discovery collectors find things `created:>=yesterday` (doc 03 §2). On day 1 there is nothing to track and no history to compute velocity from. Without seeding, the system would take months to accumulate a meaningful universe, and would be blind to everything that became important *before* day 1 (DeepSeek, Ollama, vLLM, etc. already exist).
2. **Cold cohorts.** Momentum requires cohorts of ≥ `COHORT_MIN_SIZE` (8) of the same `(entity_type, category, age_bucket)` to compute percentiles (doc 06 DR-06.3). Early on, cohorts are tiny; a percentile over 3 entities is noise. A `breakout` call against a cohort of 3 is meaningless and, worse, *looks* authoritative.
3. **Queue flood.** Seeding + a historical sweep generate a large one-time burst of new entities and candidate merges. The steady-state "20-item queue with morning coffee" (doc 04 §4) does not survive first contact with a few hundred pending pairs.

Each has a bounded, temporary treatment below.

---

## 2. Bootstrapping sequence (overview)

```
T0    Seed list authored + loaded            → ~150–300 known entities exist, registry-anchored
T0    Historical discovery sweep (180d back)  → recently-born entities + their event history land as backfill
T0+1d resolve (cold-start mode) over all of it→ links, high-precision auto-merges, queue populated
T0..  Daily live pipeline runs normally on top of the seeded base
T0+   Cohort warm-up: states computed but capped/flagged until cohorts reach COHORT_MIN_SIZE
T0+   Queue triage: high-precision pairs first; R4–R6 deferred to a cold-start bucket
~T+4–8w  Exit criteria (§7) met → warm-up flags off, Stage 3 trusted
```

The seed list and the sweep both write **ordinary `raw_events`** — the sweep as `origin='backfill'` (doc 02 §4), the seed as a small set of synthetic `seed`-origin anchor events (see §3). From `resolve` onward everything is identical to a live day.

---

## 3. The seed universe

### 3.1 Purpose and shape

The seed list is a hand-curated inventory of entities that **already matter on day 1** and would otherwise take the system months to rediscover. It is *not* a watchlist of opinions — it is a starting set of registry anchors so that (a) tracking has real targets immediately and (b) the historical sweep's events have entities to attach to.

Target size: **~150–300 entities**. Bigger is not better — the sweep will find the rest. The seed exists to cover the obvious incumbents and the well-known recent risers across every v1 category.

### 3.2 Format — `seed/seed_entities.yaml` (versioned in git)

```yaml
# seed/seed_entities.yaml — hand-curated day-1 universe. One block per entity.
# Each entity provides the registry anchors that doc 04 §2 maps to entity candidates,
# so identity resolves them exactly as if a collector had discovered them.
- name: vLLM
  entity_type: project
  category: inference-runtime
  anchors:
    github: vllm-project/vllm
    pypi: vllm
    arxiv: "2309.06180"          # PagedAttention
  themes: [efficient inference]
- name: Ollama
  entity_type: project
  category: inference-runtime
  anchors:
    github: ollama/ollama
- name: DeepSeek
  entity_type: org
  category: model-foundation
  anchors:
    github: deepseek-ai
    hf_org: deepseek-ai
- name: LangChain
  entity_type: project
  category: agent-framework
  anchors: { github: langchain-ai/langchain, pypi: langchain, npm: langchain }
# ...
```

**Coverage rule (how to choose the ~200):** for each of the ~30 categories in the vocabulary (doc 04 §5), list the 3–8 best-known members (incumbents + notable 2024–2025 risers). That mechanically yields ~150–250 and guarantees every category has cohort seed mass, which directly attacks problem #2.

### 3.3 Loader — `seismo seed-load`

A new idempotent CLI step (add to doc 02 §7):
- For each seed block, create the anchor entities (or attach to existing), and emit one synthetic anchor event per registry anchor: `source='seed'`, `origin='seed'`, `event_type='seed_anchor'`, `occurred_at` = the registry object's real creation date when cheaply fetchable (GitHub repo `created_at`, arXiv date), else the seed-load date. The synthetic event's payload records the anchor so R1–R3 links fire naturally.
- Themes in the seed apply as manual theme assignments (doc 04 §5), `entity_themes.source='seed'`.
- Idempotent on `(source='seed', source_event_uid=anchor_uri)`.

**As-of note (doc 13 A-2):** seed anchor events carry a real or seed-date `occurred_at`; a seed loaded today with `occurred_at=today` is correctly invisible to a hindcast `as_of` in the past — the seed does **not** pollute hindcast windows (which use their own `origin='backfill'` loaders, doc 11). Live scoring uses `origin in ('live','backfill','seed')`.

---

## 4. Historical discovery sweep

Seeds cover the *known*; the sweep covers the *recently-born-but-not-yet-famous*, so the system isn't blind to anything that rose in, say, the last two quarters before day 1.

- **Window:** last **180 days** before go-live (config `COLDSTART_SWEEP_DAYS=180`).
- **Mechanism:** run the existing discovery collectors in **backfill mode** over the window, using the same historical routes the hindcast harness uses (doc 11 §1): GH Archive for GitHub discovery + `repo_snapshot` reconstruction, Algolia (natively historical) for HN, arXiv OAI-PMH / Kaggle snapshot for papers. HF/PyPI download *history* is largely unavailable (doc 11 §1 documented gap) — the sweep reconstructs HF `createdAt` and PyPI presence for distribution/usable-artifact promotions but not historical download velocity. Rows land as `origin='backfill'`.
- **Scope control:** this is the one place the sweep is broader than a hindcast case (which is seed-scoped). Bound it by the same theme keyword/topic lists the live discovery collectors use (doc 03 §2.1–2.3), so the sweep pulls "AI/dev-tooling frontier over 180d," not all of GitHub. Expect low tens of thousands of events, not millions.

The sweep is **run once** at bring-up. It is not a recurring job.

---

## 5. Cohort warm-up

Until a cohort is populated, its percentiles are untrustworthy. Treatment:

- **Provisional states.** When `score` computes a momentum state whose cohort has `< COHORT_MIN_SIZE` members *even after* the `(entity_type, age_bucket)` fallback (doc 06 DR-06.3), it writes the state row with `inputs.provisional = true` and **caps the state at `COHORT_WARMUP_STATE_CAP` (`simmering`)**. Rationale: you may say "this is moving" off a thin cohort, but you may not manufacture a `breakout` from three data points.
- **Cohort size is recorded** in `momentum_states.inputs.cohort_n` and `cohort_key` for every entity, always — so provisional-ness is auditable and the dashboard can badge it.
- **The gate ignores provisional breakouts.** During warm-up the candidate set (doc 07 §1) excludes entities whose qualifying state is `provisional`. This prevents cold-start noise from spending the brief budget. (A provisional entity can still appear on the Radar as `simmering`; it just can't earn a brief.)
- **Automatic thaw.** No manual switch: as the seed + sweep + daily runs accumulate members, cohorts cross 8, `provisional` stops being set for those cohorts, and full states (including `breakout`) and gate eligibility turn on **per cohort**, not globally. Warm-up ends unevenly and correctly.

---

## 6. Exposure-map minimal first slice (unblocks the gate — doc 13 A-1)

To make the gate functional in Stage 6 without curating all 30 companies first, curate a **minimal slice** at cold start:

- **8 companies:** `NVDA MSFT GOOGL AMZN META AMD AVGO SNOW` — full doc 08 §1 YAML each (sourced revenue lines, threat surfaces). These 8 cover the reach surface for the highest-traffic categories (inference-runtime, model-foundation, model-efficiency, agent-framework, vector-db, data-pipeline).
- **`reach_links` for the top ~10 categories** derived from those 8 companies' `threat_surface` entries at load time.
- Every category **not** yet mapped is expected and fine: its entities are gate-ineligible (doc 13 A-6) and surface in the weekly **map-gaps** list, which becomes the prioritized worklist for growing the map to 30 during Stage 7.

Budget: ~45 min/company (doc 08 §1) → the minimal slice is ~6 hours, done once, before the gate is switched on.

---

## 7. Exit criteria (entry gate for Stage 3, and the map-slice gate for Stage 6)

Cold start is **done** — and Trajectory (Stage 3) may be trusted — when:

- [ ] `seed-load` complete: ~150–300 seed entities exist, each with ≥1 resolved registry anchor; no seed category is empty.
- [ ] Historical sweep complete: 180-day backfill loaded; `raw_events` count and per-source distribution sane (no source silently empty).
- [ ] **Cohort maturity:** the **top 10 categories by entity count each have ≥ `COHORT_MIN_SIZE` members** in at least one age bucket, so their momentum states are non-provisional.
- [ ] **Queue drained to steady state:** `entity_merge_queue` pending count `< 50`, and the high-precision (R1–R3) backlog is cleared (see §8).
- [ ] **As-of integrity holds on seeded data:** the doc 13 A-2 graph-purity test passes with real seed+sweep rows present (a link justified by a post-`as_of` sweep event is invisible at `as_of`).
- [ ] 7 consecutive green daily pipeline runs on top of the seeded base (extends doc 03's 7-green-runs criterion to the full pipeline).
- [ ] At least one **non-provisional** momentum state reaches `accelerating`+ from live+sweep data (proves the warm path end-to-end).

For **Stage 6**, the additional gate is: the minimal 8-company map slice (§6) is loaded, `reach_links` populated for the top 10 categories, and the gate passes ≥1 eligible entity while routing unmapped-category hotshots to map-gaps.

---

## 8. Cold-start queue triage mode

`seismo resolve --cold-start` changes two things versus steady state, and nothing else:

1. **Precision-first surfacing.** The merge queue UI (doc 10 `/queue`) shows only **R1–R3** (URL-exact / declared-ID / registry-metadata, confidence ≥0.97) candidate merges first. R4–R6 (owner+name, name+temporal, fuzzy) pairs are written to the queue with `status='deferred_coldstart'` and hidden from the default view. Rationale: the high-precision backlog is large but decisions are near-mechanical (clear coffee-throughput); the fuzzy backlog is where human time is expensive, and it is far smaller and less urgent when the universe is still forming.
2. **Batch clearing.** The `/queue` keyboard triage (doc 10 §2, M/N/S) is the same; you just process the R1–R3 bucket to empty over the first days, then lift the deferral and process R4–R6 normally.

`--cold-start` is a one-time mode. Once §7's queue criterion is met, drop the flag; `resolve` returns to steady state and `deferred_coldstart` items rejoin the normal queue.

---

## 9. Definition of done (Stage 1.5)

- [ ] `seed/seed_entities.yaml` authored (~150–300 entities, every category covered) + `seismo seed-load` idempotent + tested
- [ ] Historical discovery sweep run once; 180d of `origin='backfill'` events present and sane
- [ ] Provisional-state capping + gate exclusion + per-cohort automatic thaw implemented (doc 06 `score` change)
- [ ] Minimal 8-company exposure slice + top-10-category `reach_links` loaded (unblocks Stage 6)
- [ ] `resolve --cold-start` precision-first queue mode implemented
- [ ] All §7 exit criteria green → Stage 3 unlocked
