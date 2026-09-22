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
LAST_RUN_STAMP="$LOCK_DIR/.last_cron_run"
PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python3"

mkdir -p "$LOCK_DIR"

if [[ ! -x "$PYTHON_BIN" ]]; then
    PYTHON_BIN="python3"
fi

# Log rotation: rotate if log file exceeds 5MB
if [[ -f "$LOG_FILE" ]] && [[ $(stat -c%s "$LOG_FILE" 2>/dev/null || stat -f%z "$LOG_FILE" 2>/dev/null || echo 0) -gt 5242880 ]]; then
    mv -f "$LOG_FILE" "${LOG_FILE}.1"
fi

# Boot-time catch-up: if today's 08:00 run was missed (system was off), fire now
_catch_up_if_missed() {
    local today
    today=$(TZ=Asia/Karachi date +%Y-%m-%d)
    if [[ -f "$LAST_RUN_STAMP" ]]; then
        local last_date
        last_date=$(cat "$LAST_RUN_STAMP" 2>/dev/null || echo "")
        if [[ "$last_date" == "$today" ]]; then
            return 0  # already ran today
        fi
    fi
    # Check if current time is past 08:15 PKT (allow 15min buffer for normal run)
    local now_hour now_min
    now_hour=$(TZ=Asia/Karachi date +%H)
    now_min=$(TZ=Asia/Karachi date +%M)
    local now_minutes=$((10#$now_hour * 60 + 10#$now_min))
    if [[ $now_minutes -ge 495 ]]; then  # 08:15 = 495 min
        echo "=== [$(date -u +"%Y-%m-%dT%H:%M:%SZ")] CATCH-UP: today's 08:00 run was missed, firing now ===" >> "$LOG_FILE"
        return 1  # signal: run now
    fi
    return 0  # not yet past 08:15, skip
}
CATCHUP_NEEDED=false
if ! _catch_up_if_missed; then
    CATCHUP_NEEDED=true
fi

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    echo "=== [$(date -u +"%Y-%m-%dT%H:%M:%SZ")] skip: another local run holds cron.lock ===" >> "$LOG_FILE"
    exit 0
fi

export PYTHONPATH="${PYTHONPATH:-.}"
export DISPLAY="${DISPLAY:-:0}"
if [[ -n "${XDG_RUNTIME_DIR:-}" ]] && [[ -f "$XDG_RUNTIME_DIR/wayland-0" ]]; then
    export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}"
fi
# If running without an active X server / GUI session, run browser scrapers headless so Playwright doesn't fail
if ! (command -v xset >/dev/null 2>&1 && xset q >/dev/null 2>&1); then
    export BOARD_HEADLESS="${BOARD_HEADLESS:-1}"
fi

echo "=== [$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Starting local job loop pass (catchup=$CATCHUP_NEEDED) ===" >> "$LOG_FILE"
set +e
"$PYTHON_BIN" -m src.main >> "$LOG_FILE" 2>&1
EXIT_CODE=$?
set -e
echo "=== [$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Pass finished with exit code: $EXIT_CODE ===" >> "$LOG_FILE"

# Record today's date so catch-up knows we ran
TZ=Asia/Karachi date +%Y-%m-%d > "$LAST_RUN_STAMP"

exit $EXIT_CODE
