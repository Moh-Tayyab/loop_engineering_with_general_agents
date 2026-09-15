"""Tests for state hygiene: SeenStore TTL eviction, LoopState weekly reset,
and atomic save helpers."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from src.state import LoopState, SeenStore, atomic_write_text


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def test_seen_store_expires_old_hashes(tmp_slc, monkeypatch):
    monkeypatch.setenv("DEDUP_WINDOW_DAYS", "30")
    today = _today()
    old = (datetime.now(timezone.utc).date() - timedelta(days=40)).isoformat()
    cfg_path = tmp_slc / ".slc" / "seen.json"
    cfg_path.write_text(json.dumps({
        "seen_hashes": ["old-hash", "fresh-hash"],
        "seen_until": {"old-hash": old, "fresh-hash": today},
        "recent_jobs": [
            {"id": "old-job", "fetched_at": old + "T00:00:00+00:00"},
            {"id": "fresh-job", "fetched_at": today + "T00:00:00+00:00"},
        ],
    }), encoding="utf-8")

    store = SeenStore()
    assert "old-hash" not in store.seen_hashes
    assert "fresh-hash" in store.seen_hashes
    recent_ids = [r["id"] for r in store.recent]
    assert "old-job" not in recent_ids
    assert "fresh-job" in recent_ids


def test_seen_store_legacy_data_without_until_survives(tmp_slc):
    """Old seen.json files (no seen_until) keep their hashes — no false
    duplicates were ever pruned by the migration."""
    cfg_path = tmp_slc / ".slc" / "seen.json"
    cfg_path.write_text(json.dumps({
        "seen_hashes": ["legacy-hash"],
        "recent_jobs": [{"id": "legacy-job"}],
    }), encoding="utf-8")

    store = SeenStore()
    assert "legacy-hash" in store.seen_hashes
    assert store.recent[0]["id"] == "legacy-job"


def test_loop_state_week_reset(tmp_slc):
    state = LoopState()
    state.add_jobs_this_week(10)
    state.ensure_week("2026-W37")
    assert state.jobs_this_week() == 0
    state.add_jobs_this_week(3)
    # same week: counter accumulates
    state.ensure_week("2026-W37")
    assert state.jobs_this_week() == 3
    # new week: resets again
    state.ensure_week("2026-W38")
    assert state.jobs_this_week() == 0


def test_mark_notified_keeps_other_notifier_keys(tmp_slc):
    """The previous cleanup wiped sibling keys — enabling two channels meant
    the second one was silently dropped."""
    state = LoopState()
    today = _today()
    yesterday = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
    state.state["notifications_sent_today"] = {
        "daily:TelegramNotifier": yesterday,
        "daily:WhatsAppNotifier": yesterday,
    }
    state.mark_notified("daily:PhoneNotifier", today)
    marked = state.state["notifications_sent_today"]
    # today's entry present, yesterday's stale entries pruned
    assert marked.get("daily:PhoneNotifier") == today
    assert "daily:TelegramNotifier" not in marked
    assert "daily:WhatsAppNotifier" not in marked


def test_atomic_write_text_survives_partial(tmp_path):
    p = tmp_path / "jobs.json"
    atomic_write_text(p, '["first"]')
    assert json.loads(p.read_text(encoding="utf-8")) == ["first"]
    atomic_write_text(p, '["second"]')
    assert json.loads(p.read_text(encoding="utf-8")) == ["second"]
    # no leftover temp files
    leftovers = [f.name for f in tmp_path.iterdir() if f.name.endswith(".tmp")]
    assert leftovers == []