# Seismograph — Daily Operating Guide

Plain-language guide to running Seismograph day to day. If you only remember one thing:
**run `./scripts/daily.sh` once a day** (Ollama app open). That's the heartbeat.

---

## The one command

```bash
./scripts/daily.sh
```

That runs the whole daily cycle in order and writes a log to `logs/daily-YYYY-MM-DD.log`.
It takes roughly **40–55 minutes**, almost all of it the GitHub tracking step.

Options:
```bash
TRACK_LIMIT=800 ./scripts/daily.sh    # track fewer repos (faster, e.g. ~25 min)
SKIP_COMPREHEND=1 ./scripts/daily.sh  # skip the AI card step
```

Requirements: the **Ollama app must be open** (for the AI step) and `SEISMO_GITHUB_TOKEN` set in `.env`.

---

## What each step does (and why)

The script runs these in order (HANDOFF §8). You can also run any of them by hand.

| Step | Command | What it does | Why daily? |
|---|---|---|---|
| 1. Collect | `seismo collect --source fast --window 1d` | Finds **new** repos/papers/HN posts from the last day | Keeps the universe current |
| 2. Track | `seismo track --source github --limit 1500` | **Measures** known repos (today's star/fork counts) | **The critical one.** Momentum = how these change over ~7 days. Miss days ⇒ no momentum |
| 3. Resolve | `seismo resolve` | Folds new events into durable entities (dedupes, merges) | So new data is attached and countable |
| 4. Snapshot | `seismo snapshot` | Rebuilds the daily metrics table from the raw measurements | Feeds momentum |
| 5. Score | `seismo score` | Recomputes momentum states (dormant → simmering → … → breakout) | The living picture |
| 6. Comprehend | `seismo comprehend` | Writes AI cards for entities that just became worth it | Cheap (local, $0); self-limits via triggers |
| 7. Changes | `seismo changes` | Records today's deterministic deltas (state moves, promotions, briefs) → the **Changes** view | Cheap ($0, no LLM); the daily "what moved" |

**Why `track` is capped at 1,500:** there are ~9,000 known repos but GitHub's free tier allows
5,000 API calls/hour and each poll is ~2s. So we track a **consistent id-ordered slice** (your seed
universe + earliest-discovered repos) every day — momentum builds on that stable set. Bumping the
active set to the "right" ~1,000 repos is a future task (`retier`, A-4).

---

## What to expect over time

- **First ~week:** most things stay `dormant`. That's normal — momentum needs several days of
  `track` to see a trend. Don't expect `breakout` on day 1.
- **After ~1–2 weeks of daily runs:** repos that are genuinely rising start showing `simmering` /
  `accelerating` on the dashboard Radar.
- **Momentum only builds on days you run it.** A skipped day is a hole in the time series.

---

## Weekly (not daily)

Once a week, run the significance gate — it picks the ≤5 entities worth a deep impact analysis:
```bash
uv run seismo gate                     # current week
uv run seismo gate --week 2026-W28     # a specific ISO week
```
Right now this returns **0 candidates** (everything is `dormant`) — that's correct; it'll start
passing entities once momentum accrues.

---

## Occasionally

- **Refresh the exposure map** after editing `exposure_map/*.yaml`:
  ```bash
  uv run seismo load-map
  ```
- **Enrich more READMEs** (richer AI cards) for a batch of repos:
  ```bash
  uv run seismo enrich-readmes --limit 50   # then: seismo resolve && seismo comprehend
  ```
- **Team enrichment** (who is behind a paper/repo — employers, ex-employers, founders, via
  Wikidata; the daily run does 200/day on its own):
  ```bash
  uv run seismo enrich-wikidata --limit 200   # then: seismo resolve && seismo derive-edges
  ```
- **Health check** anytime:
  ```bash
  uv run seismo doctor
  ```

---

## Looking at the results (the dashboard)

Two terminals (Ollama app open):
```bash
uv run seismo serve                       # API on :8000
cd dashboard && npm run dev                # dashboard on :3000
```
Then open <http://localhost:3000> — Radar (what's moving), entity dossiers (the AI cards), and the
merge queue.

---

## If something looks wrong

- **`track` fails with a 403 rate-limit:** you tracked too many repos this hour. Lower `TRACK_LIMIT`.
- **`comprehend` errors / hangs:** the Ollama app isn't open, or the model isn't pulled
  (`ollama list` should show `qwen2.5:3b-instruct`).
- **Everything still `dormant` after a week:** confirm `track` actually ran each day
  (`logs/daily-*.log`) and produced snapshots — momentum needs the daily measurements.
- **Full check:** `uv run seismo doctor` should be all green.
