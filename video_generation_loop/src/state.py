"""Topic queue + day state management (resume-safe, atomic writes, cross-process lock)."""
from __future__ import annotations

import fcntl
import json
import os
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_MAX_ATTEMPTS = 3  # per clip; escalation beyond this (AGENTS-style) is a hard stop
STATE_SCHEMA_VERSION = 1  # bump when the .slc/state.json shape breaks old builds


class LockTimeoutError(TimeoutError):
    """Raised when a cross-process lock cannot be acquired in time."""


# Process-local registry: resolved lock path -> (fd, reentry count).
# flock() is associated with the open file description, so a *second* open() of
# the same path inside the SAME process would block on our own kernel lock.
# The registry makes FileLock reentrant within a process (a nested `with` on the
# same path increments the count and does not re-flock). Cross-process exclusion
# is still enforced by the kernel flock().
_HELD_LOCKS: dict[str, tuple[int, int]] = {}
_HELD_LOCKS_GUARD = threading.Lock()


class FileLock:
    """Advisory cross-process lock (POSIX flock) with in-process reentrancy.

    Usage::

        with FileLock(path, timeout_s=5):
            ...  # critical section exclusive across processes AND threads

    - The lock file persists (an empty sibling `.lock`) — flock() state lives in
      the kernel, so a crashed holder releases automatically; there is never a
      stale lock to clean.
    - Same-process reentrant `with` blocks share the held lock (counted), so
      e.g. a day-boundary lock can safely wrap `state.save()`.
    """

    def __init__(self, path: Path | str, timeout_s: float = 5.0) -> None:
        self._path = Path(path)
        self._timeout_s = timeout_s
        self._key = str(self._path.resolve())
        self._opened_fd: int | None = None
        self._entered = False

    def __enter__(self) -> "FileLock":
        with _HELD_LOCKS_GUARD:
            existing = _HELD_LOCKS.get(self._key)
            if existing is not None:
                _HELD_LOCKS[self._key] = (existing[0], existing[1] + 1)
                self._entered = True
                return self
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(self._path), os.O_CREAT | os.O_RDWR, 0o600)
        deadline = time.monotonic() + self._timeout_s
        try:
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() > deadline:
                        raise LockTimeoutError(
                            f"could not acquire lock {self._path} within {self._timeout_s}s"
                        ) from None
                    time.sleep(0.05)
        except BaseException:
            os.close(fd)
            raise
        with _HELD_LOCKS_GUARD:
            _HELD_LOCKS[self._key] = (fd, 1)
        self._opened_fd = fd
        self._entered = True
        return self

    def __exit__(self, *exc) -> None:
        if not self._entered:
            return
        self._entered = False
        with _HELD_LOCKS_GUARD:
            entry = _HELD_LOCKS.get(self._key)
            if entry is None:
                return
            fd, count = entry
            if count > 1:
                _HELD_LOCKS[self._key] = (fd, count - 1)
                return
            del _HELD_LOCKS[self._key]
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def lock_path_for(path: Path) -> Path:
    """Sibling `.lock` file for FILE_PATH (flock is advisory, so the lock file is
    just a rendezvous point; it never holds the actual lock)."""
    return path.with_name(path.name + ".lock")


@dataclass
class Topic:
    id: str
    title: str
    takeaway: str
    status: str = "pending"

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Topic":
        return cls(
            id=str(d.get("id", "")),
            title=str(d.get("title", "")),
            takeaway=str(d.get("takeaway", "")),
            status=str(d.get("status", "pending")),
        )


