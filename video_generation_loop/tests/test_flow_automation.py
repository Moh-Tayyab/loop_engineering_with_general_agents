"""Tests for the account-access gate (pure helpers only; no Playwright)."""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.flow_automation import (
    APPROVAL_SCOPES,
    APPROVE_HINTS,
    CONTINUE_PROMPT,
    EXTEND_MAX_SEGMENTS,
    EXTEND_PROGRESS_SCHEMA,
    GENERIC_CONFIRM_HINTS,
    REDOWNLOAD_RETRIES,
    FlowAutomationError,
    FlowClipper,
    _approval_candidates,
    _clip_is_real_video,
    _extend_assist_text,
    _is_generation_finished,
    _log_manual_todo,
    extend_plan,
    parse_duration_timecode,
    read_extend_progress,
    validate_reference_image,
    write_extend_progress,
)


def _cookies(names):
    return [{"name": n, "value": "x"} for n in names]


# --- manual login gate: SERVER-side session verification (stale cookies must not pass) ---
class _GateVisiblePage:
    def __init__(self, url, goto_raises=False):
        self.url = url
        self.closed = False
        self.goto_raises = goto_raises

    def goto(self, url, **_kw):
        if self.goto_raises:
            raise RuntimeError("Timeout 60000ms exceeded (initial login goto)")
        self.url = url

    def close(self):
        self.closed = True


class _GateClosedVisiblePage:
    """Visible window the human closes after Flow started loading."""

    def __init__(self):
        self.closed = False

    @property
    def url(self):
        raise RuntimeError("Target page, context or browser has been closed")

    def goto(self, *_a, **_kw):
        pass  # initial load succeeds; the human closes the window afterwards

    def close(self):
        self.closed = True


class _GateProbePage:
    def __init__(self, landings):
        self._landings = list(landings)
        self.url = ""
        self.gotos = 0
        self.last_goto = None
        self.closed = False

    def goto(self, url, **_kw):
        self.gotos += 1
        self.last_goto = url
        if self._landings:
            self.url = self._landings.pop(0)

    def wait_for_timeout(self, _ms):
        pass

    def close(self):
        self.closed = True


class _GateBrowser:
    def __init__(self, landings=None, cookies=None, visible=None, probe=None):
        self.visible = visible or _GateVisiblePage("https://flow.google.com/about")
        self.probe = probe or _GateProbePage(landings or [])
        self._opened = 0
        self._cookies = cookies or []

    def new_page(self):
        self._opened += 1
        return self.visible if self._opened == 1 else self.probe

    def cookies(self):
        return self._cookies


class _HopProbePage(_GateProbePage):
    """Signed-out /about hop simulator: the landing starts on the workspace
    URL (like a signed-out goto-return) and client-hops to /about after a few
    watch-loop ticks (like the observed +3s SPA redirect). If the gate stopped
    reading the probe URL after goto, this would verify a signed-out session."""

    def __init__(self, landings):
        super().__init__(landings)
        self._ticks = 0

    def goto(self, url, **kw):
        super().goto(url, **kw)
        self._ticks = 0

    def wait_for_timeout(self, _ms):
        self._ticks += 1
        if self._ticks >= 6:
            self.url = "https://flow.google.com/about"


def test_signin_gate_rejects_stale_but_present_cookies(tmp_path, monkeypatch):
    """Regression: the gate used to pass on cookie PRESENCE alone and closed
    the window before the human could sign in — a revoked session must keep
    waiting until the probe is verified server-side (or time out)."""
    monkeypatch.setattr("src.flow_automation.time.sleep", lambda _: None)
    c = _fresh_clipper(tmp_path)
    c._browser = _GateBrowser(
        ["https://flow.google.com/about#overview"] * 3,
        cookies=_cookies(["SID", "SAPISID", "__Secure-1PSID", "__Secure-1PSIDTS"]),
    )
    assert c.wait_for_sign_in(timeout_s=0.05) is False
    assert c._browser.visible.closed is True
    assert c._browser.probe.closed is True


def test_signin_gate_passes_only_after_flow_workspace_probe(tmp_path, monkeypatch):
    monkeypatch.setattr("src.flow_automation.time.sleep", lambda _: None)
    c = _fresh_clipper(tmp_path)
    c._browser = _GateBrowser(
        ["https://flow.google.com/about",
         "https://flow.google.com/",
         "https://flow.google.com/"],
    )
    assert c.wait_for_sign_in(timeout_s=5) is True
    assert c._browser.visible.closed is True
    assert c._browser.probe.closed is True


