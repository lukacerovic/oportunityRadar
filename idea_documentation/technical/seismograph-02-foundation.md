# Seismograph — 02 Foundation

*Covers: repository structure, tooling, PostgreSQL setup, the core schema, the as-of discipline, and the CLI skeleton. Everything else stands on this.*

> **Amended by doc 13.** Migration **0001** (below) is unchanged; **0002** (authored at the start of Stage 2) adds the A-2 as-of graph tables (`entity_links.evidence_occurred_at`, `entity_merges`, `entity_category_history`, `entity_themes.effective_at`) and the A-4 tracking-lifecycle columns (`entities.tracking_tier`, `tier_reviewed_at`). The **as-of discipline (§5) extends to the entity/merge/category graph, not just events** — see A-2. New config keys (A-8, A-5, A-4, A-12, product name) are listed in doc 13 Part C. New CLI verbs: `seed-load`, `load-map`, `retier` (docs 14, 08, 13). A minimal search index (FTS + `pg_trgm` on entity names; expression GIN on text payload keys) backs `GET /search` (A-10). **A-13:** the LLM SDK lives behind a pluggable provider (`mock`/`ollama`/`anthropic`) in `checkpoints/llm.py`; the §1 invariant-3 grep broadens to `import (anthropic|ollama)` outside `checkpoints/`, and `ollama` + `httpx` are the only extra deps (both already in the dependency list).

---

## DR-02.1 — Database: PostgreSQL 16 over SQLite
**Ops Minimalist:** single user, daily batch, one writer — SQLite would genuinely work and removes a service. **Data Engineer:** three things break SQLite later: concurrent dashboard reads during pipeline writes, window-function-heavy cohort percentiles over growing history, and `pg_trgm` similarity for entity resolution. **Adversarial Reviewer:** migrating mid-project is worse than either choice. **Verdict:** PostgreSQL 16 from day one; it costs one `apt install` on a box we already run. *Revisit trigger: none — this is settled.*

## DR-02.2 — Packaging: `uv` over pip/poetry
Fast, lockfile-native, single tool for venv + deps + Python version pinning. No dissent. Pin exact dependency versions in `uv.lock` at Stage 0.

## DR-02.3 — No Docker
Single VPS, single Python app, Postgres from apt, systemd as supervisor. Docker adds an abstraction layer with zero payoff at this scale. **Adversarial Reviewer:** what about dev/prod parity? **Verdict:** parity comes from `uv.lock` + Ubuntu 24.04 both sides + Alembic migrations. Revisit if the system ever needs a second host.

## DR-02.4 — ORM: SQLAlchemy 2.0 Core+ORM, raw SQL where it earns it
Models and CRUD through SQLAlchemy; the trajectory/cohort queries (doc 06) are hand-written SQL via `text()` because window-function SQL is clearer than any ORM rendering of it. Alembic owns the schema; no `create_all` in app code.

---

## 1. Repository layout

```
seismograph/
├── pyproject.toml            # uv-managed
├── uv.lock
├── alembic/                  # migrations
├── exposure_map/             # YAML company files (doc 08) — versioned data, not code
│   ├── NVDA.yaml
│   └── ...
├── src/seismo/
│   ├── cli.py                # typer app: collect, resolve, snapshot, score, comprehend, gate, brief, hindcast, doctor
│   ├── config.py             # pydantic-settings
│   ├── db.py                 # engine, session, as_of helpers
│   ├── models.py             # SQLAlchemy models (single file until it hurts)
│   ├── collectors/           # doc 03 — one module per source, no reasoning
│   ├── identity/             # doc 04 — link rules, merge ops
│   ├── trajectory/           # doc 06 — snapshots, cohorts, momentum
│   ├── significance/         # doc 07 — gate
│   ├── checkpoints/          # doc 05 + 08 — the ONLY modules importing the anthropic SDK
│   │   ├── comprehension.py
│   │   ├── impact.py
│   │   └── contracts.py      # Pydantic schemas for both checkpoints
│   ├── memory/               # doc 09 — changes, scoring
│   ├── api/                  # doc 10 — FastAPI app
│   └── hindcast/             # doc 11 — cases, assertions, backfill loaders
├── dashboard/                # Next.js app (doc 10)
└── tests/
```

**Enforcement of invariant 3 (CI):**
```bash
grep -rn "import anthropic" src/seismo --include="*.py" | grep -v "src/seismo/checkpoints/" && exit 1 || exit 0
```

## 2. Tooling setup (step by step)