def load_topics(path: Path | None = None) -> list[Topic]:
    path = path or (Path(__file__).resolve().parent.parent / "course" / "topics.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    topics = [Topic.from_dict(item) for item in data]
    if not topics:
        raise ValueError("topics.json is empty")
    return topics


@dataclass
class DayState:
    day: int
    topic_id: str | None
    topic_title: str | None
    status: str  # in_progress | done | failed
    attempts: int = 0
    completed_clips: list[str] = field(default_factory=list)
    # Per-clip failure ledger: clip_name -> failed attempts. Durable across a
    # crash, so a clip that already burned its budget is never silently
    # re-generated after a resume (money-safety: every retry costs credits).
    clip_attempts: dict[str, int] = field(default_factory=dict)
    final_video: str | None = None
    error: str | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "DayState":
        return cls(
            day=int(d.get("day", 0)),
            topic_id=d.get("topic_id"),
            topic_title=d.get("topic_title"),
            status=str(d.get("status", "in_progress")),
            attempts=int(d.get("attempts", 0)),
            completed_clips=list(d.get("completed_clips", [])),
            clip_attempts=_coerce_clip_attempts(d.get("clip_attempts")),
            final_video=d.get("final_video"),
            error=d.get("error"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "day": self.day,
            "topic_id": self.topic_id,
            "topic_title": self.topic_title,
            "status": self.status,
            "attempts": self.attempts,
            "completed_clips": self.completed_clips,
            "clip_attempts": self.clip_attempts,
            "final_video": self.final_video,
            "error": self.error,
        }

    def clip_failed(self, clip_name: str) -> int:
        """Record one failed attempt for a clip; returns its NEW attempt count.

        `attempts` is kept as the day-level total (legacy durable gate);
        `clip_attempts[name]` is the per-clip ledger a resume uses to never
        re-burn an already-capped clip."""
        self.clip_attempts[clip_name] = self.clip_attempts.get(clip_name, 0) + 1
        self.attempts += 1
        return self.clip_attempts[clip_name]

    def clip_succeeded(self, clip_name: str) -> None:
        """A clip completed; clear its per-clip entry (fresh budget next time)."""
        self.clip_attempts.pop(clip_name, None)


def _quarantine_corrupt(path: Path, reason: str) -> None:
    """Never die forever on a corrupt state file: quarantine + start fresh."""
    import datetime

    backup = path.with_name(f"state.corrupt-{datetime.datetime.now():%Y%m%d-%H%M%S}.json")
    try:
        path.rename(backup)
        print(f"[state] corrupt state quarantined -> {backup} ({reason})")
    except OSError:
        print(f"[state] corrupt state at {path} ({reason}); starting fresh")


def _coerce_clip_attempts(value: Any) -> dict[str, int]:
    """Garbage-tolerant parse of the per-clip ledger (bad rows dropped)."""
    out: dict[str, int] = {}
    if not isinstance(value, dict):
        return out
    for k, v in value.items():
        try:
            out[str(k)] = int(v)
        except (TypeError, ValueError):
            continue
    return out


class LoopState:
    """Loads/saves .slc/state.json atomically."""

    def __init__(
        self,
        path: Path | None = None,
        topics: list[Topic] | None = None,
    ) -> None:
        self.path = path or (Path(__file__).resolve().parent.parent / ".slc" / "state.json")
        self.lock_path = lock_path_for(self.path)
        self.topics = topics if topics is not None else load_topics()
        self.current_day: int = 1
        self.days: dict[int, DayState] = {}
        self.done_topic_ids: list[str] = []
        self.blocked_topic_ids: list[str] = []
        self._load()

    def locked(self, timeout_s: float = 5.0) -> FileLock:
        """Cross-process exclusion for the whole state file.

        Hold this across an entire generation/upload run (NOT just one save):
        it is the guarantee that two `python -m src.main` processes never both
        claim or generate for the same day. Reentrant — callers may `state.save()`
        freely while holding it.
        """
        return FileLock(self.lock_path, timeout_s=timeout_s)

    def reload(self) -> None:
        """Re-read the on-disk state (call while holding `locked()`).

        The constructor snapshots state before the caller acquires the lock, so
        a concurrent process's writes would otherwise be invisible. After
        acquiring the run lock, reload to make decisions from a fresh view."""
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            # never die forever on a corrupt state file: quarantine + start fresh
            _quarantine_corrupt(self.path, str(exc))
            return
        try:
            schema = int(raw.get("schema_version", 1))
        except (TypeError, ValueError):
            # state parses as JSON but the version field is garbage — same
            # handling as corrupt JSON (quarantine, never spin on it)
            _quarantine_corrupt(self.path, f"non-integer schema_version: {raw.get('schema_version')!r}")
            return
        if schema > STATE_SCHEMA_VERSION:
            raise SystemExit(
                f"[state] {self.path} is schema v{schema}, but this build only "
                f"reads v{STATE_SCHEMA_VERSION}. Refusing to continue — the state "
                "file was written by a NEWER build; downgrade the tool or restore "
                "an older state file."
            )
        self.current_day = int(raw.get("current_day", 1))
        self.days = {
            int(k): DayState.from_dict(v) for k, v in raw.get("days", {}).items()
        }
        self.done_topic_ids = list(raw.get("done_topic_ids", []))
        self.blocked_topic_ids = list(raw.get("blocked_topic_ids", []))

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": STATE_SCHEMA_VERSION,
            "current_day": self.current_day,
            "done_topic_ids": self.done_topic_ids,
            "blocked_topic_ids": self.blocked_topic_ids,
            "days": {str(k): v.to_dict() for k, v in self.days.items()},
        }
        # atomic write: temp file + rename
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    # --- topic selection ---
    def pick_next_topic(self) -> Topic | None:
        """First pending topic not done, not in-progress, not blocked, and not a
        day that already exhausted its retry budget. A topic whose day FAILED with
        attempts below the cap stays retryable (transient failure); one that hit
        the cap is permanently skipped until a human force-picks it."""
        busy = {
            d.topic_id
            for d in self.days.values()
            if d.topic_id is not None and d.status in ("in_progress", "done")
        }
        burned = {
            d.topic_id
            for d in self.days.values()
            if d.topic_id is not None
            and d.status == "failed"
            and d.attempts >= DEFAULT_MAX_ATTEMPTS
        }
        for t in self.topics:
            if t.id in self.done_topic_ids:
                continue
            if t.id in self.blocked_topic_ids or t.id in burned:
                continue
            if t.id in busy:
                continue
            return t
        return None

    def block_topic(self, topic_id: str) -> None:
        """Durably remove a topic from the auto-queue (human un-blocks via --topic)."""
        if topic_id and topic_id not in self.blocked_topic_ids:
            self.blocked_topic_ids.append(topic_id)

    # --- day lifecycle ---
    def start_day(self, topic: Topic) -> DayState:
        self.current_day += 1
        ds = DayState(
            day=self.current_day,
            topic_id=topic.id,
            topic_title=topic.title,
            status="in_progress",
        )
        self.days[self.current_day] = ds
        return ds

    def resume_in_progress(self) -> DayState | None:
        for ds in self.days.values():
            if ds.status == "in_progress":
                return ds
        return None

    def mark_clip_done(self, day: DayState, clip_name: str) -> None:
        if clip_name not in day.completed_clips:
            day.completed_clips.append(clip_name)

    def finish_day(self, day: DayState, *, ok: bool, error: str | None = None) -> None:
        if ok:
            day.status = "done"
            if day.topic_id and day.topic_id not in self.done_topic_ids:
                self.done_topic_ids.append(day.topic_id)
        else:
            day.status = "failed"
            day.error = error
        self.save()