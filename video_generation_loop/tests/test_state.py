"""Tests for state management."""
from __future__ import annotations

import json
import multiprocessing
import time
from pathlib import Path

import pytest

from src.state import (
    DayState,
    FileLock,
    LockTimeoutError,
    LoopState,
    Topic,
    lock_path_for,
)


def _topics():
    return [
        Topic("t1", "Alpha", "a"),
        Topic("t2", "Beta", "b"),
        Topic("t3", "Gamma", "c"),
    ]


def test_pick_next_topic_returns_first_pending(tmp_path):
    s = LoopState(path=tmp_path / "state.json", topics=_topics())
    assert s.pick_next_topic().id == "t1"


def test_pick_next_topic_skips_done_and_in_progress(tmp_path):
    s = LoopState(path=tmp_path / "state.json", topics=_topics())
    s.done_topic_ids.append("t1")
    s.days[2] = DayState(day=2, topic_id="t2", topic_title="Beta", status="in_progress")
    assert s.pick_next_topic().id == "t3"


def test_pick_next_topic_retries_failed_day(tmp_path):
    s = LoopState(path=tmp_path / "state.json", topics=_topics())
    s.days[2] = DayState(day=2, topic_id="t2", topic_title="Beta", status="failed")
    # failed topics are retryable
    assert s.pick_next_topic().id == "t1"


def test_failed_budget_exhausted_topic_not_repicked(tmp_path):
    # a day that failed WITH its retry budget burned (attempts at cap) but was
    # never explicitly blocked (e.g. crash window + --fresh) must not auto-re-pick
    s = LoopState(path=tmp_path / "state.json", topics=_topics())
    s.days[2] = DayState(
        day=2, topic_id="t2", topic_title="Beta", status="failed", attempts=3
    )
    s.save()
    s2 = LoopState(path=tmp_path / "state.json", topics=_topics())
    assert "t2" not in s2.blocked_topic_ids  # not explicitly blocked
    assert s2.pick_next_topic().id == "t1"  # budget-burn alone is sufficient


def test_save_and_reload_roundtrip(tmp_path):
    path = tmp_path / "state.json"
    s = LoopState(path=path, topics=_topics())
    topic = s.pick_next_topic()
    ds = s.start_day(topic)
    s.mark_clip_done(ds, "clip_01.mp4")
    s.finish_day(ds, ok=True)
    assert path.exists()

    s2 = LoopState(path=path, topics=_topics())
    assert s2.current_day == 2
    assert s2.done_topic_ids == ["t1"]
    assert s2.days[2].completed_clips == ["clip_01.mp4"]
    assert s2.days[2].status == "done"


def test_resume_in_progress(tmp_path):
    s = LoopState(path=tmp_path / "state.json", topics=_topics())
    s.days[2] = DayState(day=2, topic_id="t2", topic_title="Beta", status="in_progress")
    s.save()
    s2 = LoopState(path=tmp_path / "state.json", topics=_topics())
    ds = s2.resume_in_progress()
    assert ds is not None and ds.topic_id == "t2"


def test_atomic_save_no_tmp_left(tmp_path):
    s = LoopState(path=tmp_path / "state.json", topics=_topics())
    ds = s.start_day(s.pick_next_topic())
    s.finish_day(ds, ok=True)
    leftovers = [f for f in tmp_path.iterdir() if f.suffix == ".tmp"]
    assert leftovers == []


def test_save_is_atomic_under_dict(tmp_path):
    # ensure save() is invoked via finish_day and file is valid JSON at all times
    s = LoopState(path=tmp_path / "state.json", topics=_topics())
    ds = s.start_day(s.pick_next_topic())
    s.finish_day(ds, ok=False, error="boom")
    raw = json.loads(tmp_path.joinpath("state.json").read_text())
    assert raw["days"]["2"]["status"] == "failed"
    assert raw["days"]["2"]["error"] == "boom"


def test_blocked_topic_not_repicked(tmp_path):
    s = LoopState(path=tmp_path / "state.json", topics=_topics())
    s.block_topic("t1")
    s.save()
    s2 = LoopState(path=tmp_path / "state.json", topics=_topics())
    assert s2.pick_next_topic().id == "t2"
    assert "t1" in s2.blocked_topic_ids


def test_block_roundtrips(tmp_path):
    path = tmp_path / "state.json"
    s = LoopState(path=path, topics=_topics())
    s.days[2] = DayState(day=2, topic_id="t2", topic_title="Beta", status="failed", attempts=3)
    s.block_topic("t2")
    s.save()
    s2 = LoopState(path=path, topics=_topics())
    assert s2.pick_next_topic().id == "t1"
    assert "t2" in s2.blocked_topic_ids