def test_signin_gate_stops_when_human_closes_window(tmp_path, monkeypatch):
    monkeypatch.setattr("src.flow_automation.time.sleep", lambda _: None)
    c = _fresh_clipper(tmp_path)
    c._browser = _GateBrowser([], visible=_GateClosedVisiblePage())
    assert c.wait_for_sign_in(timeout_s=5) is False
    assert c._browser.visible.closed is True


def test_signin_gate_false_when_initial_goto_fails(tmp_path, monkeypatch):
    """A failing pre-loop navigation (timeout / window closed mid-load) must
    return False instead of escaping as a raw Playwright exception."""
    monkeypatch.setattr("src.flow_automation.time.sleep", lambda _: None)
    c = _fresh_clipper(tmp_path)
    c._browser = _GateBrowser(
        [], visible=_GateVisiblePage("https://flow.google.com", goto_raises=True),
    )
    assert c.wait_for_sign_in(timeout_s=5) is False
    assert c._browser.visible.closed is True


def test_signin_gate_watch_loop_catches_client_about_hop(tmp_path, monkeypatch):
    """Signed-out goto-return lands on the workspace URL before a +~3s
    client-side hop to /about. The watch loop must observe the hop and refuse
    to verify — deleting the loop (so the verdict reads the pre-hop URL) makes
    this test FAIL, pinning the loop as load-bearing."""
    monkeypatch.setattr("src.flow_automation.time.sleep", lambda _: None)
    c = _fresh_clipper(tmp_path)
    c._browser = _GateBrowser(probe=_HopProbePage(["https://flow.google.com/"]))
    assert c.wait_for_sign_in(timeout_s=0.05) is False
    assert c._browser.visible.closed is True
    assert c._browser.probe.closed is True


def test_signin_gate_probe_hits_flow_home_directly(tmp_path, monkeypatch):
    """The probe MUST navigate raw https://flow.google.com/ — that host is
    server-302'd to /about when signed out (no client race). If a future edit
    reverts the probe to cfg.flow_url() (labs.google/...) the suite must know:
    that path client-hops to /about and would reintroduce the timing race."""
    monkeypatch.setattr("src.flow_automation.time.sleep", lambda _: None)
    c = _fresh_clipper(tmp_path)
    c._browser = _GateBrowser(["https://flow.google.com/about"])  # never verifies
    assert c.wait_for_sign_in(timeout_s=0.05) is False
    assert c._browser.probe.gotos > 0
    assert c._browser.probe.last_goto == "https://flow.google.com/"


def test_signin_gate_rejects_off_host_lookalike_probe_url(tmp_path, monkeypatch):
    """Exact-host verification: an off-host URL that merely STARTS WITH the
    flow.google.com prefix must not satisfy the probe."""
    monkeypatch.setattr("src.flow_automation.time.sleep", lambda _: None)
    c = _fresh_clipper(tmp_path)
    c._browser = _GateBrowser(["https://flow.google.com.attacker.tld/signin"] * 3)
    assert c.wait_for_sign_in(timeout_s=0.05) is False


def test_signin_gate_requires_two_consecutive_verifications(tmp_path, monkeypatch):
    """A single good poll must not verify: the next poll must confirm the
    workspace landing again (transient disturbances cannot carry a pass)."""
    monkeypatch.setattr("src.flow_automation.time.sleep", lambda _: None)
    c = _fresh_clipper(tmp_path)
    c._browser = _GateBrowser(
        ["https://flow.google.com/", "https://flow.google.com/about#overview"],
    )
    assert c.wait_for_sign_in(timeout_s=0.05) is False


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


def test_generation_finished_true_on_result_thumbnail():
    """The project grid renders a finished scene as a poster tile (alt
    'Generated video thumbnail'), NOT a <video> element — detection must
    treat it as done or the 900s wait would time out on a finished render
    (the Sep 2026 failure mode)."""
    assert _is_generation_finished(
        has_stop=False, vids=0, has_download=False, has_done_btn=False,
        has_result_thumb=True,
    ) is True


