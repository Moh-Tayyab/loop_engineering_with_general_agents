"""Phase 1 (Beat 126/127): storage_state session persistence + login guardrails."""
from __future__ import annotations

import json
import logging
import stat
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


def test_load_non_utf8_is_corruption_and_removed(tmp_path):
    # Checker residual 1: a decode failure (ValueError, not OSError) must take
    # the same unlink-and-None path as bad JSON — never escape load().
    bad = tmp_path / "indeed-session.json"
    bad.write_bytes(b"\xff\xfe\x00\x80binary garbage")
    assert session.load("indeed", base_dir=tmp_path) is None
    assert not bad.exists()  # self-healing ran


def test_load_oversized_expiry_is_corruption_and_removed(tmp_path):
    # Human-approved bound fix (Beat 133): a 1000-digit expires makes
    # float(int) raise OverflowError — must self-heal (None + unlink), not escape.
    bad = tmp_path / "indeed-session.json"
    payload = (
        '{"cookies": [{"name": "a", "value": "b", "expires": '
        + "9" * 1000
        + '}], "origins": []}'
    )
    bad.write_text(payload, encoding="utf-8")
    assert session.load("indeed", base_dir=tmp_path) is None
    assert not bad.exists()  # self-healing ran


def test_nonfinite_expiry_rejected(tmp_path):
    # inf/nan expiry from a corrupt file must not count as a valid session.
    corrupt = {"cookies": [{"name": "a", "value": "b", "expires": 1e999}], "origins": []}
    assert session.session_is_valid(corrupt) is False
    corrupt["cookies"][0]["expires"] = float("nan")
    assert session.session_is_valid(corrupt) is False


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


def test_save_file_is_owner_only_0600(tmp_path):
    # Checker R1 (PR #15): auth cookies must never be world-readable,
    # regardless of the process umask (mkstemp forces 0600).
    path = session.save("indeed", _state(), base_dir=tmp_path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


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


def test_attempt_login_persist_failure_returns_none(monkeypatch, tmp_path):
    # Checker residual 2: a storage error while saving must not escape the
    # fail-closed boundary — logged None, no session file, no tmp leftovers.
    _local_env(monkeypatch)

    def _boom(*_args, **_kwargs):
        raise OSError("storage backend down")

    monkeypatch.setattr(session, "save", _boom)
    state = _state(expires=time.time() + 7200)
    assert session.attempt_login("indeed", lambda: state, base_dir=tmp_path) is None
    assert list(tmp_path.glob("*")) == []


def test_attempt_login_corrupt_expiry_returns_none(monkeypatch, tmp_path):
    # Same OverflowError signal on the do_login path must not escape.
    _local_env(monkeypatch)
    evil = {"cookies": [{"name": "a", "value": "b", "expires": 10**400}], "origins": []}
    assert session.attempt_login("indeed", lambda: evil, base_dir=tmp_path) is None
    assert list(tmp_path.glob("*")) == []


def test_attempt_login_rejects_non_callable(monkeypatch, tmp_path):
    _local_env(monkeypatch)
    with pytest.raises(TypeError):
        session.attempt_login("indeed", "not-callable", base_dir=tmp_path)


# ── Checker R2 (PR #15): exception text must never reach the logs ────────────

def _raiser(exc: Exception):
    def _fn():
        raise exc

    return _fn


def test_failed_login_never_logs_exception_text(monkeypatch, tmp_path, caplog):
    _local_env(monkeypatch)
    secret = "hunter2-super-secret-token"
    # Both failure branches: generic crash AND the CAPTCHA-classified branch
    # (message contains a captcha marker), each carrying a secret in the text.
    for exc in (
        RuntimeError(f"browser crashed; password={secret}"),
        RuntimeError(f"cloudflare turnstile challenge; token={secret}"),
    ):
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="src.session"):
            assert session.attempt_login(
                "indeed", _raiser(exc), base_dir=tmp_path
            ) is None
        assert secret not in caplog.text  # fixed outcome only, never str(exc)
        assert type(exc).__name__ in caplog.text  # class name IS logged
    assert session.load("indeed", base_dir=tmp_path) is None  # nothing persisted
