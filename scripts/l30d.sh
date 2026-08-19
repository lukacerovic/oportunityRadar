#!/usr/bin/env bash
# last30days wrapper — always saves the brief, never runs two at once.
#
# Why this exists: the first five runs of this session were lost because --save-dir
# was omitted and the output went to a temp dir. And three parallel runs knocked
# Reddit into HTTP 429, which silently produced a wrong conclusion (see
# LAST30DAYS_RUNBOOK.md §"Zašto ovo uopšte koristimo"). Both mistakes are now
# impossible to repeat through this script.
#
# Usage:
#   scripts/l30d.sh "topic"                      # research brief
#   scripts/l30d.sh --hiring "Company"           # jobs-only hiring signals
#   scripts/l30d.sh --search reddit,hackernews "topic"
#   scripts/l30d.sh --doctor                     # health check
#   scripts/l30d.sh --library "query"            # full-text search past briefs
#   scripts/l30d.sh --feed                       # build index.html + feed.xml
#
# Everything lands in research/last30days/ and is indexed into
# .last30days-library.db, so briefs accumulate into a time series you can diff.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SAVE_DIR="$REPO/research/last30days"
SKILL="$HOME/.agents/skills/last30days/scripts/last30days.py"
LOCK="$SAVE_DIR/.l30d.lock"

[ -f "$SKILL" ] || { echo "last30days not installed at $SKILL" >&2; exit 1; }
mkdir -p "$SAVE_DIR"

case "${1:-}" in
  --doctor)  exec python3 "$SKILL" doctor ;;
  --library) shift; exec python3 "$SKILL" library search "${1:?query required}" --save-dir="$SAVE_DIR" ;;
  --feed)    exec python3 "$SKILL" library feed --save-dir="$SAVE_DIR" ;;
esac

# Serialize: Reddit rate-limits hard, and a second concurrent run poisons both.
if command -v flock >/dev/null 2>&1; then
  exec 9>"$LOCK"; flock -n 9 || { echo "another l30d run is in progress — wait for it" >&2; exit 1; }
else
  # macOS has no flock(1); mkdir is atomic enough for a single-user guard.
  mkdir "$LOCK.d" 2>/dev/null || { echo "another l30d run is in progress — wait for it" >&2; exit 1; }
  trap 'rmdir "$LOCK.d" 2>/dev/null || true' EXIT
fi

ARGS=()
if [ "${1:-}" = "--hiring" ]; then
  shift; ARGS+=(--hiring-signals)
elif [ "${1:-}" = "--search" ]; then
  shift; ARGS+=(--search "${1:?source list required}"); shift
fi

TOPIC="${1:?topic required — scripts/l30d.sh \"your topic\"}"
echo "[l30d] $TOPIC  →  $SAVE_DIR"
exec python3 "$SKILL" "$TOPIC" "${ARGS[@]}" \
  --emit md --max-results 25 --save-dir "$SAVE_DIR"