def test_generation_finished_stop_beats_result_thumbnail():
    """A visible 'Stop' control still means generating even with a thumbnail
    from a previous segment on the page."""
    assert _is_generation_finished(
        has_stop=True, vids=1, has_download=True, has_done_btn=True,
        has_result_thumb=True,
    ) is False


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

# --- extend mode: pure seams (no browser) --------------------------------------
def _scene_prompts(n=6):
    return [f"scene {i} prompt" for i in range(1, n + 1)]


def test_parse_timecode_live_format_8s_clip():
    assert parse_duration_timecode("00:08:00") == 8


def test_parse_timecode_live_format_past_a_minute():
    # 8 segments at 8s -> 64s shows as MM:SS:FF with a non-zero minute field
    assert parse_duration_timecode("01:04:00") == 64


def test_parse_timecode_two_field_treated_as_mm_ss():
    assert parse_duration_timecode("10:30") == 630


def test_parse_timecode_garbage_returns_none():
    for bad in (None, "", "abc", "00:xx:00", "00:75:00", "1:2:3:4", "  :  :  "):
        assert parse_duration_timecode(bad) is None, bad


def test_parse_timecode_strips_padding():
    assert parse_duration_timecode("  00:08:00  ") == 8


def test_extend_plan_60s_target_is_8_segments_with_filler():
    plan = extend_plan(_scene_prompts(), 60, 8)
    assert len(plan) == 8  # ceil(60/8) segments -> 64s final
    assert plan[:6] == _scene_prompts()
    assert plan[6] == CONTINUE_PROMPT and plan[7] == CONTINUE_PROMPT
    assert all(p.strip() for p in plan)


def test_extend_plan_exact_multiple_uses_only_scene_prompts():
    plan = extend_plan(_scene_prompts(), 48, 8)
    assert plan == _scene_prompts()


def test_extend_plan_single_segment_target():
    assert extend_plan(_scene_prompts(), 8, 8) == [_scene_prompts()[0]]


def test_extend_plan_target_above_scene_coverage():
    # 6 scenes cover 48s; a 64s target needs 2 filler continuations
    plan = extend_plan(_scene_prompts(), 64, 8)
    assert len(plan) == 8
    assert plan[:6] == _scene_prompts()


def test_extend_plan_respects_clip_length():
    assert len(extend_plan(_scene_prompts(), 60, 10)) == 6


def test_extend_plan_more_scenes_than_segments_truncates():
    plan = extend_plan(_scene_prompts(), 8, 8)
    assert len(plan) == 1 and plan[0] == "scene 1 prompt"


def test_extend_plan_rejects_bad_inputs():
    import pytest

    with pytest.raises(ValueError):
        extend_plan([], 60, 8)
    with pytest.raises(ValueError):
        extend_plan(_scene_prompts(), 0, 8)
    with pytest.raises(ValueError):
        extend_plan(_scene_prompts(), 60, 0)


def test_extend_plan_segments_capped_by_money_guard():
    # the cap itself lives in generate_extended_video; the plan math must not
    # explode silently either — a silly target is visible in the plan length
    assert len(extend_plan(_scene_prompts(), 96, 1)) >= EXTEND_MAX_SEGMENTS


def _progress_payload(**over):
    base = {
        "day": 7,
        "project_url": "https://flow.google.com/project/abc",
        "edit_url": "https://flow.google.com/project/abc/edit/xyz",
        "segments_done": 3,
        "duration_s": 24,
        "target_s": 60,
        "clip_s": 8,
        "pending_extend": False,
        "prompts": _scene_prompts() + [CONTINUE_PROMPT] * 2,
    }
    base.update(over)
    return base


def test_progress_roundtrip(tmp_path):
    path = tmp_path / "extend_progress.json"
    write_extend_progress(path, _progress_payload())
    data = read_extend_progress(path)
    assert data is not None
    assert data["segments_done"] == 3
    assert data["duration_s"] == 24
    assert data["pending_extend"] is False
    assert data["schema_version"] == EXTEND_PROGRESS_SCHEMA
    assert data["prompts"][0] == "scene 1 prompt"
    assert data["ts"]  # timestamp stamped on every write


def test_progress_missing_file_is_none(tmp_path):
    assert read_extend_progress(tmp_path / "nope.json") is None
    assert read_extend_progress(None) is None