1. `uv init seismograph && cd seismograph && uv python pin 3.12`
2. `uv add fastapi uvicorn sqlalchemy alembic psycopg[binary] pydantic pydantic-settings typer httpx anthropic ollama tenacity pyyaml` *(`ollama` is the local-provider client, A-13; both `anthropic` and `ollama` are imported only inside `checkpoints/`)*
3. `uv add --dev pytest pytest-asyncio ruff mypy`
4. `alembic init alembic`; point `sqlalchemy.url` at env var.
5. Add `[project.scripts] seismo = "seismo.cli:app"` → `uv run seismo doctor` works.
6. ruff + mypy strict-ish config in `pyproject.toml`; pre-commit optional.

## 3. PostgreSQL setup

Local (dev) and VPS (prod) identical:
```bash
sudo apt install postgresql-16
sudo -u postgres psql -c "CREATE ROLE seismo LOGIN PASSWORD '...';"
sudo -u postgres psql -c "CREATE DATABASE seismograph OWNER seismo;"
sudo -u postgres psql -d seismograph -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
```
Connection string via `SEISMO_DATABASE_URL`. Tune later, not now; defaults are fine for years at this volume.

## 4. Core schema (migration 0001)

DDL sketch — Alembic migration is the source of truth. Types abbreviated.

```sql
-- Layer 1: immutable observations
CREATE TABLE raw_events (
  id BIGSERIAL PRIMARY KEY,
  source TEXT NOT NULL,                 -- 'github' | 'arxiv' | 'hn' | 'hf' | 'pypi' | ...
  source_event_uid TEXT NOT NULL,       -- source-native id; dedupe key
  event_type TEXT NOT NULL,             -- 'repo_snapshot' | 'paper_published' | 'story' | ...
  occurred_at TIMESTAMPTZ NOT NULL,     -- source time
  ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  origin TEXT NOT NULL DEFAULT 'live',  -- 'live' | 'backfill'
  payload JSONB NOT NULL,               -- raw, uninterpreted
  UNIQUE (source, source_event_uid)
);
CREATE INDEX ON raw_events (occurred_at);
CREATE INDEX ON raw_events USING gin (payload jsonb_path_ops);

-- Layer 2: durable things
CREATE TABLE entities (
  id BIGSERIAL PRIMARY KEY,
  entity_type TEXT NOT NULL,            -- 'project' | 'model' | 'paper' | 'org' | 'person'
  canonical_name TEXT NOT NULL,
  category TEXT,                        -- controlled vocabulary, doc 04 §5
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  merged_into BIGINT REFERENCES entities(id),   -- reversible merges
  attrs JSONB NOT NULL DEFAULT '{}'
);

CREATE TABLE entity_links (               -- event↔entity and entity↔entity evidence
  id BIGSERIAL PRIMARY KEY,
  entity_id BIGINT NOT NULL REFERENCES entities(id),
  raw_event_id BIGINT REFERENCES raw_events(id),
  linked_entity_id BIGINT REFERENCES entities(id),
  rule TEXT NOT NULL,                   -- 'R1_url_exact' ... 'R6_name_trgm'
  confidence REAL NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE entity_merge_queue (
  id BIGSERIAL PRIMARY KEY,
  entity_a BIGINT NOT NULL REFERENCES entities(id),
  entity_b BIGINT NOT NULL REFERENCES entities(id),
  confidence REAL NOT NULL,
  evidence JSONB NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',   -- 'pending' | 'merged' | 'rejected'
  decided_at TIMESTAMPTZ
);

CREATE TABLE themes (id BIGSERIAL PRIMARY KEY, name TEXT UNIQUE NOT NULL, description TEXT);
CREATE TABLE entity_themes (entity_id BIGINT, theme_id BIGINT, source TEXT, PRIMARY KEY (entity_id, theme_id));

-- Layers 3–6 outputs
CREATE TABLE comprehension_cards (
  id BIGSERIAL PRIMARY KEY, entity_id BIGINT NOT NULL, version INT NOT NULL,
  as_of TIMESTAMPTZ NOT NULL, card JSONB NOT NULL,   -- validated ComprehensionCard
  model TEXT NOT NULL, cost_usd NUMERIC(8,4), created_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE (entity_id, version)
);

CREATE TABLE entity_metrics_daily (
  entity_id BIGINT NOT NULL, metric TEXT NOT NULL,  -- 'gh_stars' | 'hf_downloads_30d' | ...
  day DATE NOT NULL, value NUMERIC NOT NULL,
  PRIMARY KEY (entity_id, metric, day)
);

CREATE TABLE maturity_promotions (
  entity_id BIGINT NOT NULL, stage TEXT NOT NULL,   -- doc 06 §4 ladder
  promoted_at TIMESTAMPTZ NOT NULL, evidence_event BIGINT REFERENCES raw_events(id),
  PRIMARY KEY (entity_id, stage)
);

CREATE TABLE momentum_states (
  entity_id BIGINT NOT NULL, day DATE NOT NULL,
  state TEXT NOT NULL,                              -- dormant|simmering|accelerating|breakout|fading
  score NUMERIC, inputs JSONB, PRIMARY KEY (entity_id, day)
);

CREATE TABLE gate_decisions (
  id BIGSERIAL PRIMARY KEY, entity_id BIGINT NOT NULL, week DATE NOT NULL,
  decision TEXT NOT NULL,                           -- 'passed' | 'suppressed'
  score NUMERIC NOT NULL, components JSONB NOT NULL, created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE impact_briefs (
  id BIGSERIAL PRIMARY KEY, entity_id BIGINT NOT NULL, version INT NOT NULL,
  as_of TIMESTAMPTZ NOT NULL, brief JSONB NOT NULL, -- validated ImpactBrief
  status TEXT NOT NULL DEFAULT 'draft',             -- draft|published|retired
  model TEXT, cost_usd NUMERIC(8,4), reviewed_at TIMESTAMPTZ, created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE brief_scores (
  brief_id BIGINT PRIMARY KEY REFERENCES impact_briefs(id),
  scored_at TIMESTAMPTZ, materialized TEXT,         -- 'yes'|'partial'|'no'|'too_early'
  falsifier_tripped BOOLEAN, notes TEXT
);

-- Exposure map (loaded from YAML, doc 08)
CREATE TABLE exposure_companies (ticker TEXT PRIMARY KEY, name TEXT, sector TEXT, doc JSONB NOT NULL, loaded_at TIMESTAMPTZ);
CREATE TABLE reach_links (category TEXT NOT NULL, ticker TEXT NOT NULL, revenue_line TEXT NOT NULL, relation TEXT NOT NULL, PRIMARY KEY (category, ticker, revenue_line, relation));

-- Bookkeeping
CREATE TABLE collector_runs (id BIGSERIAL PRIMARY KEY, source TEXT, started_at TIMESTAMPTZ, finished_at TIMESTAMPTZ, ok BOOLEAN, events_new INT, error TEXT);
CREATE TABLE pipeline_runs  (id BIGSERIAL PRIMARY KEY, stage TEXT, as_of TIMESTAMPTZ, started_at TIMESTAMPTZ, finished_at TIMESTAMPTZ, ok BOOLEAN, notes TEXT);
```

