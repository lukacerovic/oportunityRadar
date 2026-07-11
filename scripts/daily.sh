#!/usr/bin/env bash
# scripts/daily.sh — Seismograph daily heartbeat.
#
# Runs the full daily monitoring cycle in the correct order (HANDOFF §8):
#   collect (find new) → track (measure known) → resolve (fold in) → snapshot → score → comprehend
#
# Run this ONCE a day. The critical step is `track`: it records today's star/fork counts for known
# repos, and momentum = how those change over ~7 days. Miss days ⇒ gaps ⇒ momentum never builds.
#
# Steps are isolated: if one fails the script logs it and keeps going, then prints a summary and
# exits non-zero if anything failed (so you notice). Nothing here spends money — the LLM is local.
#
# Usage:
#   ./scripts/daily.sh                # tracks TRACK_LIMIT (default 1500) repos
#   TRACK_LIMIT=800 ./scripts/daily.sh
#   SKIP_COMPREHEND=1 ./scripts/daily.sh
#
# Requirements: the Ollama app must be open (for `comprehend`); SEISMO_GITHUB_TOKEN set in .env.
# NOTE: tracking is capped at TRACK_LIMIT because the free GitHub tier is 5000 calls/hr and there
# are ~9000 known repos. Until `retier` (A-4) bounds the active set properly, we track a consistent
# id-ordered slice (your seed universe + earliest-discovered repos) so momentum accrues on a stable set.

set -u
set -o pipefail  # so a step's failure is seen through the `| tee` pipe, not masked by tee's success
cd "$(dirname "$0")/.." || exit 1

TRACK_LIMIT="${TRACK_LIMIT:-1500}"
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

run "collect"  uv run seismo collect --source fast --window 1d
run "track"    uv run seismo track  --source github --limit "$TRACK_LIMIT"
run "resolve"  uv run seismo resolve
run "snapshot" uv run seismo snapshot
run "score"    uv run seismo score
if [ "${SKIP_COMPREHEND:-0}" != "1" ]; then
  run "comprehend" uv run seismo comprehend
fi

echo "" | tee -a "$LOG"
echo "########## done — $(date '+%H:%M:%S') ##########" | tee -a "$LOG"
if [ "${#FAILED[@]}" -eq 0 ]; then
  echo "All steps OK. Log: $LOG" | tee -a "$LOG"
  exit 0
else
  echo "FAILED steps: ${FAILED[*]}. See $LOG" | tee -a "$LOG"
  exit 1
fi