def test_progress_overwrite_updates_counters(tmp_path):
    path = tmp_path / "extend_progress.json"
    write_extend_progress(path, _progress_payload())
    write_extend_progress(path, _progress_payload(segments_done=4, duration_s=32,
                                                  pending_extend=True))
    data = read_extend_progress(path)
    assert data["segments_done"] == 4 and data["duration_s"] == 32
    assert data["pending_extend"] is True


def test_progress_creates_parent_dirs(tmp_path):
    path = tmp_path / "deep" / "nested" / "extend_progress.json"
    write_extend_progress(path, _progress_payload())
    assert path.exists()


def test_progress_corrupt_json_raises_never_silently_restarts(tmp_path):
    path = tmp_path / "extend_progress.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(FlowAutomationError):
        read_extend_progress(path)


def test_progress_non_object_json_raises(tmp_path):
    path = tmp_path / "extend_progress.json"
    path.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(FlowAutomationError):
        read_extend_progress(path)


def test_progress_newer_schema_raises(tmp_path):
    path = tmp_path / "extend_progress.json"
    payload = _progress_payload(schema_version=99)
    path.write_text(__import__("json").dumps(payload), encoding="utf-8")
    with pytest.raises(FlowAutomationError):
        read_extend_progress(path)


def test_progress_missing_required_fields_raise(tmp_path):
    path = tmp_path / "extend_progress.json"
    path.write_text('{"schema_version": 1, "segments_done": 1}', encoding="utf-8")
    with pytest.raises(FlowAutomationError):  # no URL at all
        read_extend_progress(path)
    write_extend_progress(path, _progress_payload(prompts=[]))
    with pytest.raises(FlowAutomationError):  # empty prompt list
        read_extend_progress(path)
    write_extend_progress(path, _progress_payload(segments_done=-1))
    with pytest.raises(FlowAutomationError):  # negative counter
        read_extend_progress(path)
    write_extend_progress(path, _progress_payload(target_s="soon"))
    with pytest.raises(FlowAutomationError):  # non-integer target
        read_extend_progress(path)


def test_progress_bad_schema_version_type_raises(tmp_path):
    path = tmp_path / "extend_progress.json"
    payload = _progress_payload(schema_version="v2")
    path.write_text(__import__("json").dumps(payload), encoding="utf-8")
    with pytest.raises(FlowAutomationError):
        read_extend_progress(path)


def test_extend_assist_text_lists_remaining_prompts_in_order(tmp_path):
    out = tmp_path / "final.mp4"
    text = _extend_assist_text(
        ["p1", "p2", "p3"], out,
        segments_done=1, edit_url="https://flow.google.com/project/a/edit/b",
        duration_s=8, target_s=24,
    )
    assert "https://flow.google.com/project/a/edit/b" in text
    assert str(out) in text
    assert "segment 2" in text and "segment 3" in text
    assert "p2" in text and "p3" in text
    assert "p1" not in text  # already generated — never ask for it again


def test_extend_assist_text_all_segments_done(tmp_path):
    text = _extend_assist_text(
        ["p1"], tmp_path / "final.mp4",
        segments_done=1, edit_url="", duration_s=8, target_s=8,
    )
    assert "nothing left to extend" in text
    assert "Download media" in text


def test_generate_extended_video_money_cap_blocks_huge_plans(tmp_path):
    # Cap fires before any browser/network use, so a bare instance suffices.
    clipper = FlowClipper.__new__(FlowClipper)
    huge = [f"p{i}" for i in range(EXTEND_MAX_SEGMENTS + 1)]
    with pytest.raises(FlowAutomationError):
        clipper.generate_extended_video(
            huge, tmp_path / "final.mp4", target_s=60, clip_s=8
        )


def test_generate_extended_video_empty_plan_rejected(tmp_path):
    clipper = FlowClipper.__new__(FlowClipper)
    with pytest.raises(FlowAutomationError):
        clipper.generate_extended_video(
            [], tmp_path / "final.mp4", target_s=60, clip_s=8
        )


def test_generate_extended_video_skips_existing_complete_final(tmp_path):
    # An already-complete final short-circuits before the browser is touched.
    import json as _json

    final = tmp_path / "final.mp4"
    final.write_bytes(b"x" * 1024)
    clipper = FlowClipper.__new__(FlowClipper)
    clipper.manifest = lambda msg: None
    clipper.generate_extended_video(
        _scene_prompts(), final, target_s=60, clip_s=8
    )  # returns without touching _browser (no AttributeError)


