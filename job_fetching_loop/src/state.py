"""Loop state: atomic, crash-safe JSON persistence with a reentrant file lock.

Reuses the proven FileLock + quarantine pattern from the video_generation_loop:
- atomic temp-file writes (never a torn file)
- POSIX flock() leadership election so two crons never double-scrape
- corrupt state quarantined, never a permanent hang
"""
from __future__ import annotations

import fcntl
import json
import os
import tempfile
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import src.config as cfg
from src.log import get_logger

log = get_logger(__name__)

STATE_SCHEMA_VERSION = 1


def _utc_today() -> date:
    """UTC date — the ONLY clock the dedup store may use.

    `date.today()` (local) drifts against `fetched_at` (UTC) in non-UTC timezones;
    the Beat 27 lesson says every user-facing/durability date string is UTC."""
    return datetime.now(timezone.utc).date()


class LockTimeoutError(TimeoutError):
    pass


_HELD_LOCKS: dict[str, tuple[int, int]] = {}
_HELD_LOCKS_GUARD = threading.Lock()


class FileLock:
    """Advisory cross-process lock (POSIX flock) with in-process reentrancy."""

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
    return path.with_name(path.name + ".lock")


def atomic_write_text(path: Path, text: str) -> None:
    """Atomically replace `path` with `text` (temp file + os.replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        tmp_path = Path(tmp)
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def atomic_write_json(path: Path, data: dict) -> None:
    atomic_write_text(path, json.dumps(data, indent=2, ensure_ascii=False))


def _load_json_quarantine(path: Path) -> dict[str, Any]:
    """Load a JSON state file; quarantine + return {} on corruption (never hang)."""
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("state must be a JSON object")
        return raw
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        backup = path.with_name(
            f"{path.stem}.corrupt-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}{path.suffix}"
        )
        try:
            path.rename(backup)
            log.warning("corrupt state quarantined -> %s (%s)", backup, exc)
        except OSError:
            log.warning("corrupt state at %s (%s); starting fresh", path, exc)
        return {}


class LoopState:
    """Durable loop state: schedule, per-source health, dedup, weekly counts.

    Single JSON file per concern keeps ownership clear:
      - STATE_PATH     -> run/schedule/source-health state
      - SEEN_PATH      -> seen job hashes + recent jobs (dedup)
      - DEAD_LETTER_PATH -> jobs/errors that exceeded retry
    """

    def __init__(self) -> None:
        self.path = cfg.STATE_PATH
        self.state: dict[str, Any] = {}
        self._load()

    def locked(self, timeout_s: float = 5.0) -> FileLock:
        return FileLock(lock_path_for(cfg.STATE_PATH), timeout_s=timeout_s)

    def _load(self) -> None:
        self.state = _load_json_quarantine(self.path)
        schema = self.state.get("schema_version", STATE_SCHEMA_VERSION)
        try:
            schema = int(schema)
        except (TypeError, ValueError):
            schema = -1
        if schema > STATE_SCHEMA_VERSION:
            raise SystemExit(
                f"[state] {self.path} is schema v{schema}, but this build reads "
                f"v{STATE_SCHEMA_VERSION}. Newer build wrote it — downgrade or restore."
            )
        self.state.setdefault("last_run", None)
        self.state.setdefault("last_fetch_window", None)
        self.state.setdefault("sources", {})
        self.state.setdefault("jobs_this_week", 0)
        self.state.setdefault("notifications_sent_today", {})
        self.state.setdefault("digest_generated_for", None)

    def save(self) -> None:
        self.state["schema_version"] = STATE_SCHEMA_VERSION
        atomic_write_json(self.path, self.state)

    def reload(self) -> None:
        """Re-read state from disk, picking up concurrent-process writes.

        Must be called under the state lock. Throws away in-memory mutations
        made by the current process since the last load/save — so always call
        it at the top of a guarded critical section, never mid-mutation."""
        self._load()

    # --- schedule ---
    def last_run(self) -> str | None:
        return self.state.get("last_run")

    def mark_run(self, ts: datetime | None = None) -> None:
        from src.models import utc_now

        self.state["last_run"] = (ts or utc_now()).isoformat(timespec="seconds")

    def sources_status(self) -> dict[str, Any]:
        return self.state["sources"]

    def jobs_this_week(self) -> int:
        return int(self.state.get("jobs_this_week", 0))

    def add_jobs_this_week(self, n: int) -> None:
        self.state["jobs_this_week"] = self.jobs_this_week() + n

    def ensure_week(self, week_key: str) -> None:
        """Reset the weekly counter when the ISO week rolls over.

        Without this, `jobs_this_week` would keep accumulating forever and the
        'This week: N' line in notifications would become meaningless."""
        if self.state.get("jobs_week_key") != week_key:
            self.state["jobs_week_key"] = week_key
            self.state["jobs_this_week"] = 0

    # --- notification dedup (never spam) ---
    def notified_today(self, kind: str, date_str: str) -> bool:
        return self.state["notifications_sent_today"].get(kind) == date_str

    def mark_notified(self, kind: str, date_str: str) -> None:
        self.state["notifications_sent_today"][kind] = date_str
        today = datetime.now(timezone.utc).date().isoformat()
        self.state["notifications_sent_today"] = {
            k: v for k, v in self.state["notifications_sent_today"].items()
            if v >= today
        }

    def digest_generated_for(self) -> str | None:
        return self.state.get("digest_generated_for")

    def mark_digest(self, week_key: str) -> None:
        self.state["digest_generated_for"] = week_key


class SeenStore:
    """Dedup store: seen hashes + recent jobs for fuzzy matching.

    Bounded in two directions:
      - `seen_hashes` expires entries after `dedup_window_days` (default 30).
      - `recent` is capped at `max_recent` entries.

    Backward compatible: old seen.json files without `seen_until` are loaded
    safely; hashes without a date entry are treated as current (no false
    negatives).
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or cfg.SEEN_PATH
        self.seen_hashes: set[str] = set()
        self.seen_until: dict[str, str] = {}  # hash -> YYYY-MM-DD first seen
        self.recent: list[dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        raw = _load_json_quarantine(self.path)
        self.seen_hashes = {str(h) for h in raw.get("seen_hashes", [])}
        raw_until = raw.get("seen_until", {})
        self.seen_until = {
            str(k): str(v) for k, v in raw_until.items() if isinstance(v, str)
        }
        recent = raw.get("recent_jobs", [])
        self.recent = recent if isinstance(recent, list) else []
        self._expire(cfg.dedup_window_days())

    def _expire(self, window_days: int) -> int:
        """Drop hashes and recent entries older than `window_days`.

        Returns the number of hashes expired (for logging).
        """
        cutoff = (_utc_today() - timedelta(days=window_days)).isoformat()
        expired = 0
        for h in list(self.seen_hashes):
            seen_on = self.seen_until.get(h)
            if seen_on and seen_on < cutoff:
                self.seen_hashes.discard(h)
                self.seen_until.pop(h, None)
                expired += 1
        # Prune recent jobs outside the window by fetched_at
        self.recent = [
            r for r in self.recent
            if self._recent_date(r) >= cutoff
        ]
        return expired

    @staticmethod
    def _recent_date(entry: dict[str, Any]) -> str:
        """Extract the YYYY-MM-DD from a recent job's fetched_at field.

        Missing fetched_at falls back to the UTC date so TTL pruning never
        drops a just-recorded entry."""
        raw = entry.get("fetched_at", "")
        return str(raw)[:10] if raw else _utc_today().isoformat()

    def save(self) -> None:
        atomic_write_json(self.path, {
            "seen_hashes": sorted(self.seen_hashes),
            "seen_until": self.seen_until,
            "recent_jobs": self.recent,
        })

    def has_exact(self, jid: str) -> bool:
        return jid in self.seen_hashes

    def mark_exact(self, jid: str) -> None:
        self.seen_hashes.add(jid)
        self.seen_until[jid] = _utc_today().isoformat()

    def recent_jobs(self) -> list[dict[str, Any]]:
        return self.recent

    def push_recent(self, job: dict[str, Any], max_recent: int = 5000) -> None:
        self.recent.insert(0, job)
        if len(self.recent) > max_recent:
            self.recent = self.recent[:max_recent]


class DeadLetterQueue:
    """Stores jobs that exceeded per-source retry so data is never lost."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or cfg.DEAD_LETTER_PATH
        self.items: list[dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        raw = _load_json_quarantine(self.path)
        items = raw.get("items", [])
        self.items = items if isinstance(items, list) else []

    def push(self, item: dict[str, Any], cap: int = 200) -> None:
        self.items.append(item)
        if len(self.items) > cap:
            self.items = self.items[-cap:]

    def save(self) -> None:
        atomic_write_json(self.path, {"items": self.items})