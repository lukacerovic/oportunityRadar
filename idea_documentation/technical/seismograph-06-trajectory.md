# Seismograph — 06 Trajectory Layer (Momentum)

*Implements idea-spec §5 Layer 4 and §8. Fully deterministic: SQL + a small state machine. No LLM anywhere in this layer.*

> **Amended by doc 13:** **A-2** (cohort joins and metric attribution must resolve entities via `canonical_entity_id(entity_id, as_of)` and `category_asof(entity_id, as_of)` — never the present-time graph, or hindcasts leak future knowledge); **A-5** (`breakout` breadth uses config `SEISMO_BREAKOUT_MIN_BREADTH`, default **2** while ≤3 evidence types are live); **A-11** (`day` = UTC calendar date of `occurred_at`). Cohort warm-up / provisional states during cold start: doc 14 §5.

---

## DR-06.1 — Cohort percentiles in SQL, not pandas
Window functions over `entity_metrics_daily` keep the computation where the data lives, make `as_of` parameterization trivial, and avoid a dataframe layer that would drift from the DB. Python orchestrates; SQL computes. *Dissent (ML Engineer): pandas is easier to iterate on — accepted for prototyping in notebooks, forbidden in the pipeline.*

## DR-06.2 — Momentum states with hysteresis
Raw scores flap; states must not. Promotion to a higher state requires the entry condition to hold **2 consecutive days**; demotion requires the exit condition for **7 consecutive days** (except `fading`, see §5). Slightly late and stable beats instant and jittery — the reader is a human.

## DR-06.3 — Age-bucketed cohorts
Cohort = `(entity_type, category, age_bucket)` with buckets `0–30d, 31–90d, 91–365d, 365d+`. **Quant:** comparing a 2-week repo's star velocity against 3-year incumbents is meaningless; age bucketing is the cheapest fix. Minimum cohort size 8; below that, fall back to `(entity_type, age_bucket)`.

---

## 1. Metric snapshots (`seismo snapshot`)

Reads yesterday's `*_snapshot` events, writes `entity_metrics_daily`. Canonical metrics v1:

| Metric | Source | Semantics |
|---|---|---|
| `gh_stars`, `gh_forks` | github | cumulative counters |
| `hn_points_7d` | hn | rolling sum of story points, 7-day window |
| `hf_downloads_30d` | hf | **level** (rolling 30d) — never diffed as a counter |
| `pypi_downloads_7d`, `npm_downloads_7d` | pypi/npm | rolling weekly |
| `evidence_breadth` | derived | count of evidence *types* active in last 30d (0–5) |

Gaps: forward-fill counters up to 3 days (collector hiccups), never fill levels.

## 2. Velocity & cohort percentile

Daily velocity for counters = 7-day slope; for levels = 7-day change of the level. Then, per metric:

```sql
WITH v AS (
  SELECT entity_id, metric,
         value - lag(value, 7) OVER (PARTITION BY entity_id, metric ORDER BY day) AS vel7
  FROM entity_metrics_daily WHERE day <= :as_of
)
SELECT entity_id, metric, vel7,
       percent_rank() OVER (PARTITION BY cohort_key(entity_id), metric ORDER BY vel7) AS pctl
FROM v JOIN ... -- cohort join, day = :as_of
```

Composite **velocity percentile** per entity = max of its per-metric percentiles across *usage/participation* metrics (attention metrics excluded from the composite by design — see idea-spec principle 3), stored in `momentum_states.inputs`.

## 3. Maturity ladder detection (rules, not inference)

| Stage | Trigger event |
|---|---|
| `idea_paper` | `paper_published`, no code link |
| `public_code` | GitHub entity exists / paper↔repo link lands |
| `usable_artifact` | first `release_published` OR HF weights exist |
| `distribution` | package appears on PyPI/npm (R3 link) |
| `commercialization` | pricing `page_changed` first-seen OR API launch keywords in release/changelog (keyword list, versioned) |
| `institutional_adoption` | ≥3 `job_mention` events from distinct orgs in 90d |

Each promotion inserts into `maturity_promotions` with the evidencing event id — every rung is auditable. Stages are monotonic; regressions are not modeled (a dead project *fades*, it doesn't un-ship).

## 4. Momentum state machine

Inputs per entity/day: `P` = velocity percentile, `B` = evidence breadth, `promo_30d` = promotions in last 30 days, `active` = any event in 14d.

| State | Entry condition (2-day hold) |
|---|---|
| `dormant` | default; `active = false` |
| `simmering` | active AND `P ≥ 0.60` in ≥1 metric |
| `accelerating` | (`P ≥ 0.80` in ≥2 metrics) OR (`promo_30d ≥ 1` AND `P ≥ 0.60`) |
| `breakout` | `promo_30d ≥ 2` OR (`P ≥ 0.95` AND `B ≥ SEISMO_BREAKOUT_MIN_BREADTH`) — default **2** in v1 (only 3 evidence types live; A-5), raise to 3 once the pricing watcher ships the 4th type |
| `fading` | was ≥ simmering; now `P < 0.40` for 14 consecutive days OR inactive 30d |

Thresholds live in config with these defaults; every state change writes a row with full `inputs` JSON. Tuning happens against hindcast cases (doc 11), not vibes.

## 5. Backfill & as-of correctness

`seismo score --as-of D` must be a pure function of events ≤ D. Practical test baked into CI: run score for a past date twice, a week apart, after live data kept arriving → identical output. If it differs, an `ingested_at` leak exists somewhere. This test is non-negotiable; it is what makes the DeepSeek hindcast (H1) mean anything.

## 6. Definition of done
- [ ] Snapshot job + metric semantics table implemented; level-vs-counter handled
- [ ] Cohort percentile SQL + min-size fallback + unit tests on synthetic cohorts
- [ ] Ladder rules + promotions table with evidence ids
- [ ] State machine with hysteresis; state history queryable for sparklines
- [ ] As-of purity CI test green
- [ ] **H1 passes:** DeepSeek reaches accelerating/breakout by 2024-05-31 on backfill data
