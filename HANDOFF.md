# Seismograph — Build Handoff

*Single entry point for any new/compacted session. Read this first. `idea_documentation/technical/seismograph-13-corrections-and-decisions.md` is AUTHORITATIVE on any conflict with other docs. All design lives in `idea_documentation/`; all build state is in git.*

**Last updated: Stages 0–8 DONE + daily heartbeat live (now incl. `changes`).** Foundation, Observation, Identity, Trajectory, Comprehension, Dashboard, Significance, Impact, **and Memory & Synthesis (Stage 8) all shipped**. **Migrations 0001–0005** (`alembic current` = `0005`; 0005 = `changes_daily` + `calibration_snapshots`). FastAPI API (`seismo serve`) + Next.js dashboard (`dashboard/`) render live data; dashboard now has **6 pages: Radar, Changes, Gate, Briefs (+scoring), Queue**. **Running on real data:** `SEISMO_GITHUB_TOKEN` set; **LLM = `ollama`, daily model `qwen2.5:3b-instruct`**. **Dev DB: ~11,480 entities · 90 cards · 8 exposure_companies · 47 reach_links · 1 gate_decision · 1 impact_brief (entity 2857) · ~719 changes_daily rows (today) · calibration_snapshots (n=0, needs 90d).** Momentum: mostly `dormant`; 1 cold-start `breakout` artifact (§19.3).

**This session shipped:** **Stage 8 — Memory & Synthesis (doc 09).** Deterministic **Changes view** (`memory/changes.py` → `changes_daily`, templated diffs, no LLM), automated **momentum calibration** (`memory/calibration.py` → `calibration_snapshots`: breakout-survival + fade-reaccel), and **brief forward-scoring** (`memory/scoring.py`: assembler + **A-7 auto-evaluation** of `system` observables + `record_score`). Migration 0005, `seismo changes`/`seismo calibrate` CLI (+`changes` in `daily.sh`), API (`/changes/{day}`, `/calibration`, `/briefs/{id}/score-packet`, `/briefs/{id}/score`), dashboard `/changes/[day]` + a scoring panel on published briefs. 9 `test_memory.py` + `test_api.py` +1. Also shipped **Stage 7** earlier this session (§20). Full Stage-8 narrative in **§21**.

**IMMEDIATE next task:** Recent ships — HF collector (§25), Reflection-70B GREEN 3/3 (§26), DeepSeek H1a identity proven cheaply + 4 identity fixes (§27), **exposure map curated 8→30 companies (§28)**. Remaining, pick one: (a) **DeepSeek H1b/H2 hindcast** — the HEAVY part (`backfill-stars` over `deepseek-ai`, hundreds of GB; H2 needs `SEISMO_MODEL_HINDCAST` pinned to 7B/anthropic, run 3×; isolated DB per §26.1); (b) **verify the 30-company map figures vs 10-Ks + add CIKs** (§28.3 — engineering is exact, numbers are first-pass); (c) **PyPI collector** (5th evidence type); (d) **run daily for weeks** so momentum wakes up; (e) deploy (Stage 10, LAST). To apply the new map to a DB: `seismo load-map` (§28.4).
**To resume:** "Read HANDOFF.md (esp. §26)." Stages 0–9 complete (harness + all-but-Wayback/PyPI loaders); Reflection-70B validated; DeepSeek is the remaining hindcast; calibration instruments read n=0 until ~90 days of daily momentum accrue.

---

## 1. What this is

Daily monitoring + impact analysis over where technology is *built* (GitHub, arXiv, HF, PyPI, HN, later Reddit/jobs/pricing). Maintains a living picture of the frontier, tracks every emerging entity through time, and for entities that cross a significance bar produces evidence-linked **impact briefs**: who is exposed, through what mechanism, in which direction, and what to watch. Analyst, not trader — explains **exposure, never predicts prices**. Solo build, personal infra, daily batch. Full spec: `idea_documentation/files/seismograph-00-idea-spec.md`.

