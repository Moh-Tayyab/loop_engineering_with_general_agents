#!/usr/bin/env bash
# ==============================================================================
# Autonomous Job Fetching Loop Runner
# Runs Monday-Friday according to schedule engine (handles lock + logs).
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

LOG_FILE="$SCRIPT_DIR/loop.log"
PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python3"

if [[ ! -x "$PYTHON_BIN" ]]; then
    PYTHON_BIN="python3"
fi

echo "=== [$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Starting Scheduled Job Loop Pass ===" >> "$LOG_FILE"
set +e
"$PYTHON_BIN" -m src.main >> "$LOG_FILE" 2>&1
EXIT_CODE=$?
set -e
echo "=== [$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Pass Finished with exit code: $EXIT_CODE ===" >> "$LOG_FILE"
exit $EXIT_CODE
