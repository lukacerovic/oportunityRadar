# Seismograph — 09 Memory & Synthesis Layer

*Implements idea-spec §5 Layer 7 and §9 forward-scoring. The system remembers what it believed and reports when its beliefs change.*

> **Amended by doc 13:** **A-7** (the quarterly scoring screen auto-evaluates `source='system'` observables from metric history before the operator judges the `manual` ones — some falsifiers become auto-trippable); **A-8** (a `SEISMO_MODEL_HINDCAST` bump is a deliberate re-baselining event recorded in the quarterly calibration report §4). Changes-view cadence is confirmed as daily deltas + Monday rollup, both deterministic (idea-spec §13 decision 5, doc 13 Part B).

---

## DR-09.1 — The Changes view is deterministic in v1
**Adversarial Reviewer:** a third LLM checkpoint for "weekly narrative" would creep past the two-call-site invariant for cosmetic benefit. **Verdict:** v1 Changes is templated rendering of computed diffs — honest, cheap, and zero hallucination surface. A weekly narrative checkpoint is explicitly deferred; if added later it becomes a *third registered checkpoint* with its own contract, not an exception smuggled in. *(This resolves the one place the idea spec was soft.)*

## DR-09.2 — Scoring is a ritual with a UI, not an automation
Brief scoring requires judgment about the world; automating it would grade the system with the system. Quarterly, ~1 h, in the dashboard. What *is* automated: assembling everything needed to score in one screen.

---

## 1. Changes computation (`memory/changes.py`, runs daily after scoring)

Diff yesterday→today (and Monday runs also diff week-over-week):
- New entities that survived the 7-day gate (with card one-liner)
- Momentum state transitions, grouped by direction (↑ accelerating/breakout, ↓ fading)
- Maturity promotions (entity, rung, evidence link)
- Brief lifecycle: new drafts awaiting review, published, version bumps
- Gate week summary (Mondays): passed / notable suppressed / map gaps
- Theme rollups: per theme, net entities by state (the "direction of the field" line)

Rendered through fixed sentence templates (`"{entity} promoted to {stage} ({evidence})"`) into a `changes_daily` table consumed by the dashboard Changes view. Templates live in one module; boring on purpose.

## 2. Forward scoring of briefs (quarterly)

For each published brief older than one quarter, the scoring screen shows: the brief, its observables, and auto-fetched context (the entity's metric history since publication; relevant `page_changed` events). Operator records into `brief_scores`:
- `materialized`: yes / partial / no / too_early
- `falsifier_tripped`: bool + which observable
- free-text verdict, incl. "counter-mechanism was the better story" flag

## 3. Momentum-call review (automated, monthly)

- **Breakout survival:** share of entities that entered `breakout` ≥90 days ago still `simmering+` today. Healthy target ≥50%; below → thresholds too loose (doc 06 §4 tuning).
- **Fade accuracy:** share of `fading` calls where the entity re-accelerated within 60 days (should be low).
- Written to a `calibration_snapshots` table; trended on the dashboard.

## 4. Calibration report (quarterly artifact)

One generated markdown file: brief scoring distribution, momentum survival curves, gate near-miss regrets, LLM checkpoint quality-loop grades, map staleness. This report is the input to the two standing governance decisions: (a) may briefs auto-publish yet? (b) do thresholds/weights move? Both decisions are recorded in the report itself — the system's constitution-amendment log.

## 5. Definition of done
- [ ] Diff computations + templates + `changes_daily`; renders in dashboard
- [ ] Scoring screen assembles brief + observables + since-publication context
- [ ] Monthly calibration job + trend storage
- [ ] First quarterly calibration report generated (dry-run on hindcast briefs acceptable)
