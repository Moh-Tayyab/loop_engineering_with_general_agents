"""Portable `storage_state` sessions for headed-browser sources (Phase 1 / Beat 126).

Replaces the bulky `.runtime/<source>-profile/` Chrome profile directory with a
single portable Playwright `storage_state` JSON (cookies + localStorage) at
`.runtime/<source>-session.json`, so sessions can be validated, expired, and
moved without carrying the whole profile.

Fail-closed contract (AGENTS.md §2 rules 6/10 — never hang, never leak):
  - missing / corrupt / fully-expired session → `load()` returns None, which
    means "fresh launch path", never an error.
  - `attempt_login()` REFUSES to run in any automation runner (amendment A1):
    cloud cron (`JOB_LOOP_CLOUD=1`) and GitHub Actions (`GITHUB_ACTIONS=true`)
    must never automate credential logins — CAPTCHA solving is a local-human
    operation.
  - `attempt_login()` is bounded by `LOGIN_TIMEOUT_S` (15 s) and converts every
    failure (timeout, CAPTCHA, crash, empty state) into a logged `None` so the
    caller records a circuit-breaker failure instead of hanging.
  - credential values are never logged; only source names and outcomes are.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable

import src.config as cfg
from src.browser import CaptchaDetected, CaptchaTimeout

log = logging.getLogger(__name__)

LOGIN_TIMEOUT_S = 15.0

_CAPTCHA_MARKERS = (
    "captcha",
    "cloudflare",
    "turnstile",
    "verify you are human",
    "enable javascript and cookies",
)


def session_file(source: str, base_dir: Path | None = None) -> Path:
    """`.runtime/<source>-session.json` (overridable for tests)."""
    root = Path(base_dir) if base_dir is not None else cfg.RUNTIME_DIR
    return root / f"{source}-session.json"


def _in_automation_runner() -> bool:
    """A1: credential auto-login is local-human-only.

    Covers both the cloud cron (`JOB_LOOP_CLOUD=1`) and ANY GitHub Actions
    environment (`GITHUB_ACTIONS=true` — includes the pytest test-gate, where
    such logins must never be attempted either).
    """
    return os.environ.get("GITHUB_ACTIONS", "") == "true" or cfg.is_cloud_runner()


def session_is_valid(state: Any, now: float | None = None) -> bool:
    """True if `state` is a storage_state with at least one usable cookie.

    Playwright cookie expiry semantics: `expires < 0` (usually -1) means a
    session cookie with no fixed expiry → usable; a numeric `expires` in the
    past means the cookie is dead. A fully-expired cookie set is invalid —
    the caller falls back to a fresh launch.
    """
    if not isinstance(state, dict):
        return False
    cookies = state.get("cookies")
    if not isinstance(cookies, list) or not cookies:
        return False
    now_s = time.time() if now is None else now
    for cookie in cookies:
        if not isinstance(cookie, dict):
            continue
        raw_exp = cookie.get("expires")
        if raw_exp is None:
            return True  # no expiry field → treat as a usable session cookie
        try:
            expires = float(raw_exp)
        except (TypeError, ValueError):
            continue
        if expires < 0 or expires > now_s:
            return True
    return False  # every cookie expired


def save(source: str, state: dict, base_dir: Path | None = None) -> Path:
    """Atomically persist a storage_state (write temp file, then rename)."""
    if not isinstance(state, dict):
        raise TypeError("storage_state must be a dict")
    path = session_file(source, base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(state), encoding="utf-8")
    os.replace(tmp, path)
    return path


def load(source: str, base_dir: Path | None = None) -> dict | None:
    """Return a usable storage_state, or None (missing/corrupt/expired).

    Fail-closed: never raises for I/O or parse problems; a corrupt file is
    unlinked so the next run starts clean.
    """
    path = session_file(source, base_dir)
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        log.warning("cannot read session for %s: %s", source, exc)
        return None
    try:
        state = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("corrupt session file for %s — removing %s", source, path)
        try:
            path.unlink()
        except OSError:
            pass
        return None
    if not session_is_valid(state):
        log.info("session for %s missing/expired — fresh launch needed", source)
        return None
    return state


def attempt_login(
    source: str,
    do_login: Callable[[], dict],
    *,
    timeout_s: float = LOGIN_TIMEOUT_S,
    base_dir: Path | None = None,
) -> dict | None:
    """Run `do_login()` bounded by `timeout_s`; persist the resulting session.

    `do_login` is an injected callable (the actual browser login, wired by the
    scraper) returning a Playwright `storage_state` dict.

    Never raises on login failures (fail-closed boundary): refusal in an
    automation runner, timeout, CAPTCHA/challenge, crash, or an unusable state
    all log a warning and return None so the caller records a circuit-breaker
    failure. Programmer errors (non-callable `do_login`) still raise.
    """
    if _in_automation_runner():
        log.warning(
            "attempt_login refused for %s in automation runner "
            "(cloud/Actions) — credential login is local-human-only (A1)",
            source,
        )
        return None
    if not callable(do_login):
        raise TypeError("do_login must be callable")

    outcome: dict[str, Any] = {}

    def _run() -> None:
        try:
            outcome["state"] = do_login()
        except Exception as exc:  # noqa: BLE001 — deliberate fail-closed boundary
            outcome["exc"] = exc

    worker = threading.Thread(target=_run, name=f"login-{source}", daemon=True)
    worker.start()
    worker.join(timeout_s)
    if worker.is_alive():
        log.warning(
            "login for %s exceeded %.1fs — timing out fail-closed "
            "(worker will be abandoned; no credentials logged)",
            source,
            timeout_s,
        )
        return None

    exc = outcome.get("exc")
    if exc is not None:
        msg = str(exc).lower()
        if isinstance(exc, (CaptchaDetected, CaptchaTimeout)) or any(
            marker in msg for marker in _CAPTCHA_MARKERS
        ):
            log.warning(
                "login for %s hit a CAPTCHA/challenge — aborting fail-closed: %s",
                source,
                exc,
            )
        else:
            log.warning("login for %s failed: %s", source, exc)
        return None

    state = outcome.get("state")
    if not session_is_valid(state):
        log.warning("login for %s returned no usable session", source)
        return None

    saved = save(source, state, base_dir)
    log.info("login ok for %s — session saved to %s", source, saved.name)
    return state
