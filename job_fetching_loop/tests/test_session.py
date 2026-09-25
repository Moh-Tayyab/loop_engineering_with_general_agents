"""Phase 1 (Beat 126): storage_state session persistence + login guardrails."""
from __future__ import annotations

import json
import time

import pytest

from src import session
from src.browser import CaptchaDetected


def _state(*, expires: float | None = -1.0) -> dict:
    cookie = {
        "name": "sid",
        "value": "abc",
        "domain": ".example.com",
        "path": "/",
    }
    if expires is not None:
        cookie["expires"] = expires
    return {"cookies": [cookie], "origins": []}


def _local_env(monkeypatch):
    """Make the test environment look like a local human run (A1)."""
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("JOB_LOOP_CLOUD", raising=False)


# ── persistence ──────────────────────────────────────────────────────────────

def test_save_load_roundtrip(tmp_path):
    state = _state()
    path = session.save("indeed", state, base_dir=tmp_path)
    assert path == tmp_path / "indeed-session.json"
    assert path.exists()
    loaded = session.load("indeed", base_dir=tmp_path)
    assert loaded == state


def test_load_missing_returns_none(tmp_path):
    assert session.load("indeed", base_dir=tmp_path) is None


def test_load_corrupt_unlinks_and_returns_none(tmp_path):
    bad = tmp_path / "indeed-session.json"
    bad.write_text("{not json", encoding="utf-8")
    assert session.load("indeed", base_dir=tmp_path) is None
    assert not bad.exists()  # self-healing: corrupt file removed


def test_expired_cookies_are_invalid(tmp_path):
    dead = _state(expires=time.time() - 60)
    assert session.session_is_valid(dead) is False
    session.save("indeed", dead, base_dir=tmp_path)
    assert session.load("indeed", base_dir=tmp_path) is None


def test_future_and_session_cookies_are_valid():
    assert session.session_is_valid(_state(expires=time.time() + 3600))
    assert session.session_is_valid(_state(expires=-1))  # Playwright session cookie
    assert session.session_is_valid({"cookies": [], "origins": []}) is False
    assert session.session_is_valid(None) is False
    assert session.session_is_valid("nope") is False


def test_save_rejects_non_dict(tmp_path):
    with pytest.raises(TypeError):
        session.save("indeed", [("not", "a state")], base_dir=tmp_path)


def test_save_is_atomic_no_tmp_left(tmp_path):
    session.save("indeed", _state(), base_dir=tmp_path)
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []
    # saved file is valid JSON
    json.loads((tmp_path / "indeed-session.json").read_text(encoding="utf-8"))


# ── attempt_login: A1 automation-runner refusal ──────────────────────────────

def test_attempt_login_refuses_on_github_actions(monkeypatch, tmp_path):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    called = []

    def do_login():
        called.append(1)
        return _state()

    assert session.attempt_login("indeed", do_login, base_dir=tmp_path) is None
    assert called == []  # never invoked


def test_attempt_login_refuses_on_cloud_runner(monkeypatch, tmp_path):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setenv("JOB_LOOP_CLOUD", "1")
    called = []

    def do_login():
        called.append(1)
        return _state()

    assert session.attempt_login("indeed", do_login, base_dir=tmp_path) is None
    assert called == []


# ── attempt_login: local paths (fail-closed outcomes) ────────────────────────

def test_attempt_login_success_saves_session(monkeypatch, tmp_path):
    _local_env(monkeypatch)
    state = _state(expires=time.time() + 7200)
    result = session.attempt_login("indeed", lambda: state, base_dir=tmp_path)
    assert result == state
    assert session.load("indeed", base_dir=tmp_path) == state


def test_attempt_login_times_out_fail_closed(monkeypatch, tmp_path):
    _local_env(monkeypatch)

    def slow_login():
        time.sleep(5)

    started = time.monotonic()
    result = session.attempt_login(
        "indeed", slow_login, timeout_s=0.1, base_dir=tmp_path
    )
    elapsed = time.monotonic() - started
    assert result is None
    assert elapsed < 2.0  # bounded by timeout_s, never the full sleep
    assert session.load("indeed", base_dir=tmp_path) is None


def test_attempt_login_captcha_returns_none(monkeypatch, tmp_path):
    _local_env(monkeypatch)

    def captcha_login():
        raise CaptchaDetected("indeed", "https://pk.indeed.com")

    assert session.attempt_login("indeed", captcha_login, base_dir=tmp_path) is None
    assert session.load("indeed", base_dir=tmp_path) is None


def test_attempt_login_crash_returns_none(monkeypatch, tmp_path):
    _local_env(monkeypatch)

    def broken_login():
        raise RuntimeError("browser closed unexpectedly")

    assert session.attempt_login("indeed", broken_login, base_dir=tmp_path) is None


def test_attempt_login_unusable_state_returns_none(monkeypatch, tmp_path):
    _local_env(monkeypatch)
    empty = {"cookies": [], "origins": []}
    assert session.attempt_login("indeed", lambda: empty, base_dir=tmp_path) is None
    assert session.load("indeed", base_dir=tmp_path) is None


def test_attempt_login_rejects_non_callable(monkeypatch, tmp_path):
    _local_env(monkeypatch)
    with pytest.raises(TypeError):
        session.attempt_login("indeed", "not-callable", base_dir=tmp_path)
