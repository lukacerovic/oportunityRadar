# Seismograph — 01 Build Plan (Master Checklist)

*Phase 2 output. Derived from `seismograph-00-idea-spec.md`. This is the map; documents 02–12 are the territory. Work top to bottom; never start a stage before the previous stage's exit criteria pass.*

> **Amended by doc 13 (Corrections & Decisions) and doc 14 (Cold-Start).** Read both immediately after this document and before writing code. Doc 13 is authoritative where it conflicts with anything below; the specific amendments touching this file are **A-1** (exposure-map/`reach_links` before the gate), **A-3** (cold start is Stage 1.5), and **A-4/A-5** (tracking lifecycle; pricing watcher promoted into v1). The corrected reading order and stage map are reflected inline below.

---

## 1. The resolved stack (summary)

Full derivations and dissents live in the layer docs as Decision Records.

| Concern | Choice | Doc |
|---|---|---|
| Language / runtime | Python 3.12, packaged with `uv` | 02 |
| Database | PostgreSQL 16 (single instance, JSONB + window functions) | 02 |
| ORM / migrations | SQLAlchemy 2.0 + Alembic; raw SQL for scoring queries | 02 |
| Validation / contracts | Pydantic v2 everywhere (events, LLM I/O, API) | 02 |
| Scheduling | systemd timers → `seismo` CLI stages (idempotent) | 03, 12 |
| API backend | FastAPI (read API + curation endpoints) | 10 |
| Dashboard | Next.js 14+ (App Router, TypeScript, Tailwind, Recharts) | 10 |
| LLM checkpoints | Pluggable provider behind `checkpoints/llm.py` — `mock`/local `ollama` for dev+CI ($0), Anthropic Claude Sonnet class for prod; structured output via schema — exactly two call sites (comprehension, impact) | 05, 08, **13 A-13** |
| Exposure map | YAML files versioned in git, loaded into Postgres | 08 |
| Hosting | Hetzner VPS (CX32 class), Ubuntu 24.04, no Docker, Caddy reverse proxy | 12 |
| Backups | Nightly `pg_dump` → Hetzner Storage Box via rclone | 12 |
| Historical data (hindcast) | GH Archive, Algolia HN API, arXiv OAI-PMH, PyPI BigQuery dataset | 11 |

**Global invariants** (enforced from Stage 0, checked in code review forever):

1. Raw events are immutable; every event carries `occurred_at` (source time) and `ingested_at` (our time).
2. Every downstream computation takes an `as_of` parameter and may only read events with `occurred_at <= as_of`. This is what makes hindcasting possible without a second codebase.
3. LLM calls exist in exactly two modules: `checkpoints/comprehension.py` and `checkpoints/impact.py`. Nowhere else. CI greps for the SDK import outside `checkpoints/`.
4. Collectors never reason; scorers never fetch; checkpoints never decide what gets attention.
5. Every merge, gate decision, and brief is logged with its inputs — the system must be able to explain itself retroactively.

---

## 2. Stage map and dependency order

```
Stage 0  Foundation ──► Stage 1 Observation ──► Stage 1.5 Cold-start (doc 14) ──► Stage 2 Identity ──► Stage 3 Trajectory
                                                                                                            │
                    Stage 5 Dashboard v0 ◄── Stage 4 Comprehension ◄──────────────────────────────────────┘
                           │
                           ▼
                    Stage 6 Significance ──► Stage 7 Impact ──► Stage 8 Memory & Scoring
                    (needs minimal exposure                            │
                     map slice first — A-1)                            │
                    Stage 9 Hindcast completion ◄─────────────────────┘
                           │
                           ▼
                    Stage 10 Operations hardening
```

**Two amendments to this graph (doc 13):**
- **Stage 1.5 — Cold-start bring-up (doc 14)** sits between Observation and Identity: seed universe + 180-day historical discovery sweep + cohort warm-up. Its exit criteria (doc 14 §7) are the entry gate for Stage 3 — momentum computed against unwarmed cohorts is untrustworthy.
- **Stage 6 depends on a Stage-7 artifact.** The gate's Reach component reads `reach_links`, which come from the exposure-map loader (doc 08). Per **A-1**, the loader + a minimal 8-company map slice (doc 14 §6) are a prerequisite built at the *start* of Stage 6; only the full 30-company curation stays in Stage 7.