## 5. The as-of discipline (the most important 30 lines in the codebase)

Every read that feeds analysis goes through one helper:

```python
# db.py
def events_asof(session, as_of: datetime, **filters):
    q = select(RawEvent).where(RawEvent.occurred_at <= as_of)
    ...
```

Rules:
1. `as_of` is an explicit parameter on every trajectory/significance/checkpoint function. Live runs pass `now()`; hindcasts pass historical dates. Same code path — that is the whole point.
2. Nothing may filter on `ingested_at` for analytical purposes; it exists for ops only.
3. Backfilled events (`origin='backfill'`) are first-class citizens: their `occurred_at` is the historical truth.
4. Unit test in Stage 0: insert an event dated tomorrow → `events_asof(today)` must not see it.

## 6. Configuration

`pydantic-settings` class with env prefix `SEISMO_`: `DATABASE_URL`, `ANTHROPIC_API_KEY`, `GITHUB_TOKEN`, `REDDIT_CLIENT_ID/SECRET`, `HF_TOKEN` (optional), budgets (`BRIEFS_PER_WEEK=5`), thresholds (doc 06/07 defaults). Server: `/etc/seismograph/env` loaded by systemd `EnvironmentFile` (doc 12). Never in git.

## 7. CLI skeleton

```
seismo collect [--source github] [--window 1d]
seismo resolve                     # link rules + queue population
seismo snapshot                    # entity_metrics_daily
seismo score [--as-of 2026-07-10]  # trajectory + momentum states
seismo comprehend                  # checkpoint 1, trigger policy applied
seismo gate --week 2026-W28
seismo brief --entity-id 123       # checkpoint 2, writes draft
seismo hindcast --case deepseek
seismo doctor                      # health: collectors, queue depth, spend, backups age
```
Each subcommand is idempotent for its (stage, as_of) and records a `pipeline_runs` row. The daily systemd timer just runs them in order (doc 12 §3).

## 8. Testing baseline

- Unit: link rules, momentum state machine, as-of visibility, YAML loader validation.
- Contract: Pydantic schemas for both checkpoints round-trip sample payloads.
- Golden: one tiny frozen fixture day of raw events → deterministic snapshot/score output committed as expected JSON.
- Hindcast assertions (doc 11) run under pytest markers, excluded from the fast suite.
