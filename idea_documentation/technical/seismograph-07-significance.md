# Seismograph — 07 Significance Gate

*Implements idea-spec §5 Layer 5 and §9. Decides which entities earn an Impact Brief this week, under a fixed budget. Fully deterministic.*

> **Amended by doc 13:** **A-1** (the exposure-map loader + a minimal `reach_links` slice are a prerequisite of this stage — build them first, per doc 14 §6), and **A-6** (`R = 0` is a **hard eligibility exclusion**, not a 0.4 floor — see §2 below).

---

## DR-07.1 — No LLM in the gate
**Adversarial Reviewer:** letting a model rank "importance" reintroduces vibes at the exact chokepoint the budget exists to protect. **Verdict:** the gate is arithmetic over three deterministic components. The LLM's judgment enters *after* the gate (writing the brief), never *as* the gate.

## DR-07.2 — Budget as top-K, not threshold
Thresholds drift with the news cycle; a fixed weekly K self-calibrates. K briefs/week (default 5) + at most 1 breakout call-out/day on the dashboard. Weeks with fewer than K worthy candidates simply pass fewer — unused budget does **not** carry forward (scarcity is the feature).

---

## 1. Inputs and cadence

Runs weekly (`seismo gate --week`). Candidate set: entities in `accelerating` or `breakout` at any point during the week, minus entities with a published brief younger than 60 days (re-briefing needs a *new* promotion or a thesis-relevant `page_changed`).

## 2. The three components

**Momentum (M)** — normalized 0–1 from the week's peak state and velocity percentile: breakout=1.0, accelerating=0.7, scaled by composite percentile.

**Reach (R)** — does this plausibly touch the exposure map? Computed from `reach_links` (doc 08 §4): the entity's `category` maps to (ticker, revenue_line, relation) rows curated alongside the map. **Reach is an eligibility gate that precedes scoring (doc 13 A-6):** an entity is gate-eligible only if `R > 0`. Entities with `R = 0` (no mapped surface) are **never scored and never passed** — they get a `gate_decisions` row with `decision='suppressed'`, `components.reason='unmapped_reach'`, and are aggregated into the weekly **map-gaps** list, which forces the map to grow deliberately. Among *eligible* entities: R = 0.5 (touches ≥1 revenue line), 1.0 (touches ≥3 lines or any line flagged `core`).

**Novelty (N)** — proxy without judgment: N = 1.0 if the entity is among the first 3 in its (category, age<180d) cohort; 0.6 if the cohort has <10 members; 0.3 otherwise. Crowded-category clones rank low even when fast.

**Score = M × (0.4 + 0.6·R) × (0.4 + 0.6·N)** — evaluated **only over the eligible set** (`R > 0`, per A-6), so within it `R ∈ {0.5, 1.0}`. The `0.4 + 0.6·N` floor keeps novelty collapse from zeroing a real thesis; zero-reach can no longer buy its way in because it is excluded before scoring, not floored. Weights in config.

## 3. Mechanics & audit

Top-K by score pass → brief generation queue (doc 08). **Every** candidate, passed or suppressed, gets a `gate_decisions` row with the component breakdown. The dashboard's gate page shows both lists — suppressed items are one click from inspection, because trust in the gate comes from being able to check what it *didn't* show you (idea-spec principle 7).

## 4. Tuning loop

Monthly: review suppressed items ≥0.8× the cut line ("near misses"). A regretted miss = raise K or fix R/N inputs — recorded as a note on the `gate_decisions` row so the tuning history is reconstructable. Hindcast H3 (flop case) asserts the gate suppresses attention-only spikes: Reflection-70B-style entities have huge M, near-zero B-corroborated velocity and thin R → must not pass.

## 5. Definition of done
- [ ] Component functions + score with config weights; unit tests incl. edge cohorts
- [ ] `reach_links` populated for all v1 categories or explicitly listed in map-gaps
- [ ] Weekly run wired; audit rows complete; dashboard gate page lists passed + suppressed
- [ ] Four consecutive weeks within budget; near-miss review ritual documented
- [ ] **H3 passes:** flop case suppressed on backfill data
