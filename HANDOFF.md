# Seismograph — Build Handoff

*Single entry point for any new/compacted session. Read this first. `idea_documentation/technical/seismograph-13-corrections-and-decisions.md` is AUTHORITATIVE on any conflict with other docs. All design lives in `idea_documentation/`; all build state is in git.*

**Last updated after Stage 1** — commits: `6946b15` (Stage 0), `24e4bef` (Stage 1), plus this handoff.
**To resume:** "Read HANDOFF.md and continue the Seismograph build."

---

## 1. What this is

Daily monitoring + impact analysis over where technology is *built* (GitHub, arXiv, HF, PyPI, HN, later Reddit/jobs/pricing). Maintains a living picture of the frontier, tracks every emerging entity through time, and for entities that cross a significance bar produces evidence-linked **impact briefs**: who is exposed, through what mechanism, in which direction, and what to watch. Analyst, not trader — explains **exposure, never predicts prices**. Solo build, personal infra, daily batch. Full spec: `idea_documentation/files/seismograph-00-idea-spec.md`.

**Two goals:** awareness (what's emerging + direction) and consequence (economic impact pathways).
**Four design consequences:** daily heartbeat · explanation-first (every claim traces to raw events) · exposure-not-prices · attention-budgeted (≤5 briefs/week).

## 2. The 7 layers (= the pipeline)

1. **Observation** — collectors record raw, uninterpreted events. *(Stage 1 ✅)*
2. **Identity** — resolve events to durable entities across registries (the hard problem).
3. **Comprehension** — LLM checkpoint 1: entity → structured card + summary.
4. **Trajectory** — deterministic momentum states from velocity/promotions/breadth.
5. **Significance** — deterministic gate: which entities earn a brief under a fixed budget.
6. **Impact** — LLM checkpoint 2: fill the impact-brief schema over the exposure map.
7. **Memory & synthesis** — changes view, forward-scoring, calibration.

**Core ontology:** Event (immutable) · Entity (durable) · Theme (curated cluster) · Momentum state (recomputed daily) · Impact thesis (versioned).
**5 evidence types:** attention (HN) · participation (GitHub) · usage (HF/PyPI) · commitment (jobs) · commercialization (pricing). *Corroboration breadth beats amplitude.* **v1 has only 3 live** (attention/participation/usage) — see A-5.
**Momentum states:** dormant · simmering · accelerating · breakout · fading (with hysteresis).
**Maturity ladder:** idea_paper → public_code → usable_artifact → distribution → commercialization → institutional_adoption. *v1 live tops out at `distribution`* until pricing/jobs collectors ship (A-5).
**5 mechanisms:** substitution · cost_collapse · commoditization · enablement · dependency_risk.

## 3. Reading order (design docs)

`00 idea-spec → 01 build-plan → 13 corrections (AUTHORITATIVE) → 14 cold-start → 02 foundation → 03 observation → 04 identity → 05 comprehension → 06 trajectory → 07 significance → 08 impact → 09 memory → 10 dashboard → 11 validation → 12 operations.` Every layer doc has an "Amended by doc 13" banner.

## 4. Resolved stack (doc 01 §1)

Python 3.12 (uv) · PostgreSQL 16+ (JSONB + window functions + pg_trgm) · SQLAlchemy 2.0 + Alembic (raw SQL for scoring) · Pydantic v2 · Typer CLI · systemd timers · FastAPI (read+curation API) · Next.js 14 dashboard · **pluggable LLM (mock/ollama/anthropic)** · exposure map = YAML-in-git → Postgres · Hetzner VPS + Caddy, no Docker · nightly pg_dump backups.

---

## 5. Progress

| Stage | Status | Commit |
|---|---|---|
| 0 — Foundation | ✅ | `6946b15` |
| 1 — Observation | ✅ | `24e4bef` |
| **1.5 — Cold-start (doc 14)** | ⬜ **NEXT** | — |
| 2 — Identity (+ migration 0002) | ⬜ | — |
| 3 — Trajectory | ⬜ | — |
| 4 — Comprehension (first LLM; needs key or ollama) | ⬜ | — |
| 5 — Dashboard v0 | ⬜ | — |
| 6 — Significance (needs exposure-map slice first, A-1) | ⬜ | — |
| 7 — Impact | ⬜ | — |
| 8 — Memory & scoring | ⬜ | — |
| 9 — Hindcast completion | ⬜ | — |
| 10 — Operations hardening | ⬜ | — |

**Stage 0:** uv project, `src/seismo/` layout, `seismo` CLI, migration 0001 (17 core tables = doc 02 §4), SQLAlchemy models, `as_of` helper + purity test, config, bookkeeping, ruff+mypy+pytest+CI. Exit met.
**Stage 1:** collector framework (dedupe via `RETURNING`, `collector_runs` health, failure isolation), GitHub/HN/arXiv collectors, GH Archive backfill (`origin='backfill'`), CLI `collect`, systemd timer. Idempotency live-proven (hn 193→0, arxiv 293→0). ~486 real events in dev DB.

---

## 6. File map (what exists)

```
src/seismo/
  config.py          pydantic-settings, env prefix SEISMO_ (all keys §9)
  db.py              engine, session_scope, events_asof(as_of, source, origins)  ← the as-of guard
  models.py          SQLAlchemy models for all 17 migration-0001 tables
  bookkeeping.py     record_pipeline_run() context manager
  health.py          doctor checks (run_checks) — extend per stage
  cli.py             typer app: collect (real) + stage skeletons + doctor
  collectors/
    base.py          Window, RawEventDraft, TrackTarget, BaseCollector, RateLimiter
    http.py          make_client() with UA+contact
    runner.py        run_collector(), persist_drafts() (ON CONFLICT … RETURNING)
    registry.py      FACTORIES + GROUPS (fast=github,hn,arxiv), resolve_sources()
    github.py hn.py arxiv.py     Wave-1 collectors
    backfill_gharchive.py        filter_events() (pure, tested) + backfill()
  checkpoints/       contracts.py stub — ONLY place allowed to import anthropic/ollama
  identity/ trajectory/ significance/ memory/ api/ hindcast/   empty (their stages)
alembic/versions/0001_core_schema.py    schema source of truth
tests/               test_asof, test_config, test_invariants, test_collectors, conftest (db_session)
deploy/systemd/      seismo-collect-fast.{service,timer} + deploy/README.md
scripts/check_llm_import.sh   invariant-3 grep
seed/ exposure_map/  empty (.gitkeep) — filled in cold-start / Stage 7
.github/workflows/ci.yml      ruff+format+mypy+invariant+migrate+doctor+pytest
```

**Testing pattern:** `conftest.py` provides `db_session` — a real Postgres transaction that is always **rolled back**, so tests exercise real SQL (ON CONFLICT, pg_trgm, window fns) without persisting. Unit tests default to LLM provider `mock` ($0). `mypy src` only (tests untyped by design).

---

## 7. Environment (this machine)

- **Postgres 17.9** on `localhost:5432`. OS superuser `lukacerovic` (local trust auth). App role **`seismo`**/pw `seismo`, db **`seismograph`**, `pg_trgm` installed.
- **`.env`** (git-ignored): `SEISMO_DATABASE_URL=postgresql+psycopg://seismo:seismo@localhost:5432/seismograph`, `SEISMO_LLM_PROVIDER=mock`.
- **Python 3.12** via uv 0.8.x. **Network works from Bash** (used it to test collectors live).
- **Git repo, committing to `master`, no remote.** Solo linear build. Scratchpad for temp files: `/private/tmp/claude-501/-Users-lukacerovic-Desktop-OportunityRadar/<session>/scratchpad`.
- Convention: end commit messages with `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

## 8. Run / verify

```bash
uv sync
uv run alembic upgrade head
uv run seismo doctor                 # all green expected
uv run pytest -q                     # 12 passing, mock LLM, $0
uv run ruff check && uv run ruff format --check && uv run mypy src
bash scripts/check_llm_import.sh
uv run seismo collect --source fast --window 1d   # live; github needs a token
```

## 9. Config keys (doc 13 Part C) — `SEISMO_` prefix

`DATABASE_URL` · `PRODUCT_NAME=Seismograph` · `LLM_PROVIDER=mock|ollama|anthropic` · `OLLAMA_HOST` · `OLLAMA_MODEL=qwen2.5:7b-instruct` · `MODEL_LIVE` / `MODEL_HINDCAST` (anthropic snapshots) · `ANTHROPIC_API_KEY` · `GITHUB_TOKEN` · `BRIEFS_PER_WEEK=5` · `BREAKOUT_CALLOUTS_PER_DAY=1` · `BREAKOUT_MIN_BREADTH=2` (→3 when 4th evidence type ships) · `LLM_BUDGET_USD` · `COHORT_MIN_SIZE=8` · `COHORT_WARMUP_STATE_CAP=simmering` · `TRACKING_ARCHIVE_DAYS=90` · `PENDING_ALERT_HOURS=48` · `COLDSTART_SWEEP_DAYS=180`.

## 10. Amendments index (doc 13 Part A) — what each fixes

- **A-1** BLOCKER: exposure-map loader + `reach_links` + minimal 8-company slice must exist **before** the Stage 6 gate.
- **A-2** CORRECTNESS (critical): as-of discipline extends to the entity graph — merges/links/category resolved via `canonical_entity_id(id, as_of)`. Prevents hindcast future-leak. → **migration 0002** (§12).
- **A-3** cold start is a real stage (doc 14).
- **A-4** bounded tracking set via `tracking_tier` (active/slow/archived) + `seismo retier`.
- **A-5** v1 = 3 evidence types / 4 ladder rungs; **pricing watcher promoted into v1**; `BREAKOUT_MIN_BREADTH=2`.
- **A-6** gate `R=0` = hard exclusion (unmapped_reach → map-gaps), not a 0.4 floor.
- **A-7** observables are structured + `source: system|manual` (prefer machine-measurable).
- **A-8** pin `MODEL_HINDCAST` snapshot; separate from `MODEL_LIVE`.
- **A-9** arXiv cats extended: +cs.CR, cs.MA, cs.CV, cs.DC (done in Stage 1).
- **A-10** minimal `/search` endpoint (FTS + trigram).
- **A-11** `day` = UTC calendar date of `occurred_at` (done in collectors).
- **A-12** LLM budget-ceiling → status `pending` (≠ `failed`); gate never briefs on a `pending` card.
- **A-13** pluggable LLM provider mock/ollama/anthropic; dev+CI = $0; only prod + H2 spend.

## 11. Resolved decisions (doc 13 Part B)

- **Name:** Seismograph. **Budgets:** 5 briefs/wk, 1 breakout callout/day, no carryover.
- **Changes cadence:** daily deltas + Monday rollup, both deterministic.
- **Human-in-loop:** briefs are draft→review→publish; auto-publish only after 2 quarters of good calibration.
- **Hindcast cases:** DeepSeek (positive, pinned) + **Ollama** (mid-size positive; asserts ladder→distribution + breakout, *not* commercialization) + Reflection-70B (flop negative, must be gate-suppressed). Alternate for commercialization coverage: Continue.dev.
- **Exposure roster (30):** `NVDA AMD TSM AVGO ASML ARM ANET · MSFT AMZN GOOGL META AAPL ORCL · CRM ADBE NOW TEAM WDAY INTU · SNOW MDB DDOG NET CFLT · PLTR SHOP U DOCN PATH CRWD`. **Cold-start minimal 8:** `NVDA MSFT GOOGL AMZN META AMD AVGO SNOW`.

## 12. Migration 0002 spec (author at start of Stage 2 — A-2 + A-4)

```sql
-- A-2: as-of correct entity graph
ALTER TABLE entity_links ADD COLUMN evidence_occurred_at TIMESTAMPTZ;   -- = raw_event.occurred_at (or MAX for R4-R6)
CREATE TABLE entity_merges (
  loser_id BIGINT PRIMARY KEY REFERENCES entities(id),
  survivor_id BIGINT NOT NULL REFERENCES entities(id),
  justified_at TIMESTAMPTZ NOT NULL,            -- MAX(occurred_at) of supporting evidence
  rule TEXT NOT NULL, confidence REAL NOT NULL,
  decided_by TEXT NOT NULL,                      -- 'auto' | 'human'
  decided_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  active BOOLEAN NOT NULL DEFAULT true
);  -- entities.merged_into stays as a convenience denorm; as-of code reads entity_merges
CREATE TABLE entity_category_history (
  id BIGSERIAL PRIMARY KEY, entity_id BIGINT NOT NULL REFERENCES entities(id),
  category TEXT NOT NULL, effective_at TIMESTAMPTZ NOT NULL,
  evidence_event BIGINT REFERENCES raw_events(id), created_at TIMESTAMPTZ DEFAULT now()
);
ALTER TABLE entity_themes ADD COLUMN effective_at TIMESTAMPTZ;
-- A-4: bounded tracking
ALTER TABLE entities ADD COLUMN tracking_tier TEXT NOT NULL DEFAULT 'active';  -- active|slow|archived
ALTER TABLE entities ADD COLUMN tier_reviewed_at TIMESTAMPTZ;
```
Then `canonical_entity_id(entity_id, as_of)` (recursive CTE over `entity_merges` where `active AND justified_at <= as_of`) + `category_asof()` + **graph-purity test** (a link/merge justified by a post-`as_of` event must be invisible at `as_of`). This test is the Stage 2 DoD and what makes hindcasts meaningful.

## 13. Global invariants (enforced forever)

1. Raw events immutable; carry `occurred_at` + `ingested_at`. 2. Every analytical read goes through `as_of` (`occurred_at <= as_of`), never `ingested_at`; extends to the entity graph (A-2). 3. LLM SDKs (`anthropic`/`ollama`) only in `src/seismo/checkpoints/` — CI greps this. 4. Collectors never reason; scorers never fetch; checkpoints never rank. 5. Every merge/gate/brief logged with inputs.

## 14. Gotchas / lessons (do not relearn)

- **GitHub needs `SEISMO_GITHUB_TOKEN`** — Search API 403s unauthenticated; failure is isolated (`ok=false`), not fatal.
- **arXiv query:** join terms with real spaces (`" OR "`), never literal `+OR+` — httpx re-encodes `+`→`%2B` and silently returns 0. (Fixed.)
- **Insert counts:** `RETURNING` + `len(fetchall())`, not `result.rowcount` (−1 for multi-row psycopg3 inserts).
- **Test collectors against real APIs**, not only mocks — both Stage-1 bugs were invisible to mocks.
- **HF `downloads` is a 30-day rolling level, not a counter** — never diff it (doc 03 §2.4). Watch for this in Stage 2/3.
- **No Anthropic key needed until Stage 4** (use `mock`/`ollama`). Keep `anthropic`/`ollama` imports inside `checkpoints/`.
- Snapshot metrics (stars etc.) are states → `event_type='*_snapshot'`, uid `native:UTC-date`; trajectory diffs them.

## 15. NEXT — Stage 1.5 Cold-start (doc 14), then Stage 2 Identity

Recommended order (identity + cold-start interleave — doc 14 §2):
1. **Migration 0002** (§12) + `canonical_entity_id(as_of)` + graph-purity test.
2. Minimal entity resolution: event→entity attachment (doc 04 §2) + deterministic link rules R1–R6 (doc 04 §3) + reversible merges + merge queue + category/theme YAML vocab.
3. `seed/seed_entities.yaml` (~150–300 entities, every category) + `seismo seed-load` (emits `origin='seed'` anchors; idempotent).
4. 180-day historical discovery sweep (Wave-1 collectors in backfill mode + GH Archive loader).
5. `resolve --cold-start` precision-first (R1–R3) queue mode; cohort warm-up hooks (land with Stage 3/6).
6. Minimal 8-company exposure slice — defer until just before Stage 6 (A-1).

**Stage 2 DoD (doc 04 §7):** R1–R6 unit-tested; reversible merge + `canonical_entity_id`; queue populated; theme/category vocab committed; DeepSeek backfill resolves paper 2405.04434 + `deepseek-ai` GitHub + HF into one entity via R1/R2; **graph-purity test green**; sampled queue precision ≥80% at the 0.60–0.89 band.