def test_corrupt_state_is_quarantined(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{\"broken\": ", encoding="utf-8")  # invalid JSON
    s = LoopState(path=path, topics=_topics())
    assert s.current_day == 1  # fresh start, no crash
    # corrupt file was renamed aside
    bad = [f for f in tmp_path.iterdir() if f.name.startswith("state.corrupt-")]
    assert len(bad) == 1
    # and a valid state can be saved afterwards
    ds = s.start_day(s.pick_next_topic())
    s.finish_day(ds, ok=True)
    json.loads(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- locking

def test_lock_path_is_sibling():
    assert lock_path_for(Path("/x/state.json")) == Path("/x/state.json.lock")


def test_filelock_reentrant_same_process(tmp_path):
    p = tmp_path / "s.lock"
    with FileLock(p, timeout_s=2):
        with FileLock(p, timeout_s=0.1):  # nested same-process: no deadlock, no raise
            pass
    # fully released: a fresh timed acquire succeeds immediately
    with FileLock(p, timeout_s=0.1):
        pass
    # and the lock file (rendezvous point) exists but holds no kernel lock
    assert p.exists()


def _hold_lock(path, q, seconds):
    with FileLock(path, timeout_s=10):
        q.put("held")
        time.sleep(seconds)
        q.put("released")


def test_filelock_excludes_other_process(tmp_path):
    p = tmp_path / "s.lock"
    q = multiprocessing.get_context("fork").Queue()
    proc = multiprocessing.get_context("fork").Process(
        target=_hold_lock, args=(p, q, 0.6)
    )
    proc.start()
    try:
        assert q.get(timeout=5) == "held"
        with pytest.raises(LockTimeoutError):
            with FileLock(p, timeout_s=0.15):
                pass  # parent must NOT be able to acquire while child holds
        assert q.get(timeout=5) == "released"
        # after the child releases, the parent can acquire
        with FileLock(p, timeout_s=0.15):
            pass
    finally:
        proc.join(10)
    assert proc.exitcode == 0


def _write_day_under_lock(path, day, topic_id, title, q):
    s = LoopState(path=path, topics=_topics())
    s.days[day] = DayState(day=day, topic_id=topic_id, topic_title=title, status="in_progress")
    with s.locked(timeout_s=10):
        s.save()
    q.put("done")


def test_locked_reload_sees_other_process_write(tmp_path):
    path = tmp_path / "state.json"
    s = LoopState(path=path, topics=_topics())
    assert 41 not in s.days  # our (stale) instance predates the write

    q = multiprocessing.get_context("fork").Queue()
    proc = multiprocessing.get_context("fork").Process(
        target=_write_day_under_lock, args=(path, 41, "tX", "X", q)
    )
    proc.start()
    assert q.get(timeout=10) == "done"
    proc.join(10)
    assert proc.exitcode == 0

    # after acquiring the run lock + reloading, the concurrent write is visible
    with s.locked(timeout_s=5):
        s.reload()
    assert 41 in s.days
    assert s.days[41].status == "in_progress"


def _increment_attempts(path, rounds):
    s = LoopState(path=path, topics=_topics())
    for _ in range(rounds):
        with s.locked(timeout_s=15):  # lock + reload = atomic read-modify-write
            s.reload()
            ds = s.days.get(
                2,
                DayState(day=2, topic_id="t2", topic_title="Beta", status="in_progress"),
            )
            s.days[2] = ds
            ds.attempts += 1
            s.save()


def test_concurrent_rmw_writers_lose_nothing(tmp_path):
    path = tmp_path / "state.json"
    ctx = multiprocessing.get_context("fork")
    procs = [ctx.Process(target=_increment_attempts, args=(path, 3)) for _ in range(2)]
    for p in procs:
        p.start()
    for p in procs:
        p.join(20)
    assert all(p.exitcode == 0 for p in procs)

    # both writers' increments survived (3+3) and the file is valid JSON
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["days"]["2"]["attempts"] == 6


# --- schema_version + per-clip attempt ledger (Beat 4) -------------------------
def test_save_writes_schema_version(tmp_path):
    s = LoopState(path=tmp_path / "state.json", topics=_topics())
    s.save()
    raw = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert raw["schema_version"] == 1


def test_load_accepts_missing_or_equal_schema(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"current_day": 3, "days": {}}))  # legacy: no key
    assert LoopState(path=path, topics=_topics()).current_day == 3
    path.write_text(json.dumps({"schema_version": 1, "current_day": 4, "days": {}}))
    assert LoopState(path=path, topics=_topics()).current_day == 4


def test_load_rejects_newer_schema(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"schema_version": 999, "current_day": 4, "days": {}}))
    with pytest.raises(SystemExit):
        LoopState(path=path, topics=_topics())


def test_load_quarantines_noninteger_schema(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"schema_version": "abc", "current_day": 4, "days": {}}))
    s = LoopState(path=path, topics=_topics())  # no SystemExit, no infinite spin
    assert s.current_day == 1  # fresh state
    assert not path.exists()  # quarantined, not left to traceback forever
    assert list(tmp_path.glob("state.corrupt-*.json"))


def test_daystate_clip_failed_and_succeeded(tmp_path):
    d = DayState(day=9, topic_id="t1", topic_title="T", status="in_progress")
    assert d.clip_failed("clip_01.mp4") == 1
    assert d.clip_failed("clip_01.mp4") == 2
    assert d.attempts == 2  # day-level total kept in sync
    d.clip_succeeded("clip_01.mp4")
    assert "clip_01.mp4" not in d.clip_attempts
    d.clip_failed("clip_02.mp4")
    assert d.clip_attempts == {"clip_02.mp4": 1}


def test_daystate_clip_attempts_roundtrip(tmp_path):
    s = LoopState(path=tmp_path / "state.json", topics=_topics())
    s.days[9] = DayState(
        day=9,
        topic_id="t1",
        topic_title="T",
        status="in_progress",
        attempts=5,
        clip_attempts={"clip_01.mp4": 3},
    )
    s.save()
    s2 = LoopState(path=tmp_path / "state.json", topics=_topics())
    assert s2.days[9].clip_attempts == {"clip_01.mp4": 3}
    assert s2.days[9].attempts == 5


def test_daystate_garbage_clip_attempts_dropped(tmp_path):
    s = LoopState(path=tmp_path / "state.json", topics=_topics())
    s.days[9] = DayState(day=9, topic_id="t1", topic_title="T", status="in_progress")
    s.days[9].clip_attempts = {"c1": "abc", "c2": 3, "c3": 3.9, "c4": None}
    s.save()
    s2 = LoopState(path=tmp_path / "state.json", topics=_topics())
    assert s2.days[9].clip_attempts == {"c2": 3, "c3": 3}