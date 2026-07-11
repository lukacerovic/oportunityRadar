# Seismograph — Command Cheat-Sheet

Practical "how do I run this" reference. For architecture/state see `HANDOFF.md`.

- **Project root:** `~/Desktop/OportunityRadar` — run everything from here unless noted.
- **You do NOT need `source .venv/bin/activate`** — `uv run <cmd>` handles the environment.
- **Database:** Postgres `seismograph` (role `seismo`), local. **LLM:** local Ollama app.
- Every pipeline command is **idempotent** — safe to re-run; it only adds genuinely new data.

---

## 0. One-time setup (already done on this machine)

```bash
uv sync                              # install Python deps
uv run alembic upgrade head          # create/upgrade the DB schema (migrations 0001–0003)
uv run seismo doctor                 # health check — expect "All green"
cd dashboard && npm install && cd .. # install dashboard deps (Node 22)
```

Requirements that must exist: Postgres running, the **Ollama macOS app** open, and `.env`
(git-ignored) with `SEISMO_DATABASE_URL`, `SEISMO_GITHUB_TOKEN`, `SEISMO_LLM_PROVIDER=ollama`,
`SEISMO_OLLAMA_MODEL=llama3.2:latest`.

---

## 1. Run the app (see the dashboard)  — 3 things

Keep the **Ollama app** open (it serves the LLM at `localhost:11434`). Then two terminals:

```bash
# Terminal 1 — API (the only door to the data)
uv run seismo serve                  # http://127.0.0.1:8000   (Ctrl+C to stop)

# Terminal 2 — dashboard
cd dashboard && npm run dev          # http://localhost:3000  (or 3001 if 3000 is busy)
```

Then open **http://localhost:3000** → Radar. Click an entity for its Dossier; `/queue` for merge triage.

> After editing anything in `src/seismo/api/`, **restart Terminal 1** — the API has no hot-reload.
> Point the dashboard at a different API: `SEISMO_API_BASE=http://127.0.0.1:8001 npm run dev`.

---

## 2. Daily data pipeline (get fresh data)

Run these **once a day**, in order. (On a server the first two are systemd timers; see `deploy/`.)

```bash
uv run seismo collect --source fast --window 1d   # 1. discover new repos/papers/stories (last day)
uv run seismo track  --source github              # 2. snapshot star counts for known repos (~13 min)
uv run seismo resolve                             # 3. attach new events → entities, auto-merges
uv run seismo snapshot                            # 4. rebuild entity_metrics_daily from snapshots
uv run seismo score                               # 5. velocity → momentum states (dormant/…/breakout)
uv run seismo comprehend                          # 6. LLM cards for entities crossing the trigger
```

- `--source` for collect/track: `fast` (github+hn+arxiv), `all`, or a single `github|hn|arxiv`.
- Momentum stays **dormant** until `track` has run on ≥2 days ~a week apart (velocity needs history).
- Re-running the same day = no new data (idempotent), just spends a little API budget.

---

## 3. One-off / cold-start jobs

```bash
# Historical sweep — pull repos/papers created in the last 180 days (ALREADY RUN once).
uv run seismo sweep --days 180                    # discovery over past windows → resolve --cold-start
uv run seismo sweep --days 90 --chunk 30 --source fast   # smaller/tunable variant

# Seed universe (hand-curated day-1 entities) — already loaded.
uv run seismo seed-load
uv run seismo resolve --cold-start                # defer low-confidence merges during cold start

# GH Archive star-history backfill (HEAVY — hundreds of GB; for hindcasts like DeepSeek).
uv run seismo backfill-stars --since 2024-01-01 --until 2024-06-01 --repos deepseek-ai
```

---

## 4. Comprehension cards (LLM summaries)

```bash
uv run seismo comprehend                          # cards for all trigger-eligible entities
uv run seismo comprehend --entity 5564            # FORCE a card for one entity (bypasses the trigger)
uv run seismo comprehend --limit 20               # cap how many candidates this run (cost/time control)

# Card a batch (e.g. specific ids):
for id in 5418 5564 5895 6930 8759; do uv run seismo comprehend --entity $id; done
```

- Provider comes from `.env` (`ollama` now). $0 and local. Keep the Ollama app open.
- Cards appear in the dashboard Dossier on refresh. Forcing `--entity` always adds a new version.
- Better prose: `ollama pull qwen2.5:7b-instruct` then set `SEISMO_OLLAMA_MODEL=qwen2.5:7b-instruct` in `.env`.

---

## 5. Dev checks (before committing code)

