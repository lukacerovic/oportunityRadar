# Seismograph — Build Handoff

*Single entry point for any new/compacted session. Read this first. `idea_documentation/technical/seismograph-13-corrections-and-decisions.md` is AUTHORITATIVE on any conflict with other docs. All design lives in `idea_documentation/`; all build state is in git.*

**Last updated: Stage 5 shipped + first real-data run.** Stages 0–5 done (Foundation, Observation, Identity, Trajectory, Comprehension, Dashboard). Migrations 0001–0003. FastAPI API (`seismo serve`) + Next.js dashboard (`dashboard/`, dark Meridian palette) both run and render live data. **Now running on real data:** `SEISMO_GITHUB_TOKEN` set; **LLM provider = `ollama` (model `llama3.2:latest`)**; the **180-day sweep ran** → dev DB has **~11,056 entities** (was 1,366), **41 have real ollama cards**, 1,067 repo_snapshots, 6 queue pairs. Everything still `dormant` (momentum needs ~a week of daily `track`). **IMMEDIATE next task (user-requested): enrich comprehension packs with repo READMEs so cards are richer — see §16.** Then Stage 6 Significance (blocked on the A-1 exposure-map slice).
**To resume:** "Read HANDOFF.md and continue the Seismograph build." **The single most important next action is §16 (README enrichment).**

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
| 6 — Significance (needs exposure-map slice first, A-1) | ⬜ | — |
| 7 — Impact | ⬜ | — |
| 8 — Memory & scoring | ⬜ | — |
| 9 — Hindcast completion | ⬜ | — |
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
  api/               app.py models.py  ← Stage 5 FastAPI (read+curation; the only door to the graph)
dashboard/           Next.js 14 app (App Router, Tailwind, Meridian palette) ← Stage 5 UI; node_modules git-ignored
  identity/          normalize.py anchors.py vocab.py resolve.py seed.py  ← Stage 2/1.5
  trajectory/        metrics.py cohorts.py velocity.py ladder.py states.py score.py  ← Stage 3
  significance/ memory/ hindcast/   empty (their stages)
alembic/versions/0001_core_schema.py    schema source of truth
alembic/versions/0002_asof_entity_graph.py   as-of graph + tracking_tier (A-2/A-4)
alembic/versions/0003_card_status.py         comprehension_cards.status + pack_version (A-12)
seed/categories.yaml themes.yaml seed_entities.yaml   vocab + day-1 universe
tests/               test_asof/config/invariants/collectors/graph_purity/trajectory/comprehension/targets/api + conftest (db_session, clean_db)
deploy/systemd/      seismo-collect-fast.{service,timer} + seismo-track.{service,timer} + README.md
scripts/check_llm_import.sh   invariant-3 grep
seed/ exposure_map/  empty (.gitkeep) — filled in cold-start / Stage 7
.github/workflows/ci.yml      ruff+format+mypy+invariant+migrate+doctor+pytest
```

**Testing pattern:** `conftest.py` provides `db_session` — a real Postgres transaction that is always **rolled back**, so tests exercise real SQL (ON CONFLICT, pg_trgm, window fns) without persisting. Unit tests default to LLM provider `mock` ($0). `mypy src` only (tests untyped by design).

---

## 7. Environment (this machine)

- **Postgres 17.9** on `localhost:5432`. OS superuser `lukacerovic` (local trust auth). App role **`seismo`**/pw `seismo`, db **`seismograph`**, `pg_trgm` installed.
- **`.env`** (git-ignored): `SEISMO_DATABASE_URL=…`, **`SEISMO_LLM_PROVIDER=ollama`**, **`SEISMO_OLLAMA_MODEL=llama3.2:latest`** (only model pulled; config default is `qwen2.5:7b-instruct` — pull it for better cards), **`SEISMO_GITHUB_TOKEN` set** (classic PAT, public scope). CI/tests still default to `mock` ($0) via conftest. **Ollama runs via the macOS app** (`ollama serve`, PID auto-started, `:11434`) — keep the app open for `comprehend`.
- **Dev DB data state (post-sweep):** ~11,056 entities (8,998 github-anchored), 41 ollama cards, 1,067 repo_snapshots, 6 queue pairs. All entities `dormant` (no star time-series yet). This is committed data in the shared dev DB — count-asserting tests must use the `clean_db` fixture.
- **Python 3.12** via uv 0.8.x. **Network works from Bash** (used it to test collectors live).
- **Git repo, committing to `main`, no remote.** Solo linear build. Scratchpad for temp files: `/private/tmp/claude-501/-Users-lukacerovic-Desktop-OportunityRadar/<session>/scratchpad`.
- Convention: end commit messages with `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

## 8. Run / verify

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

## 15. NEXT — enrich cards (§16), let momentum accrue, then Stage 6

**Done this session (✅):** Stage 5 Dashboard (API + Next.js UI). Plus the **first real-data run**: added `SEISMO_GITHUB_TOKEN`; switched provider to **ollama/llama3.2**; ran the **180-day `sweep`** (1,366 → 11,056 entities); ran the **heartbeat** (`track` → 1,062 repo_snapshots, after fixing a transient-error abort); **generated 41 ollama cards** (the original + top-40 repos by stars, forced via `--entity`); shipped the **radar cold-start ordering** (`29d1fed`) and **localhost CORS** (`f201e96`) fixes. The dashboard now shows a real browsable frontier.

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

## 16. IMMEDIATE TASK — enrich comprehension packs with repo READMEs

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
