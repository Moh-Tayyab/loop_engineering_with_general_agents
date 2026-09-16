#!/usr/bin/env bash
# ==============================================================================
# Local Job Fetching Loop runner (cron / --serve accelerator).
# Cloud production uses .github/workflows/job-loop-cron.yml instead.
# If JOB_LOOP_PRIMARY=github in .env, src.main exits 0 without scraping.
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

LOG_FILE="$SCRIPT_DIR/loop.log"
LOCK_DIR="$SCRIPT_DIR/.slc"
LOCK_FILE="$LOCK_DIR/cron.lock"
PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python3"

mkdir -p "$LOCK_DIR"

if [[ ! -x "$PYTHON_BIN" ]]; then
    PYTHON_BIN="python3"
fi

# Log rotation: rotate if log file exceeds 5MB
if [[ -f "$LOG_FILE" ]] && [[ $(stat -c%s "$LOG_FILE" 2>/dev/null || stat -f%z "$LOG_FILE" 2>/dev/null || echo 0) -gt 5242880 ]]; then
    mv -f "$LOG_FILE" "${LOG_FILE}.1"
fi

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    echo "=== [$(date -u +"%Y-%m-%dT%H:%M:%SZ")] skip: another local run holds cron.lock ===" >> "$LOG_FILE"
    exit 0
fi

export PYTHONPATH="${PYTHONPATH:-.}"
echo "=== [$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Starting local job loop pass ===" >> "$LOG_FILE"
set +e
"$PYTHON_BIN" -m src.main >> "$LOG_FILE" 2>&1
EXIT_CODE=$?
set -e
echo "=== [$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Pass finished with exit code: $EXIT_CODE ===" >> "$LOG_FILE"
exit $EXIT_CODE
