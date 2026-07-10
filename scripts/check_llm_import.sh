#!/usr/bin/env bash
# Invariant 3 (doc 02 §1, doc 13 A-13): no LLM SDK is imported outside checkpoints/.
# CI runs this; a hit fails the build.
set -euo pipefail

if grep -rnE "import (anthropic|ollama)" src/seismo --include="*.py" \
     | grep -v "src/seismo/checkpoints/"; then
  echo "INVARIANT 3 VIOLATED: LLM SDK imported outside src/seismo/checkpoints/ (above)." >&2
  exit 1
fi
echo "invariant 3 OK: no LLM SDK import outside checkpoints/"