The hindcast harness (doc 11) is **not** a late stage — it is built incrementally: its data ingestion starts in Stage 1, and hindcast assertions are the exit criteria of Stages 3, 4, and 7.

---

## 3. Stage checklists

### Stage 0 — Foundation (doc 02)
- [ ] Repo scaffold, `uv` project, lockfile, `seismo` CLI entrypoint (typer)
- [ ] PostgreSQL 16 installed locally + on VPS; roles, database, extensions (`pg_trgm`)
- [ ] Alembic initialized; migration 0001 creates the full core schema (doc 02 §4)
- [ ] Config system: `pydantic-settings`, `/etc/seismograph/env` on server, `.env` locally
- [ ] `as_of` convention implemented as a shared query helper; unit test proving future events are invisible
- [ ] `pipeline_runs` + `collector_runs` bookkeeping tables wired into CLI skeleton
- [ ] pytest + ruff + mypy configured; CI grep rule for invariant 3

**Exit criteria:** `seismo doctor` reports green on an empty database; a fake event inserted with tomorrow's `occurred_at` is invisible to an `as_of=today` query.

### Stage 1 — Observation (doc 03)
- [ ] Collector base contract (`BaseCollector.collect(window) -> list[RawEvent]`)
- [ ] Wave 1 collectors: GitHub, Hacker News (Algolia), arXiv
- [ ] Wave 2 collectors: Hugging Face, PyPI/npm
- [ ] Dedupe on `(source, source_event_uid)` unique index; idempotent re-runs proven
- [ ] systemd timer per collector group; journald logging; `collector_runs` health rows
- [ ] GH Archive backfill script writing into the same `raw_events` table (flagged `origin='backfill'`)

**Exit criteria:** 7 consecutive daily runs with zero manual intervention; re-running a day produces zero duplicate events; backfill of one historical month completes.

### Stage 1.5 — Cold-start bring-up (doc 14)
- [ ] `seed/seed_entities.yaml` authored (~150–300 entities, every category covered); `seismo seed-load` idempotent
- [ ] 180-day historical discovery sweep run once (`origin='backfill'`)
- [ ] Provisional-state capping + gate exclusion + per-cohort automatic thaw (doc 14 §5)
- [ ] `resolve --cold-start` precision-first queue mode (doc 14 §8)

**Exit criteria:** doc 14 §7 — top-10 categories have mature cohorts (≥8), pending queue <50, as-of graph-purity test green on seeded data, 7 green full-pipeline runs. This is the entry gate for Stage 3.

### Stage 2 — Identity (doc 04)
- [ ] **Migration 0002 (A-2, A-4):** `entity_links.evidence_occurred_at`, `entity_merges`, `entity_category_history`, `entity_themes.effective_at`, `entities.tracking_tier`/`tier_reviewed_at` — authored before any resolution code runs
- [ ] `canonical_entity_id(entity_id, as_of)` resolver + graph-purity test (A-2)
- [ ] `seismo retier` tracking-lifecycle job (A-4)
- [ ] `entities`, `entity_links`, `entity_merge_queue` live
- [ ] Deterministic link rules R1–R6 implemented with per-rule confidence
- [ ] Auto-link ≥0.90, queue 0.60–0.90, ignore <0.60 (tunable)
- [ ] Merge operation reversible (provenance retained); CLI `seismo resolve`
- [ ] Theme taxonomy seeded (~15 themes); assignment rules + manual override

**Exit criteria:** DeepSeek backfill data resolves arXiv paper + GitHub org + HF repos into one entity without manual help; merge queue false-positive rate <20% on a 50-item sample.

### Stage 3 — Trajectory (doc 06)
- [ ] `entity_metrics_daily` snapshot job
- [ ] Cohort definition (type × category × age bucket) + percentile SQL
- [ ] Maturity-ladder promotion detection (6 stages, rules table)
- [ ] Momentum state machine with hysteresis; `momentum_states` history table

**Exit criteria (hindcast assertion H1):** replaying the DeepSeek case with `as_of` stepped daily, the entity reaches **accelerating or breakout by 2024-05-31**. Doc 11 defines the assertion format.

