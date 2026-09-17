"""Schedule engine: day-of-week aware fetch window calculator.

Monday  → 3-day backfill (Fri/Sat/Sun weekend catch-up) + weekly digest trigger
          (the weekly roundup now lands on Monday: Friday is LinkedIn-only)
Tue-Thu → 24-hour incremental
Friday  → LinkedIn hiring-feed ONLY ("we are hiring" feed posts; see spec) —
          the one day we do NOT sweep the other sources
Sat-Sun → idle (no scrape)
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from src.log import get_logger

log = get_logger(__name__)


FREQ_IDLE       = "idle"
FREQ_BACKFILL   = "backfill"
FREQ_DAILY      = "daily"
FREQ_WEEKLY     = "weekly"


@dataclass
class FetchWindow:
    reason: str
    window_start: datetime
    window_end: datetime
    generate_digest: bool
    window_label: str
    day_of_week: int
    # Subset of sources to run this window. None = all enabled sources.
    sources: list[str] | None = None

    def is_idle(self) -> bool:
        return self.reason == FREQ_IDLE

    def to_dict(self) -> dict[str, Any]:
        return {
            "reason": self.reason,
            "window_start": self.window_start.isoformat(timespec="seconds"),
            "window_end": self.window_end.isoformat(timespec="seconds"),
            "generate_digest": self.generate_digest,
            "window_label": self.window_label,
        }


# Friday is the spec'd "LinkedIn hiring-feed day": NO other source sweeps.
FRIDAY_SOURCES = ["linkedin"]

_DAY_LABELS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _get_tz() -> ZoneInfo:
    raw = os.environ.get("SCRAPE_TZ", "UTC")
    try:
        return ZoneInfo(raw)
    except Exception:
        log.warning("bad SCRAPE_TZ=%r, falling back to UTC", raw)
        return ZoneInfo("UTC")


def compute_fetch_window(now: datetime | None = None) -> FetchWindow:
    tz = _get_tz()
    now = now or datetime.now(tz)
    if now.tzinfo is None:
        now = now.replace(tzinfo=tz)
    now = now.astimezone(tz)
    day = now.weekday()
    window_end = now

    match day:
        case 0:
            # Monday: 3-day weekend catch-up for ALL sources (Fri/Sat/Sun) AND
            # the weekly digest trigger. Friday is now LinkedIn-only, so the
            # cross-source weekly roundup/notify (Telegram/WhatsApp/LinkedIn
            # posting) lands here on Monday morning instead.
            return FetchWindow(
                reason=FREQ_BACKFILL,
                window_start=window_end - timedelta(days=3),
                window_end=window_end,
                generate_digest=True,
                window_label=f"{_DAY_LABELS[day]} backfill (3 days, weekend catch-up) + weekly digest",
                day_of_week=day,
            )
        case d if 1 <= d <= 3:
            return FetchWindow(
                reason=FREQ_DAILY,
                window_start=window_end - timedelta(hours=24),
                window_end=window_end,
                generate_digest=False,
                window_label=f"{_DAY_LABELS[day]} daily",
                day_of_week=day,
            )
        case 4:
            # Friday: the user's spec is "scrape and fetch posts directly from
            # the LinkedIn feed containing 'we are hiring' keywords/scenes".
            # No other source sweeps on Friday — Monday's 3-day backfill picks
            # up any Fri/Sat/Sun stragglers. Feed posts are DE-duplicated by
            # URL and TTL, so the 7-day window is harmless re-scrape padding.
            return FetchWindow(
                reason=FREQ_WEEKLY,
                window_start=window_end - timedelta(days=7),
                window_end=window_end,
                generate_digest=False,
                window_label=f"{_DAY_LABELS[day]} — LinkedIn hiring-feed scrape",
                day_of_week=day,
                sources=FRIDAY_SOURCES,
            )
        case _:
            return FetchWindow(
                reason=FREQ_IDLE,
                window_start=window_end,
                window_end=window_end,
                generate_digest=False,
                window_label=f"{_DAY_LABELS[day]} idle",
                day_of_week=day,
            )


def check_last_run_freshness(state_last_run: str | None, window: FetchWindow) -> str:
    """Return a status message if the last run is too old or suspiciously recent."""
    if not state_last_run:
        return "[schedule] first run detected"
    try:
        last = datetime.fromisoformat(state_last_run)
    except ValueError:
        return "[schedule] last_run is malformed — proceeding as fresh run"
    now = datetime.now(ZoneInfo("UTC"))
    if last.tzinfo is None:
        last = last.replace(tzinfo=ZoneInfo("UTC"))
    gap_hours = (now - last).total_seconds() / 3600
    if gap_hours < 1 and window.reason != FREQ_IDLE:
        return f"[schedule] last run was {gap_hours:.1f}h ago — re-scraping anyway"
    if gap_hours > 72 and window.reason == FREQ_DAILY:
        return f"[schedule] last run was {gap_hours:.1f}h ago — large catch-up expected"
    return f"[schedule] last run {gap_hours:.1f}h ago — OK"


def next_fetch_start(now: datetime | None = None, tz: ZoneInfo | None = None, run_hour: int | None = None) -> datetime:
    """Start of the next non-idle fetch window (weekday run_hour local).

    Matches the daily schedule rule: Sat/Sun are idle in the spec,
    so the next window is the next Mon-Fri at run_hour (configurable via SCRAPE_RUN_HOUR,
    defaulting to 9; use SCRAPE_RUN_HOUR=8 for 08:00 PKT local crontab alignment).
    The self-scheduling daemon (`python -m src.main --serve`) sleeps until this time.
    """
    tz = tz or _get_tz()
    now = now or datetime.now(tz)
    if now.tzinfo is None:
        now = now.replace(tzinfo=tz)
    now = now.astimezone(tz)
    if run_hour is None:
        raw_hour = os.environ.get("SCRAPE_RUN_HOUR")
        run_hour = int(raw_hour) if raw_hour is not None else 9
    candidate = now.replace(hour=run_hour, minute=0, second=0, microsecond=0)
    if now >= candidate:
        candidate += timedelta(days=1)
    while candidate.weekday() >= 5:  # Saturday=5, Sunday=6 → idle, skip
        candidate += timedelta(days=1)
    return candidate