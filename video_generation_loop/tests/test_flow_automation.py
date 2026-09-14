"""Tests for the account-access gate (pure helpers only; no Playwright)."""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.flow_automation import (
    APPROVAL_SCOPES,
    APPROVE_HINTS,
    GENERIC_CONFIRM_HINTS,
    GOOGLE_SESSION_COOKIES,
    REDOWNLOAD_RETRIES,
    FlowAutomationError,
    FlowClipper,
    _approval_candidates,
    _clip_is_real_video,
    _has_google_session,
    _is_generation_finished,
    _log_manual_todo,
    validate_reference_image,
)


def _cookies(names):
    return [{"name": n, "value": "x"} for n in names]


def test_signed_in_cookie_detected():
    assert _has_google_session(_cookies(["SAPISID", "NID"])) is True


def test_secure_signed_cookie_detected():
    assert _has_google_session(_cookies(["__Secure-3PSID"])) is True


def test_no_session_when_anonymous_cookies_only():
    assert _has_google_session(_cookies(["NID", "OTZ", "ANID"])) is False


def test_empty_jar_is_not_a_session():
    assert _has_google_session([]) is False


def test_constant_looks_like_real_google_auth_cookies():
    assert "SID" in GOOGLE_SESSION_COOKIES
    assert "SAPISID" in GOOGLE_SESSION_COOKIES


# --- presenter reference-image guard (paid-account safety; no browser needed) ---

def test_reference_none_returns_empty(tmp_path):
    assert validate_reference_image(None) == ""
    assert validate_reference_image("") == ""


def test_reference_exists_is_echoed(tmp_path):
    img = tmp_path / "ref_01.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n\x00")
    assert validate_reference_image(str(img)) == str(img)


def test_reference_missing_raises(tmp_path):
    with pytest.raises(FlowAutomationError):
        validate_reference_image(str(tmp_path / "does_not_exist.png"))


def test_reference_empty_file_raises(tmp_path):
    img = tmp_path / "ref_empty.png"
    img.write_bytes(b"")
    with pytest.raises(FlowAutomationError):
        validate_reference_image(str(img))


# --- Beat 2 money-path seams (pure; no browser) ---

def test_approval_candidates_are_overlay_scoped_only():
    """Credit approval must NEVER be page-wide: a stray Continue/OK/Yes button
    in the page background must not be able to spend credits (double-charge
    guard). The scope must be a real modal overlay marker."""
    candidates = _approval_candidates()
    assert candidates, "no approval candidates"
    for scope, _sel in candidates:
        assert any(scope.startswith(s) for s in APPROVAL_SCOPES), f"unsafe scope: {scope!r}"
    assert all(scope.strip() != "" for scope, _sel in candidates)


def test_approval_candidates_dedicated_hints_first():
    """Every dedicated credit-approval button is tried before any generic
    confirm button, within every overlay scope."""
    labels = [sel for _s, sel in _approval_candidates()]
    for generic in GENERIC_CONFIRM_HINTS:
        for dedicated in APPROVE_HINTS:
            assert labels.index(dedicated) < labels.index(generic), (
                f"dedicated hint {dedicated!r} tried after generic {generic!r}"
            )


def test_approval_scopes_cover_real_modal_markers():
    """The scope set covers the marker shapes Flow/overlay dialogs actually use
    — role=dialog, role=alertdialog, and aria-modal — never just one."""
    scopes = set(APPROVAL_SCOPES)
    assert "[role='dialog'] " in scopes
    assert "[role='alertdialog'] " in scopes
    assert "[aria-modal='true'] " in scopes


def test_generation_finished_ignores_stop_control():
    """A visible 'Stop' control means still generating — never done, even if a
    video element is already on screen."""
    assert _is_generation_finished(has_stop=True, vids=1, has_download=True, has_done_btn=True) is False


@pytest.mark.parametrize(
    ("vids", "dl", "done"),
    [(1, False, False), (0, True, False), (0, False, True)],
)
def test_generation_finished_true_when_result_present(vids, dl, done):
    assert _is_generation_finished(has_stop=False, vids=vids, has_download=dl, has_done_btn=done) is True


