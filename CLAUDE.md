# Seismograph (OpportunityRadar)

Daily monitoring & impact analysis of the technology frontier. Pipeline:
collectors (github/hn/arxiv/hf) → raw_events → entity resolution → daily metrics →
momentum scoring → significance gate (≤5 briefs/week, no LLM) → AI impact briefs →
human publish/reject in the dashboard.

## Navigate via the knowledge graph FIRST

`graphify-out/graph.json` is a prebuilt knowledge graph of this repo (2.6k nodes:
all code symbols + doc concepts, community-labeled). Before exploring the codebase,
answer structural questions from it (`/graphify query "<question>"`) and only read
the source files it points to. Rebuild after big changes: `/graphify . --update`
(code re-extraction is free, no LLM).

## Layout

- `src/seismo/` — Python package; CLI is `uv run seismo <cmd>` (typer app in `cli.py`)
- `src/seismo/api/` — FastAPI (`seismo serve`, port 8000, **no hot-reload — restart after edits**)
- `dashboard/` — Next.js UI (`cd dashboard && npm run dev`, port 3000)
- `alembic/` — migrations (head = 0006). **NEVER `alembic downgrade` a DB with data**
- `exposure_map/*.yaml` — per-company AI-exposure maps; reload with `uv run seismo load-map`
- `seed/` — hand-curated seed universe, categories, themes
- `idea_documentation/` — the 15 seismograph design docs (the "doc NN" citations)

## Doc index (don't re-derive; read these)

- `COMMANDS.md` — every runnable command (the authoritative cheat-sheet)
- `HANDOFF.md` — current state + architecture; `DECISIONS.md` — why choices were made
- `DATA_EXPLAINED.md` — the six-layer data architecture; `DAILY.md` — daily ritual
- `GRAPH_PLAN.md` / `WIKIDATA_ENRICHMENT_PLAN.md` — graph-layer work in progress

## Key commands

```bash
./scripts/daily.sh                      # the whole 9-step daily pipeline (idempotent)
uv run seismo doctor                    # health check: DB + schema + LLM provider
uv run seismo serve                     # API on :8000 (dashboard needs it)
uv run ruff check && uv run mypy src    # lint + types (tests untyped by design)
bash scripts/check_llm_import.sh        # invariant: no LLM SDK outside checkpoints/
```

## Hard constraints

- **Tests share the dev/prod Postgres (`seismograph`).** Never run pytest concurrently
  with pipeline commands. Full suite times out (>10 min) — run by file:
  `uv run pytest tests/test_collectors.py -q` etc. `clean_db` tests take 1–2 min each.
- Requires local Postgres + the Ollama macOS app (`qwen2.5:3b-instruct`) + `.env`
  with `SEISMO_DATABASE_URL`, `SEISMO_GITHUB_TOKEN`, `SEISMO_LLM_PROVIDER=ollama`.
- All LLM calls live in `src/seismo/checkpoints/` only (invariant 3, CI-enforced).
- Pipeline commands are idempotent; momentum needs ~2 weeks of daily `track` history
  before anything leaves "dormant" — that's expected, not a bug.