```bash
uv run pytest -q                                  # full test suite (75 tests, $0 mock LLM)
uv run pytest tests/test_api.py -q                # one file
uv run ruff check                                 # lint
uv run ruff format                                # auto-format
uv run mypy src                                   # type-check (src only; tests untyped by design)
bash scripts/check_llm_import.sh                  # invariant 3: no LLM SDK outside checkpoints/
uv run seismo doctor                              # DB + extension + schema + LLM-provider health

# Dashboard:
cd dashboard && npm run build                     # type-check + production build
```

Migrations:
```bash
uv run alembic upgrade head                       # apply pending migrations
uv run alembic current                            # show current revision
# NOTE: never `alembic downgrade` a DB that has data — it drops history tables. See HANDOFF §5.
```

---

## 6. Inspect the database (read-only sanity checks)

```bash
# quick counts
PGPASSWORD=seismo psql -U seismo -h localhost -d seismograph -c "
  select 'entities', count(*) from entities
  union all select 'events', count(*) from raw_events
  union all select 'cards(ok)', count(distinct entity_id) from comprehension_cards where status='ok'
  union all select 'queue', count(*) from entity_merge_queue where status in ('pending','deferred_coldstart');"

# events by source / type
PGPASSWORD=seismo psql -U seismo -h localhost -d seismograph -c \
  "select source, event_type, count(*) from raw_events group by 1,2 order by 3 desc limit 20;"

# top repos by stars (good candidates to card)
PGPASSWORD=seismo psql -U seismo -h localhost -d seismograph -c "
  select e.id, e.canonical_name from entities e
  where attrs->'anchors' ? 'github' and merged_into is null order by e.id limit 20;"
```

See the exact **LLM context** (evidence pack) for an entity — the input the model got:
```bash
uv run python -c "
from datetime import datetime, UTC
from seismo.db import session_scope
from seismo.checkpoints.evidence import build_evidence_pack
with session_scope() as s:
    p = build_evidence_pack(s, 5564, datetime.now(UTC))   # <-- entity id
    print(p.markdown)
    print('\n--- length:', len(p.markdown), 'chars ---')
"
```

---

## 7. API endpoints (what the dashboard calls)

With `seismo serve` running (`http://127.0.0.1:8000`):

```bash
curl -s "http://127.0.0.1:8000/health" | python3 -m json.tool
curl -s "http://127.0.0.1:8000/radar?limit=20&state=breakout"      # ?state=, ?theme=, ?as_of=
curl -s "http://127.0.0.1:8000/entities/5564"                      # dossier (?as_of= for time-travel)
curl -s "http://127.0.0.1:8000/search?q=agent&type=project"
curl -s "http://127.0.0.1:8000/queue"
curl -s -X POST "http://127.0.0.1:8000/merge-queue/23/decision?decision=merge"   # merge|reject|skip
```
Interactive API docs (OpenAPI): open **http://127.0.0.1:8000/docs** in a browser.

---

## 8. Git

```bash
git status
git log --oneline -10
git add -A && git commit -m "message"             # commits to main (solo, no remote)
```

---

## 9. Troubleshooting

| Symptom | Fix |
|---|---|
| `address already in use` on `:8000` | `lsof -ti tcp:8000 \| xargs kill` (a stray `seismo serve`). Or `seismo serve --port 8001`. |
| Dashboard shows "Can't reach the API" | Start Terminal 1 (`uv run seismo serve`) first. |
| Dashboard on `:3001`, `/queue` fails | CORS allows any localhost port now; if not, free `:3000` (`lsof -ti tcp:3000 \| xargs kill`) and restart `npm run dev`. |
| `comprehend` errors / hangs | Ollama app must be open. Check: `curl -s localhost:11434/api/version`. Model must be pulled: `ollama list`. |
| GitHub `403` in `collect`/`track` | Token missing/expired in `.env` (`SEISMO_GITHUB_TOKEN`). Failure is isolated, not fatal. |
| Everything is "Dormant" on the Radar | Expected until `track` runs on ≥2 days ~a week apart (velocity needs star history). |
| Cards look too short | Packs lack READMEs — see `HANDOFF.md` §16 (README enrichment). |
| `doctor` red on schema | `uv run alembic upgrade head`. |
| Ollama not running | Open the Ollama macOS app, or `ollama serve` in a terminal. |

---

## 10. Cheat-sheet: "I just want to…"

- **…see the dashboard:** Ollama app open → `uv run seismo serve` → `cd dashboard && npm run dev` → open `localhost:3000`.
- **…refresh the data:** run the 6 commands in §2 (once a day).
- **…make more cards to browse:** `for id in <ids>; do uv run seismo comprehend --entity $id; done` (ids from §6).
- **…add lots of real projects:** `uv run seismo sweep --days 180` (already done once).
- **…check nothing is broken:** `uv run pytest -q && uv run ruff check && uv run mypy src && uv run seismo doctor`.