# --- Checker round 1: force-gate contract, resume reconciliation, coercion edges ---

def test_approve_credits_force_rescans_despite_session_shortcircuit(monkeypatch, tmp_path):
    """Extend chains re-open the money gate EVERY segment: free daily credits
    can run out mid-chain, so force=True must bypass both short-circuits and
    hard-stop on a paid dialog without FLOW_APPROVE_CREDITS."""
    monkeypatch.setattr("src.flow_automation.time.sleep", lambda _: None)
    monkeypatch.delenv("FLOW_APPROVE_CREDITS", raising=False)
    monkeypatch.delenv("FLOW_CREDITS_PREAPPROVED", raising=False)
    c = _fresh_clipper(tmp_path)
    c._credits_approved = True
    c._run_credits_approved = True
    c._approve_credits(_page_no_dialog())  # short-circuits: page untouched
    with pytest.raises(FlowAutomationError, match="FLOW_APPROVE_CREDITS"):
        c._approve_credits(_page_with_dialog(), force=True)  # rescans -> hard stop
    # the hard stop must not silently flip the approval flags
    assert c._credits_approved is True
    assert c._run_credits_approved is True


def test_approve_credits_force_free_path_reaccepts(monkeypatch, tmp_path):
    monkeypatch.setattr("src.flow_automation.time.sleep", lambda _: None)
    c = _fresh_clipper(tmp_path)
    c._credits_approved = True
    c._run_credits_approved = True
    c._approve_credits(_page_no_dialog(), force=True)  # free-credit re-scan
    assert c._credits_approved


def test_approve_credits_force_autoapproves_only_with_env(monkeypatch, tmp_path):
    monkeypatch.setattr("src.flow_automation.time.sleep", lambda _: None)
    monkeypatch.setenv("FLOW_APPROVE_CREDITS", "1")
    c = _fresh_clipper(tmp_path)
    c._credits_approved = True
    c._run_credits_approved = True
    c._approve_credits(_page_with_dialog(), force=True)
    assert c._credits_approved and c._run_credits_approved


class _ResumePage:
    def __init__(self, url):
        self.url = url

    def goto(self, _url, **_kw):
        pass

    def wait_for_timeout(self, _ms):
        pass


def _resume_clipper(tmp_path, durations, **methods):
    """Fresh clipper with browser-touching methods stubbed; `durations` feeds
    successive _read_duration_s calls (last value repeats)."""
    c = _fresh_clipper(tmp_path)
    c._generation_in_progress = lambda page: False
    vals = list(durations)

    def _read(_page):
        return vals.pop(0) if len(vals) > 1 else vals[0]

    c._read_duration_s = _read
    c._exit_extend_mode = lambda page: None
    # Real `_wait_for_scene_extend` RAISES when the committed duration never
    # grows (fail-closed — never re-pays). Tests that exercise a landed
    # pending extend override this with a grown-duration stub; resume tests
    # drive the decision through _read_duration_s only when pending is False.
    def _never_lands(*_a, **_k):
        raise FlowAutomationError("scene duration did not grow — never committed")

    c._wait_for_scene_extend = _never_lands
    for name, fn in methods.items():
        setattr(c, name, fn)
    return c


def _resume_progress(tmp_path, **over):
    path = tmp_path / "extend_progress.json"
    write_extend_progress(path, _progress_payload(**over))
    return read_extend_progress(path), path


class _TimecodePage:
    def __init__(self, values):
        self.values = iter(values)

    def wait_for_timeout(self, _ms):
        pass

    def next_timecode(self):
        return next(self.values)


def test_read_duration_s_skips_zero_before_player_loads(tmp_path):
    """Right after /edit/ navigation the timecode reads 00:00:00 while the
    player is still loading, then settles to the real duration (live-verified
    Sep 2026). A 0 read must never be returned — it would mis-segment the
    extend chain and stop it one segment early."""
    page = _TimecodePage(["00:00:00", "00:08:00"])
    c = _fresh_clipper(tmp_path)
    c._duration_value = lambda p: p.next_timecode()
    assert c._read_duration_s(page) == 8


def test_read_duration_s_raises_when_never_leaves_zero(tmp_path):
    page = _TimecodePage(["00:00:00"])
    c = _fresh_clipper(tmp_path)
    c._duration_value = lambda p: "00:00:00"
    with pytest.raises(FlowAutomationError, match="timecode"):
        c._read_duration_s(page)


