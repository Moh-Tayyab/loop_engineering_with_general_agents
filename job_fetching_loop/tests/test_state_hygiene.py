"""Tests for state hygiene: SeenStore TTL eviction, LoopState weekly reset,
and atomic save helpers."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from src.state import FileLock, LoopState, SeenStore, atomic_write_text, lock_holder


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


# ── FileLock watchdog sidecar (P2: starved run vs hung holder) ───────────────

def test_lock_writes_and_clears_holder_sidecar(tmp_path):
    """Acquiring the lock writes a {pid, acquired_at} sidecar; releasing the
    last holder clears it — a starved run can read who holds the lock."""
    lock_path = tmp_path / "state.json"
    holder_path = tmp_path / "state.json.holder"
    with FileLock(lock_path):
        assert holder_path.exists()
        holder = json.loads(holder_path.read_text(encoding="utf-8"))
        assert holder["pid"] > 0
        from datetime import datetime as _dt
        _dt.fromisoformat(holder["acquired_at"])  # parses → valid ISO timestamp
        assert lock_holder(lock_path) == holder
    assert not holder_path.exists()
    assert lock_holder(lock_path) is None


def test_lock_holder_none_when_absent(tmp_path):
    assert lock_holder(tmp_path / "missing.json") is None


def test_lock_holder_survives_abrupt_crash(tmp_path):
    """A killed process (SIGKILL) can't clear the sidecar — that's the point:
    the stale marker keeps a hung holder detectable after flock released."""
    lock_path = tmp_path / "state.json"
    holder_path = tmp_path / "state.json.holder"
    holder_path.write_text('{"pid": 99999, "acquired_at": "2026-09-01T00:00:00+00:00"}',
                           encoding="utf-8")
    holder = lock_holder(lock_path)
    assert holder is not None
    assert holder["pid"] == 99999


# ── weekly digest delivery tracking (retry until every channel confirms) ─────

def test_weekly_delivered_kinds_defaults_and_prunes(tmp_slc):
    state = LoopState()
    assert state.weekly_delivered_kinds("2026-W38") == set()
    state.mark_weekly_delivered("2026-W38", ["telegram", "whatsapp"])
    assert state.weekly_delivered_kinds("2026-W38") == {"telegram", "whatsapp"}
    # a new week's first mark replaces the old week — no unbounded growth
    state.mark_weekly_delivered("2026-W39", ["telegram"])
    assert state.weekly_delivered_kinds("2026-W38") == set()
    assert state.weekly_delivered_kinds("2026-W39") == {"telegram"}


def test_concurrent_filelock_cross_process(tmp_path):
    import subprocess
    import sys

    lock_file = tmp_path / "concurrent.lock"
    with FileLock(lock_file):
        cmd = [
            sys.executable,
            "-c",
            f"from src.state import FileLock; FileLock(r'{lock_file}', timeout_s=0.2).__enter__()",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        assert res.returncode != 0
        assert "LockTimeoutError" in res.stderr


def test_dead_letter_queue_peek_and_clear(tmp_slc):
    from src.state import DeadLetterQueue

    dlq = DeadLetterQueue()
    assert dlq.items == []
    assert dlq.peek() == []

    dlq.push({"source": "test_src_1", "error": "timeout", "timestamp": "2026-09-17T00:00:00Z"})
    dlq.push({"source": "test_src_2", "error": "conn_error", "timestamp": "2026-09-17T00:01:00Z"})
    dlq.save()

    reloaded = DeadLetterQueue()
    assert len(reloaded.items) == 2
    peeked = reloaded.peek(limit=1)
    assert len(peeked) == 1
    assert peeked[0]["source"] == "test_src_2"

    reloaded.clear()
    assert len(reloaded.items) == 0

    reloaded_again = DeadLetterQueue()
    assert len(reloaded_again.items) == 0