### Stage 4 — Comprehension (doc 05)
- [ ] Evidence-pack assembler (entity → bounded, deterministic input document)
- [ ] Anthropic structured-output call with Pydantic-validated schema; retries; cost log
- [ ] Trigger policy: new entity, or maturity promotion, or 30-day staleness + activity
- [ ] `comprehension_cards` versioned storage

**Exit criteria:** 50 cards generated on live data; manual review of 20 finds ≥17 accurate and evidence-grounded; cost per card ≤ $0.03.

### Stage 5 — Dashboard v0 (doc 10)
- [ ] FastAPI read endpoints (radar, entity, changes-stub)
- [ ] Next.js app: Radar view + Dossier view, read-only
- [ ] Merge-queue curation page (the first human-in-the-loop UI)
- [ ] Caddy basic-auth in front

**Exit criteria:** you check it with morning coffee three days in a row and it answers "what moved?" faster than opening the sources manually.

### Stage 6 — Significance (doc 07)
- [ ] **Prerequisite (A-1):** exposure-map loader + `reach_links` derivation + minimal 8-company slice (doc 14 §6) loaded, `reach_links` populated for the top 10 categories
- [ ] Category → threat-surface linkage table (`reach_links`)
- [ ] Novelty proxy (theme crowding, first-mover flag)
- [ ] Gate score + weekly budget mechanics (top-K with carryover)
- [ ] `gate_decisions` audit log including *suppressed* candidates

**Exit criteria:** four weeks of gate output; ≤5 briefs/week enforced; spot-check of suppressed items produces no regretted misses.

### Stage 7 — Impact (doc 08)
- [ ] Exposure map YAML schema + loader + validation; first 30 companies curated
- [ ] EDGAR companyfacts fetcher for revenue-line grounding
- [ ] Impact checkpoint: schema with mandatory counter-mechanism + falsifiers
- [ ] Draft → review → publish workflow in dashboard

**Exit criteria (hindcast assertion H2):** DeepSeek brief generated from ≤2024-05-31 data names cost-structure collapse + layer commoditization, lists NVDA/MSFT/GOOGL-class exposure, and states the counter-mechanism. (H3): Reflection-70B-style flop case generates **no** brief.

### Stage 8 — Memory & scoring (doc 09)
- [ ] Deterministic Changes view (state diffs, promotions, new entities, brief updates)
- [ ] Quarterly brief-scoring workflow + UI fields
- [ ] Momentum-call review job (90-day survival of breakouts)

**Exit criteria:** first Changes digest renders from pure diffs; scoring workflow dry-run on the hindcast briefs.

### Stage 9 — Hindcast completion (doc 11)
- [ ] All three cases (DeepSeek positive, mid-size positive, flop negative) pass as CI-runnable assertions
- [ ] Calibration report v0 generated

### Stage 10 — Operations hardening (doc 12)
- [ ] Backups verified by actual restore drill
- [ ] healthchecks.io pings on all timers; `seismo doctor` covers collectors, queue depth, LLM spend
- [ ] ufw, fail2ban, unattended-upgrades; deploy runbook tested

---

## 4. Effort and cost envelope (solo builder, evenings/weekends)

| Stage | Rough effort |
|---|---|
| 0 | 1 weekend |
| 1 | 2–3 weekends (collectors are fiddly) |
| 2 | 1–2 weekends |
| 3 | 1–2 weekends |
| 4 | 1 weekend |
| 5 | 1–2 weekends |
| 6 | 1 weekend |
| 7 | 2 weekends (map curation is the long pole) |
| 8–10 | 2 weekends |

**Running cost:** VPS ~€8/mo · Storage Box ~€4/mo · LLM ~$10–30/mo at v1 volume · everything else free tiers. Total ≈ €25/mo.

---

## 5. Reading order for the layer docs

**13 Corrections & Decisions → 14 Cold-Start →** 02 Foundation → 03 Observation → 04 Identity → 05 Comprehension → 06 Trajectory → 07 Significance → 08 Impact → 09 Memory & Synthesis → 10 Dashboard → 11 Validation → 12 Operations.

(13 and 14 come first because they resolve every open decision and fix the ordering/correctness bugs that the layer docs would otherwise inherit. 13 is authoritative on any conflict.)