def test_generation_finished_false_without_result():
    """Placeholder editor chrome (title/timeline/thumbnail) is NOT a done signal;
    only a real result counts. This is the seam that kills the old false-done
    double-charge path — those inputs are no longer part of the predicate."""
    assert _is_generation_finished(has_stop=False, vids=0, has_download=False, has_done_btn=False) is False


def test_redownload_retries_finite_and_small():
    """A broken download must loop a bounded number of times, never forever."""
    assert 1 <= REDOWNLOAD_RETRIES <= 3


def test_clip_is_real_video_accepts_readable_video(tmp_path, monkeypatch):
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"not-empty")
    monkeypatch.setattr("src.flow_automation.merger.probe_media", lambda p: {"has_video": True})
    assert _clip_is_real_video(f) is True


def test_clip_is_real_video_rejects_empty_and_audio_only(tmp_path, monkeypatch):
    empty = tmp_path / "empty.mp4"
    empty.write_bytes(b"")
    assert _clip_is_real_video(empty) is False  # rejected before any probe
    audio_only = tmp_path / "audio.mp4"
    audio_only.write_bytes(b"bytes")
    monkeypatch.setattr("src.flow_automation.merger.probe_media", lambda p: {"has_video": False})
    assert _clip_is_real_video(audio_only) is False


def test_clip_is_real_video_rejects_missing_and_unreadable(tmp_path):
    assert _clip_is_real_video(tmp_path / "missing.mp4") is False


def test_clip_is_real_video_passes_on_size_when_ffprobe_missing(tmp_path, monkeypatch):
    """Mirror evaluate_final: no ffprobe -> pass-on-size. A valid clip must NOT
    be re-generated just because nothing can probe it (double-charge guard)."""
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"real bytes")
    monkeypatch.setattr("src.flow_automation.cfg.ffprobe_binary", lambda: None)
    assert _clip_is_real_video(f) is True


def test_clip_is_real_video_rejects_ffprobe_unreadable(tmp_path, monkeypatch):
    """ffprobe present but the file is not readable media -> reject (fail
    closed; the download was garbage)."""
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"garbage")
    monkeypatch.setattr("src.flow_automation.cfg.ffprobe_binary", lambda: "/usr/bin/ffprobe")
    monkeypatch.setattr("src.flow_automation.merger.probe_media", lambda p: None)
    assert _clip_is_real_video(f) is False


# --- Beat 3 fail-fast: unattended runs log manual tasks, never block ---

def test_log_manual_todo_writes_append_only(tmp_path, monkeypatch):
    todo = tmp_path / "manual_todo.txt"
    monkeypatch.setattr("src.flow_automation.cfg.manual_todo_path", lambda: todo)
    _log_manual_todo("first prompt", tmp_path / "clip01.mp4")
    _log_manual_todo("second prompt", tmp_path / "clip02.mp4")
    text = todo.read_text()
    assert "first prompt" in text and "second prompt" in text
    assert "clip01.mp4" in text and "clip02.mp4" in text
    assert text.count("-" * 40) == 2  # one separator block per entry


def test_manual_assist_fails_fast_when_unattended(tmp_path, monkeypatch):
    from src.flow_automation import FlowClipper, _log_manual_todo

    todo = tmp_path / "manual_todo.txt"
    monkeypatch.setattr("src.flow_automation.cfg.fail_fast_enabled", lambda: True)
    monkeypatch.setattr("src.flow_automation.cfg.manual_todo_path", lambda: todo)
    clipper = FlowClipper(headless=True, profile_dir=tmp_path)
    with pytest.raises(FlowAutomationError, match="fail-fast"):
        clipper._manual_assist("prompt xyz", tmp_path / "clip.mp4")
    assert "prompt xyz" in todo.read_text()


def _page_no_dialog():
    page = MagicMock()
    loc = MagicMock()
    loc.count.return_value = 0
    loc.is_visible.return_value = False
    page.locator.return_value.first = loc
    return page