def _extend_wait_clipper(tmp_path, durations, generating=False):
    c = _fresh_clipper(tmp_path)
    c._generation_in_progress = lambda page: generating
    c._exit_extend_mode = lambda page: None
    vals = list(durations)

    def _read(_page):
        return vals.pop(0) if len(vals) > 1 else vals[0]

    c._read_duration_s = _read
    c.manifest = lambda m: None
    return c


def test_scene_extend_wait_returns_once_duration_grows(tmp_path, monkeypatch):
    """The extend render COMMITS when the timecode grows — never on the
    scene editor's always-present Download/Done chrome (the Sep 2026 stall)."""
    monkeypatch.setattr("src.flow_automation.time.sleep", lambda _: None)
    c = _extend_wait_clipper(tmp_path, [8, 8, 16])
    assert c._wait_for_scene_extend(_TimecodePage([]), 8, 8) == 16


def test_scene_extend_wait_raises_when_duration_never_grows(tmp_path, monkeypatch):
    monkeypatch.setattr("src.flow_automation.time.sleep", lambda _: None)
    c = _extend_wait_clipper(tmp_path, [8])
    with pytest.raises(FlowAutomationError, match="never committed"):
        c._wait_for_scene_extend(_TimecodePage([]), 8, 8, budget=1)


def test_scene_extend_wait_defers_read_while_progress_shows(tmp_path, monkeypatch):
    """While a live progress control is visible the real duration would be
    stale — the wait must not read (or exit extend mode) until it's gone."""
    monkeypatch.setattr("src.flow_automation.time.sleep", lambda _: None)
    c = _extend_wait_clipper(tmp_path, [16], generating=True)
    with pytest.raises(FlowAutomationError, match="never committed"):
        c._wait_for_scene_extend(_TimecodePage([]), 8, 8, budget=1)


def test_resume_reconciles_pending_extend_that_landed(tmp_path):
    progress, path = _resume_progress(
        tmp_path, segments_done=1, duration_s=8, pending_extend=True
    )
    page = _ResumePage("https://flow.google.com/project/abc/edit/xyz")
    c = _resume_clipper(
        tmp_path, [16],
        _wait_for_scene_extend=lambda _p, _b, _c, **_k: 16,  # committed
    )
    _proj, _edit, seg, dur = c._resume_extend(page, progress, 8, path, None)
    assert (seg, dur) == (2, 16)
    reloaded = read_extend_progress(path)
    assert reloaded["pending_extend"] is False
    assert reloaded["segments_done"] == 2


def test_resume_pending_never_lands_raises_never_repays(tmp_path):
    """pending=True + duration never growing is indistinguishable from a
    server render still in flight (no progress chip in the scene editor) —
    the resume must RAISE (fail-closed, manual assist) instead of concluding
    'never started' and re-paying the same segment."""
    progress, path = _resume_progress(
        tmp_path, segments_done=1, duration_s=8, pending_extend=True
    )
    page = _ResumePage("https://flow.google.com/project/abc/edit/xyz")
    c = _resume_clipper(tmp_path, [8])  # default stub: wait never lands -> raise
    with pytest.raises(FlowAutomationError, match="never committed"):
        c._resume_extend(page, progress, 8, path, None)
    # the progress file must still be pending — no false reconciliation
    assert read_extend_progress(path)["pending_extend"] is True


def test_resume_pending_stale_read_rewaits_then_reconciles(tmp_path):
    """If the unconditional pending wait LANDED but the immediate duration
    read came back stale (== pre-wait value), the belt-and-braces branch must
    re-wait and reconcile from the commit — never re-pay, never conclude
    'never started'."""
    progress, path = _resume_progress(
        tmp_path, segments_done=1, duration_s=8, pending_extend=True
    )
    page = _ResumePage("https://flow.google.com/project/abc/edit/xyz")
    calls = []

    def _landed(_page, before, _clip, **_k):
        calls.append(before)
        return 16

    c = _resume_clipper(tmp_path, [8], _wait_for_scene_extend=_landed)
    _proj, _edit, seg, dur = c._resume_extend(page, progress, 8, path, None)
    assert (seg, dur) == (2, 16)          # reconciled from the 16s commit
    assert len(calls) == 2                # first wait + stale-read re-wait
    reloaded = read_extend_progress(path)
    assert reloaded["pending_extend"] is False
    assert reloaded["segments_done"] == 2


