#!/usr/bin/env bash
# scripts/daily.sh — Seismograph daily heartbeat.
#
# Runs the FULL daily monitoring cycle in the correct order (HANDOFF §8, COMMANDS.md §1):
#   collect → track → resolve → snapshot → score → comprehend → gate → brief → changes
# i.e. discover → measure → identify → momentum → AI cards → pick significant → draft impact briefs
# → record deltas. This is the one command to run each day for the full analysis.
#
# Run this ONCE a day. The critical step is `track`: it records today's star/fork counts for known
# repos, and momentum = how those change over ~7 days. Miss days ⇒ gaps ⇒ momentum never builds.
#
# `gate`/`brief` operate on the current ISO week and are re-runnable (the gate deletes the week's
# rows and re-scores; brief skips entities that already have a live draft). Early on both do nothing
# — the gate passes nobody until entities reach accelerating/breakout (needs ~1–2 weeks of `track`).
#
# Steps are isolated: if one fails the script logs it and keeps going, then prints a summary and
# exits non-zero if anything failed (so you notice). Nothing here spends money — the LLM is local.
#
# Usage:
#   ./scripts/daily.sh                # full cycle; tracks TRACK_LIMIT (default 1500) repos
#   TRACK_LIMIT=800 ./scripts/daily.sh
#   SKIP_COMPREHEND=1 ./scripts/daily.sh   # skip both LLM steps (comprehend + brief) — no Ollama needed
#   SKIP_BRIEF=1 ./scripts/daily.sh        # run cards but skip drafting briefs
#
# Requirements: the Ollama app must be open (for `comprehend`); SEISMO_GITHUB_TOKEN set in .env.
# NOTE: tracking is capped at TRACK_LIMIT because the free GitHub tier is 5000 calls/hr and there
# are ~9000 known repos. Until `retier` (A-4) bounds the active set properly, we track a consistent
# id-ordered slice (your seed universe + earliest-discovered repos) so momentum accrues on a stable set.

set -u
set -o pipefail  # so a step's failure is seen through the `| tee` pipe, not masked by tee's success
cd "$(dirname "$0")/.." || exit 1

TRACK_LIMIT="${TRACK_LIMIT:-1500}"
WEEK="$(date +%G-W%V)"          # current ISO week (e.g. 2026-W28) for gate/brief
LOG_DIR="logs"
mkdir -p "$LOG_DIR"
STAMP="$(date +%Y-%m-%d)"
LOG="$LOG_DIR/daily-$STAMP.log"

declare -a FAILED=()

run() {  # run "<label>" <command...>
  local label="$1"; shift
  echo "" | tee -a "$LOG"
  echo "=== [$label] $(date '+%H:%M:%S') ===" | tee -a "$LOG"
  if "$@" 2>&1 | tee -a "$LOG"; then
    echo "--- [$label] OK" | tee -a "$LOG"
  else
    echo "--- [$label] FAILED (continuing)" | tee -a "$LOG"
    FAILED+=("$label")
  fi
}

echo "########## Seismograph daily — $STAMP ##########" | tee -a "$LOG"

# 3-day window, not 1: two independent reasons, both learned the hard way.
#   * Self-healing. A missed or failed day used to be a permanent hole — the next run only looked
#     back 24h. Three days of overlap means a run can fail twice and still lose nothing.
#   * Hugging Face needs it structurally. Unlike github/hn/arxiv, which query date-ordered feeds,
#     HF has no server-side date filter: `discover` scans the *trending* list (20 pages x 100) and
#     uses the window as a post-filter, keeping models both trending now AND born in the window.
#     At 1d that intersection is nearly empty — a model is rarely trending within 24h of birth —
#     so the same ~2,000-model scan was being thrown away. HF discovery had produced 78 events
#     total, against 32,971 for GitHub.
# Re-seeing an item is free: `source_event_uid` dedupes on insert, which is why collect reports
# events_new rather than events_seen. The cost is extra API calls on the date-ordered sources;
# watch GitHub's rate limit if TRACK_LIMIT is also raised.
run "collect"  uv run seismo collect --source all --window "${COLLECT_WINDOW:-3d}"
run "track"    uv run seismo track  --source github --limit "$TRACK_LIMIT"
run "track-hf" uv run seismo track  --source hf
run "resolve"  uv run seismo resolve
# Enrichment (Wave-3): fetch deep readable content for EVERY source so cards have real substance,
# not just titles. Each targets only still-un-enriched items (NOT EXISTS) with a per-day cap, so
# daily runs steadily complete coverage across the whole universe. A second resolve folds the
# fetched text onto the entities. arXiv abstracts arrive free at collection, so no step is needed.
if [ "${SKIP_ENRICH:-0}" != "1" ]; then
  run "enrich-launches" uv run seismo enrich-launches
  run "enrich-hn"       uv run seismo enrich-hn
  run "enrich-readmes"  uv run seismo enrich-readmes --missing --limit "${README_LIMIT:-300}"
  run "enrich-hf"       uv run seismo enrich-hf --limit "${HF_CARD_LIMIT:-300}"
  # Team enrichment (WIKIDATA_ENRICHMENT_PLAN.md): who is behind each paper/repo/model —
  # employer history, founders. Un-enriched entities only, so coverage completes over days.
  run "enrich-wikidata" uv run seismo enrich-wikidata --limit "${WIKIDATA_LIMIT:-200}"
  run "resolve-enrich"  uv run seismo resolve
fi
# Graph edges (authored_by/built_by/cited/depends_on + wikidata team edges) — was manual-only;
# without this the correlation graph silently goes stale as new evidence lands.
run "derive-edges" uv run seismo derive-edges
run "snapshot" uv run seismo snapshot
run "score"    uv run seismo score
if [ "${SKIP_COMPREHEND:-0}" != "1" ]; then
  run "comprehend" uv run seismo comprehend
  # Backlog: card the richest still-uncarded items (arXiv abstracts, HF/launch content) a slice at
  # a time so the whole universe gradually gets readable cards, not just the momentum-triggered few.
  run "comprehend-backlog" uv run seismo comprehend --backlog --limit "${BACKLOG_LIMIT:-100}"
fi
# Stage 6 (doc 07): deterministic significance gate — no LLM. Picks ≤5 briefs for the current week.
run "gate"     uv run seismo gate --week "$WEEK"
# Stage 7 (doc 08): impact briefs (LLM #2, local Ollama) for entities the gate passed — stored draft.
# Needs Ollama, like comprehend; skip it when comprehend is skipped or SKIP_BRIEF=1.
if [ "${SKIP_COMPREHEND:-0}" != "1" ] && [ "${SKIP_BRIEF:-0}" != "1" ]; then
  run "brief"  uv run seismo brief --week "$WEEK"
fi
# Stage 8 (doc 09): deterministic Changes view — cheap ($0, no LLM), records today's deltas.
run "changes"  uv run seismo changes

echo "" | tee -a "$LOG"
echo "########## done — $(date '+%H:%M:%S') ##########" | tee -a "$LOG"
if [ "${#FAILED[@]}" -eq 0 ]; then
  echo "All steps OK. Log: $LOG" | tee -a "$LOG"
  exit 0
else
  echo "FAILED steps: ${FAILED[*]}. See $LOG" | tee -a "$LOG"
  exit 1
fi
