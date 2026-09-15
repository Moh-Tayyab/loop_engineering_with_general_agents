"""Tests for the day-of-week schedule engine."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import src.config as cfg
from src.schedule import (
    FREQ_BACKFILL,
    FREQ_DAILY,
    FREQ_IDLE,
    FREQ_WEEKLY,
    FetchWindow,
    check_last_run_freshness,
    compute_fetch_window,
)


def _monday():
    return datetime(2026, 9, 14, 10, 0, tzinfo=timezone.utc)


def _tuesday():
    return datetime(2026, 9, 15, 10, 0, tzinfo=timezone.utc)


def _friday():
    return datetime(2026, 9, 18, 10, 0, tzinfo=timezone.utc)


def _saturday():
    return datetime(2026, 9, 19, 10, 0, tzinfo=timezone.utc)


def test_monday_backfill(monkeypatch):
    monkeypatch.setenv("SCRAPE_TZ", "UTC")
    w = compute_fetch_window(_monday())
    assert w.reason == FREQ_BACKFILL
    assert w.window_label.startswith("Monday")
    # Weekly digest moved here (Friday is now LinkedIn-feed-only)
    assert w.generate_digest
    assert w.sources is None  # all enabled sources run Mon-Thu


def test_monday_backfill_covers_weekend_three_days(monkeypatch):
    """Monday must re-fetch exactly the Fri/Sat/Sun weekend catch-up window —
    the user's spec: jobs posted Friday->Sunday are picked up on Monday."""
    monkeypatch.setenv("SCRAPE_TZ", "UTC")
    w = compute_fetch_window(_monday())
    assert w.window_end - w.window_start == timedelta(days=3)
    assert w.sources is None  # all sources sweep the weekend


def test_tuesday_daily(monkeypatch):
    monkeypatch.setenv("SCRAPE_TZ", "UTC")
    w = compute_fetch_window(_tuesday())
    assert w.reason == FREQ_DAILY
    assert w.sources is None  # Tue-Thu run all enabled sources


def test_thursday_daily(monkeypatch):
    monkeypatch.setenv("SCRAPE_TZ", "UTC")
    thursday = datetime(2026, 9, 17, 10, 0, tzinfo=timezone.utc)
    w = compute_fetch_window(thursday)
    assert w.reason == FREQ_DAILY


def test_friday_linkedin_feed_only(monkeypatch):
    """Friday is the spec'd 'LinkedIn hiring-feed scrape' day: LinkedIn only,
    no weekly digest (digest moved to Monday), 7-day window for feed padding."""
    monkeypatch.setenv("SCRAPE_TZ", "UTC")
    w = compute_fetch_window(_friday())
    assert w.reason == FREQ_WEEKLY
    assert not w.generate_digest
    assert w.sources == ["linkedin"]
    assert w.window_end - w.window_start == timedelta(days=7)


def test_weekend_idle(monkeypatch):
    monkeypatch.setenv("SCRAPE_TZ", "UTC")
    w = compute_fetch_window(_saturday())
    assert w.reason == FREQ_IDLE
    assert w.is_idle()


def test_window_is_utc_aware(monkeypatch):
    monkeypatch.setenv("SCRAPE_TZ", "UTC")
    w = compute_fetch_window(_tuesday())
    assert w.window_start.tzinfo is not None
    assert w.window_end.tzinfo is not None


def test_freshness_first_run():
    msg = check_last_run_freshness(None, FetchWindow(
        reason=FREQ_DAILY, window_start=datetime.now(timezone.utc),
        window_end=datetime.now(timezone.utc), generate_digest=False,
        window_label="x", day_of_week=1,
    ))
    assert "first run" in msg


def test_freshness_ok():
    from datetime import timedelta
    last = (datetime.now(timezone.utc) - timedelta(hours=20)).isoformat()
    msg = check_last_run_freshness(last, FetchWindow(
        reason=FREQ_DAILY, window_start=datetime.now(timezone.utc),
        window_end=datetime.now(timezone.utc), generate_digest=False,
        window_label="x", day_of_week=1,
    ))
    assert "OK" in msg


def test_freshness_stale():
    from datetime import timedelta
    last = (datetime.now(timezone.utc) - timedelta(hours=100)).isoformat()
    msg = check_last_run_freshness(last, FetchWindow(
        reason=FREQ_DAILY, window_start=datetime.now(timezone.utc),
        window_end=datetime.now(timezone.utc), generate_digest=False,
        window_label="x", day_of_week=1,
    ))
    assert "catch-up" in msg