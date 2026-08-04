# Seismograph — Command Cheat-Sheet

Practical "how do I run this" reference. For architecture/state see `HANDOFF.md`.

- **Project root:** `~/Desktop/OportunityRadar` — run everything from here unless noted.
- **You do NOT need `source .venv/bin/activate`** — `uv run <cmd>` handles the environment.
- **Database:** Postgres `seismograph` (role `seismo`), local. **LLM:** local Ollama app.
- Every pipeline command is **idempotent** — safe to re-run; it only adds genuinely new data.
- **Requirements each run:** Postgres running · the **Ollama macOS app** open (for `comprehend`/`brief`) ·
  `.env` with `SEISMO_DATABASE_URL`, `SEISMO_GITHUB_TOKEN`, `SEISMO_LLM_PROVIDER=ollama`,
  `SEISMO_OLLAMA_MODEL=qwen2.5:3b-instruct`.

---

## ⭐ 1. THE DAILY RUNBOOK — one command

**This is the whole daily cycle in a single command:**

```bash
cd ~/Desktop/OportunityRadar && ./scripts/daily.sh
```

That runs all 9 steps below in order, isolates failures (one bad step doesn't stop the rest), logs
everything to `logs/daily-<date>.log`, and prints a summary (exit non-zero if anything failed).
Total time ≈ 15–25 min (mostly `track`). Nothing costs money — the LLM is local. **Requirements:** the
**Ollama app** open (for the AI steps) and `SEISMO_GITHUB_TOKEN` in `.env`.

```bash
# handy variants:
TRACK_LIMIT=800  ./scripts/daily.sh    # track fewer repos (faster / smaller rate budget)
SKIP_BRIEF=1     ./scripts/daily.sh    # do everything except drafting briefs
SKIP_COMPREHEND=1 ./scripts/daily.sh   # skip BOTH AI steps (cards + briefs) — no Ollama needed
```

> **Why once a day, every day:** momentum = how star/download counts *change* over ~7 days. `track`
> records today's numbers; miss days ⇒ gaps ⇒ momentum never builds. Consistency matters more than
> the exact time of day.

### The 9 steps it runs (or run them by hand)

If you ever want to run them individually (e.g. to debug one step), this is exactly what the script
does — `$WEEK` is the current ISO week:

```bash
WEEK=$(date +%G-W%V)                                   # current ISO week, e.g. 2026-W28

uv run seismo collect --source fast --window 1d        # 1. find new repos/papers/stories (last 24h)
uv run seismo track   --source github --limit 1500     # 2. re-measure known repos' stars/forks (~13 min)
uv run seismo resolve                                  # 3. fold new events into entities + auto-merge
uv run seismo enrich-wikidata --limit 200              # 3b. team enrichment — who is behind each paper/repo
                                                       #     (Wikidata: employers, ex-employers, founders)
uv run seismo derive-edges                             # 3c. typed graph edges (built_by/cited/authored_by/
                                                       #     employed_by/formerly_at/founded) for the graph page
uv run seismo snapshot                                 # 4. rebuild the daily metric table from snapshots
uv run seismo score                                    # 5. velocity → momentum states (dormant…breakout)
uv run seismo waves                                    # 5b. convergences: several independent teams,
                                                       #     same idea, same window (+ lead time, + outcome)
uv run seismo comprehend                               # 6. AI summary cards for entities crossing the trigger
uv run seismo gate    --week "$WEEK"                   # 7. pick which entities deserve a brief this week
uv run seismo brief   --week "$WEEK"                   # 8. draft an impact brief for each one the gate passed
uv run seismo changes                                  # 9. record today's deltas → the Changes view
```

### What each step does (the detail)

| # | Command | Layer | What it produces | Notes |
|---|---|---|---|---|
| 1 | `collect` | Observation | new `raw_events` (repos, papers, HN stories) | `--source fast` = github+hn+arxiv. Isolated per source: one failing doesn't stop the rest. |
| 2 | `track` | Observation | today's `repo_snapshot` (star/fork counts) | **The heartbeat.** Capped at `--limit 1500` (free GitHub tier = 5000 calls/hr). This is what makes momentum possible. |
| 3 | `resolve` | Identity | entities + merges from the new events | Global + idempotent. Links a paper↔repo↔model into one entity (R1–R6 rules). |
| 4 | `snapshot` | Trajectory | `entity_metrics_daily` rows | Turns raw snapshots into per-day metric values (stars, downloads, breadth). |
| 5 | `score` | Trajectory | `momentum_states` (dormant/simmering/accelerating/breakout) | Velocity percentiles vs. peers + maturity promotions, with hysteresis. |
| 5b | `waves` | Convergence | `wave_clusters` / `wave_members` / `wave_observations` / `wave_outcomes` | The only stage that looks at a *population*, not one entity. Deterministic, **no LLM**, no network. Also re-scores older waves as their 90-day horizons elapse, so run it daily. |
| 6 | `comprehend` | Comprehension (AI #1) | `comprehension_cards` (what-it-is summaries) | Only cards entities that cross the trigger. Uses local Ollama ($0). |
| 7 | `gate` | Significance | `gate_decisions` (pass / suppressed + reason) | Deterministic M×R×N pick of ≤5 briefs/week. **No LLM.** Re-runnable per week. |
| 8 | `brief` | Impact (AI #2) | `impact_briefs` (draft) | An evidence-linked exposure brief for each passed entity. Stored **draft** for you to review. |
| 9 | `changes` | Memory | `changes_daily` rows | Plain-English deltas for the dashboard's Changes tab. Cheap, no LLM. |

### What to expect early on (important — not a bug)
- **Everything shows "dormant" and the gate passes nobody** until `track` has run on **≥2 days about a
  week apart** — velocity needs a star-count *history*. So steps 7–8 will draft nothing for the first
  ~1–2 weeks. That's expected: keep running daily and momentum wakes up.
- Once entities start reaching **accelerating/breakout**, step 7 begins passing them and step 8 drafts
  real briefs — which then wait for you in the dashboard's **Briefs** tab.

---

## 👀 2. See the results (the dashboard)

Keep the **Ollama app** open, then two terminals:

```bash
# Terminal 1 — the API (the only door to the data)
uv run seismo serve                    # http://127.0.0.1:8000   (Ctrl+C to stop)

# Terminal 2 — the dashboard
cd dashboard && npm run dev            # http://localhost:3000  (or 3001 if 3000 is busy)
```

Open **http://localhost:3000**. The 7 pages (each has an ⓘ button explaining every field):

| Page | URL | What you do there |
|---|---|---|
| **Radar** | `/` | See every entity by momentum + velocity; the main overview. |
| **Entity dossier** | `/entity/<id>` | One entity's registries, metrics, AI card, maturity ladder. |
| **Changes** | `/changes/current` | What moved today (new survivors, promotions, brief lifecycle). |
| **Gate** | `/gate/current` | This week's significance decisions — who passed, who was suppressed + why. |
| **Briefs** | `/brief` | Review inbox: **publish or reject** each draft brief (humans gate publish). |
| **Brief detail** | `/brief/<id>` | Full brief — exposures, mechanisms, counter-argument, observables. |
| **Queue** | `/queue` | Merge-triage for uncertain identity matches (keyboard M/N/S). |

> After editing anything in `src/seismo/api/`, **restart Terminal 1** — the API has no hot-reload.
> Free a stuck port: `lsof -ti tcp:8000 | xargs kill`.

---

## 🗓️ 3. Weekly / monthly rituals (not daily)

```bash
# WEEKLY — review & publish the briefs the gate produced this week.
#   Do this in the dashboard: open /brief → read each draft → Publish or Reject (with a reason).
#   Publishing is a human decision (DR-08.2). Only published briefs get forward-scored.

# WEEKLY — forward-score PUBLISHED briefs (a judgment ritual, in the dashboard).
#   Open a published brief → the scoring panel auto-checks its measurable observables (A-7);
#   you record whether the thesis materialized / a falsifier tripped. This is the calibration loop.

# MONTHLY — momentum-call review (how good were past breakout/fade calls?).
uv run seismo calibrate                # → calibration_snapshots; shows in the dashboard
#   Reads n=0 until ~90 days of daily momentum accrue (breakout-survival needs ≥90-day-old calls).
#   That's expected — run it monthly and it starts reading real numbers after a quarter.
```

---

## 🔌 4. Optional daily add-on — Hugging Face (the 4th evidence type: model usage)

HF is built but **not** in the `fast` group (its discovery is broader/noisier), so the daily runbook
above doesn't include it. To also monitor AI-model usage, add these — then re-run `resolve`/`snapshot`/
`score` so the new signal flows through:

```bash
uv run seismo collect --source hf --window 1d          # discover trending models born recently
uv run seismo track   --source hf --limit 500          # re-measure known models' download counts
uv run seismo resolve && uv run seismo snapshot && uv run seismo score
```

---

## 🧰 5. Setup & maintenance (rare)

```bash
# One-time setup (already done on this machine)
uv sync                                # install Python deps
uv run alembic upgrade head            # DB schema — migrations 0001–0006
cd dashboard && npm install && cd ..   # dashboard deps

# Load / refresh the company exposure map (after editing exposure_map/*.yaml).
uv run seismo load-map                 # → 30 companies, 133 reach_links (authoritative rebuild)
uv run seismo load-map --strict        # same, but fail loudly on any bad file

# Health check — run anytime something feels off.
uv run seismo doctor                   # DB + pg_trgm + schema + LLM-provider; "All green" expected
```

---

## 🌱 6. One-off / cold-start jobs (already run once — for reference)

```bash
uv run seismo sweep --days 180                    # pull repos/papers created in the last 180 days
uv run seismo seed-load                           # load the hand-curated day-1 seed universe
uv run seismo resolve --cold-start                # defer low-confidence merges during cold start
uv run seismo enrich-readmes --carded-only        # fetch READMEs so AI cards have real substance (§16)

# GH Archive star-history backfill — HEAVY (hundreds of GB); only for hindcast validation.
uv run seismo backfill-stars --since 2024-01-01 --until 2024-06-01 --repos deepseek-ai
```

---

## 🧠 7. Comprehension & briefs — forcing one by hand

```bash
uv run seismo comprehend --entity 5564            # FORCE an AI card for one entity (bypass the trigger)
uv run seismo comprehend --limit 20               # cap candidates this run (time/cost control)
for id in 5418 5564 5895 6930; do uv run seismo comprehend --entity $id; done   # a batch

uv run seismo brief --entity-id 2857              # FORCE a brief for one entity (bypass the gate)
```

- Cards/briefs use local Ollama (`qwen2.5:3b-instruct`) at $0. Keep the Ollama app open.
- **Better prose:** `ollama pull qwen2.5:7b-instruct`, then for a one-off run prefix the command:
  `SEISMO_OLLAMA_MODEL=qwen2.5:7b-instruct uv run seismo brief --entity-id 2857` (~4 min/brief).
- Forcing `--entity`/`--entity-id` always appends a new version.

---

## 🔍 8. Inspect the database (read-only sanity checks)

```bash
# quick counts
psql -d seismograph -c "
  select 'entities', count(*) from entities
  union all select 'events', count(*) from raw_events
  union all select 'cards(ok)', count(distinct entity_id) from comprehension_cards where status='ok'
  union all select 'momentum!=dormant', count(*) from momentum_states m
    where day=(select max(day) from momentum_states) and state<>'dormant'
  union all select 'briefs(draft)', count(*) from impact_briefs where status='draft'
  union all select 'companies', count(*) from exposure_companies;"

# today's momentum leaders (once momentum is live)
psql -d seismograph -c "
  select e.canonical_name, m.state, round(m.score::numeric,3) as velocity_pct
  from momentum_states m join entities e on e.id=m.entity_id
  where m.day=(select max(day) from momentum_states) and m.state<>'dormant'
  order by m.score desc limit 20;"
```

See the exact **LLM context** (evidence pack) an entity's card was built from:
```bash
uv run python -c "
from datetime import datetime, UTC
from seismo.db import session_scope
from seismo.checkpoints.evidence import build_evidence_pack
with session_scope() as s:
    p = build_evidence_pack(s, 5564, datetime.now(UTC))   # <-- entity id
    print(p.markdown); print('\n--- length:', len(p.markdown), 'chars ---')
"
```

---

## 🌐 9. API endpoints (what the dashboard calls) — with `seismo serve` running

```bash
curl -s "http://127.0.0.1:8000/health" | python3 -m json.tool
curl -s "http://127.0.0.1:8000/radar?limit=20&state=breakout"      # ?state= ?theme= ?as_of=
curl -s "http://127.0.0.1:8000/entities/5564"                      # dossier (?as_of= to time-travel)
curl -s "http://127.0.0.1:8000/gate/current"                       # this week's gate decisions
curl -s "http://127.0.0.1:8000/briefs"                             # review inbox
curl -s "http://127.0.0.1:8000/changes/latest"                     # latest Changes view
curl -s "http://127.0.0.1:8000/waves"                              # detected convergences, strongest first
curl -s "http://127.0.0.1:8000/waves/1"                            # one wave: members, early mentions, outcome
curl -s "http://127.0.0.1:8000/search?q=agent&type=project"
```
Interactive API docs (OpenAPI): open **http://127.0.0.1:8000/docs**.

---

## ✅ 10. Dev checks (before committing code)

```bash
uv run ruff check && uv run ruff format --check    # lint + format
uv run mypy src                                    # type-check (src only; tests untyped by design)
bash scripts/check_llm_import.sh                   # invariant 3: no LLM SDK outside checkpoints/
uv run seismo doctor                               # DB + schema + LLM-provider health
cd dashboard && npm run build && cd ..             # dashboard type-check + prod build

# Tests: the FULL suite times out (>10 min — the shared dev DB is large). Run by file instead:
uv run pytest tests/test_collectors.py tests/test_exposure.py tests/test_identity_pure.py -q
uv run pytest tests/test_hindcast.py -q            # heavier (uses clean_db)
```

Migrations:
```bash
uv run alembic upgrade head                        # apply pending migrations (head = 0006)
uv run alembic current                             # show current revision
# NEVER `alembic downgrade` a DB with data — it drops history tables. See HANDOFF §5.
```

---

## 🆘 11. Troubleshooting

| Symptom | Fix |
|---|---|
| `address already in use` on `:8000` | `lsof -ti tcp:8000 \| xargs kill` (a stray `seismo serve`). Or `seismo serve --port 8001`. |
| Dashboard: "Can't reach the API" | Start Terminal 1 (`uv run seismo serve`) first. |
| `comprehend`/`brief` errors or hangs | Ollama app must be open: `curl -s localhost:11434/api/version`. Model pulled? `ollama list`. |
| GitHub `403` in `collect`/`track` | Token missing/expired in `.env` (`SEISMO_GITHUB_TOKEN`). Failure is isolated, not fatal. |
| Everything "Dormant"; gate passes nobody | Expected until `track` runs ≥2 days ~a week apart (velocity needs star history). Keep running daily. |
| `brief` drafts nothing | Nothing reached accelerating/breakout yet, or the entity's card is still `pending`. Normal early on. |
| Cards look too short | Pack lacks a README — `uv run seismo enrich-readmes --carded-only`, then re-`comprehend`. |
| `doctor` red on schema | `uv run alembic upgrade head`. |

---

## 📌 12. "I just want to…"

- **…do my full daily run:** `./scripts/daily.sh` (one command — see **§1**).
- **…see the dashboard:** Ollama open → `uv run seismo serve` → `cd dashboard && npm run dev` → `localhost:3000`.
- **…review today's briefs:** open `/brief` in the dashboard → Publish or Reject each draft.
- **…understand why nothing's happening yet:** momentum needs ~1–2 weeks of daily `track`. See §1 "What to expect early on".
- **…check nothing is broken:** `uv run seismo doctor` + the by-file tests in §10.
