#!/usr/bin/env bash
# CI gate sequence (plan 06 §5). Run from sdoc-hackathon-docker/.
#
#   tools/ci.sh w2                 # gate W2 against a freshly run submission
#   tools/ci.sh w3 --submission submission.json
#   tools/ci.sh w1 --no-submit     # offline only (skip the Docker preflight)
#
# Steps (each wave runs the subset its gate defines):
#   1. pytest tests/ -q                                  unit suite        (all)
#   2. verify_extraction --scope <txt|all>               structural oracle (W2+)
#   3. verify_edges --scope <txt|all>                    edges + classes   (W2+)
#   4. verify_comparison --wave <wave>                   local score gate  (all)
#   5. preflight submission.json [--server URL]          submission safety (all)
#
# W1's gate (plan 01) is stage-1 only: rules + sim + frozen cache macro-F1
# >= 0.95, rule_pct >= 0.60, and no attachment bytes opened. The extraction
# oracle and edge verifier are W2 gates, so W1 runs steps 1, 4, 5 only.
#
# Offline vs Docker: steps 1-4 run offline; step 5's `/health` + `/submit`
# checks need the organizers' server. Pass --server to enable them.
set -uo pipefail

cd "$(dirname "$0")/.." || exit 2

WAVE="w2"
SCOPE="txt"
SUBMISSION=""
SERVER=""
NO_SUBMIT=0
DATA="data_v2"

while [ $# -gt 0 ]; do
  case "$1" in
    w1|w2|w3|w4|w5) WAVE="$1" ;;
    --scope) SCOPE="$2"; shift ;;
    --submission) SUBMISSION="$2"; shift ;;
    --server) SERVER="$2"; shift ;;
    --data) DATA="$2"; shift ;;
    --no-submit) NO_SUBMIT=1 ;;
    -h|--help)
      sed -n '2,20p' "$0"
      exit 0
      ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done

case "$WAVE" in
  w1) SCOPE="all" ;;
  w2) SCOPE="${SCOPE:-txt}" ;;
  *) SCOPE="all" ;;
esac

# Resolve an interpreter that actually runs here *and* has the deps. On
# Windows this script may run under Git Bash or WSL, where the PATH order can
# pick a bare python3 without pytest; the Windows install is preferred.
if [ -z "${PYTHON:-}" ]; then
  for candidate in python python3 py python.exe; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c "import pytest" >/dev/null 2>&1; then
      PYTHON="$candidate"
      break
    fi
  done
fi
if [ -z "${PYTHON:-}" ]; then
  # Fall back to a known Windows install (Git Bash mounts it under /c, WSL
  # under /mnt/c, and WSL also exposes the Windows python as python.exe).
  for candidate in \
    "/c/Program Files/Python313/python.exe" \
    "/mnt/c/Program Files/Python313/python.exe" \
    "/c/Users/$USER/AppData/Local/Programs/Python/Python313/python.exe" \
    "/mnt/c/Users/$USER/AppData/Local/Programs/Python/Python313/python.exe"; do
    if [ -x "$candidate" ] && "$candidate" -c "import pytest" >/dev/null 2>&1; then
      PYTHON="$candidate"
      break
    fi
  done
fi
if [ -z "${PYTHON:-}" ]; then
  echo "cannot find a python interpreter with pytest; set PYTHON=/path/to/python" >&2
  exit 2
fi
echo "using python: $PYTHON"
FAILED=0

step() {
  echo
  echo "=== $1"
}

step "1/5  unit suite"
if ! "$PYTHON" -m pytest tests/ -q; then
  FAILED=1
fi

if [ "$WAVE" = "w1" ]; then
  step "2-3/5 structural + edge verifiers"
  echo "skipped (W1 gate is stage-1 only; extraction gates start at W2)"
else
  step "2/5  structural oracle (scope=$SCOPE)"
  if ! "$PYTHON" tools/verify_extraction.py --data "$DATA" --scope "$SCOPE"; then
    FAILED=1
  fi

  step "3/5  edge verifier (scope=$SCOPE)"
  if [ -n "$SUBMISSION" ]; then
    if ! "$PYTHON" tools/verify_edges.py --data "$DATA" --scope "$SCOPE" "$SUBMISSION"; then
      FAILED=1
    fi
  else
    if ! "$PYTHON" tools/verify_edges.py --data "$DATA" --scope "$SCOPE"; then
      FAILED=1
    fi
  fi
fi

step "4/5  local score gate ($WAVE)"
if [ -n "$SUBMISSION" ]; then
  if ! "$PYTHON" tools/verify_comparison.py --data "$DATA" --scope "$SCOPE" --wave "$WAVE" --diagnose "$SUBMISSION"; then
    FAILED=1
  fi
else
  if ! "$PYTHON" tools/verify_comparison.py --data "$DATA" --scope "$SCOPE" --wave "$WAVE" --run --diagnose; then
    FAILED=1
  fi
fi

step "5/5  preflight"
if [ "$NO_SUBMIT" -eq 1 ]; then
  echo "skipped (--no-submit)"
elif [ -n "$SUBMISSION" ]; then
  if [ -n "$SERVER" ]; then
    if ! "$PYTHON" tools/preflight.py "$SUBMISSION" --data "$DATA" --server "$SERVER" --dry-run; then
      FAILED=1
    fi
  else
    if ! "$PYTHON" tools/preflight.py "$SUBMISSION" --data "$DATA"; then
      FAILED=1
    fi
  fi
else
  echo "skipped (no --submission given; step 3/4 already ran the pipeline)"
fi

echo
if [ "$FAILED" -ne 0 ]; then
  echo "CI FAILED for $WAVE"
  exit 1
fi
echo "CI PASSED for $WAVE"
