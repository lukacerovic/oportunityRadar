# Seismograph

Daily monitoring and impact analysis over the places where technology is *built* —
GitHub, arXiv, Hugging Face, PyPI, Hacker News, and more. It tracks emerging entities
through time and, for the ones that cross a significance bar, produces explained,
evidence-linked exposure analyses.

Design and build documentation lives in [`idea_documentation/`](idea_documentation/).
**Read `technical/seismograph-13-corrections-and-decisions.md` first** — it is authoritative
on any conflict with the layer docs.

## Global invariants (enforced forever)

1. Raw events are immutable; every event carries `occurred_at` (source time) and `ingested_at` (our time).
2. Every downstream computation takes an `as_of` and may only read events with `occurred_at <= as_of`.
3. LLM calls exist only in `src/seismo/checkpoints/`. CI greps for the SDK import elsewhere.
4. Collectors never reason; scorers never fetch; checkpoints never decide what gets attention.
5. Every merge, gate decision, and brief is logged with its inputs.

## Quickstart (dev)

```bash
uv sync                       # create venv, install deps (Python 3.12)
cp .env.example .env          # then edit if your Postgres differs
uv run alembic upgrade head   # apply migration 0001 (core schema)
uv run seismo doctor          # should report all green on an empty database
uv run pytest                 # fast suite (mock LLM provider, no credits)
```

Stack: Python 3.12 · PostgreSQL 16+ · SQLAlchemy 2.0 + Alembic · Pydantic v2 · Typer CLI.
LLM checkpoints are pluggable (`mock` / local `ollama` / `anthropic`) — dev and CI cost $0.
