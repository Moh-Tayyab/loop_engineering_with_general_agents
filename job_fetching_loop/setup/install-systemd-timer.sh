#!/usr/bin/env bash
# ==============================================================================
# Install systemd timer for the job fetching loop.
# Run once with sudo: sudo bash setup/install-systemd-timer.sh
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_FILE="$SCRIPT_DIR/job-fetching-loop.service"
TIMER_FILE="$SCRIPT_DIR/job-fetching-loop.timer"

echo "[1/5] Copying service file..."
cp "$SERVICE_FILE" /etc/systemd/system/job-fetching-loop.service

echo "[2/5] Copying timer file..."
cp "$TIMER_FILE" /etc/systemd/system/job-fetching-loop.timer

echo "[3/5] Removing old cron entry (if exists)..."
# Remove the job_fetching_loop cron entry from current user's crontab
crontab -l 2>/dev/null | grep -v "job_fetching_loop/run_loop.sh" | crontab - 2>/dev/null || true
echo "  -> Old cron entry removed."

echo "[4/5] Reloading systemd daemon..."
systemctl daemon-reload

echo "[5/5] Enabling and starting timer..."
systemctl enable --now job-fetching-loop.timer

echo ""
echo "=== Timer installed and started ==="
echo ""
echo "Verify:"
echo "  systemctl status job-fetching-loop.timer"
echo "  systemctl list-timers job-fetching-loop.timer"
echo ""
echo "Manual run:"
echo "  systemctl start job-fetching-loop.service"
echo ""
echo "Logs:"
echo "  journalctl -u job-fetching-loop.service -f"
echo "  tail -f $(dirname "$SCRIPT_DIR")/loop.log"