**Two goals:** awareness (what's emerging + direction) and consequence (economic impact pathways).
**Four design consequences:** daily heartbeat · explanation-first (every claim traces to raw events) · exposure-not-prices · attention-budgeted (≤5 briefs/week).

## 2. The 7 layers (= the pipeline)

1. **Observation** — collectors record raw, uninterpreted events. *(Stage 1 ✅)*
2. **Identity** — resolve events to durable entities across registries (the hard problem).
3. **Comprehension** — LLM checkpoint 1: entity → structured card + summary. *(Stage 4 ✅ engine; mock/ollama/anthropic)*
4. **Trajectory** — deterministic momentum states from velocity/promotions/breadth. *(Stage 3 ✅ engine; live signal awaits the sweep)*
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
| 2 — Identity (migration 0002, R1–R6, merges, queue, vocab) | ✅ core | `a51b0d1` `5eba2d4` `35fc4f7` |
| 1.5 — Cold-start (seed + **180-day sweep RAN**; warm-up built) | ✅ core | `35fc4f7` + sweep run |
| 3 — Trajectory (snapshot + score engine; live H1 needs star history) | ✅ core | `3c46cc1` `dc581ec` |
| 4 — Comprehension (LLM checkpoint 1; mock/ollama/anthropic) | ✅ core | `95f1738` |
| 5 — Dashboard v0 (FastAPI API + Next.js UI) | ✅ core | `b005474` `6074159` |
| 6 — Significance — A-1 map ✅ + gate engine ✅ + gate dashboard page ✅ (`/gate/[week]`) | ✅ | `0056dff`→ |
| 7 — Impact (LLM checkpoint 2: brief contract + pack + orchestrator + CLI + API + dashboard) | ✅ core | see §20 |
| 8 — Memory & Synthesis (changes + calibration + brief forward-scoring w/ A-7 auto-eval) | ✅ core | see §21 |
| 9 — Hindcast completion (H2 DeepSeek; **NEXT candidate**) | ⬜ | — |
| 10 — Operations hardening | ⬜ | — |

**Stage 0:** uv project, `src/seismo/` layout, `seismo` CLI, migration 0001 (17 core tables = doc 02 §4), SQLAlchemy models, `as_of` helper + purity test, config, bookkeeping, ruff+mypy+pytest+CI. Exit met.
**Stage 1:** collector framework (dedupe via `RETURNING`, `collector_runs` health, failure isolation), GitHub/HN/arXiv collectors, GH Archive backfill (`origin='backfill'`), CLI `collect`, systemd timer. Idempotency live-proven (hn 193→0, arxiv 293→0). ~486 real events in dev DB.
**Stage 2 (this session):** migration 0002 (as-of entity graph: `entity_merges`, `entity_category_history`, `entity_links.evidence_occurred_at`, `entity_themes.effective_at`, `entities.tracking_tier`). `canonical_entity_id(session,id,as_of)` + `category_asof()` recursive-CTE helpers in `db.py`. **Graph-purity test green** (future/inactive/transitive/category). Resolution engine (`identity/{normalize,anchors,vocab,resolve}.py`): attachment → R1–R3 auto-merge (reversible, both-endpoints-canonicalized) / R4–R5 queue / R6 audit link; deterministic category (30-slug YAML) + theme (15 YAML). `seismo resolve [--cold-start]`. **DeepSeek DoD proven in tests** (paper+github+hf → one entity via R1/R2). Live: 396 events → 392 entities, idempotent.
**Stage 1.5 (this session):** `seed/seed_entities.yaml` (143 entities, every category) + `seismo seed-load` (idempotent, `origin='seed'`, load-date `occurred_at` so no hindcast pollution). `--cold-start` defers R4–R6 to `deferred_coldstart`. Live: dev DB now **535 entities**; second resolve is a clean no-op. **40 tests green.** (Do not `alembic downgrade` a DB with data — it drops `entity_category_history`; regenerate via `UPDATE entities SET category=NULL` + re-resolve.)
**Stage 3 — Trajectory (this session):** full engine in `src/seismo/trajectory/{metrics,cohorts,velocity,ladder,states,score}.py`, no migration (tables exist from 0001). `seismo snapshot [--as-of]` rebuilds `entity_metrics_daily` from `*_snapshot`/story events — counters (`gh_stars/forks`, ff≤3d), levels (`hf_downloads_30d`/`pypi_downloads_7d`, never filled), rolling (`hn_points_7d`), derived `evidence_breadth`. `seismo score [--as-of]` runs maturity ladder → velocity 7-day-change → **cohort percentiles (as-of correct, Python-ranked over `canonical_entity_id`+`category_asof`+first-evidence age)** → momentum states with hysteresis (2-day promote / 7-day demote / fading) + **cold-start provisional cap at `simmering`** (doc 14 §5). Writes full replayed history `[first_seen..as_of]` per run (upsert). **54 tests green** incl. as-of-purity (score twice = identical, future events invisible) and a synthetic riser→breakout vs flat cohort. **Live momentum status:** token set + sweep ran + heartbeat produced 1,067 `repo_snapshot`s, but every entity is still `dormant` because velocity needs **≥2 snapshots ~7 days apart** (we have ~1 day). This resolves with *time* (daily `track`), not code. **DeepSeek H1** (accelerating/breakout on backfill) still open — needs the heavy GH Archive `backfill-stars`. Engine proven on synthetic cohorts.
**Stage 1.5 tracking (prior + this session):** `seismo track --source github` (systemd `seismo-track`, 06:00 UTC) polls active/unmerged github-anchored entities → `repo_snapshot`. `collectors/targets.py::select_targets`. `track()` isolates **per-target** 404/451 (attrition) AND transient `httpx.TransportError` (one disconnect over ~1,000 sequential polls used to zero the whole ~35-min batch). `seismo sweep --days N` (cold-start discovery loop) + `seismo backfill-stars --since --until [--repos]` (GH Archive `repo_star`→cumulative `gh_stars`, HEAVY). `SEISMO_GITHUB_TOKEN` is set.
**Stage 4 — Comprehension (this session):** LLM checkpoint 1 in `src/seismo/checkpoints/{contracts,llm,evidence,comprehend}.py`. **Migration 0003** adds `comprehension_cards.status` (ok|pending|failed) + `pack_version`. Pluggable provider (A-13): **`mock`** (returns a deterministic rule-derived fallback card, dev/CI = $0), `ollama` (REST, `format`=tool schema), `anthropic` (forced tool call, **no `temperature`** — current models reject it; model from `SEISMO_MODEL_LIVE`/`_HINDCAST`). `contracts.ComprehensionCard` constrains category/maturity to the controlled vocab (`vocab.category_slugs()`, `ladder.MATURITY_STAGES`); `card_tool_schema()` injects the enums. `evidence.build_evidence_pack` is pure/versioned (`PACK_VERSION=1`)/bounded (~12k tok); nothing outside the pack reaches the model. `comprehend.run_comprehend` = trigger policy (DR-05.3: survived-7d+breadth≥2 / promotion-since-card / stale+simmering) → validate-with-one-retry (DR-05.2) then `failed` → versioned store (§5) → **category-disagreement flag** (`card.category_disputed`, never overwrites the rule category) → **budget→`pending`** without calling (A-12). `seismo comprehend [--as-of --entity --limit]`. **70 tests green.** Live-proven at $0 (`comprehend --entity` → valid card). **DoD "50 live cards / 20-card review ≥85% / median ≤$0.03/card" needs a real ollama (`ollama pull qwen2.5:7b-instruct`) or anthropic run** — machinery done, only the spend/eval left. (Only place `anthropic` may be imported is `checkpoints/llm.py` — invariant 3.)
**Stage 5 — Dashboard v0 (this session):** two codebases. **`src/seismo/api/`** = FastAPI read+curation API (the *only* door to the graph; every read takes `?as_of=`): `GET /health /radar /entities/{id} /queue /search` + `POST /merge-queue/{id}/decision` (bearer-gated, DR-10.2; merge appends a reversible `entity_merges` human row). Pydantic models throughout (`api/models.py`) → OpenAPI → TS client. `seismo serve` (uvicorn); config `api_token` + `dashboard_origin` (CORS). **`dashboard/`** = Next.js 14 App Router + Tailwind, **dark "Meridian" palette** (tokens in `tailwind.config.ts`/`globals.css`; teal accent, emerald positive, amber warn; momentum 5-scale is the one place hue = meaning). Views: `/` Radar (momentum→velocity grid, StateChip + SVG sparkline + card one-liner, state filter), `/entity/[id]` Dossier (header+registries, KPI row, CardPanel rendered like the reference AI-summary = thesis vs open-questions, SVG MetricChart w/ promotion dots, MaturityLadder), `/queue` (keyboard M/N/S triage). Charts are hand-rolled SVG (no Recharts) to stay dependency-light. **5 API tests (75 total); `next build` green (TS strict, 4 routes).** Verified end-to-end vs `seismo serve` on the dev DB: Radar renders 240 entities, Dossier renders the card+ladder+KPIs, Queue renders triage. **Run:** `uv run seismo serve` + (in `dashboard/`) `npm install && npm run dev`. `dashboard/node_modules` is git-ignored. Briefs/gate/map/review pages are Stage 7–8 adds.

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
    targets.py       select_targets() — active/unmerged anchored entities → TrackTarget (Stage 1.5)
    github.py hn.py arxiv.py     Wave-1 collectors
    backfill_gharchive.py        filter_events() (pure, tested) + backfill()
  checkpoints/       contracts.py llm.py evidence.py comprehend.py  ← Stage 4 (llm.py = ONLY anthropic import)
                     impact_pack.py impact.py                       ← Stage 7 (brief pack + orchestrator)
  api/               app.py models.py  ← Stage 5 FastAPI (read+curation; the only door to the graph)
dashboard/           Next.js 14 app (App Router, Tailwind, Meridian palette) ← Stage 5 UI; node_modules git-ignored
  identity/          normalize.py anchors.py vocab.py resolve.py seed.py  ← Stage 2/1.5
  trajectory/        metrics.py cohorts.py velocity.py ladder.py states.py score.py  ← Stage 3
  significance/      exposure.py (A-1 map loader + category_reach + RELATION_MECHANISMS) + gate.py (M×R×N)  ← Stage 6/7
  memory/            changes.py (Changes view) + calibration.py (momentum review) + scoring.py (brief forward-scoring + A-7)  ← Stage 8
  hindcast/          empty (its stage)
alembic/versions/0001_core_schema.py    schema source of truth
alembic/versions/0002_asof_entity_graph.py   as-of graph + tracking_tier (A-2/A-4)
alembic/versions/0003_card_status.py         comprehension_cards.status + pack_version (A-12)
alembic/versions/0004_reach_link_core.py     reach_links.core flag for the gate's R=1.0 rule (A-1)
alembic/versions/0005_memory_synthesis.py    changes_daily + calibration_snapshots (Stage 8)
exposure_map/*.yaml                          8-company slice (NVDA MSFT GOOGL AMZN META AMD AVGO SNOW)
seed/categories.yaml themes.yaml seed_entities.yaml   vocab + day-1 universe
tests/               test_asof/config/invariants/collectors/graph_purity/trajectory/comprehension/targets/api/exposure/gate/impact/memory + conftest (db_session, clean_db)
deploy/systemd/      seismo-collect-fast.{service,timer} + seismo-track.{service,timer} + README.md
scripts/check_llm_import.sh   invariant-3 grep
seed/ exposure_map/  empty (.gitkeep) — filled in cold-start / Stage 7
.github/workflows/ci.yml      ruff+format+mypy+invariant+migrate+doctor+pytest
```

**Testing pattern:** `conftest.py` provides `db_session` — a real Postgres transaction that is always **rolled back**, so tests exercise real SQL (ON CONFLICT, pg_trgm, window fns) without persisting. Unit tests default to LLM provider `mock` ($0). `mypy src` only (tests untyped by design).

---

## 7. Environment (this machine)

- **Postgres 17.9** on `localhost:5432`. OS superuser `lukacerovic` (local trust auth). App role **`seismo`**/pw `seismo`, db **`seismograph`**, `pg_trgm` installed.
- **`.env`** (git-ignored): `SEISMO_DATABASE_URL=…`, **`SEISMO_LLM_PROVIDER=ollama`**, **`SEISMO_OLLAMA_MODEL=qwen2.5:3b-instruct`** (daily model — chosen for the 8 GB M2; `qwen2.5:7b-instruct` also pulled ~4.7 GB and gives richer cards but is heavy on 8 GB, use it for occasional batch regens; llama3.2 still installed). The **40 carded repos were regenerated with the 7b** this session. **`SEISMO_GITHUB_TOKEN` set** (classic PAT, public scope). CI/tests still default to `mock` ($0) via conftest. **Ollama runs via the macOS app** (`ollama serve`, `:11434`) — keep the app open for `comprehend`.
- **Dev DB data state (post first daily run, 2026-07-11):** **11,480 entities** (~9,000 github-anchored), **13,880 raw_events**, **1,501 repo_snapshots**, **90 comprehension cards across 42 entities**, **236,548 entity_metrics_daily rows**, **8 exposure_companies + 47 reach_links**, **1 gate_decision** (week 2026-07-06), **2 pending queue pairs**. Momentum: **1 `breakout`** (entity 13523 `rightnow-ai/auto`, promotion-driven artifact — §19), rest `dormant`. This is committed data in the shared dev DB — count-asserting tests MUST use the `clean_db` fixture (conftest, rolled back).
- **Python 3.12** via uv 0.8.x. **Network works from Bash** (used it to test collectors live).
- **Git repo, committing to `main`, no remote.** Solo linear build. Scratchpad for temp files: `/private/tmp/claude-501/-Users-lukacerovic-Desktop-OportunityRadar/<session>/scratchpad`.
- Convention: end commit messages with `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

## 8. Run / verify

**Daily operation:** `./scripts/daily.sh` runs the whole heartbeat (collect→track→resolve→snapshot→score→comprehend); operator guide is `DAILY.md`. `track` is capped via `--limit` (default 1500) because the free GitHub tier is 5000 calls/hr vs ~9000 active targets — bounding the active set properly is a future `retier` (A-4) task.

```bash
uv sync
uv run alembic upgrade head
uv run seismo doctor                 # all green expected
uv run pytest -q                     # 75 passing, mock LLM, $0
uv run ruff check && uv run ruff format --check && uv run mypy src
bash scripts/check_llm_import.sh
# daily pipeline:
uv run seismo collect --source fast --window 1d   # live discovery (github token set)
uv run seismo track  --source github              # daily repo_snapshot (heartbeat)
uv run seismo resolve                             # attach new events → entities/merges
uv run seismo snapshot && uv run seismo score     # trajectory: metrics → momentum states
uv run seismo comprehend                          # LLM cards for trigger-eligible entities (ollama)
# one-offs:
uv run seismo sweep --days 180                    # cold-start discovery over past windows (ALREADY RAN)
uv run seismo comprehend --entity <id>            # force a card for one entity (bypasses trigger)
# app (two terminals + Ollama app open):
uv run seismo serve                               # API :8000
cd dashboard && npm install && npm run dev        # dashboard :3000  (restart API after code edits — no hot-reload)
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

## 12. Migration 0002 (✅ SHIPPED `a51b0d1` — A-2 + A-4)

Authored as `alembic/versions/0002_asof_entity_graph.py` exactly as specced below (plus a
`loser_id <> survivor_id` CHECK and a partial index on active merges). `canonical_entity_id` /
`category_asof` live in `db.py` as recursive-CTE helpers (note: `CAST(:eid AS BIGINT)` in the
CTE anchor — an untyped param breaks the recursive UNION type match). Graph-purity test is
`tests/test_graph_purity.py` (green).

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
- **No Anthropic key needed to run Stage 4** — `mock` (CI/$0) or local `ollama` cover it; only prod/H2 spends. `anthropic` is imported **only** in `checkpoints/llm.py`; ollama is reached via `httpx` (no `ollama` import). `anthropic` path sends no `temperature` (current models 400 on it) and requires `SEISMO_MODEL_LIVE`.
- Snapshot metrics (stars etc.) are states → `event_type='*_snapshot'`, uid `native:UTC-date`; trajectory diffs them.
- **Resolution is global + idempotent, not as-of-gated** — `seismo resolve` sweeps *all* unlinked events (the as-of discipline governs graph *reads* via `canonical_entity_id`, not this write pass). Tests that assert counts must use the `clean_db` fixture (conftest) since the dev DB carries committed events.
- **`_merge_pair` canonicalizes BOTH endpoints then flushes** before writing — transitive refs (hf→paper→repo) must collapse to one terminal survivor, or you hit `entity_merges_pkey` (loser can only be a loser once). Direction: registry-anchored (non-paper) beats paper, then earliest `created_at`.
- **Unowned events reprocess every run** (HN stories with no registry link never get an attachment link) — harmless/idempotent at v1 scale; revisit with a high-water mark if it ever bites.
- **Category matcher allows a trailing `s`** (`\b{kw}s?\b`) so keywords match plurals; word boundaries still keep `rag` out of `storage`.
- **`track()` isolates per-target 404/451 AND transient `httpx.TransportError`** — a deleted/renamed/private repo (attrition) OR one network disconnect over the ~1,000 sequential polls used to zero the whole ~35-min batch (found live twice: a 404, then a `RemoteProtocolError`). Both now skip that one target and continue; a real outage skips them all → `events_new=0` for monitoring. Systemic HTTP status errors (403 rate-limit, 5xx) still raise and fail the run.
- **Two sources feed `gh_stars`** — live `repo_snapshot` (absolute level) and backfilled `repo_star` (cumulative count within the GH Archive window). Velocity (7-day *change*) is correct from either; the seam where they meet (live snapshots right after a historical backfill) shows an absolute-vs-window jump — harmless because a hindcast at a past `as_of` sees only backfill. Snapshot upsert dedups `(entity,metric,day)`.
- **`gh_stars` needs a time series** — a single `track` run is one data point; velocity needs ~2 snapshots ≥7 days apart. The dev DB is all-`dormant` until either the heartbeat accumulates days or `backfill-stars` reconstructs history.
- **Comprehension packs are THIN for swept repos** → cards read terse. The discovery `repo_discovered` payload has only the GitHub *description* (one sentence + topics), **not the README body**. `build_evidence_pack` for such a repo is ~880 chars, so the model (told "use ONLY the pack") can only rephrase the tagline. **The fix is §16 (fetch READMEs)**, not a bigger model or prompt tweak. Inspect any pack: `uv run python -c "from datetime import*;from seismo.db import session_scope;from seismo.checkpoints.evidence import build_evidence_pack; s=session_scope().__enter__(); print(build_evidence_pack(s,<id>,datetime.now(UTC)).markdown)"`.
- **Radar cold-start ordering** (`29d1fed`): when momentum is uniform (all dormant), the API's `/radar` sorts by `state → velocity → has-card → newest-created → id`, so swept repos + carded entities surface instead of low-id arXiv papers. Revisit if this masks something once momentum is live.
- **CORS is localhost-port-agnostic** (`f201e96`): API allows `http://(localhost|127.0.0.1):\d+` so `/queue` client-fetch works whether Next lands on 3000 or 3001. The API has **no hot-reload** — restart `seismo serve` after editing `api/`.
- **Leftover servers hold ports** — `seismo serve` runs as a `python` process (not literally `uvicorn`); `pkill -f uvicorn` misses it. Free a port with `lsof -ti tcp:8000 | xargs kill`.
- **`sweep` discovery events carry historical `occurred_at`** (repo creation date, spread over the window) — good for entity age/cohorts, but it means most swept repos have **1 evidence type** so `comprehend`'s auto-trigger (breadth≥2) skips them; that's why cards were generated by forcing `--entity` on the top-by-stars repos.

## 15. NEXT — let momentum accrue, then Stage 6 (§16 README enrichment is DONE)

**Done this session (✅):** **§16 README enrichment** (see §16) — collector `readmes()` + `enrich-readmes` CLI + `_absorb_payload` fold; enriched all 40 carded repos; **pulled `qwen2.5:7b-instruct`** and regenerated all 40 cards on the fat packs (function 40/40, open_questions 37/40). Set `.env` `SEISMO_OLLAMA_MODEL=qwen2.5:7b-instruct`. (Prior sessions: Stage 5 Dashboard; first real-data run — `SEISMO_GITHUB_TOKEN`, ollama, 180-day sweep 1,366→11,056 entities, heartbeat 1,062 snapshots, radar cold-start ordering `29d1fed` + localhost CORS `f201e96`.)

**Run the app:** Ollama app open → `uv run seismo serve` (:8000) → `cd dashboard && npm run dev` (:3000/3001). Point at a non-default API with `SEISMO_API_BASE`. **Restart the API after editing `api/`** (no hot-reload).

**Immediate next task → §16 (README enrichment).** The user's live feedback: cards are accurate but **too short**, because packs contain only the GitHub one-line description, not the README. §16 is the plan to fix it.

**Then, in rough order:**
1. **Live momentum:** run `seismo track` daily (systemd `seismo-track` on a server) → real `gh_stars` velocity over ~8 days → run `snapshot`+`score` → Radar shows Simmering/Accelerating/Breakout instead of all-dormant. This needs *time*, not code.
2. **Stage 4 DoD grade:** once cards are enriched (§16), grade ~20 A/B/F; optionally `ollama pull qwen2.5:7b-instruct` (set `SEISMO_OLLAMA_MODEL` back to it) for better prose.
3. **DeepSeek H1** (Stage 3 tail): heavy GH Archive `backfill-stars --repos deepseek-ai` → resolve → snapshot/score `--as-of 2024-05-31`. Hundreds of GB; run once when doing hindcast validation.
4. **Queue-precision ≥80%** (Stage 2 tail) · **`seismo retier`** (A-4) — low priority.

**Then Stage 6 — Significance (doc 07):** the deterministic gate that picks ≤5 briefs/week. **BLOCKER A-1:** build the exposure-map loader + `reach_links` + the minimal 8-company slice (`exposure_companies`/`reach_links` tables exist, empty) *before* the gate. Gate never briefs on a `pending` card (A-12); `R=0` = hard exclusion → map-gaps (A-6). Provisional/cold-start entities excluded from the candidate set (doc 14 §5). Then the gate audit page (`/gate/[week]`) + brief pages are Stage 7's dashboard adds.

**Dashboard gotchas for next session:** (a) the dashboard reads the API only — start `seismo serve` first or every page shows the "Can't reach the API" panel. (b) `dashboard/lib/types.ts` mirrors `api/models.py` *by hand* — if you change a response model, update both (or generate from OpenAPI). (c) charts are dependency-light SVG (`components/{Sparkline,MetricChart}.tsx`), not Recharts. (d) curation POSTs are open in dev (`api_token` empty); set `SEISMO_API_TOKEN` + send `Authorization: Bearer` before exposing the API. (e) the momentum 5-colour scale lives in `dashboard/lib/format.ts::STATE_META` and `tailwind.config.ts` — keep them in sync.

**Comprehension gotchas (still current):** (a) `mock` returns the deterministic *fallback* card (rule category + "not established by evidence" text) — real content needs ollama/anthropic. (b) The model's `category` is a **proposal**: stored as `card.category` + `card.category_disputed`, but `entity_category_history` (the deterministic category) is never touched. (c) budget is a **calendar-month** sum of `cost_usd`; `pending` cards (A-12) carry the fallback card + `status='pending'` and cost 0. (d) forcing `--entity` bypasses the trigger and always appends a new version. (e) `anthropic` path sends **no `temperature`** (rejected by current models) and needs `SEISMO_MODEL_LIVE` set or it raises.

**Trajectory gotchas (still current):** (a) `score` writes the **whole replayed history** `[first_seen..as_of]` each run and a later `as_of` rewrites recent days — expected for a daily heartbeat, still pure per `as_of`. (b) Cohort membership is evaluated once at the run's `as_of` (velocities are per-day) — a deliberate, documented simplification that keeps `score --as-of D` a pure function of events ≤ D. (c) `evidence_breadth` needs ≥2 evidence *types* for a `breakout` (A-5, `BREAKOUT_MIN_BREADTH=2`); a github-only entity tops out below breakout no matter how fast it rises. (d) percentile ranking is done in Python (not SQL `percent_rank`) because cohort membership is as-of-dependent; the heavy 7-day window is still set-wise.

---

## 16. ✅ DONE — enrich comprehension packs with repo READMEs

**Shipped this session.** Implemented exactly as planned below. `GitHubCollector.readmes()` fetches
`GET /repos/{full_name}/readme` (raw Accept, per-target 404/451/TransportError isolation like `track`,
idempotent uid `repo_readme:{full_name}`, body ≤20k). `resolve._absorb_payload` folds the README
`text` into `entities.attrs['text']` (still capped 4k) — no pack-builder change, so `PACK_VERSION`
stays 1. New CLI `seismo enrich-readmes [--limit N] [--carded-only]` over `select_targets` /
`select_carded_targets` (new helper: unmerged github-anchored entities that already have a card). +3
tests (readme fetch/404/transient/empty skip; README text folds into attrs). Quality gate green.
**Ran it:** all 40 carded github repos enriched → resolved (folded 35 new README events, refined 15
categories) → cards **regenerated with qwen2.5:7b-instruct** on the fat packs. Result: packs ~550–850
→ ~4,400 chars; `function` 40/40 and `open_questions` 37/40 (both empty before); `claimed_advantage`
went from empty to grounded multi-sentence pitches. The optional `detail` field was judged
**unnecessary** — the existing structured fields now carry the depth. **Loose end:** qwen tends to
over-read `maturity_stage` (`institutional_adoption` for small repos); it's only the model's proposal
(the deterministic ladder is untouched), but a prompt tweak could rein it in. **To broaden:**
`seismo enrich-readmes --limit N` (no `--carded-only`) enriches active-tier repos beyond the 40;
scope with `--limit` (5000 GitHub calls/hr). Original planning notes below, kept for reference.

**Why:** User feedback on live cards — accurate but **too short**. Root cause (verified, not guessed): the evidence pack for a swept GitHub repo is ~880 chars because it contains only the GitHub *description* (one sentence + topic list), **no README body**. The system prompt forbids outside knowledge, so the model can only rephrase the tagline. Bigger models / prompt tweaks won't help — the **input** is thin. Fix = put the README in the pack.

**Architectural fit (respect invariant 4: collectors fetch, checkpoints never fetch).** Do NOT fetch inside `build_evidence_pack`. Instead: a collector fetches the README and records it as a raw event; `resolve` folds its text into `entities.attrs['text']`; the pack builder already reads `attrs['text']` (truncated to 4k, doc 05 §2). So:

1. **Collector** — add `GitHubCollector.readme(full_name)` → `GET https://api.github.com/repos/{full_name}/readme` with `Accept: application/vnd.github.raw` (or default + base64-decode `content`); on 404 return None. Emit a new event: `event_type='repo_readme'`, `source='github'`, `source_event_uid=f"repo_readme:{repo_id}"` (idempotent), `payload={'full_name':…, 'text': readme[:20000]}`. Reuse the 2s `RateLimiter`. Isolate per-target errors like `track()` (404/`TransportError` skip).
2. **Wire it** — either fold into `track()` (one extra call per repo — but that doubles track's API budget; ~9k repos > 5000/hr so scope to active-tier or a `--limit`), OR a dedicated `seismo enrich-readmes [--limit N]` command over `select_targets(...)`. **Recommended for the immediate win:** a small command that enriches just a target set; run it first on the **41 already-carded repos** (fast, ~41 calls) to prove the quality jump, then broaden.
3. **`resolve` absorb** — in `identity/resolve.py::_absorb_payload`, add the README field to the text chunks it folds into `attrs['text']` (it already reads `title/description/summary/topics/tags`; add `payload.get('text')` when `event_type=='repo_readme'`, or just include `text`). Keep `_TEXT_CAP=4000`.
4. **Re-run** for the enriched set: `resolve` → `comprehend --entity <id>` (or plain `comprehend`). Cards should get materially richer (and `open_questions` stops being empty).
5. **Tests** — mock the README HTTP (like `test_github_track_skips_deleted_repos`): 200 with body → `repo_readme` draft with text; 404 → skipped. Assert `_absorb_payload` folds README text into `attrs['text']` and the pack includes it.

**Complementary (optional):** `ollama pull qwen2.5:7b-instruct` + set `SEISMO_OLLAMA_MODEL=qwen2.5:7b-instruct` — better prose *once the pack has real content*. And note the card schema deliberately caps `what_it_is` ≤60 words (analyst tile, not essay); if the user wants longer prose after enrichment, consider adding a `detail`/`summary` field to `ComprehensionCard` (migration not needed — it's JSONB) + render it in `dashboard/components/CardPanel.tsx`.

**Verify the fix like this (before/after):** print the pack (`build_evidence_pack(s, <id>, now)` — see §14 gotcha) — it should jump from ~880 chars to ~4k with real README content; then the regenerated card should be several sentences of substance rather than a rephrased tagline.

**Watch-outs:** README fetch is 1 API call/repo (rate-limited, 5000/hr authenticated) — don't blast all 9k at once; scope with `--limit`/active-tier. `repo_readme` events get historical-or-now `occurred_at` (use `now` — it's an enrichment, not a discovery); this doesn't affect as-of momentum since README text isn't a metric. Keep `anthropic`/`ollama` out of the collector (invariant 3 is about SDK imports; the collector uses `httpx` — fine).

---

## 17. Stage 6 — Significance (IN PROGRESS)

**A-1 exposure map — DONE this session.** The gate's prerequisite (doc 07 §5, doc 14 §6) is built:
- `src/seismo/significance/exposure.py` — Pydantic schema (`ExposureCompanyDoc` → `RevenueLine` → `ThreatSurface`) + `load_map()` + `derive_reach_links()`. Validates: revenue shares sum ≤1.05, every `threat_surface.category` in the vocab, every line has a `source`, controlled `relation` set. `reach_links` are **authoritatively rebuilt** per company on every load (drop-then-derive), so YAML is the sole truth.
- **Migration 0004** adds `reach_links.core` (the gate's R=1.0 "any core line" rule reads it directly).
- **`exposure_map/*.yaml`** — the minimal **8-company slice**: NVDA MSFT GOOGL AMZN META AMD AVGO SNOW. Loaded: 8 companies, 25 revenue lines, **47 reach_links, 18 categories covered** (target was top-10). Core threats flagged: NVDA/model-efficiency, GOOGL/rag-framework, MSFT/code-assistant, SNOW/data-pipeline, META/multimodal-model.
- **`seismo load-map [--path --strict]`** CLI; `tests/test_exposure.py` (9 tests: schema validation, core OR-ing, authoritative rebuild, all 8 real files valid, idempotent load).
- ⚠️ **The revenue-share NUMBERS are first-pass approximations** flagged in each line's `source` — the *engineering* is exact; the *figures* need verification against 10-K segment notes in the quarterly refresh (doc 08 §5). This is operator curation, not code.

**Run it:** `uv run alembic upgrade head` (applies 0004) → `uv run seismo load-map`.

**The gate engine — DONE this session.** `src/seismo/significance/gate.py` + `seismo gate --week`:
candidate selection (non-provisional accelerating/breakout in the week, minus recently-briefed) →
**M×R×N** score → top-`briefs_per_week` pass, rest suppressed → a `gate_decisions` audit row for
**every** candidate (pass + suppressed with `reason`: `unmapped_reach`/`card_pending`/`budget`).
M = peak-state base (breakout 1.0 / accel 0.7) × (floor + (1−floor)·P_peak); R via `reach_links`
(R=0 hard-excluded per A-6 → map-gaps; else 0.5, or 1.0 if ≥3 lines or any `core`); N = first-3 in
(category, age<180d) cohort → 1.0 / small cohort → 0.6 / crowded → 0.3, from the doc-06 cohort facts.
Gate config keys added (`gate_*`). Re-runnable (deletes the week's rows first). **`tests/test_gate.py`
(9 tests)** on synthetic momentum: A-6 hard exclusion, A-12 pending-card block, provisional
exclusion, top-K budget, the score/momentum arithmetic, and **H3** (breakout + zero-reach flop →
suppressed, never briefed). Live smoke: `seismo gate` on the dev DB = 0 candidates (all-dormant, as
expected). **Reference — the original NEXT plan (now built):**
1. **Candidate set** (doc 07 §1): entities `accelerating`/`breakout` during the week, minus published-brief-<60d, minus **provisional** qualifying states (doc 14 §5 — read `momentum_states.inputs.provisional`).
2. **Components:** **M** from peak state (breakout=1.0, accelerating=0.7) × velocity percentile `inputs.P`; **R** from `reach_links` matched on the entity's `category_asof` — **R=0 is a hard exclusion** (A-6) → `decision='suppressed'`, `reason='unmapped_reach'`, aggregated into **map-gaps**; among eligible R∈{0.5 (≥1 line), 1.0 (≥3 lines or any `core`)}; **N** = first-3-in-(category,age<180d)-cohort→1.0, cohort<10→0.6, else 0.3.
3. **Score = M × (0.4 + 0.6·R) × (0.4 + 0.6·N)** over the eligible set only. Top-K (`briefs_per_week`=5) pass. **Every** candidate (passed/suppressed) gets a `gate_decisions` row with the component breakdown (table exists: entity_id, week, decision, score, components JSONB).
4. **`seismo gate --week`** wired (currently a stub in cli.py); tests incl. edge cohorts + **H3** (Reflection-70B-style flop: high M, thin R → suppressed). Add config weights if tuning is needed (defaults inline).
5. ~~Stage 7 dashboard: `/gate/[week]` page~~ **DONE** — API `GET /gate/{week}` (`api/app.py`, models `GateWeekResponse`/`GateDecisionItem`/`GateComponents`) + Next page `dashboard/app/gate/[week]/page.tsx` (passed + suppressed-with-reasons + map-gaps + week switcher; nav "Gate" → `/gate/current`). Verified live: renders the real suppressed breakout (`rightnow-ai/auto`, Card-pending, M0.50 R1.00 N0.30). Next real Stage-7 work is the **impact brief** (LLM checkpoint 2, doc 08 §2 — new contract in `checkpoints/contracts.py`).

**Gotchas:** (a) the gate is deterministic — **no LLM** (DR-07.1); the model only writes the brief *after* the gate. (b) `R=0` excludes *before* scoring, not a floor (A-6). (c) provisional/cold-start entities never earn a brief (doc 14 §5) even if `accelerating`. (d) with everything currently `dormant`, the live gate passes nobody until momentum accrues — test the gate on synthetic/hindcast momentum rows, not the current dev DB. (e) the exposure-map figures are placeholders — don't cite them as real financials.

---

## 18. Backlog / noted follow-ups (not blocking)

Recorded from the first real daily-heartbeat run (`./scripts/daily.sh`, 2026-07-11). Neither is
urgent; both improve signal quality.

1. **More tracked sources — HF + PyPI (usage evidence, A-5 / Wave 2).** Today only **GitHub** has a
   live `track` loop: `collectors/targets.py::_SOURCE_REGISTRY = {"github": "github"}`. arXiv and HN
   are point-in-time (a paper/story is captured once at discovery — nothing to re-poll), so momentum
   in v1 rides on **gh_stars velocity + hn_points_7d (rolling) + evidence_breadth**. To add
   multi-source corroboration, build **HF** (model download counts) and **PyPI** (package downloads)
   *tracking* collectors → add their registry to `_SOURCE_REGISTRY` → fill the `hf_downloads_30d` /
   `pypi_downloads_7d` metrics (already scaffolded as `level`-type in `trajectory/metrics.py` but
   never populated). **Gotcha:** HF `downloads` is a 30-day rolling *level*, not a counter — never
   diff it. This lifts the `BREAKOUT_MIN_BREADTH` bar to a real ≥2-type corroboration and is part of
   A-5 (which also promotes a pricing watcher into v1).

2. **Seed org-anchors waste track budget (data-quality fix).** The first daily `track` polled 1500
   targets but produced only **434 snapshots** — most misses are seed entries anchored on a github
   **org handle** (e.g. `deepseek-ai`) rather than a repo (`deepseek-ai/DeepSeek-V2`), so
   `GET /repos/{org}` 404s (skipped, harmless, but it consumes rate budget + `--limit` slots that
   yield nothing). Quick fix: in `select_targets`, only return github anchors that look like
   `owner/repo` (`native_id LIKE '%/%'`) so org handles aren't polled as repos; or split org anchors
   into a `github_org` registry. Org entities still matter for identity/references — this only
   changes what gets *deep-polled for stars*.

**Also still open from earlier (unchanged):** `retier` (A-4, bound the ~9000-entity active set so
`track` covers the *right* repos, not just an id-ordered slice); DeepSeek **H1/H2** hindcast
(`backfill-stars`); dashboard `/gate/[week]` page; then **Stage 7** impact brief (LLM checkpoint 2).

---

## 19. SESSION LOG (2026-07-11 pm) + Stage 7 plan — READ THIS TO CONTINUE

This session took the build from "Stage 5 done, all dormant" to **Stages 0–6 complete with a live
daily heartbeat and the first real run**. Commits (newest first): `a9d3d3b` gate dashboard page ·
`507f092` §18 backlog · `98bddda` daily script · `2448d82` gate engine · `0056dff` A-1 exposure map
· `76d62b6` daily model note · `45bc898` §16 README enrichment. All on `main`, no remote.

### 19.1 What shipped, in order
1. **§16 README enrichment (`45bc898`).** `GitHubCollector.readmes()` (fetch `GET /repos/{full_name}/readme`, raw Accept, per-target 404/451/TransportError isolation, idempotent uid `repo_readme:{full_name}`, body ≤20k) → `resolve._absorb_payload` folds README `text` into `entities.attrs['text']` (still 4k-capped, so `PACK_VERSION` unchanged) → `seismo enrich-readmes [--limit N] [--carded-only]` over `select_targets`/new `select_carded_targets`. Ran it: all **40 carded repos** enriched, packs jumped **~550–850 → ~4,400 chars**. **Pulled `qwen2.5:7b-instruct`, regenerated all 40 cards** on the fat packs — `function` 40/40, `open_questions` 37/40, `claimed_advantage` now grounded (were empty before). Then **set `.env` to `qwen2.5:3b-instruct` for daily use** (8 GB M2; 7b too heavy for daily) (`76d62b6`). +3 tests.
2. **Stage 6 A-1 exposure map (`0056dff`).** `src/seismo/significance/exposure.py`: Pydantic `ExposureCompanyDoc→RevenueLine→ThreatSurface` + `load_map()` + `derive_reach_links()`. Validates shares≤1.05, threat categories ∈ vocab, every line sourced, controlled `relation` set. **Migration 0004** = `reach_links.core`. **`exposure_map/*.yaml`** = 8 companies (NVDA MSFT GOOGL AMZN META AMD AVGO SNOW) → 47 reach_links / 18 categories. `seismo load-map`. **⚠ revenue figures are FIRST-PASS PLACEHOLDERS** (flagged per line's `source`) — verify vs 10-Ks. `tests/test_exposure.py` (9).
3. **Stage 6 gate engine (`2448d82`).** `src/seismo/significance/gate.py` + `seismo gate --week`: candidates = non-provisional accel/breakout in the week, minus recently-briefed → **M×R×N** → top-`briefs_per_week` pass, rest suppressed → a `gate_decisions` row per candidate (reason: `unmapped_reach`/`card_pending`/`budget`) + map-gaps. Config `gate_*` keys. `tests/test_gate.py` (9) incl. **H3** flop-suppression. Deterministic, **no LLM** (DR-07.1).
4. **Daily heartbeat (`98bddda`).** `scripts/daily.sh` (collect→track→resolve→snapshot→score→comprehend, per-step isolation, `logs/`, `TRACK_LIMIT` default 1500) + **`DAILY.md`** operator guide.
5. **Gate dashboard page (`a9d3d3b`).** API `GET /gate/{week}` (`GateWeekResponse`/`GateDecisionItem`/`GateComponents` in `api/models.py`) + `dashboard/app/gate/[week]/page.tsx` (budget, week switcher, passed + suppressed-with-reasons + map-gaps; nav "Gate"→`/gate/current`). `tests/test_api.py::test_gate_week_audit`. **Verified live** against `seismo serve`.

### 19.2 First real daily run (2026-07-11, via `./scripts/daily.sh`)
collect **+371 gh / +74 hn** · track **1500 targets → 434 snapshots** · resolve **+424 entities, 2 merges** · snapshot/score fresh · comprehend +1. **First-ever momentum: 1 `breakout` (`rightnow-ai/auto`, model-efficiency, entity 13523).** Gate now yields **1 candidate**, correctly **suppressed `card_pending`** (A-12). Everything else still `dormant`.

### 19.3 IMPORTANT FINDING — the first breakout is a cold-start artifact, not real momentum
Entity 13523's breakout is driven by **`promo_30d=2`** (two maturity-ladder promotions in 30d), NOT star velocity: its inputs show **`P=0.0`, `breadth=1`, `count_95=0`**. Cause: today was the **first-ever ladder run**, which stamped clustered promotions (idea_paper→public_code…) "recently" for repos already sitting a rung up → `promo_30d≥2` trips the `raw_tier` breakout condition (`states.py`). It's *legitimate per the state machine* but weak — and the gate **already discounts it** (M = base×P_peak = `1.0×(0.5+0.5·0)=0.5`). **It will wash out** as those promotions age past 30 days. Not a bug; do NOT "fix" it. Real (velocity-driven) breakouts need ~a week of daily `track`.

### 19.4 Gotchas / learnings from THIS session (don't relearn)
- **`test_config.py::test_defaults_are_dev_safe` FAILS** (pre-existing, not ours): `.env` sets `SEISMO_LLM_PROVIDER=ollama` so `Settings()` reads `ollama` where the test asserts `mock`. Full suite is **95 passed / 1 failed** = only this. Ignore, or the fix is to make that test construct Settings ignoring `.env`.
- **The shell is zsh** — unquoted `$VAR` does **NOT** word-split (unlike bash). Cost us a silently-failing regen loop. In scripts, split explicitly or read args from a file. (`scripts/daily.sh` uses `set -o pipefail` so a step failing through `| tee` is caught.)
- **track attrition:** 1500 targets → only 434 snapshots because many **seed anchors are github *org* handles** (`deepseek-ai`) not repos → `GET /repos/{org}` 404s. Wastes rate budget + `--limit` slots. Fix in §18 (filter `native_id LIKE '%/%'` in `select_targets`).
- **Only GitHub has a live `track` loop** (`targets.py::_SOURCE_REGISTRY = {"github":"github"}`). arXiv/HN are point-in-time (captured once at discovery — nothing to re-poll). Momentum rides on **gh_stars velocity + hn_points_7d (rolling) + evidence_breadth**. More tracked sources (HF/PyPI downloads) = §18 / A-5.
- **Exposure-map financials are placeholders** — never cite them as real numbers.
- **API has no hot-reload** — restart `seismo serve` after editing `api/`. Free a port: `lsof -ti tcp:8000 | xargs kill`.
- **Dashboard now 3 pages** (Radar/Gate/Queue); `dashboard/lib/types.ts` still mirrors `api/models.py` **by hand** — update both. `next build` green (TS strict, 5 routes).

### 19.5 NEXT — Stage 7: the Impact Brief (LLM checkpoint 2, doc 08 §2)
The payoff: a *passed* entity → an evidence-linked brief naming **who is exposed, via what mechanism, in which direction, and what to watch**. **Explain exposure, never predict prices.** Human review before publish (DR-08.2: draft→review→publish). Nothing blocks it — the gate, exposure map, and cards it reads all exist.

**Build order (mirror the Stage 4 comprehension pattern — it's the template):**
1. **Contract** in `checkpoints/contracts.py` (doc 08 §2, verbatim): `ImpactBrief` (entity_ref, `mechanisms: list[MechanismEnum]` [substitution|cost_collapse|commoditization|enablement|dependency_risk], `transmission_path: list[TransmissionStep{from_node,to_node,effect}]`, `exposures: list[Exposure{kind:ticker|sector_class, ref, revenue_line, direction:negative|positive|ambiguous, magnitude_class:marginal|material|structural}]`, `counter_mechanism` REQUIRED, `observables: list[Observable{statement, source:system|manual, system_metric, horizon, direction_if_thesis_holds}]` ≥1, confidence, horizon, summary ≤200w, evidence_refs). Add a `brief_tool_schema()` like `card_tool_schema()`.
2. **Input pack** (deterministic/versioned like `evidence.py`): latest comprehension card + momentum summary + **only the exposure-map slices whose `reach_links` match this entity's category** (never the whole map) + mechanism taxonomy verbatim. System prompt: doc 08 §3 ("You explain exposure; you never predict prices. State the strongest counter-mechanism as convincingly as its holder would. Ambiguous is a finding, not a failure.").
3. **Orchestrator** `checkpoints/impact.py` (like `comprehend.py`): pull the gate's passed queue → build pack → forced tool call via `llm.py` → validate + **post-validation** (every ticker exposure's `revenue_line` must exist in the loaded map; every mechanism legal for the touched `threat_surface` relations) with one retry then `failed` → store `impact_briefs` (table exists: entity_id, version, as_of, brief JSONB, status default `draft`, model, cost_usd). Model from `SEISMO_MODEL_LIVE`/pinned `_HINDCAST` (A-8); ollama fine for dev.
4. **CLI** `seismo brief --entity-id N` (stub exists in `cli.py`) — fed by the gate queue.
5. **Dashboard** `/brief/[id]` page: render the schema (transmission path, exposures table, counter-mechanism, observables) + evidence links + **draft→review→publish/reject-with-reason** (curation POST, bearer-gated like `/merge-queue`).
6. **DoD / H2:** DeepSeek brief from ≤2024-05-31 data names cost_collapse + commoditization, NVDA/MSFT/GOOGL-class exposures, a real counter-mechanism, dated observables (needs the heavy `backfill-stars` hindcast — can defer; build the machinery first and prove on a live carded entity).

**Invariants that still bind Stage 7:** LLM SDKs only in `checkpoints/` (invariant 3; ollama via httpx, `anthropic` only in `llm.py`); the gate never briefs a `pending` card (A-12); `R=0` never reaches a brief (A-6); provisional entities excluded (doc 14 §5). To actually *see* a brief today you'd need a carded, non-dormant, mapped entity — currently none qualify (13523 is card_pending + velocity 0). Either card 13523 and force a brief to prove the path, or wait for real momentum.

---

## 20. SESSION LOG (2026-07-11, cont.) — Stage 7 the Impact Brief, SHIPPED

Built Stage 7 exactly to the §19.5 plan (which is now DONE — the plan text above is kept as the spec). The whole checkpoint-2 path is live and proven on real data.

### 20.1 What shipped (files)
1. **Contract — `checkpoints/contracts.py`.** Added `MECHANISMS` (the closed taxonomy tuple), `TransmissionStep`, `Observable`, `Exposure`, `ImpactBrief` (validators: mechanisms ∈ taxonomy, `counter_mechanism`/`observables` required via `min_length`, `summary` coerced to ≤200 words), and `brief_tool_schema()` (injects the mechanism enum onto the array items, like `card_tool_schema`).
2. **Relation→mechanism legality — `significance/exposure.py`.** `RELATION_MECHANISMS` maps each map `relation` to the mechanisms it may legally manifest as (e.g. `demand_risk → {substitution, cost_collapse, commoditization}`). Plus **`category_reach(session, category) → CategoryReach`**: the company slices a category touches (via `reach_links` + the stored `exposure_companies.doc`), the union of allowed mechanisms, and the per-ticker valid-revenue-line index — everything the pack renders and the orchestrator post-validates against. Pure read; empty when unmapped.
3. **Input pack — `checkpoints/impact_pack.py`** (`BRIEF_PACK_VERSION=1`). `build_brief_pack` assembles 4 sections (doc 08 §3): the latest *ok* card, a momentum summary, **only the matched map slices** (`category_reach`), and the mechanism taxonomy verbatim (`MECHANISM_TAXONOMY`). Pure/deterministic/as-of-correct/bounded (48k cap). Returns the `CategoryReach` so the orchestrator validates against the exact surface the model saw.
4. **Provider — `checkpoints/llm.py`.** Refactored to a generic `_complete(...)` and added **`complete_brief`** (tool `emit_brief`, `max_tokens=3072`) alongside `complete_card`; `_ollama`/`_anthropic` now take tool name/description/max_tokens. `anthropic` still the only SDK import (invariant 3 green). ollama now passes `num_predict`.
5. **Orchestrator — `checkpoints/impact.py`.** `run_brief(session, as_of, *, entity_id=None, week_start=None, limit=None)`: candidates = the gate's **passed** queue for the week (or a forced `entity_id`), skipping entities that already have a live draft/published brief (queue mode is idempotent) → build pack → deterministic `mock`/fallback brief → **budget ceiling → `pending`** (A-12) → `complete_brief` → `_validate` (schema) + **`_post_validate`** (every ticker exposure's `revenue_line` exists for that ticker; every mechanism legal for the touched relations) with **one retry then `failed`** → store `impact_briefs` version+1 as **`draft`** (DR-08.2). `week_as_of()` helper matches the gate's scoring instant.
6. **CLI — `seismo brief`.** `--entity-id N` forces one (bypasses the gate, always appends a version); `--week 2026-W28` briefs the whole passed queue; `--as-of`, `--limit`. Wired with `record_pipeline_run`.
7. **API — `api/app.py` + `api/models.py`.** `GET /briefs` (review inbox — latest version per entity, draft+published by default), `GET /briefs/{entity_id}` (detail, `?version=`), `POST /briefs/{brief_id}/decision?decision=publish|reject&reason=` (bearer-gated; only a `draft` is decidable, published/rejected are immutable → 409; reject stores `_reject_reason` in the JSONB). Models: `Brief`, `BriefListItem`, `BriefExposure`/`BriefObservable`/`BriefTransmissionStep`, `BriefDecisionResult`.
8. **Dashboard.** Nav gained **"Briefs"**. `app/brief/page.tsx` = review inbox (status chips, mechanisms, exposure count). `app/brief/[id]/page.tsx` = full brief render (summary + mechanism chips, exposures table with direction colours, transmission path, counter-mechanism, observables with system/manual tags, evidence refs) + `components/BriefActions.tsx` (client publish/reject-with-reason POST). `next build` green — **6 routes**. `lib/types.ts`/`api.ts` mirror the new models (still hand-kept).

### 20.2 Verified
- **Unit:** `tests/test_impact.py` (10) — contract accept/reject + summary truncation + tool-schema enum; pack deterministic/as-of/**map-scoped** (an unrelated company must NOT leak); post-validation rejects unknown revenue_line + illegal mechanism; mock end-to-end stores a valid versioned `draft`; budget→`pending`; queue-mode briefs only the passed set and skips existing. `tests/test_api.py` +1 (inbox/detail/publish→409). **`mypy src` clean, ruff clean, invariant-3 grep clean.**
- **Live end-to-end:** `uv run seismo brief --entity-id 2857` (inference-runtime, "Linear Attention Architectures") against **ollama qwen2.5:3b** → `drafted=1 failed=0`, stored `impact_briefs` id 18 v1 `status=draft`. Real content: mechanism `enablement`, a `sector_class:semiconductors` datacenter exposure (ambiguous/marginal), a **fair counter-mechanism** (AMD chiplet cost/perf advantages), a 2-step transmission path, 1 observable. Schema + post-validation both passed on the real model output — the guardrails work on live generations, not just mocks.

### 20.3 Gotchas / learnings (don't relearn)
- **Tests hitting a real model by accident.** `.env` sets `SEISMO_LLM_PROVIDER=ollama` and the Ollama app is often open, so any test that calls `run_brief`/`run_comprehend` without forcing `mock` will **hit the local model** (non-deterministic — one impact test flip-flopped pass/fail this way). `test_impact.py` has an **autouse fixture forcing `settings.llm_provider="mock"`**; do the same for any new end-to-end LLM test. (The pre-existing comprehension mock tests are quietly relying on ollama being lenient — fragile, but not ours to fix now.)
- **`clean_db` does NOT clear `exposure_companies`/`reach_links`** (the map is global, like the seed). So a test that uses a **real** category slug (e.g. `inference-runtime`) pulls in the **loaded map's real reach + companies** on top of any synthetic ones — which broke two impact tests until switched to a synthetic `ztest-category`/`ZTST` that never collides. Use synthetic map surfaces in tests, or add those two tables to `_CLEAR_TABLES` if a future test needs a clean map.
- **Post-validation only checks `revenue_line` for `kind='ticker'`** — a `sector_class` exposure may carry a `revenue_line` (the live qwen brief did) and that's allowed. Mechanism-legality only applies when the reach is non-empty (an unmapped forced entity has no surface to test against; the gate hard-excludes those anyway, A-6).
- **No migration for Stage 7** — `impact_briefs` has existed since 0001 (entity_id, version, as_of, brief JSONB, status default `draft`, model, cost_usd, reviewed_at). Reject reasons live inside the `brief` JSONB (`_reject_reason`), not a new column.
- **`impact.py` imports `significance.exposure`** — a one-way `checkpoints → significance` dependency (no cycle; significance never imports checkpoints). Fine, but keep it one-way.

### 20.4 The daily heartbeat now has a brief step
`scripts/daily.sh` does **not** yet run `seismo gate` / `seismo brief` — the heartbeat stops at `comprehend`. To close the loop once momentum is live: add `seismo gate --week $(current)` then `seismo brief --week $(current)` after `comprehend` (briefs are drafts, so this is safe to automate; humans still publish). Deferred because with everything `dormant` the gate passes nobody.

### 20.5 NEXT (pick one)
1. **Stage 8 — Memory & scoring (doc 09).** Forward-score published briefs against their observables; `brief_scores` table already exists (brief_id, scored_at, materialized, falsifier_tripped, notes). This is the calibration loop that eventually earns auto-publish (DR-08.2).
2. **H2 DeepSeek hindcast** — the Stage-7 DoD. Machinery is done; needs the heavy GH Archive `backfill-stars --repos deepseek-ai` → resolve → snapshot/score `--as-of 2024-05-31` → comprehend → gate → `brief --entity-id`, with `SEISMO_MODEL_HINDCAST` pinned (A-8). Assert cost_collapse + commoditization + NVDA/MSFT/GOOGL exposures + a real counter + dated observables. Hundreds of GB — run once during validation.
3. **Curate the exposure map 8 → 30 companies** with sourced (not placeholder) revenue figures from 10-K segment notes (doc 08 §5). This directly widens what the gate + briefs can reach; it's operator curation, not code.
4. **Wire gate+brief into `scripts/daily.sh`** (§20.4) once momentum is live.

---

## 21. SESSION LOG (2026-07-11, cont.) — Stage 8 Memory & Synthesis, SHIPPED

Built Stage 8 (doc 09) right after Stage 7, in the same session. The user asked whether the briefs were "good enough" / should get investor features (KPIs, scenarios); the answer chosen was **build the scoring loop first** — you validate the briefs before enriching them. So this stage is the calibration machinery.

### 21.1 What shipped (files)
1. **Migration 0005** — `changes_daily` (deterministic Changes view rows) + `calibration_snapshots` (momentum-review time series, PK `(day, metric)`). `brief_scores` already existed since 0001. Additive only.
2. **`memory/changes.py`** — `compute_changes(session, as_of, prev_day=None)`: deterministic, **templated** daily deltas (DR-09.1, **no LLM**) → `changes_daily`. Kinds: `new_entity` (first-evidence exactly 7d old = survived the gate, with card one-liner), `state_up`/`state_down` (momentum vs prev day, by heat ordering; `fading` is cold), `promotion`, `brief_drafted`/`brief_published`, and a Monday-only `gate_week` rollup. Re-runnable (deletes the day first).
3. **`memory/calibration.py`** — `run_momentum_review(session, as_of)`: **breakout survival** (share of ≥90d-old breakout calls still simmering+) and **fade false-alarm** (share of fade calls that re-accelerated within 60d) → upsert `calibration_snapshots`. Handles empty cohorts (value NULL + a note). Fully automated (doc 09 §3).
4. **`memory/scoring.py`** — the human ritual's *assembler* (DR-09.2). `assemble_score_packet(session, brief_id)` gathers the brief + observables + since-publication metric history and, per **A-7**, **auto-evaluates each `source='system'` observable**: compares the `system_metric`'s actual movement since publication vs `direction_if_thesis_holds` → `on_track | counter | flat | too_early | unmeasurable` (`manual` observables → `operator_judgment`). `record_score(...)` writes the operator's verdict to `brief_scores` (materialized/falsifier + verdict/counter-flag/which-observable packed into `notes` JSON — no schema change).
5. **CLI** — `seismo changes [--as-of]`, `seismo calibrate [--as-of]`. Added `changes` to `scripts/daily.sh` (cheap, $0, deterministic — safe to automate). Scoring stays UI-driven (it's a judgment ritual).
6. **API** — `GET /changes/{day}` (grouped, fixed display order, `latest` alias), `GET /calibration` (per-metric series + latest), `GET /briefs/{entity_id}/score-packet` (the assembled + auto-evaluated scoring screen), `POST /briefs/{brief_id}/score` (bearer-gated, records the verdict). Models in `api/models.py`.
7. **Dashboard** — nav gained **"Changes"**. `app/changes/[day]/page.tsx` = the Changes view (grouped deltas + a calibration strip + day switcher). `components/BriefScoring.tsx` = a client scoring panel on **published** briefs (renders the A-7 auto-eval + a materialized/falsifier/counter/verdict form → POST). `next build` green — **7 routes**.

### 21.2 Verified
- **Unit:** `test_memory.py` (9) — changes transitions/promotions/rerunnable/survival, breakout-survival ratio + empty-cohort, system-observable auto-eval (on_track vs counter vs too_early), `record_score` upsert + bad-value reject. `test_api.py` +1 (changes/calibration/score-packet/score round-trip). `mypy src` clean (48 files), ruff clean.
- **Live:** `seismo calibrate` → correctly `n=0` with the "need ≥90d" note (the instrument works; it just needs time). `seismo changes` → **231 new-survived · 487 promotions · 1 draft** written to `changes_daily` for 2026-07-11 (the 487 promotions are the §19.3 cold-start ladder artifact). The Changes view now has real content.

### 21.3 Gotchas / learnings (don't relearn)
- **`clean_db` must clear `changes_daily` + `calibration_snapshots`** — they're now in conftest `_CLEAR_TABLES`. Two tests failed first because a **live** `seismo calibrate`/`changes` smoke run had committed rows into the shared dev DB, and `/calibration` returns the *latest* snapshot across all days → the test's older row wasn't "latest". Any test asserting on these tables needs `clean_db`.
- **The calibration instruments read n=0 for ~90 days.** Breakout-survival needs breakout calls ≥90d old; fade-reaccel needs ≥60d forward history. Momentum only went live ~now, so these are structurally empty until the daily heartbeat accrues history — same "needs time, not code" situation as trajectory velocity. Don't mistake n=0 for a bug.
- **Changes `new_entity` fires once, on day-7 exactly** (first-evidence date == day−7). A back-run for an arbitrary past day only shows entities that hit day-7 *that* day — correct, but means a first-ever `changes` run won't retro-populate every past day; run it daily going forward.
- **Scoring auto-eval is advisory** (DR-09.2) — it never writes a score; `record_score` is always an explicit operator action. The `system_metric` on an observable must match an `entity_metrics_daily` metric name (`gh_stars`, `hf_downloads_30d`, …) for auto-eval to measure it; otherwise it's `unmeasurable`.
- **`memory/scoring.py` reads metrics for the brief's own entity.** A ticker exposure's observable ("NVDA datacenter revenue") is NOT auto-measurable in v1 (no financials feed) — those stay `manual`. System observables are about the *entity's* pipeline metrics (downloads/stars), which is what A-7 can actually watch.

### 21.4 The Changes view is deterministic — DR-09.1 upheld
No third LLM checkpoint was added. Every Changes row is a fixed-template sentence over computed diffs. If a "weekly narrative" model is ever wanted it becomes a *registered fourth checkpoint* with its own contract, not an exception (the two-checkpoint invariant holds: comprehend + brief).

### 21.5 NEXT (the brief-quality thread the user opened)
The user's original question — are briefs good enough, add KPIs/scenarios? — is now un-blocked because the scoring loop exists to validate any enrichment. Recommended order:
1. **Prove the quality ceiling:** regenerate a brief or two with `qwen2.5:7b-instruct` (or anthropic) — the entity-2857 brief was 3B-thin; the schema is likely fine, the model was the limit. Cheapest way to know what's actually missing.
2. **Enrich the brief schema (if step 1 says so):** add `scenarios` (bull/base/bear *exposure* branches tied to observables) + baselined observables (`baseline`/`threshold`, prefer `source=system`). Both JSONB — no migration. **Hold the line on no $ figures** until the map is curated (placeholder financials). These are the investor features, done philosophy-safely.
3. **H2 DeepSeek hindcast** (§20.5) — now that scoring exists, a hindcast brief can be forward-scored too.
4. **Curate the map 8→30** with real 10-K figures — unlocks honest quantification later.
5. **Quarterly calibration report** (doc 09 §4) — the one markdown artifact still unbuilt (brief-score distribution + momentum curves + map staleness). Small; do it once there's data to report.

---

## 22. SESSION LOG (2026-07-11, cont.) — brief-quality A/B (3B vs 7B) + counter-mechanism guard

Answered the standing "are the briefs good enough / add scenarios?" question **empirically** by regenerating 3 briefs (2857 inference-runtime, 6603 code-assistant, 6611 multimodal-model) with `qwen2.5:7b-instruct` and diffing against the 3B daily model.

### 22.1 Finding: the schema is good; the 3B model was the ceiling
- **Entity 2857 (Linear Attention):** 3B produced **one vague `sector_class` exposure**; the **7B produced five real ticker+revenue-line exposures with divergent directions** — NVDA **negative** (fewer GPUs per capability) while AMZN/GOOGL/MSFT cloud lines and AMD are **positive** (more inference workloads). That NVDA-down/cloud-up split is genuinely investor-grade and came from the *existing* schema. **Conclusion: do NOT add scenarios/KPIs — the gap was model capability, not schema.**
- The daily model stays `qwen2.5:3b-instruct` (8 GB M2); use the 7B for batch/quality regens (`SEISMO_OLLAMA_MODEL=qwen2.5:7b-instruct uv run seismo brief --entity-id N`). The 7B is ~4 min/brief on this box.

### 22.2 Fix shipped: counter_mechanism must be a real argument (idea-spec §7)
The A/B exposed a real defect: the **7B mis-filled `counter_mechanism` with a bare taxonomy keyword** (`"dependency_risk"`) on both briefs, instead of a fair argument — the exact "one-sided brief is marketing" failure idea-spec §7 warns about. (Ironically the 3B wrote a proper counter.) Fixed in `checkpoints/impact.py`:
- **Prompt:** `counter_mechanism` is now spelled out as "a REQUIRED one-to-three-sentence ARGUMENT … prose, NOT a mechanism name — never answer with a bare word like 'dependency_risk'."
- **Post-validation** (`_post_validate`): rejects a counter that is a bare mechanism keyword (`cm.lower().rstrip('.') in MECHANISMS`) or `< 4` words → triggers the existing one-retry, then `failed`. A brief without a real counter-mechanism is not publishable.
- **Proven:** regenerated 2857 v3 with 7B → counter is now *"The Jevons paradox suggests that cheaper inference could lead to an increase in overall model usage, potentially offsetting any direct revenue loss…"* — a genuine argument, 5 exposures kept.
- +1 test (`test_post_validation_rejects_keyword_counter_mechanism`); 3 test helpers updated to realistic counters; ruff/mypy clean.

### 22.3 Gotcha
- **Weak models will now `fail` more briefs** if they can't produce a real counter-mechanism — that's intended (the bar is genuine). The 3B daily model usually writes a sentence, so this mostly bites lazy keyword outputs. If daily failure rate climbs, the lever is a better daily model, not relaxing the guard.
- Entity 2857 now has **v1 (3B) + v2/v3 (7B)** briefs in the dev DB — the dashboard shows the latest (v3). Good demo content.

### 22.4 NEXT — the project is feature-complete; what's left is validation + ops + data
Per the "what's left" analysis: all 7 layers + both checkpoints + dashboard + calibration are built and the brief quality is validated. Remaining to call v1 *complete*:
1. **Stage 9 — Hindcast validation (doc 11):** DeepSeek (positive) + Reflection-70B (must be suppressed) + one mid-size, via a case-YAML/assertion harness (`seismo hindcast` is a stub) + historical loaders. The biggest remaining code chunk; the scientific proof it works. Heavy `backfill-stars` (hundreds of GB).
2. **Stage 10 — Operations (doc 12):** deploy to the Hetzner VPS (Caddy, systemd timers `Persistent=true`, pg_dump backups + restore drill, healthchecks.io, runbook) + a 14-day soak. `deploy/` has scaffolding.
3. **Data:** curate the map 8→30 with real 10-K figures; build HF + PyPI download tracking (4th/5th evidence types, A-5); then just *run it daily* ~1–2 weeks so momentum stops being all-dormant and the calibration instruments start reading > n=0.
Feature work remaining ≈ 3–5 focused sessions; project *maturity* is gated on weeks-to-a-quarter of daily running (momentum accrual, 14-day soak, quarterly rituals).

---

## 23. SESSION LOG (2026-07-11, cont.) — Stage 9 Hindcast harness, SHIPPED (machinery + cases; real backfill deferred)

Built the Stage 9 validation harness (doc 11) — the case-YAML format, the assertion evaluators, the `seismo hindcast` runner, and the two v1 cases (DeepSeek positive, Reflection-70B negative). Per the session brief, the harness **machinery is built and proven on synthetic/small data**; the heavy GH Archive `backfill-stars` (hundreds of GB) and the real-model H2 3/3 run are **flagged and deferred** — see §23.5.

### 23.1 What shipped (files)
1. **Migration 0006 + `HindcastRun` model** — `hindcast_runs` (case_name, window_from/to, brief_as_of, passed, total, failed, results JSONB per-assertion, report markdown, created_at). Additive; re-running a case appends a row (the regression ledger, DR-11.2). Added to conftest `_CLEAR_TABLES`.
2. **`hindcast/case.py`** — pydantic case format + YAML loader. A `Case` = window + `Seeds` (github/arxiv/hf_orgs/wayback/pypi) + optional `BriefTarget` (as_of + entity ref) + `Assertion` list. **Assertions are STRUCTURED, not the doc's prose DSL** (`single_entity(...) via rules [...]`): parsing free-form expressions would be fragile, so `expect` became typed fields. `ASSERTION_TYPES` is closed (unknown type → load-time error). `CASES_DIR = <repo>/hindcast/cases`.
3. **`hindcast/assertions.py`** — five evaluators, each reading the pipeline's *structured* output (never prose, DR-11.2): `identity` (all refs resolve to ONE canonical entity at as_of), `momentum` (reached a state-set by as_of ≤ bound), `gate` (pass / suppressed — suppressed also passes when the entity was *never a candidate*, i.e. an attention-only spike that never hit accelerating/breakout), `brief` (schema facts: mechanisms ⊇/∩, ticker exposures, counter nonempty, observables+horizon), `brief_absent`. `_resolve_ref("registry:native_id")` → canonical entity via `entities.attrs->'anchors'` + `canonical_entity_id` (as-of merge purity, A-2); github native_ids are lowercased so it tries both casings.
4. **`hindcast/runner.py`** — `run_hindcast(session, case, *, reload, loader, comprehend, step_days, store)`. Drives the **real orchestrators** (resolve → snapshot/score daily → gate weekly → comprehend+brief at the pin), evaluates assertions, renders the report, writes the `hindcast_runs` row. **No separate backtest engine** (DR-11.1). `default_loader` is the only network path (GH Archive backfill for github seeds; other sources recorded as loader-gaps) and only runs behind `--reload`; tests inject a synthetic `loader`.
5. **`hindcast/report.py`** — markdown trace: verdict + per-assertion table + loader notes + the **per-day momentum-state trace** of the case entity (the PMG-demo artifact, doc 11 §4).
6. **CLI — `seismo hindcast --case <name> [--reload] [--step-days] [--report-path]`** replaces the stub. Loads `hindcast/cases/<case>.yaml`, runs, prints per-assertion PASS/FAIL, exits non-zero if any red.
7. **Cases — `hindcast/cases/deepseek.yaml`** (positive, brief pinned 2024-05-31: H1a identity, H1b momentum, H2 brief facts) + **`reflection70b.yaml`** (negative, brief-free: reached simmering, gate suppressed, brief_absent). Both carry an in-file NOTE that only the GitHub loader exists today.

### 23.2 Key design decision — resolve ONCE is as-of correct
The runner runs `resolve(now=window_end)` a single time before the daily replay, **not** per-day, and it's still as-of pure: entity birth = earliest evidence (`_find_or_create` sets `created_at=event.occurred_at`) and category `effective_at = _latest_evidence(ent)` which is **birth-anchored** (refs+created_at, not future events), so a one-shot resolve over the full window yields the same graph an incremental one would, and every downstream read (snapshot/score/gate/brief) already filters by `as_of`. Verified by reading `resolve._assign_categories`/`_latest_evidence` — do NOT "fix" this into a per-day resolve loop; it would be ~200× slower for zero correctness gain.

### 23.3 Verified
- **`tests/test_hindcast.py` — 22 passed.** Case format (load the 2 shipped cases + unknown-type/bad-window rejection + roundtrip); all 5 evaluators (identity single/distinct/unresolved, momentum reached/not/as-of-bound, gate never-candidate/suppressed-row/passed-when-suppression-expected/pass, brief_absent present/absent, brief all-facts/missing-mechanism/missing-ticker); **two end-to-end `run_hindcast` replays through the real orchestrators** — a green negative-shape run (synthetic loader → suppressed + brief-free, `hindcast_runs` row written) and the **forced-brief step** (mock provider → a real `draft` brief, brief assertion green).
- **`ruff check src tests` clean, `mypy src` clean (52 files), invariant-3 grep clean** (hindcast/ imports the checkpoint *orchestrators* run_comprehend/run_brief, never an LLM SDK — the SDK stays in `checkpoints/llm.py`).
- **CLI** `seismo hindcast --help` renders; `test_invariants`, `test_gate`+`test_memory` (18) still green with the conftest change.

### 23.4 Gotchas / learnings (don't relearn)
- **The full `pytest -q` suite now TIMES OUT (>10 min) — environmental, NOT a regression.** `clean_db` DELETEs the whole dev DB per test, and `momentum_states` has grown to **733k rows** (236k `entity_metrics_daily`) from the Stage-8 live `score` runs, so each `clean_db` test costs ~9–11s. My new evaluator/format tests therefore use the **fast rollback-only `db_session`** fixture (they query by specific entity id / a unique synthetic anchor, so a globally-empty DB is unnecessary); only the 2 runner tests need `clean_db` (the replay must see only the synthetic seed). If the suite must run green in CI, the lever is trimming the dev DB (or a dedicated test DB), not the tests. Run affected files individually meanwhile.
- **Structured assertions, not the prose DSL in doc 11 §2.** The doc's `expect: single_entity([...]) via rules [R1,R2]` is illustrative; the shipped format uses typed fields (`refs`, `states`, `mechanisms_superset`, …). Same facts, no fragile parser, still "schema-level, never string-matching prose."
- **Only the GitHub backfill loader exists.** `collectors/backfill_gharchive.py` (repo_star/repo_discovered from the GH Archive firehose) is the sole historical loader. **arXiv (OAI-PMH), Hugging Face (createdAt), Wayback (pricing), PyPI (BigQuery) are documented gaps** — the runner records them as warnings, never silently skips. So today the DeepSeek `arxiv:`/`hf:` refs in H1a won't resolve and Reflection-70B's `hf:` entity won't resolve until those loaders ship. The cases are authored to spec and ready; they can't be *graded on real data* yet.
- **`gate` decision=suppressed passes when there is no gate row at all** (entity never became an accelerating/breakout candidate). This is the correct semantics for the flop: attention is excluded from the velocity composite (idea-spec principle 3), so Reflection-70B tops out at `simmering`, never enters the gate, and is thereby "not briefed."

### 23.5 NEXT — run the real cases (needs the heavy backfill + the missing loaders + a pinned model)
The machinery is done and proven; grading the cases on **real history** is the remaining work, and it's flagged because it's expensive:
1. **DeepSeek H1b/H2 (the Stage-7/9 DoD):** `seismo hindcast --case deepseek --reload` runs `backfill-stars` over `deepseek-ai` for Jan–Jul 2024 — **HEAVY (hundreds of GB of GH Archive firehose)**; scope tightly, run once. For **H1a and H2** you also need the **arXiv + HF loaders** (build them next; they're cheap — Algolia/OAI are natively historical) and, for H2 at **3/3**, `SEISMO_MODEL_HINDCAST` pinned (A-8) with the 7B/anthropic model, not the 3B daily. Run H2 3× and require 3/3 on mechanisms/exposures.
2. **Reflection-70B:** needs the **HN (Algolia-historical) + HF** loaders to inject the Sept-2024 attention spike; then `seismo hindcast --case reflection70b` should be green (suppressed + brief-free) with no `--reload` firehose (HN/HF are light).
3. **Mid-size positive case** (doc 11 §3, still unselected): a dev tool that climbed the full ladder over ~2 quarters with a clean GH Archive trail + a PyPI/npm presence (tests R3 + distribution promotion) + a pricing-page appearance (tests commercialization). Author `hindcast/cases/<pick>.yaml` once its loaders exist.
4. Wire the hindcast assertions into the quarterly calibration report (doc 11 §5) as the permanent regression floor.

---

## 24. SESSION LOG (2026-07-11, cont.) — dashboard info-modals + HN/arXiv hindcast loaders

Two ships after Stage 9, plus a scoping correction on the loaders. **This is the context-clear handoff: read §22.4, §23, and this section to resume.**

### 24.1 What shipped (commits)
- **`287922f` — dashboard per-page info (ⓘ) modals.** A reusable `InfoButton` + modal (`dashboard/components/InfoModal.tsx`) driven by a central content registry (`dashboard/lib/help.ts`), wired into all 7 pages (Radar, Entity, Changes, Gate, Brief inbox, Brief detail, Queue). Each modal explains every value on the page in plain terms + a "How to read it" analysis block (e.g. "read the counter-mechanism before the thesis — if it's weak, distrust the brief"). Esc/backdrop/button close; `next build` green. Pure UI, no backend touch.
- **`3c230aa` — HN + arXiv hindcast loaders.** Two of the three validation loaders, both cheap. New `src/seismo/hindcast/loaders.py` (`load_hn`, `load_arxiv`); `ArxivCollector.fetch_ids` added; wired into `runner.default_loader`; loaded rows stamped `origin='backfill'`. +5 tests, ruff/mypy clean.

### 24.2 The loader scoping correction (important — supersedes §23.5's loader list)
Reading the collectors settled which "loaders" actually need building:
- **Hacker News needs NO new loader.** `collectors/hn.py::discover(window)` already queries the Algolia API by `created_at_i` range — its own docstring calls it "the hindcast workhorse." `load_hn` just points that existing collector at the case window. This is the attention signal Reflection-70B rides on.
- **arXiv needed only a targeted fetch, not a full loader.** `discover` pages from the *newest* submissions and can't reach an arbitrary past window — but a case pins exact paper ids, so `ArxivCollector.fetch_ids(id_list)` jumps straight to them. `load_arxiv` uses it for the case's seed papers (DeepSeek's `2405.04434` for the H1a identity check).
- **Hugging Face is the only genuine remaining loader** — no HF collector exists at all yet.

**Loader status (as of §24 — SUPERSEDED by §25.2, HF now ✅):** GitHub ✅ (GH Archive, HEAVY) · Hacker News ✅ (already historical, wired) · arXiv ✅ (targeted seed fetch) · **Hugging Face ❌ (the one real remaining build)** · Wayback ❌ · PyPI ❌ (last two deferred — not needed for the two v1 cases).

### 24.3 NEXT — build the Hugging Face collector (the last loader before real validation)
Agreed plan (deployment deferred to the very end):
1. **HF collector — `collectors/hf.py` (DO THIS NEXT).** The only piece blocking validation, and "two birds": historical `createdAt` (identity + the `usable_artifact` maturity promotion) **and** live `downloads` tracking (a currently-missing evidence type — the `hf_downloads_30d` metric spec already exists in `trajectory/metrics.py`, waiting for this collector). Build `discover`/fetch-by-org via the HF API (`huggingface.co/api/models?author=<org>` → `createdAt`, `downloads`), a `track` for downloads, register it in `collectors/registry.py`, and add `load_hf(session, orgs, window)` to `hindcast/loaders.py`. Mirror the existing collector pattern (MockTransport tests in `test_collectors.py`). This unblocks DeepSeek's `hf:` identity ref AND the entire Reflection-70B entity (`hf:mattshumer/Reflection-Llama-3.1-70B`).
2. **Run the real validation** (the payoff — see §23.5): DeepSeek (`--reload` = HEAVY GH firehose, run once; H2 3/3 with `SEISMO_MODEL_HINDCAST` pinned to 7B/anthropic) + Reflection-70B (light — HN+HF only, no firehose). Then pick/author the mid-size third case.
3. **Exposure map data** — curate 8 → 30 companies with real 10-K figures.
4. **PyPI download tracking** (5th evidence type) — after HF.
5. **Run daily for weeks-to-a-quarter** so momentum stops being all-dormant and calibration reads > n=0. Time, not code.
6. **Deployment (Stage 10)** — LAST, by user's instruction.

### 24.4 Conceptual notes the user now shares (so the framing is consistent next session)
- **DeepSeek + Reflection-70B are TESTS, not training data.** The system does not learn from them — its logic (deterministic momentum math + a general-purpose LLM's world knowledge) is fixed. The cases are regression/acceptance tests: one real "should-catch" (DeepSeek's mid-2024 cost-collapse foreshock → NVDA-down/cloud-up thesis) and one real "must-ignore" (Reflection-70B's Sept-2024 hype that collapsed in days). They prove the machine is wired right; generalization comes from the design, not the examples. This is deliberately NOT an ML-trained architecture — the whole point is explainability/auditability (rules you can inspect + an LLM that cites evidence).

### 24.5 Standing gotchas (still true — don't relearn)
- **Full `pytest -q` TIMES OUT (>10 min) — environmental, not a regression.** `momentum_states` has ~733k rows from Stage-8 live runs, so every `clean_db` DELETE costs ~9–11s. New evaluator/format/loader tests use the fast rollback-only `db_session` fixture and pass in <0.5s; only the 2 runner tests need `clean_db`. Verify affected files individually; the fix for green CI is a dedicated/trimmed test DB, not the tests.
- **`db_session` tests share the live dev DB** (rollback-only), so any seed data must use collision-proof synthetic ids (e.g. arXiv `0000.00001`, category `ztest-category`/`ZTST`) — the real `2405.04434` already lives in the DB and would make a dupe-insert test read the pre-existing row.
- **`.env` sets `SEISMO_LLM_PROVIDER=ollama`** → `test_config.py::test_defaults_are_dev_safe` fails (pre-existing, documented); and any end-to-end LLM test must force `mock` or it hits the local model.
- **`explain.txt`** at repo root is the user's scratch file — not committed, leave it.

---

## 25. SESSION LOG (2026-07-11, cont.) — Hugging Face collector, SHIPPED (the last v1 loader)

Built the HF collector per §24.3 item 1 — the final piece blocking real hindcast validation. Usage
is now a live evidence type (the 4th, A-5) and the DeepSeek/Reflection-70B `hf:` identity refs
resolve.

### 25.1 What shipped (files)
1. **`collectors/hf.py` — `HuggingFaceCollector` (source `hf`).** Three methods over the public Hub
   API (`huggingface.co/api/models`), optional `SEISMO_HF_TOKEN` (already in config):
   - **`discover(window)`** — models *trending now* (`sort=trendingScore`) that were *born in the
     window* (createdAt) with real traction + a relevant modality. **Key design correction (found
     via live smoke, not mocks):** sorting by `createdAt` is self-defeating — the newest models top
     that sort but have ~0 usage, so a traction gate rejects them all (returned **0**). The Hub has
     no server-side date filter and `MAX_PAGES` only covers ~hours of the firehose. The inverse
     (trending desc, filter by birth date) surfaces the right thing: `discover(30d)` live returns
     ~289 real models (`zai-org/glm-5.2-fp8` 2.5M dl, `nvidia/kimi-k2.7-code`, `baidu/unlimited-ocr`),
     not spam clones. Relevance = traction (`downloads≥1000` OR `likes≥10`) **AND** modality
     (relevant `pipeline_tag` OR keyword in id/tags) — a bare `text-generation` clone with 0 usage
     is noise (an early too-loose filter yielded **652 junk/day**).
   - **`fetch_by_author(authors)`** — the hindcast seed path (`?author=<org>&full=true&limit=1000`);
     keeps each model's real `createdAt`. Live-proven: `deepseek-ai` → 101 models incl.
     `DeepSeek-V2` (born 2024-05); `mattshumer` → `reflection-*` models. No pagination gap for real
     orgs (limit honored past 100, no Link header).
   - **`track(targets, window)`** — `model_snapshot` with `downloads` (the `hf_downloads_30d` level;
     **never diff it** — rolling level, doc 06 §1). Per-target 401/404/451 + `TransportError`
     isolation exactly like the GitHub tracker. Live: `deepseek-ai/DeepSeek-V2` → downloads 7000.
   - Discovery uid `model_discovered:{id}` (id lowercased), snapshot uid via `snapshot_uid`.
2. **Wiring (no new code needed downstream — it was all waiting):** `anchors.primary_anchor`/`references`
   already handle `hf` (`payload['id']`, `arxiv:` tags); `ladder` already promotes `usable_artifact`
   on any `source=='hf'` event; `metrics.METRIC_SPECS` already declares `hf_downloads_30d`
   (`model_snapshot`/`downloads`, level, usage). Registered in `collectors/registry.py` (FACTORIES
   + `all` group, **not** `fast` — HF discovery is broader, own cadence); added `hf` to
   `targets._SOURCE_REGISTRY` so `seismo track --source hf` polls hf-anchored entities.
3. **`hindcast/loaders.py::load_hf(session, orgs, window)`** — org-scoped fetch, drops models born
   after `window.until` (no future leak), stamps `origin='backfill'`. Wired into
   `runner.default_loader` (HF removed from the loader-gap list). arXiv/HF/HN loaders now all live;
   only Wayback + PyPI remain gaps (deferred — not needed for the two v1 cases).
4. **Tests — `test_collectors.py` +5** (discover window/traction/modality gates across a Link cursor,
   fetch_by_author preserves createdAt, track snapshots downloads + skips 401/404, track skips
   transient). 17 collector tests green. `ruff`/`mypy src` (54 files)/invariant-3/`doctor` all green.

### 25.2 Loader status now: GitHub ✅ · Hacker News ✅ · arXiv ✅ · **Hugging Face ✅** · Wayback ❌ · PyPI ❌ (deferred)

### 25.3 NEXT — run the real validation (machinery is now complete)
All three loaders the v1 cases need exist. The payoff work (§23.5 / §24.3.2). **UPDATE: Reflection-70B
is now GREEN 3/3 — see §26.** Remaining:
1. ~~**Reflection-70B**~~ **✅ DONE (§26)** — green 3/3 on real Sept-2024 history.
2. **DeepSeek (HEAVY):** `seismo hindcast --case deepseek --reload` — arXiv `2405.04434` + HF
   `deepseek-ai` are cheap, but GH Archive `backfill-stars` for H1b momentum is hundreds of GB; scope
   tightly, run once. For **H2 3/3** pin `SEISMO_MODEL_HINDCAST` to the 7B/anthropic model (A-8), not
   the 3B daily. Assert cost_collapse + commoditization + NVDA-down/cloud-up exposures + real counter.
3. Then: pick the mid-size 3rd case · curate map 8→30 · PyPI tracking (5th type) · run daily for
   weeks · deploy (Stage 10, LAST).

### 25.4 Gotchas / learnings (don't relearn)
- **HF `discover` must sort by traction, not recency.** `sort=createdAt` + a traction filter = always
  0 (newest models have no usage yet, and `MAX_PAGES` can't scan deep enough to reach aged-but-now-
  popular ones). Use `sort=trendingScore` desc, filter by `createdAt`-in-window. This was invisible
  to mocks — only the live smoke test caught it (the recurring "test collectors against real APIs"
  lesson, §14).
- **HF `downloads` is a 30-day rolling LEVEL, not a counter** — same trap as always; `metrics.py`
  already treats it as `kind='level'` (no diff, no forward-fill). Don't "fix" it into a counter.
- **`fetch_by_author` limit=1000 covers real orgs** (deepseek-ai = 101, no Link header). A hypothetical
  >1000-model org would truncate; add cursor paging then, not now (YAGNI).
- **HF is in the `all` group but not `fast`** — daily `scripts/daily.sh` (`--source fast`) still only
  runs github/hn/arxiv, so HF discovery does NOT yet run daily. To turn it on, add a step or switch
  the group; deferred because HF discovery volume/cadence wants its own timer.

---

## 26. SESSION LOG (2026-07-11, cont.) — Reflection-70B hindcast GREEN 3/3 (first real validation)

Ran the negative "must-ignore" case on **real Sept-2024 history** end-to-end (collect→resolve→
snapshot→score→gate→brief). **`seismo hindcast --case reflection70b --reload` = PASS 3/3.** First hard
evidence the whole machine works on real data: the infamous Reflection-70B hype flop is correctly
ignored — never accelerating/breakout, never a gate candidate, **never briefed.**

### 26.1 Two operational findings (both matter for every future hindcast)
1. **A hindcast MUST run against an isolated, clean DB — not the live dev DB.** Running the CLI against
   the dev DB hit `IntegrityError: entity_merges_pkey (loser_id=15665 already exists)`. Root cause:
   `entity_merges` has a **single-column global `loser_id` PK**, but the runner calls
   `resolve(now=window_end=2024-09-30)`; `canonical_entity_id` at that past as-of **can't see the dev
   DB's 2026-dated merges**, so resolve legitimately tries to merge an entity that is *already* a
   committed (future-dated) loser → PK collision. The transaction rolled back (dev DB untouched). Fix
   = replay in a dedicated DB holding only the case's backfill (this is what the runner tests' `clean_db`
   already does; the CLI doesn't). **Operational recipe (used this run):**
   ```bash
   dropdb --if-exists seismograph_hindcast && createdb -O seismo seismograph_hindcast
   psql -d seismograph_hindcast -c 'CREATE EXTENSION IF NOT EXISTS pg_trgm;'
   export SEISMO_DATABASE_URL="postgresql+psycopg://seismo:seismo@localhost:5432/seismograph_hindcast"
   uv run alembic upgrade head && uv run seismo load-map
   uv run seismo hindcast --case reflection70b --reload
   ```
   Vocab (categories/themes) is read from `seed/*.yaml` on disk, so a clean DB needs no seeding; the
   exposure map does (`load-map`) if a case's gate could pass anything. **A `seismo hindcast` that
   auto-provisions/uses an isolated DB is a worthwhile future ergonomic** — for now, do it by hand.
2. **H3a reframed to the TRUE invariant (with the user's sign-off).** The old H3a asserted the flop
   "reached simmering". It can't in v1, and shouldn't: attention (HN) is **excluded from the velocity
   composite by design** (idea-spec principle 3 — hype must not move momentum), and the only real path
   to `simmering` for an HF model is **download velocity, which is NOT historically reconstructable**
   (the HF API returns only the *current* 30-day download level, no daily history). So the model
   correctly stays `dormant`. H3a now asserts the real guarantee: **`mode: never`, `states:
   [accelerating, breakout]`** — a pure attention spike must NEVER climb to a briefable state. That is
   exactly what H3b (gate suppression) enforces downstream; H3a proves it at the momentum layer.

### 26.2 What shipped (files)
- **`hindcast/assertions.py::_eval_momentum`** gained a `mode` param: `reached` (default, existing) vs
  **`never`** (entity must NOT have reached any listed state; requires real momentum history so it
  can't pass vacuously). No new assertion *type* (schema unchanged — `mode` rides `extra="allow"`).
- **`hindcast/cases/reflection70b.yaml`** — H3a → `mode: never` over `[accelerating, breakout]`; NOTE
  rewritten to explain the download-curve gap + the attention-exclusion rationale.
- **`hindcast/loaders.py::load_hf`** — now tolerant of a seed given as a **full model id** (`org/model`)
  or a bare **author** (`org`): it fetches by author (part before `/`), de-duped. (The case seeded
  `mattshumer/Reflection-Llama-3.1-70B`; author is `mattshumer`.)
- **Tests — `test_hindcast.py` +3** (`mode:never` passes below ceiling / fails when breached / fails
  without history). 29 hindcast + 17 collector tests green; ruff/mypy(54)/invariant-3 clean.

### 26.3 The result (isolated `seismograph_hindcast` DB, Sept 2024)
Loaded 193 HN stories + 18 `mattshumer` HF models. Entity 15 = `mattshumer/reflection-llama-3.1-70b`,
resolved from the HF createdAt (2024-09-05). Its only attached signal is that one `model_discovered`
event (→ `usable_artifact` promotion, breadth=1) — **zero HN stories attached** (the real Sept-2024
HN threads linked to Twitter/news, not the HF page; and attention couldn't lift momentum anyway).
Result per assertion: **H3a** never reached accelerating/breakout (`dormant` throughout) · **H3b** never
a gate candidate · **H3c** no brief in any status. Report: scratchpad `reflection70b_report.md`.

### 26.4 NEXT
1. **DeepSeek hindcast (the positive, HEAVY):** same isolated-DB recipe, `--case deepseek --reload`.
   arXiv `2405.04434` + HF `deepseek-ai` load cheap; **H1b momentum needs GH Archive `backfill-stars`
   over `deepseek-ai` for 2024 — hundreds of GB, scope tight, run once.** For **H2 3/3** pin
   `SEISMO_MODEL_HINDCAST` to 7B/anthropic (A-8), run 3×, require cost_collapse + commoditization +
   NVDA-down/cloud-up exposures + a real counter-mechanism. **First** sanity-check `deepseek.yaml`'s
   refs against reality like we did here (the DeepSeek-V2 arXiv id, the `deepseek-ai` HF/GH anchors).
2. Then: mid-size 3rd case · curate map 8→30 · PyPI (5th type) · run daily for weeks · deploy (LAST).

---

## 27. SESSION LOG (2026-07-11, cont.) — DeepSeek case ref-validation + 4 identity fixes (H1a proven cheaply)

Before committing to the HEAVY GH Archive `backfill-stars`, validated the DeepSeek case's refs against
reality (arXiv + HF + README — no firehose). **H1a identity now PASSES**: the three refs
(`github:deepseek-ai/deepseek-v2` + `arxiv:2405.04434` + `hf:deepseek-ai/DeepSeek-V2`) collapse to
ONE entity at the 2024-05-31 pin. Found and fixed **four** real issues along the way — none were
visible without running it on real data.

### 27.1 The identity chain (how the three unify)
The **arXiv paper is the hub**: the HF model card carries an `arxiv:2405.04434` tag (R2 → model↔paper),
and the repo's **README** cites the same id (R1 → repo↔paper). The arXiv *comment* is EMPTY (verified
live — the paper does NOT cite the repo from its side), so the README R1 link is load-bearing.

### 27.2 Four fixes (all shipped this session)
1. **Ref bug — `hf:deepseek-ai` → `hf:deepseek-ai/DeepSeek-V2`.** The HF loader anchors individual
   *models* (`hf:deepseek-ai/deepseek-v2`); there is **no bare-org `hf:deepseek-ai` entity**, so the
   old ref never resolved. Fixed in `hindcast/cases/deepseek.yaml`.
2. **`anchors.references('github')` ignored the README body (latent LIVE bug too).** It read
   `payload['readme']`, but a `repo_readme` enrichment event (§16) stores the body under
   `payload['text']` — so **README arXiv citations never created R1 links**, in hindcast *or* the live
   pipeline (every `enrich-readmes` run was silently not linking repos to their papers). Now reads
   `payload.get('readme') or payload.get('text')`. +1 test (`test_identity_pure.py`).
3. **GH Archive backfill = identity island → added `load_github_readmes`.** The backfill payload is
   bare (`{"repo": …, "backfilled": True}` — no description/homepage/README), so a seeded repo has
   nothing to link on. New `hindcast/loaders.py::load_github_readmes(session, github_seeds, window)`
   fetches the seed `owner/repo` READMEs (skips org handles) via `GitHubCollector.readmes`; wired into
   `runner.default_loader` right after the star backfill. Cheap (one call/repo).
4. **Enrichment events are `now()`-dated → invisible at a past as-of.** `GitHubCollector.readmes`
   stamps `occurred_at=now()` (README text isn't an as-of metric, §16), so the R1 merge it justified
   was dated 2026 and `canonical_entity_id(…, 2024-05-31)` (which only follows merges
   `justified_at <= as_of`) couldn't see it — H1a failed with the repo still separate. `load_github_readmes`
   now **backdates the README event to `window.since`** so the identity link is visible throughout the
   case. +2 tests (`test_hindcast.py`: org-filter + backdate; no-repo-seed no-op).

### 27.3 Verified
- **Cheap live H1a proof** (isolated `seismograph_hindcast` DB, no firehose): `load_arxiv` +
  `load_hf(['deepseek-ai'])` + `load_github_readmes(['deepseek-ai/DeepSeek-V2'])` → `resolve` → all
  three refs → **entity 12** at as_of 2024-05-31. **PASS.**
- 60 tests green (`test_hindcast` + `test_identity_pure` + `test_collectors`); ruff/mypy(54)/invariant-3 clean.

### 27.4 NEXT — DeepSeek H1b + H2 (the HEAVY part, refs now proven)
Identity is validated; the remaining two assertions need the expensive inputs:
1. **H1b (momentum → accelerating by 2024-05-31):** needs `backfill-stars` over `deepseek-ai` for
   Jan–May 2024 (GH Archive firehose, **hundreds of GB** — scope tight, run once). Run the full case in
   the isolated DB: `seismo hindcast --case deepseek --reload` (the `default_loader` now does arXiv +
   HF + README + the star firehose). Watch that the merged entity's `gh_stars` velocity clears the
   cohort percentile — a single-repo cohort may need care (percentile over a thin cohort).
2. **H2 (brief facts):** pin `SEISMO_MODEL_HINDCAST` to 7B/anthropic (A-8, NOT the 3B daily), run 3×,
   require cost_collapse + commoditization + NVDA (+ MSFT/GOOGL) exposures + a real counter + dated
   observables. The brief entity is `github:deepseek-ai/deepseek-v2` (the unified entity).
3. Then: mid-size 3rd case · curate map 8→30 · PyPI (5th type) · run daily · deploy (LAST).

---

## 28. SESSION LOG (2026-07-11, cont.) — exposure map curated 8 → 30 companies

Expanded the exposure map from the minimal 8-company slice to the full **30-company roster** (doc 13
§11 / HANDOFF §11). This directly widens what the gate can reach and what every impact brief can name.

### 28.1 What shipped
- **22 new `exposure_map/*.yaml` files** (the roster minus the existing 8): **TSM ASML ARM ANET · AAPL
  ORCL · CRM ADBE NOW TEAM WDAY INTU · MDB DDOG NET CFLT · PLTR SHOP U DOCN PATH CRWD.** Each follows
  the existing schema exactly: revenue lines with approximate segment shares (summing ≤1.0), a
  `source` note on every line, and a `threat_surface` mapping the line to frontier categories with a
  `relation` (demand_risk / substitution_* / enablement / dependency_risk) + a `core` flag on the
  defining exposure. `moat_notes` + `sensitivity_notes` per company.
- **Loader verified:** `seismo load-map --strict` → **30 companies, 76 revenue lines, 133 reach_links,
  22 of 29 categories covered** (was 8 / 25 / 47 / 18). Idempotent + authoritative rebuild intact.
- **Tests:** `test_exposure.py` de-hardcoded from `== 8` to `== len(files)` (future-proof); 9 green.
  ruff/mypy clean.

### 28.2 The 7 remaining map-gaps (deliberate, not missing work)
No public company maps defensibly to: **eval-tooling, memory-framework, prompt-tooling, sdk-client,
structured-output, synthetic-data, training-framework.** These are developer-tooling niches without a
clear listed-company *revenue* exposure — fabricating a link would be worse than an honest gap. The
gate already handles unmapped categories via A-6 (R=0 hard-exclusion → surfaced as map-gaps), so an
emerging entity in one of these still shows up; it just won't manufacture a false exposure.

### 28.3 ⚠️ Figures are still FIRST-PASS approximations
Every revenue-share number is an educated estimate flagged in each line's `source` — the *engineering*
(schema, categories, relations, directions) is exact; the *figures* need verification against 10-K/20-F
segment notes in the quarterly refresh (doc 08 §5). No `cik` on the new files (omitted rather than
risk a wrong one → wrong filing); add verified CIKs during the 10-K pass.

### 28.4 To apply it to a running DB
`exposure_map/` on disk is the source of truth, but the DB's `exposure_companies`/`reach_links` tables
only update when `seismo load-map` runs. The dev DB still holds the OLD 8-company map until then. Run
`uv run seismo load-map` (idempotent, authoritative — drops+rebuilds per company) to apply the 30.

### 28.5 NEXT (unchanged priorities)
DeepSeek H1b/H2 hindcast (heavy, §27.4) · verify map figures vs 10-Ks + add CIKs · PyPI (5th evidence
type) · run daily for weeks · deploy (Stage 10, LAST).

---

## 29. SESSION LOG (2026-07-11, cont.) — daily.sh now runs the FULL cycle (one command)

`scripts/daily.sh` previously stopped at comprehend+changes (§20.4). It now runs the **complete**
heartbeat in order: `collect → track → resolve → snapshot → score → comprehend → gate → brief →
changes`. Added a `WEEK="$(date +%G-W%V)"` (current ISO week) and two isolated steps — `gate --week
$WEEK` (deterministic, always runs) and `brief --week $WEEK` (LLM; skipped when `SKIP_COMPREHEND=1`
or new `SKIP_BRIEF=1`, since it needs Ollama). Verified live: the exact invocations run clean on the
(dormant) dev DB — `date +%G-W%V` → gate week-start 2026-07-06, gate handled its 1 pending candidate,
brief drafted 0 ($0). `bash -n` clean, script executable. **`COMMANDS.md` §1 rewritten** to lead with
the single command `./scripts/daily.sh` (variants: `TRACK_LIMIT=`, `SKIP_BRIEF=1`, `SKIP_COMPREHEND=1`)
and refreshed to current facts (model `qwen2.5:3b-instruct`, migrations 0001–0006, 30-company map,
full-suite-times-out test note, HF add-on, all 7 dashboard pages + API aliases `/gate/current`
`/changes/latest`). This **supersedes §20.4** ("not yet in daily.sh") and the §1 caveat in the old
COMMANDS.md. So the manual daily routine is now literally one command until deployment (Stage 10).