def test_resume_duration_backwards_raises(tmp_path):
    progress, path = _resume_progress(
        tmp_path, segments_done=2, duration_s=16, pending_extend=False
    )
    page = _ResumePage("https://flow.google.com/project/abc/edit/xyz")
    c = _resume_clipper(tmp_path, [8])
    with pytest.raises(FlowAutomationError, match="went backwards"):
        c._resume_extend(page, progress, 8, path, None)


def test_resume_pending_with_unreachable_editor_never_regenerates(tmp_path):
    """pending=True means segment 1 may already be paid — falling back to a
    fresh generation here would burn credits twice (money rule)."""
    progress, path = _resume_progress(
        tmp_path,
        edit_url="",
        segments_done=0,
        duration_s=0,
        pending_extend=True,
    )
    page = _ResumePage("https://flow.google.com/project/abc")

    def _boom(_page, _url):
        raise FlowAutomationError("editor unreachable")

    c = _resume_clipper(tmp_path, [0], _open_scene_editor=_boom)
    with pytest.raises(FlowAutomationError, match="not regenerating"):
        c._resume_extend(page, progress, 8, path, None)


def test_resume_unreachable_editor_without_pending_regenerates(tmp_path):
    """pending=False + segments_done=0 = segment 1 never paid: same-project
    regeneration is safe and is the intended recovery path."""
    progress, path = _resume_progress(
        tmp_path,
        edit_url="",
        segments_done=0,
        duration_s=0,
        pending_extend=False,
    )
    page = _ResumePage("https://flow.google.com/project/abc")

    def _boom(_page, _url):
        raise FlowAutomationError("editor unreachable")

    called = {}

    def _start(*args, **kw):
        called["yes"] = True
        return ("https://flow.google.com/project/abc", "", 1, 8)

    c = _resume_clipper(tmp_path, [0], _open_scene_editor=_boom, _start_extend=_start)
    _proj, _edit, seg, dur = c._resume_extend(page, progress, 8, path, None)
    assert called.get("yes") and (seg, dur) == (1, 8)


def test_progress_bad_day_value_raises(tmp_path):
    path = tmp_path / "extend_progress.json"
    write_extend_progress(path, _progress_payload(day="soon"))
    with pytest.raises(FlowAutomationError, match="non-integer day"):
        read_extend_progress(path)


def test_progress_pending_extend_string_false_is_false(tmp_path):
    path = tmp_path / "extend_progress.json"
    write_extend_progress(path, _progress_payload(pending_extend="false"))
    assert read_extend_progress(path)["pending_extend"] is False
    write_extend_progress(path, _progress_payload(pending_extend=3))
    with pytest.raises(FlowAutomationError, match="pending_extend"):
        read_extend_progress(path)


def test_extend_plan_coerces_and_rejects_blank_prompts():
    assert len(extend_plan(_scene_prompts(), "60", 8)) == 8
    with pytest.raises(ValueError):
        extend_plan(_scene_prompts(), "sixty", 8)
    with pytest.raises(ValueError, match="blank"):
        extend_plan(["scene 1", "   "], 60, 8)


# --- Checker round 2: expected-duration gate, exit-extend raises, setup limbo ---

def test_expected_final_s_rounds_up_to_clip_multiple():
    """Shared gate: generator short-circuit AND final evaluation must agree
    on the rounded-up clip multiple (targets ≡1-2 mod clip used to fail eval
    AFTER every credit was spent)."""
    from src.flow_automation import expected_final_s

    assert expected_final_s(60, 8) == 64
    assert expected_final_s(61, 8) == 64   # ≡1 (mod 8): was the failing class
    assert expected_final_s(62, 8) == 64   # ≡2 (mod 8): ditto
    assert expected_final_s(64, 8) == 64
    assert expected_final_s(65, 8) == 72
    assert expected_final_s(90, 8) == 96
    with pytest.raises(ValueError):
        expected_final_s(60, 0)
    with pytest.raises(ValueError):
        expected_final_s(0, 8)


