# Seismograph — Build Handoff

*Entry point for any new/compacted session. Read this first, then `idea_documentation/technical/seismograph-13-corrections-and-decisions.md` (authoritative on any conflict). All design lives in `idea_documentation/`; all build state is in git history.*

Last updated after **Stage 1** (commit `24e4bef`).

---

## What this project is

Daily monitoring + impact analysis over where technology is *built* (GitHub, arXiv, HF, PyPI, HN…). Tracks emerging entities through time; for the ones that cross a significance bar, produces evidence-linked exposure analyses. Solo build, personal infra, Python + Postgres. Full spec: `idea_documentation/files/seismograph-00-idea-spec.md`.

## Reading order (for design)

`00 idea-spec → 01 build-plan → 13 corrections-and-decisions (AUTHORITATIVE) → 14 cold-start → 02 foundation → 03 observation → 04 identity → 05 comprehension → 06 trajectory → 07 significance → 08 impact → 09 memory → 10 dashboard → 11 validation → 12 operations.`

Docs 13 and 14 were added in review; 13 fixes bugs/contradictions in 00–12 and closes all open decisions. Every layer doc has an "Amended by doc 13" banner listing which `A-n` amendments touch it.

---

## Progress

| Stage | Status | Commit |
|---|---|---|
| 0 — Foundation | ✅ done | `6946b15` |
| 1 — Observation | ✅ done | `24e4bef` |
| **1.5 — Cold-start (doc 14)** | ⬜ **NEXT** | — |
| 2 — Identity (doc 04 + migration 0002) | ⬜ | — |
| 3 — Trajectory | ⬜ | — |
| 4 — Comprehension | ⬜ | — |
| 5 — Dashboard v0 | ⬜ | — |
| 6 — Significance (needs exposure-map slice first, A-1) | ⬜ | — |
| 7 — Impact | ⬜ | — |
| 8 — Memory & scoring | ⬜ | — |
| 9 — Hindcast completion | ⬜ | — |
| 10 — Operations hardening | ⬜ | — |

### Stage 0 delivered
uv project (Py 3.12), `src/seismo/` layout, `seismo` CLI (typer), Postgres core schema via Alembic **migration 0001** (`alembic/versions/0001_core_schema.py` = doc 02 §4, all 17 tables), SQLAlchemy models (`models.py`), `as_of` visibility helper (`db.events_asof`) + purity test, config (`config.py`), pipeline_runs/collector_runs bookkeeping, ruff+mypy+pytest+invariant-3 grep + GitHub Actions CI. Exit criteria met: `seismo doctor` green on empty DB; future events invisible at `as_of=today`.

### Stage 1 delivered
Collector framework (`collectors/base.py`, `runner.py`) — `ON CONFLICT … RETURNING` dedupe, `collector_runs` health rows, per-source failure isolation. Wave 1 collectors: `github.py`, `hn.py`, `arxiv.py`. GH Archive backfill (`backfill_gharchive.py`, `origin='backfill'`). CLI `collect` wired; `registry.py` groups. systemd `collect-fast` timer in `deploy/`. Idempotency live-proven (hn 193→0, arxiv 293→0). ~486 real events currently in the dev DB.

---

## Environment (this machine)

- **Postgres:** v17.9 running on `localhost:5432`. Superuser is OS user `lukacerovic` (trust auth locally). App role **`seismo`** / password `seismo`, database **`seismograph`**, `pg_trgm` installed.
- **`.env`** (git-ignored) sets `SEISMO_DATABASE_URL=postgresql+psycopg://seismo:seismo@localhost:5432/seismograph` and `SEISMO_LLM_PROVIDER=mock`.
- **Python 3.12** via uv (uv 0.8.x). Network access works from Bash (used it to test collectors live).
- Repo is a **git repo, committing to `master`** (no remote). Solo linear build.

## Run / verify commands

```bash
uv sync                                   # deps
uv run alembic upgrade head               # apply migrations
uv run seismo doctor                      # health table (should be all green)
uv run pytest -q                          # fast suite, mock LLM, $0  (12 passing)
uv run ruff check && uv run ruff format --check && uv run mypy src
bash scripts/check_llm_import.sh          # invariant 3
uv run seismo collect --source fast --window 1d   # live collect (github needs a token)
```

## Gotchas / lessons (don't relearn these)

- **GitHub needs `SEISMO_GITHUB_TOKEN`** — Search API is 403-rate-limited unauthenticated. Failure is isolated (recorded `ok=false`), not fatal.
- **arXiv query encoding:** join category terms with real spaces (`" OR "`), NOT literal `+OR+` — httpx re-encodes `+`→`%2B` and silently returns 0 results. (Fixed; noted here so it isn't reintroduced.)
- **Insert counts:** use `RETURNING` + `len(fetchall())`, not `result.rowcount` (returns -1 for multi-row inserts with psycopg3).
- **Run collectors against real APIs**, not only mocks — both Stage-1 bugs above were invisible to mocked tests.
- **LLM provider is pluggable** (`mock`/`ollama`/`anthropic`); dev/CI default `mock` = $0. No Anthropic key needed until Stage 4 / H2. `anthropic` and `ollama` imports must stay inside `src/seismo/checkpoints/` (CI greps this).

## Invariants (enforced forever — see README)

1. Raw events immutable; carry `occurred_at` + `ingested_at`. 2. Every analytical read goes through `as_of` (`occurred_at <= as_of`), never `ingested_at`. 3. LLM SDKs only in `checkpoints/`. 4. Collectors never reason; scorers never fetch; checkpoints never rank. 5. Every merge/gate/brief logged with inputs.

---

## NEXT: Stage 1.5 — Cold-start (doc 14)

Build in this order (doc 14 §§3–8):
1. `seed/seed_entities.yaml` (~150–300 entities, every category covered) + `seismo seed-load` (idempotent; emits `origin='seed'` anchor events).
2. 180-day historical discovery sweep (reuse Wave-1 collectors in backfill mode + GH Archive loader).
3. Cohort warm-up: provisional states capped at `simmering` until cohort ≥ `COHORT_MIN_SIZE` (8); gate excludes provisional (this hook lands with Stage 3/6).
4. `resolve --cold-start` precision-first queue mode (lands with Stage 2 identity).
5. Minimal 8-company exposure slice (`NVDA MSFT GOOGL AMZN META AMD AVGO SNOW`) — unblocks Stage 6 gate (A-1). Can defer until just before Stage 6.

**Then Stage 2 — Identity** starts with **migration 0002** (doc 13 A-2 + A-4): `entity_links.evidence_occurred_at`, `entity_merges` (as-of merge resolution), `entity_category_history`, `entity_themes.effective_at`, `entities.tracking_tier`/`tier_reviewed_at`. Plus `canonical_entity_id(entity_id, as_of)` + the graph-purity test (the critical correctness item).

Note: seed-load and the sweep create entities, but full entity resolution is Stage 2. Practically, cold-start seeding and identity interleave — a reasonable path is to do migration 0002 + minimal resolution first, then seed-load, then the sweep. Decide at start of the next session based on doc 14 §2's sequence.