def _page_with_dialog():
    page = MagicMock()
    loc = MagicMock()
    loc.count.return_value = 1
    loc.is_visible.return_value = True
    page.locator.return_value.first = loc
    return page


def _fresh_clipper(tmp_path):
    c = FlowClipper(headless=True, profile_dir=tmp_path, manifest=lambda m: None)
    c._credits_approved = False
    c._run_credits_approved = False
    return c


def test_first_clip_no_dialog_accepts_free_path(monkeypatch, tmp_path):
    """Sep 2026 UI: no modal + generation already starting -> Flow consumes the
    account's FREE daily credits; accept (nothing paid is auto-spent)."""
    monkeypatch.setattr("src.flow_automation.time.sleep", lambda _: None)
    c = _fresh_clipper(tmp_path)
    c._approve_credits(_page_no_dialog())
    assert c._credits_approved
    assert c._run_credits_approved


def test_paid_dialog_without_optin_hard_stops(monkeypatch, tmp_path):
    monkeypatch.setattr("src.flow_automation.time.sleep", lambda _: None)
    c = _fresh_clipper(tmp_path)
    with pytest.raises(FlowAutomationError, match="FLOW_APPROVE_CREDITS"):
        c._approve_credits(_page_with_dialog())
    assert not c._credits_approved
    assert not c._run_credits_approved


def test_paid_dialog_autoapproves_only_with_env(monkeypatch, tmp_path):
    monkeypatch.setattr("src.flow_automation.time.sleep", lambda _: None)
    monkeypatch.setenv("FLOW_APPROVE_CREDITS", "1")
    c = _fresh_clipper(tmp_path)
    c._approve_credits(_page_with_dialog())
    assert c._credits_approved
    assert c._run_credits_approved


def test_second_clip_no_dialog_continues_when_session_approved(monkeypatch, tmp_path):
    monkeypatch.setattr("src.flow_automation.time.sleep", lambda _: None)
    c = _fresh_clipper(tmp_path)
    c._run_credits_approved = True
    c._approve_credits(_page_no_dialog())  # free-credit mode already known
    assert c._credits_approved


def test_preapproved_env_skips_gate(monkeypatch, tmp_path):
    monkeypatch.setattr("src.flow_automation.time.sleep", lambda _: None)
    monkeypatch.setenv("FLOW_CREDITS_PREAPPROVED", "1")
    c = _fresh_clipper(tmp_path)
    c._approve_credits(_page_no_dialog())
    assert not c._credits_approved  # no actual dialog click happened
    assert c._run_credits_approved


# --- Sep 2026 progress detection (no 'Stop' text; percent chip instead) ---

class _StubLoc:
    def __init__(self, n):
        self._n = n

    def count(self):
        return self._n


class _StubPage:
    def __init__(self, stop=0, progressbar=0, percent=0):
        self.stop, self.progressbar, self.percent = stop, progressbar, percent

    def locator(self, sel):
        return _StubLoc(self.stop if "Stop" in sel else self.progressbar)

    def get_by_text(self, _pat):
        return _StubLoc(self.percent)


def test_progress_detected_via_stop_control(tmp_path):
    c = _fresh_clipper(tmp_path)
    assert c._generation_in_progress(_StubPage(stop=1))


def test_progress_detected_via_progressbar(tmp_path):
    c = _fresh_clipper(tmp_path)
    assert c._generation_in_progress(_StubPage(progressbar=1))


def test_progress_detected_via_percent_chip(tmp_path):
    c = _fresh_clipper(tmp_path)
    assert c._generation_in_progress(_StubPage(percent=1))


def test_no_progress_detected_when_idle(tmp_path):
    c = _fresh_clipper(tmp_path)
    assert not c._generation_in_progress(_StubPage())


def test_progress_detection_never_raises(tmp_path):
    """Even when the DOM/API throws, the guard degrades to False (never crash)."""
    c = _fresh_clipper(tmp_path)

    class _Broken:
        def locator(self, sel):
            raise RuntimeError("boom")

        def get_by_text(self, _pat):
            raise RuntimeError("boom")

    assert c._generation_in_progress(_Broken()) is False