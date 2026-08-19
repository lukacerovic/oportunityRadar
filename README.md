# Seismograph

Daily monitoring and impact analysis over the places where technology is *built* —
GitHub, arXiv, Hugging Face, PyPI, Hacker News, OpenRouter, Wikidata. It resolves raw events into
durable entities, tracks their momentum through time, and for the few that cross a significance bar
produces evidence-linked exposure analyses.

**It explains exposure; it never predicts prices.** Analyst, not trader.
**Every claim traces back to a raw event.**

---

## Start here

| If you want to… | Read |
|---|---|
| **Understand what we're building and why** | **[PRODUCT.md](PRODUCT.md)** ← start here |
| **Understand how the system works** | **[ARCHITECTURE.md](ARCHITECTURE.md)** |
| Know what's live right now | [STATE.md](STATE.md) |
| Run a specific command | [COMMANDS.md](COMMANDS.md) |
| Understand what the data means | [DATA_EXPLAINED.md](DATA_EXPLAINED.md) |
| Operate the daily loop | [DAILY.md](DAILY.md) |
| Resume a compacted session | [HANDOFF.md](HANDOFF.md) |

### Design docs

`idea_documentation/files/seismograph-00-idea-spec.md` is the original spec.
`idea_documentation/technical/` holds the layer docs (01–15).

**`technical/seismograph-13-corrections-and-decisions.md` is AUTHORITATIVE** on any conflict with
the other layer docs. Reading order: `00 → 01 → 13 → 14 → 02…12`.

### Research and planning

| Doc | What it covers |
|---|---|
| [COMPETITIVE_LANDSCAPE.md](COMPETITIVE_LANDSCAPE.md) | Who else builds this (nobody does the full combination) |
| [DATA_SOURCE_OPTIONS.md](DATA_SOURCE_OPTIONS.md) | Verified free sources to fill the two missing evidence types |
| [AGENT_GUARDRAIL_WAVE.md](AGENT_GUARDRAIL_WAVE.md) | A worked example of reading the graph for a real trend |
| [DECISIONS.md](DECISIONS.md) | Standing decisions and why |
| [GRAPH_PLAN.md](GRAPH_PLAN.md) · [WIKIDATA_ENRICHMENT_PLAN.md](WIKIDATA_ENRICHMENT_PLAN.md) | Graph roadmap |
| [TAXONOMY_PLAN.md](TAXONOMY_PLAN.md) | Emergent taxonomy — embeddings, clusters, and growing the vocabulary from data |
| [SOURCE_EXPANSION.md](SOURCE_EXPANSION.md) | Where the wave layer's data should come from — candidates + probe |
| [LAST30DAYS_RUNBOOK.md](LAST30DAYS_RUNBOOK.md) | External demand-side research tool — how to run it, per-source limits, setup links |
| [WAVES_HANDOFF.md](WAVES_HANDOFF.md) | **Wave Radar — how to run it, what to watch for, what's next** |
| [WAVE_PLAN.md](WAVE_PLAN.md) | Wave Radar — the detection design |
| [LEAD_TIME_PLAN.md](LEAD_TIME_PLAN.md) | Lead time, early observers, and the product argument |
| [TESTING_PLAN.md](TESTING_PLAN.md) | Test strategy |

---

## Global invariants (enforced forever)

1. Raw events are immutable; every event carries `occurred_at` (source time) and `ingested_at` (our time).
2. Every downstream computation takes an `as_of` and may only read events with `occurred_at <= as_of`.
3. LLM calls exist only in `src/seismo/checkpoints/`. CI greps for the SDK import elsewhere.
4. Collectors never reason; scorers never fetch; checkpoints never decide what gets attention.
5. Every merge, gate decision, and brief is logged with its inputs — including the rejected ones.

## Quickstart (dev)

```bash
uv sync                       # create venv, install deps (Python 3.12)
cp .env.example .env          # then edit if your Postgres differs
uv run alembic upgrade head   # apply all migrations (head = 0012)
uv run seismo doctor          # should report all green
uv run pytest                 # full suite, mock LLM provider, $0
```

Run the app:

```bash
uv run seismo serve                    # API on :8000
cd dashboard && npm run dev            # dashboard on :3000
./scripts/daily.sh                     # the full daily pipeline
```

⚠️ **Never run the test suite and the pipeline against the same database at the same time.**
They fight over locks on `entities` / `raw_events` and produce FK-violation errors that look like
real bugs. Serialize them.

## Stack

Python 3.12 (uv) · PostgreSQL 16+ · SQLAlchemy 2.0 + Alembic · Pydantic v2 · Typer CLI ·
FastAPI · Next.js 14 dashboard.

LLM checkpoints are pluggable — `mock` (deterministic, $0) / local `ollama` ($0) / `anthropic` (prod).
Dev and CI cost nothing.