class _ExitLoc:
    def __init__(self, page, sel):
        self._page, self._sel = page, sel

    @property
    def first(self):
        return self

    def _is_chip(self):
        return "Exit extend mode" in self._sel

    def _is_placeholder(self):
        return "What happens next?" in self._sel or "prosemirror-placeholder" in self._sel

    def count(self):
        if self._is_chip():
            return int(self._page.chip)
        if self._is_placeholder():
            return int(self._page.placeholder)
        return 0

    def is_visible(self):
        return self.count() > 0

    def all(self):
        return []

    def click(self, **_kw):
        if self._page.click_fails:
            raise RuntimeError("stub click failure")
        self._page.chip = False
        if self._page.exits:
            self._page.placeholder = False


class _ExitPage:
    def __init__(self, *, chip=True, placeholder=True, click_fails=False, exits=True):
        self.chip, self.placeholder = chip, placeholder
        self.click_fails, self.exits = click_fails, exits

    def locator(self, sel):
        return _ExitLoc(self, sel)

    def get_by_role(self, _role, name="", **_kw):
        return _ExitLoc(self, f"role-button:{name}")

    def wait_for_timeout(self, _ms):
        pass


def test_exit_extend_mode_visible_without_chip_raises(tmp_path):
    c = _fresh_clipper(tmp_path)
    with pytest.raises(FlowAutomationError, match="Exit extend mode"):
        c._exit_extend_mode(_ExitPage(chip=False, placeholder=True))


def test_exit_extend_mode_click_failure_raises(tmp_path):
    c = _fresh_clipper(tmp_path)
    with pytest.raises(FlowAutomationError, match="could not exit extend mode"):
        c._exit_extend_mode(_ExitPage(chip=True, placeholder=True, click_fails=True))


def test_exit_extend_mode_stuck_after_click_raises(tmp_path):
    c = _fresh_clipper(tmp_path)
    with pytest.raises(FlowAutomationError, match="still active"):
        c._exit_extend_mode(_ExitPage(chip=True, placeholder=True, exits=False))


def test_exit_extend_mode_happy_path_returns(tmp_path):
    c = _fresh_clipper(tmp_path)
    c._exit_extend_mode(_ExitPage(chip=True, placeholder=True, exits=True))  # no raise


def test_extend_chain_setup_failure_finishes_day_then_raises(tmp_path):
    """A setup error (bad plan / bad reference) must close the day failed and
    surface as RuntimeError so the caller exits 1 — never leave state
    in_progress with a raw traceback."""
    from types import SimpleNamespace

    import src.main as main

    state = MagicMock()
    day_state = MagicMock()
    day_state.day = 7
    sb = SimpleNamespace(scenes=[])  # extend_plan([]) -> ValueError inside setup try
    with pytest.raises(RuntimeError, match="extend setup failed"):
        main._generate_extend_chain(sb, tmp_path / "day_07" / "final.mp4", day_state, state)
    state.finish_day.assert_called_once()
    assert state.finish_day.call_args.kwargs.get("ok") is False


def test_generate_extended_video_in_window_final_skips(tmp_path, monkeypatch):
    """A leftover INSIDE the eval window (expected ±5) is accepted — no pay."""
    monkeypatch.setattr("src.flow_automation.merger.probe_duration", lambda _p: 64)
    final = tmp_path / "final.mp4"
    final.write_bytes(b"x" * 1024)
    clipper = FlowClipper.__new__(FlowClipper)
    msgs = []
    clipper.manifest = msgs.append
    clipper.generate_extended_video(_scene_prompts(), final, target_s=60, clip_s=8)
    assert any("skipping generation" in m for m in msgs)


def test_generate_extended_video_outside_window_continues_chain(tmp_path, monkeypatch):
    """A leftover OUTSIDE the eval window (e.g. 72s vs the 64±5 gate) must
    NOT skip — skipping would pay nothing, then fail eval with no recovery."""
    monkeypatch.setattr("src.flow_automation.merger.probe_duration", lambda _p: 72)
    final = tmp_path / "final.mp4"
    final.write_bytes(b"x" * 1024)
    clipper = FlowClipper.__new__(FlowClipper)
    msgs = []
    clipper.manifest = msgs.append
    with pytest.raises(AttributeError):  # no browser on a bare instance
        clipper.generate_extended_video(_scene_prompts(), final, target_s=60, clip_s=8)
    assert any("continuing the chain" in m for m in msgs)
    assert not any("skipping generation" in m for m in msgs)
